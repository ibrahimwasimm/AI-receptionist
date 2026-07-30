"""
telnyx_main.py — FastAPI router: Telnyx webhook + WebSocket audio bridge
=========================================================================
Mount onto the existing app in main.py (already done via voice_router).

Add this to main.py:
    from voice.telnyx_main import router as telnyx_router
    app.include_router(telnyx_router)

Endpoints added:
  POST /telnyx/voice            — Telnyx calls this when a call arrives
                                  Returns TeXML connecting call to WebSocket
  POST /telnyx/transfer-result  — Telnyx calls this after transfer completes/fails
                                  Returns TeXML with fallback message if no answer
  WS   /telnyx/stream           — Real-time bidirectional audio bridge
                                  Telnyx µ-law 8kHz ↔ Gemini PCM 16/24kHz

How Telnyx streaming works (vs Twilio):
  Twilio:  <Connect><Stream url="wss://..."/></Connect>   (TeXML same!)
  Telnyx:  <Connect><Stream url="wss://..."/></Connect>   (identical!)

  Audio format: both send µ-law 8kHz base64-encoded over WebSocket.
  WebSocket message structure is nearly identical.

  Key difference: Telnyx uses "call_control_id" instead of Twilio's "callSid"
  for REST API operations (transfers, hangup, TTS speak).

Configure your Telnyx phone number:
  Portal → Phone Numbers → your number → Messaging & Voice
  → Voice Method: TeXML
  → TeXML App URL: https://xxxx.ngrok-free.app/telnyx/voice
  → Save

Audio pipeline (identical to Twilio):
  Telnyx → server: base64 → µ-law 8kHz → PCM 16kHz → Gemini
  Gemini → server: PCM 24kHz → PCM 8kHz → µ-law → base64 → Telnyx
"""

import asyncio
import base64
import json
import logging
import os

# audioop removed from Python 3.13 stdlib — audioop-lts is a drop-in replacement
try:
    import audioop
except ImportError:
    import audioop_lts as audioop  # pip install audioop-lts

from fastapi import APIRouter, Request, Response, WebSocket, WebSocketDisconnect
from dotenv import load_dotenv

load_dotenv()

from voice.gemini_voice import GeminiVoiceHandler   # reused from Twilio implementation
from voice.emergency import is_emergency             # reused from Twilio implementation
from voice.telnyx_helper import transfer_to_dentist

logger = logging.getLogger("voice.telnyx")

router = APIRouter()

NGROK_URL = os.getenv("NGROK_URL", "").rstrip("/")

# ── Audio constants (same as Twilio — both use µ-law 8kHz) ───────────────────
_TELNYX_RATE     = 8_000   # Telnyx streams µ-law at 8kHz (same as Twilio)
_GEMINI_IN_RATE  = 16_000  # Gemini Live expects PCM 16kHz
_GEMINI_OUT_RATE = 24_000  # Gemini Live outputs PCM 24kHz
_SAMPLE_WIDTH    = 2       # 16-bit = 2 bytes per sample

_TRANSCRIPT_WINDOW = 5     # how many recent patient utterances to scan for emergency


# ─────────────────────────────────────────────────────────────────────────────
# POST /telnyx/voice  — inbound call webhook (returns TeXML)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/telnyx/voice")
async def telnyx_voice_webhook(request: Request) -> Response:
    """
    Telnyx calls this HTTP endpoint when someone calls your Telnyx number.
    We return TeXML instructing Telnyx to stream call audio to our WebSocket.

    TeXML format is IDENTICAL to Twilio TwiML — easy migration.
    """
    if not NGROK_URL:
        logger.error("[Telnyx] NGROK_URL is not set in .env!")

    ws_url = NGROK_URL.replace("https://", "wss://") + "/telnyx/stream"

    # TeXML <Stream> is identical to Twilio's <Connect><Stream>
    texml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="{ws_url}"/>
  </Connect>
</Response>"""

    logger.info(f"[Telnyx] Inbound call → streaming to {ws_url}")
    return Response(content=texml, media_type="application/xml")


# ─────────────────────────────────────────────────────────────────────────────
# POST /telnyx/transfer-result  — called when dentist transfer completes/fails
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/telnyx/transfer-result")
async def telnyx_transfer_result(request: Request) -> Response:
    """
    Telnyx posts the transfer outcome here after the dentist transfer attempt.

    Called when:
      - Transfer timed out (dentist did not answer within 20 seconds)
      - Transfer was rejected / call failed
      - Dentist answered (we can return empty TeXML or log it)

    We detect no-answer by reading the event payload and respond with
    TeXML to play a bilingual fallback message then hang up.
    """
    try:
        body = await request.json()
        event_type = body.get("data", {}).get("event_type", "")
        logger.info(f"[Telnyx] Transfer result event: {event_type}")
    except Exception:
        event_type = "unknown"

    # Any non-success outcome → play fallback and hang up
    # Successful bridge → Telnyx handles it; we return empty response
    if event_type in ("call.bridged",):
        # Dentist answered and is bridged — nothing for us to do
        logger.info("[Telnyx] ✅ Patient connected to dentist")
        return Response(content="<?xml version='1.0'?><Response/>", media_type="application/xml")

    # No answer / timeout / failure → play fallback message
    logger.info(f"[Telnyx] Dentist transfer failed ({event_type}) — playing fallback")

    texml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say language="en-US">
    Dentist abhi available nahi hain.
    Shadeed takleef mein ek sow pandraa call karein
    ya qareeb tareen hospital jayein.
    Hum jald aapko call back karein ge.
  </Say>
  <Pause length="1"/>
  <Say>
    The dentist is unavailable right now.
    For severe pain, please call 115 or visit the nearest hospital emergency.
    We will call you back as soon as possible. Thank you.
  </Say>
  <Hangup/>
</Response>"""

    return Response(content=texml, media_type="application/xml")


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket /telnyx/stream  — real-time audio bridge
# ─────────────────────────────────────────────────────────────────────────────

@router.websocket("/telnyx/stream")
async def telnyx_stream(websocket: WebSocket):
    """
    Telnyx streams µ-law 8kHz audio here over WebSocket (same format as Twilio).
    We bridge it bidirectionally to Gemini Live and run emergency detection.
    """
    await websocket.accept()
    logger.info("[Telnyx] WebSocket accepted")

    state = {
        "stream_sid"         : None,   # Telnyx stream_id
        "call_control_id"    : None,   # Telnyx call_control_id (for REST actions)
        "emergency_handled"  : False,
    }
    transcript_chunks: list[str] = []

    try:
        async with GeminiVoiceHandler() as gemini:
            await asyncio.gather(
                _telnyx_to_gemini(websocket, gemini, state, transcript_chunks),
                _gemini_to_telnyx(websocket, gemini, state, transcript_chunks),
            )
    except WebSocketDisconnect:
        logger.info("[Telnyx] WebSocket disconnected (call ended)")
    except Exception as e:
        logger.error(f"[Telnyx] Session error: {e}")
    finally:
        logger.info(f"[Telnyx] Call finished — stream={state['stream_sid']}")


# ─────────────────────────────────────────────────────────────────────────────
# Internal coroutine 1: Telnyx audio → Gemini
# ─────────────────────────────────────────────────────────────────────────────

async def _telnyx_to_gemini(
    websocket      : WebSocket,
    gemini         : GeminiVoiceHandler,
    state          : dict,
    transcript_buf : list,
) -> None:
    """
    Read JSON messages from Telnyx WebSocket.
    Telnyx message format is virtually identical to Twilio Media Streams.

    Event types:
      connected  → stream handshake
      start      → stream started; contains stream_id and call_control_id
      media      → audio chunk (base64 µ-law 8kHz)
      stop       → call ended
    """
    try:
        async for raw in websocket.iter_text():
            msg   = json.loads(raw)
            event = msg.get("event", "")

            if event == "connected":
                logger.info("[Telnyx] Stream connected")

            elif event == "start":
                # Telnyx start event — extract IDs
                # Telnyx uses "stream_id" (Twilio uses "streamSid")
                # Telnyx uses "call_control_id" (Twilio uses "callSid")
                start = msg.get("start", {})

                state["stream_sid"]      = (
                    msg.get("stream_id")
                    or msg.get("streamSid")       # fallback if format differs
                    or start.get("stream_id")
                )
                state["call_control_id"] = (
                    start.get("call_control_id")
                    or start.get("callSid")        # fallback
                    or msg.get("call_control_id")
                )

                logger.info(
                    f"[Telnyx] Stream started | "
                    f"stream={state['stream_sid']} | "
                    f"call_control_id={state['call_control_id']}"
                )

            elif event == "media":
                if state["emergency_handled"]:
                    continue   # emergency transfer already in progress

                # base64 → raw µ-law bytes
                payload     = msg["media"]["payload"]
                mulaw_bytes = base64.b64decode(payload)

                # µ-law 8-bit → PCM 16-bit (8kHz)
                pcm_8k = audioop.ulaw2lin(mulaw_bytes, _SAMPLE_WIDTH)

                # 8kHz → 16kHz (Gemini expects 16kHz input)
                pcm_16k, _ = audioop.ratecv(
                    pcm_8k, _SAMPLE_WIDTH, 1,
                    _TELNYX_RATE, _GEMINI_IN_RATE, None,
                )

                await gemini.send_audio(pcm_16k)

            elif event == "stop":
                logger.info("[Telnyx] Stream stopped")
                break

    except WebSocketDisconnect:
        logger.info("[Telnyx] _telnyx_to_gemini: WebSocket closed")
    except Exception as e:
        logger.error(f"[Telnyx] _telnyx_to_gemini error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Internal coroutine 2: Gemini responses → Telnyx
# ─────────────────────────────────────────────────────────────────────────────

async def _gemini_to_telnyx(
    websocket      : WebSocket,
    gemini         : GeminiVoiceHandler,
    state          : dict,
    transcript_buf : list,
) -> None:
    """
    Read responses from Gemini Live session.
    - "audio"      → convert and send to Telnyx WebSocket
    - "transcript" → patient speech → emergency check
    - "bot_text"   → log only
    """
    try:
        async for kind, data in gemini.receive():

            # ── Bot audio → Telnyx ────────────────────────────────────────
            if kind == "audio":
                if state["emergency_handled"] or not state["stream_sid"]:
                    continue

                # PCM 24kHz → PCM 8kHz
                pcm_8k, _ = audioop.ratecv(
                    data, _SAMPLE_WIDTH, 1,
                    _GEMINI_OUT_RATE, _TELNYX_RATE, None,
                )
                # PCM 16-bit → µ-law 8-bit
                mulaw   = audioop.lin2ulaw(pcm_8k, _SAMPLE_WIDTH)
                payload = base64.b64encode(mulaw).decode("utf-8")

                try:
                    # Telnyx WebSocket media message
                    # Uses "stream_id" key (vs Twilio's "streamSid")
                    # Both formats are accepted — we send both for compatibility
                    await websocket.send_text(json.dumps({
                        "event"    : "media",
                        "stream_id": state["stream_sid"],
                        "streamSid": state["stream_sid"],  # Twilio compat fallback
                        "media"    : {"payload": payload},
                    }))
                except WebSocketDisconnect:
                    logger.info("[Telnyx] WebSocket closed while sending audio")
                    break

            # ── Patient transcript → emergency check ──────────────────────
            elif kind == "transcript":
                logger.info(f"[Patient] {data!r}")
                transcript_buf.append(data)

                if not state["emergency_handled"] and state["call_control_id"]:
                    combined = " ".join(transcript_buf[-_TRANSCRIPT_WINDOW:])
                    detected = await asyncio.to_thread(is_emergency, combined)

                    if detected:
                        logger.info("[Telnyx] 🚨 EMERGENCY detected — transferring call")
                        state["emergency_handled"] = True

                        # Telnyx REST API takes over the call → stream ends
                        await transfer_to_dentist(state["call_control_id"])
                        break

            # ── Bot speech text → log only ────────────────────────────────
            elif kind == "bot_text":
                logger.info(f"[Bot] {data!r}")

    except Exception as e:
        logger.error(f"[Telnyx] _gemini_to_telnyx error: {e}")
