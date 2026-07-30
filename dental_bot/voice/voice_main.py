"""
voice_main.py — FastAPI router: Twilio webhook + WebSocket audio bridge
=======================================================================
Mount onto the existing app in main.py:

    from voice.voice_main import router as voice_router
    app.include_router(voice_router)

Endpoints added:
  POST /voice             — Twilio calls this when a call arrives
                            Returns TwiML connecting call to WebSocket stream
  POST /voice/dial-fallback — Twilio calls this when dentist doesn't answer
                            Returns TwiML with fallback message + hangup
  WS   /media-stream      — Real-time bidirectional audio bridge
                            Twilio µ-law 8kHz ↔ Gemini PCM 16/24kHz

Audio conversion pipeline:
  Twilio → Gemini:  base64 → µ-law → PCM 16-bit 8kHz → PCM 16-bit 16kHz
  Gemini → Twilio:  PCM 16-bit 24kHz → PCM 16-bit 8kHz → µ-law → base64
"""

import asyncio
import base64
import json
import logging
import os

# audioop was removed from Python stdlib in 3.13 — use audioop-lts as drop-in
try:
    import audioop
except ImportError:
    import audioop_lts as audioop  # pip install audioop-lts

from fastapi import APIRouter, Request, Response, WebSocket, WebSocketDisconnect
from dotenv import load_dotenv

load_dotenv()

from voice.gemini_voice import GeminiVoiceHandler
from voice.emergency import is_emergency
from voice.twilio_helper import transfer_to_dentist

logger = logging.getLogger("voice.main")

router = APIRouter()

NGROK_URL       = os.getenv("NGROK_URL", "").rstrip("/")

# Audio sample rates
_TWILIO_RATE    = 8_000    # µ-law 8kHz  (Twilio Media Streams format)
_GEMINI_IN_RATE = 16_000   # PCM 16kHz   (Gemini Live input)
_GEMINI_OUT_RATE= 24_000   # PCM 24kHz   (Gemini Live output)
_SAMPLE_WIDTH   = 2        # 16-bit PCM = 2 bytes per sample

# How many recent transcript chunks to inspect for emergency
_TRANSCRIPT_WINDOW = 5


# ─────────────────────────────────────────────────────────────────────────────
# POST /voice  — Twilio inbound call webhook
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/voice")
async def voice_webhook(request: Request) -> Response:
    """
    Twilio hits this endpoint the moment a patient calls.
    We reply with TwiML that tells Twilio to stream audio to /media-stream.
    """
    if not NGROK_URL:
        logger.error("[Voice] NGROK_URL is not set in .env!")

    ws_url = NGROK_URL.replace("https://", "wss://") + "/media-stream"

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="{ws_url}"/>
  </Connect>
</Response>"""

    logger.info(f"[Voice] Inbound call → streaming to {ws_url}")
    return Response(content=twiml, media_type="application/xml")


# ─────────────────────────────────────────────────────────────────────────────
# POST /voice/dial-fallback  — dentist did not answer (20s timeout)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/voice/dial-fallback")
async def dial_fallback(request: Request) -> Response:
    """
    Twilio calls this when the dentist transfer times out or is rejected.
    We play a bilingual fallback message and end the call cleanly.
    """
    form        = await request.form()
    dial_status = form.get("DialCallStatus", "no-answer")
    call_sid    = form.get("CallSid", "unknown")
    logger.info(f"[Transfer] Fallback triggered — status={dial_status} call={call_sid}")

    twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say language="ur-PK">
    Dentist abhi available nahi hain.
    Shadeed takleef mein ek sow pandraa call karein
    ya qareeb tareen hospital jayein.
    Hum jald aapko call back karein ge. Shukriya.
  </Say>
  <Pause length="1"/>
  <Say>
    The dentist is unavailable right now.
    For severe pain, please call 115 or visit the nearest hospital emergency.
    We will call you back as soon as possible. Thank you.
  </Say>
  <Hangup/>
</Response>"""

    return Response(content=twiml, media_type="application/xml")


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket /media-stream  — real-time audio bridge
# ─────────────────────────────────────────────────────────────────────────────

@router.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    """
    Twilio streams µ-law 8kHz audio here over WebSocket.
    We convert and pipe it to Gemini Live, then pipe responses back.
    Emergency detection runs on every patient speech transcript.
    """
    await websocket.accept()
    logger.info("[Voice] WebSocket accepted")

    # Shared state between the two concurrent coroutines
    state = {
        "stream_sid"       : None,
        "call_sid"         : None,
        "emergency_handled": False,
        "connected"        : True,
    }
    transcript_chunks: list[str] = []   # rolling buffer of patient speech

    try:
        async with GeminiVoiceHandler() as gemini:
            # Run Twilio→Gemini and Gemini→Twilio pipelines concurrently
            await asyncio.gather(
                _twilio_to_gemini(websocket, gemini, state, transcript_chunks),
                _gemini_to_twilio(websocket, gemini, state, transcript_chunks),
            )
    except WebSocketDisconnect:
        logger.info("[Voice] WebSocket disconnected by Twilio (call ended)")
    except Exception as e:
        logger.error(f"[Voice] Session error: {e}")
    finally:
        state["connected"] = False
        logger.info(f"[Voice] Call finished — stream_sid={state['stream_sid']}")


# ─────────────────────────────────────────────────────────────────────────────
# Internal coroutine 1: Twilio audio → Gemini
# ─────────────────────────────────────────────────────────────────────────────

async def _twilio_to_gemini(
    websocket       : WebSocket,
    gemini          : GeminiVoiceHandler,
    state           : dict,
    transcript_buf  : list,
) -> None:
    """
    Reads JSON messages from Twilio WebSocket.
    On "media" events: decodes µ-law audio and forwards to Gemini.
    Also extracts stream_sid and call_sid from the "start" event.
    """
    try:
        async for raw in websocket.iter_text():
            msg   = json.loads(raw)
            event = msg.get("event", "")

            if event == "connected":
                logger.info("[Voice] Twilio stream connected")

            elif event == "start":
                start_data          = msg.get("start", {})
                state["stream_sid"] = msg.get("streamSid") or start_data.get("streamSid")
                state["call_sid"]   = start_data.get("callSid", "")
                logger.info(
                    f"[Voice] Stream started | "
                    f"SID={state['stream_sid']} | Call={state['call_sid']}"
                )

            elif event == "media":
                if state["emergency_handled"]:
                    # Transfer already triggered — stop feeding audio
                    continue

                # base64 → raw µ-law bytes
                mulaw_bytes = base64.b64decode(msg["media"]["payload"])

                # µ-law 8-bit → PCM 16-bit (same rate: 8kHz)
                pcm_8k = audioop.ulaw2lin(mulaw_bytes, _SAMPLE_WIDTH)

                # 8kHz → 16kHz (Gemini expects 16kHz)
                pcm_16k, _ = audioop.ratecv(
                    pcm_8k, _SAMPLE_WIDTH, 1,
                    _TWILIO_RATE, _GEMINI_IN_RATE, None,
                )

                await gemini.send_audio(pcm_16k)

            elif event == "stop":
                logger.info("[Voice] Twilio stream stopped")
                break

    except WebSocketDisconnect:
        logger.info("[Voice] _twilio_to_gemini: WebSocket closed")
    except Exception as e:
        logger.error(f"[Voice] _twilio_to_gemini error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Internal coroutine 2: Gemini responses → Twilio
# ─────────────────────────────────────────────────────────────────────────────

async def _gemini_to_twilio(
    websocket       : WebSocket,
    gemini          : GeminiVoiceHandler,
    state           : dict,
    transcript_buf  : list,
) -> None:
    """
    Reads responses from the Gemini Live session.
    - "audio"     → converts to µ-law and sends to Twilio
    - "transcript" → appends to buffer, checks for dental emergency
    - "bot_text"  → logged for debugging
    """
    try:
        async for kind, data in gemini.receive():

            # ── Bot audio → Twilio ─────────────────────────────────────────
            if kind == "audio":
                if state["emergency_handled"] or not state["stream_sid"]:
                    continue

                # PCM 24kHz → PCM 8kHz
                pcm_8k, _ = audioop.ratecv(
                    data, _SAMPLE_WIDTH, 1,
                    _GEMINI_OUT_RATE, _TWILIO_RATE, None,
                )

                # PCM 16-bit → µ-law 8-bit
                mulaw   = audioop.lin2ulaw(pcm_8k, _SAMPLE_WIDTH)
                payload = base64.b64encode(mulaw).decode("utf-8")

                try:
                    await websocket.send_text(json.dumps({
                        "event"    : "media",
                        "streamSid": state["stream_sid"],
                        "media"    : {"payload": payload},
                    }))
                except WebSocketDisconnect:
                    logger.info("[Voice] WebSocket closed while sending audio")
                    break

            # ── Patient transcript → emergency check ───────────────────────
            elif kind == "transcript":
                logger.info(f"[Patient] {data!r}")
                transcript_buf.append(data)

                # Only check if we haven't already triggered a transfer
                if not state["emergency_handled"] and state["call_sid"]:
                    # Combine the last N utterances for better context
                    combined = " ".join(transcript_buf[-_TRANSCRIPT_WINDOW:])

                    # Run blocking keyword/Gemini check in thread pool
                    detected = await asyncio.to_thread(is_emergency, combined)

                    if detected:
                        logger.info("[Voice] 🚨 EMERGENCY detected — initiating transfer")
                        state["emergency_handled"] = True

                        # This calls Twilio REST API to redirect the call.
                        # Twilio will then close our WebSocket automatically.
                        await transfer_to_dentist(state["call_sid"])
                        break   # Stop the Gemini receive loop

            # ── Bot's own speech text (for logs) ──────────────────────────
            elif kind == "bot_text":
                logger.info(f"[Bot] {data!r}")

    except Exception as e:
        logger.error(f"[Voice] _gemini_to_twilio error: {e}")
