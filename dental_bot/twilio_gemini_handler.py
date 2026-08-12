import os
import json
import base64
import asyncio
import audioop
import time
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import Request, Response, WebSocket
from google import genai
from google.genai import types
from twilio.rest import Client as TwilioClient
from dotenv import load_dotenv

load_dotenv(override=True)
logger = logging.getLogger("voice")

from gcal import get_open_slots, create_booking, cancel_booking
from agent import notify_doctor, get_patient, register_patient
from database import supabase
from female_verbal_fillers import VERBAL_FILLER_CHECKING, VERBAL_FILLER_BOOKING, VERBAL_FILLER_GENERAL

TWILIO_ACCOUNT_SID  = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN   = os.getenv("TWILIO_AUTH_TOKEN", "")
GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY", "")
CLINIC_NAME         = os.getenv("CLINIC_NAME", "Centre of Modern Dentistry")
DR_MUSTAFA_NUMBER   = os.getenv("DR_MUSTAFA_NUMBER", "")
DR_QASIM_NUMBER     = os.getenv("DR_QASIM_NUMBER", "")
EMERGENCY_NUMBER    = os.getenv("EMERGENCY_NUMBER", "")
NGROK_URL           = os.getenv("NGROK_URL", "")

TWILIO_RATE  = 8000
GEMINI_IN    = 16000
GEMINI_OUT   = 24000
SAMPLE_WIDTH = 2


async def voice_webhook(request: Request) -> Response:
    form          = await request.form()
    caller_number = form.get("From", "unknown")
    call_sid      = form.get("CallSid", "")
    # Smart Host detection for Render cloud deployment & ngrok
    host = request.headers.get("host") or ""
    if host and ("onrender.com" in host or "ngrok" in host):
        ws_url = f"wss://{host}"
    else:
        ws_url = NGROK_URL.replace("https://", "wss://").replace("http://", "ws://")

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="{ws_url}/media-stream">
      <Parameter name="caller"  value="{caller_number}"/>
      <Parameter name="callSid" value="{call_sid}"/>
    </Stream>
  </Connect>
</Response>"""
    return Response(
        content=twiml,
        media_type="application/xml",
        status_code=200
    )


async def media_stream(websocket: WebSocket):
    await websocket.accept()
    logger.info("[Voice] WebSocket accepted")

    state = {
        "stream_sid":              None,
        "call_sid":                None,
        "caller_number":           None,
        "ratecv_in_state":         None,   # Twilio 8kHz -> Gemini 16kHz resampler state
        "ratecv_out_state":        None,  # Gemini 24kHz -> Twilio 8kHz resampler state
        "last_user_speech_time":   None,
        "waiting_for_first_audio": False,
    }

    # Slots are fetched dynamically via tool calling — no upfront blocking Google Calendar API call on stream startup!
    slots_text = "Use the get_available_slots tool when a patient asks about available timings or appointments."

    gemini_client = genai.Client(api_key=GEMINI_API_KEY)

    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name="Aoede"
                )
            )
        ),
        tools=[
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name="get_available_slots",
                        description="Get available appointment slots from Google Calendar",
                        parameters=types.Schema(
                            type="OBJECT",
                            properties={
                                "date": types.Schema(
                                    type="STRING",
                                    description="Optional date YYYY-MM-DD"
                                )
                            }
                        )
                    ),
                    types.FunctionDeclaration(
                        name="book_appointment",
                        description="Book appointment in Google Calendar and Supabase",
                        parameters=types.Schema(
                            type="OBJECT",
                            properties={
                                "patient_name": types.Schema(type="STRING"),
                                "patient_phone": types.Schema(type="STRING"),
                                "date_str": types.Schema(type="STRING"),
                                "time_str": types.Schema(type="STRING"),
                                "procedure": types.Schema(type="STRING")
                            },
                            required=[
                                "patient_name",
                                "patient_phone",
                                "date_str",
                                "time_str",
                                "procedure"
                            ]
                        )
                    ),
                    types.FunctionDeclaration(
                        name="cancel_appointment",
                        description="Cancel existing appointment",
                        parameters=types.Schema(
                            type="OBJECT",
                            properties={
                                "patient_phone": types.Schema(type="STRING"),
                                "date_str": types.Schema(type="STRING"),
                                "time_str": types.Schema(type="STRING")
                            },
                            required=[
                                "patient_phone",
                                "date_str",
                                "time_str"
                            ]
                        )
                    ),
                    types.FunctionDeclaration(
                        name="transfer_to_doctor",
                        description="Transfer call to doctor for consultation or emergency",
                        parameters=types.Schema(
                            type="OBJECT",
                            properties={
                                "doctor": types.Schema(
                                    type="STRING",
                                    enum=[
                                        "dr_mustafa",
                                        "dr_qasim",
                                        "emergency"
                                    ]
                                )
                            },
                            required=["doctor"]
                        )
                    )
                ]
            )
        ],
        system_instruction=f"""CRITICAL RULE: You MUST speak ONLY in Pakistani Urdu or Roman Urdu at ALL times.
NEVER use English unless the caller themselves speak full English sentences to you.

Aap ka naam Sana hai. Aap {CLINIC_NAME} ki friendly voice receptionist hain.

════ GREETING ════
Jab call connect ho, FORAN yeh bolein (Urdu mein):
"Assalam u Alaikum! mein sana baat krhi  {CLINIC_NAME} . Aap ki kya madad kar sakti hoon?"

════ CLINIC INFO ════
Timings : Monday to Saturday, sham 5 baje se raat 10 baje tak
Closed  : Sunday
Doctors : Dr. Mustafa aur Dr. Qasim
Fees    : Consultation par bata denge

════ AVAILABLE SLOTS ════
{slots_text}

════ APPOINTMENT BOOKING ════
1. Pucho: aap ko kiya pochna hai clinic ke baray mai ya ap koi appointment book krwana hai?
2. get_available_slots tool call karo
3. Patient ko max 3 slots batao
4. Patient jo slot choose kare confirm karo
5. Naam pucho
6. book_appointment call karo
7. Warmly Urdu mein confirm karo

════ CANCELLATION ════
1. Phone number pucho
2. Date pucho
3. Time pucho
4. cancel_appointment call karo
5. Urdu mein confirm karo

════ EMERGENCY ════
Agar severe pain, swelling, bleeding ya broken tooth ho:
Foran transfer_to_doctor emergency call karo.

════ DOCTOR TRANSFER ════
Agar patient doctor se milna chahe:
Pucho: "Dr. Mustafa ya Dr. Qasim?"
Phir transfer_to_doctor call karo.

════ FEMALE GENDER GRAMMAR RULE (STRICT CRITICAL) ════
Aap Larki / Female (Sana) hain. Hamesha FEMALE Urdu grammar use karein!
- SAHI (Female): "Main batati hoon", "Main karti hoon", "Main dekhti hoon", "Main confirm karti hoon", "Main bata deti hoon"
- SAKHT MANA HAI (Male): "Main batata hoon", "Main karta hoon", "Main dekhta hoon", "Main confirm karta hoon"

════ RULES ════
1. SIRF Urdu ya Roman Urdu mein jawab do
2. Short jawab — max 2-3 sentences
3. Warm, natural aur professional raho
4. Apni AI identity mat batao"""
    )

    stopped = asyncio.Event()

    LIVE_MODEL_NAME = "gemini-3.1-flash-live-preview"
    try:
        logger.info(f"[Voice] 🚀 Initializing Gemini Live Session | Model: {LIVE_MODEL_NAME}")
        async with gemini_client.aio.live.connect(
            model=LIVE_MODEL_NAME,
            config=config
        ) as session:
            logger.info("[Voice] Gemini Live session opened")
            await asyncio.gather(
                _receive_from_twilio(websocket, session, state, stopped),
                _send_to_twilio(websocket, session, state, stopped)
            )
    except Exception as e:
        logger.error(f"[Voice] Session error: {e}")
    finally:
        stopped.set()
        logger.info(f"[Voice] Call ended — {state['caller_number']}")


async def _receive_from_twilio(
    websocket: WebSocket,
    session,
    state: dict,
    stopped: asyncio.Event
):
    pcm_buffer = bytearray()
    CHUNK_SIZE = 3200  # 100ms of 16kHz 16-bit mono PCM (16000 * 2 bytes * 0.1s)

    try:
        async for message in websocket.iter_text():
            if stopped.is_set():
                break
            data  = json.loads(message)
            event = data.get("event", "")

            if event == "connected":
                logger.info("[Voice] Stream connected")

            elif event == "start":
                state["stream_sid"] = data["streamSid"]
                start  = data.get("start", {})
                state["call_sid"] = start.get("callSid", "")
                params = start.get("customParameters", {})
                state["caller_number"] = params.get("caller", "unknown")
                logger.info(
                    f"[Voice] Stream started | Caller: {state['caller_number']}"
                )

                # Trigger greeting ONCE stream_sid is set
                try:
                    await session.send_client_content(
                        turns=[
                            types.Content(
                                role="user",
                                parts=[types.Part.from_text(
                                    text="Sana, call aa gayi hai. Abhi Urdu mein greeting do."
                                )]
                            )
                        ],
                        turn_complete=True
                    )
                    logger.info("[Voice] Urdu greeting trigger sent")
                except Exception as e:
                    logger.warning(f"[Voice] Greeting trigger warning: {e}")

            elif event == "media":
                state["last_user_speech_time"]   = time.perf_counter()
                state["waiting_for_first_audio"] = True
                raw    = base64.b64decode(data["media"]["payload"])
                pcm_8k = audioop.ulaw2lin(raw, SAMPLE_WIDTH)

                # 8kHz -> 16kHz resample with state persistence across chunks
                pcm_16k, state["ratecv_in_state"] = audioop.ratecv(
                    pcm_8k, SAMPLE_WIDTH, 1,
                    TWILIO_RATE, GEMINI_IN,
                    state["ratecv_in_state"]
                )

                # Buffer into 100ms chunks before forwarding to Gemini
                pcm_buffer.extend(pcm_16k)
                if len(pcm_buffer) >= CHUNK_SIZE:
                    try:
                        await session.send_realtime_input(
                            audio=types.Blob(
                                data      = bytes(pcm_buffer),
                                mime_type = "audio/pcm;rate=16000"
                            )
                        )
                        pcm_buffer.clear()
                    except Exception as e:
                        logger.error(f"[Voice] send_realtime_input error: {e}")

            elif event == "stop":
                logger.info("[Voice] Stream stopped")
                break

        # Flush any remaining audio in buffer on exit
        if pcm_buffer and not stopped.is_set():
            try:
                await session.send_realtime_input(
                    audio=types.Blob(
                        data      = bytes(pcm_buffer),
                        mime_type = "audio/pcm;rate=16000"
                    )
                )
                pcm_buffer.clear()
            except Exception:
                pass

    except Exception as e:
        logger.error(f"[Voice] receive error: {e}")
    finally:
        stopped.set()


async def _send_to_twilio(
    websocket: WebSocket,
    session,
    state: dict,
    stopped: asyncio.Event
):
    try:
        # Loop continuously to keep the connection open across multiple conversation turns
        while not stopped.is_set():
            async for response in session.receive():
                if stopped.is_set():
                    break

                audio_bytes = None

                if hasattr(response, "server_content") and response.server_content:
                    sc = response.server_content

                    if hasattr(sc, "model_turn") and sc.model_turn and hasattr(sc.model_turn, "parts"):
                        for part in sc.model_turn.parts:
                            if hasattr(part, "inline_data") and part.inline_data and part.inline_data.data:
                                audio_bytes = part.inline_data.data
                            elif hasattr(part, "text") and part.text:
                                logger.info(f"[Voice] Bot text: {part.text}")

                    if hasattr(sc, "output_transcription") and sc.output_transcription and sc.output_transcription.text:
                        logger.info(f"[Voice] Bot spoken: {sc.output_transcription.text}")
                    if hasattr(sc, "input_transcription") and sc.input_transcription and sc.input_transcription.text:
                        logger.info(f"[Voice] User spoken: {sc.input_transcription.text}")

                # Log token usage metadata if provided in response
                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    um = response.usage_metadata
                    in_tokens  = getattr(um, "prompt_token_count", 0)
                    out_tokens = getattr(um, "candidates_token_count", 0)
                    tot_tokens = getattr(um, "total_token_count", 0)
                    logger.info(
                        f"[Usage] Tokens — Input: {in_tokens} | Output: {out_tokens} | Total: {tot_tokens}"
                    )

                if audio_bytes:
                    if state.get("waiting_for_first_audio") and state.get("last_user_speech_time"):
                        ttfa_ms = (time.perf_counter() - state["last_user_speech_time"]) * 1000
                        logger.info(f"⚡ [Latency] Time-To-First-Audio (TTFA): {ttfa_ms:.2f} ms")
                        state["waiting_for_first_audio"] = False
                    # 24kHz -> 8kHz resample with state persistence across chunks
                    pcm, state["ratecv_out_state"] = audioop.ratecv(
                        audio_bytes, SAMPLE_WIDTH, 1,
                        GEMINI_OUT, TWILIO_RATE,
                        state["ratecv_out_state"]
                    )
                    mulaw   = audioop.lin2ulaw(pcm, SAMPLE_WIDTH)
                    payload = base64.b64encode(mulaw).decode()
                    if state["stream_sid"]:
                        await websocket.send_text(json.dumps({
                            "event":     "media",
                            "streamSid": state["stream_sid"],
                            "media":     {"payload": payload}
                        }))
                        logger.info(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Audio chunk sent back to Twilio")

                if hasattr(response, "tool_call") and response.tool_call is not None:
                    # Instantly stream an authentic female Urdu verbal filler to Twilio (<50ms)
                    if state.get("stream_sid"):
                        try:
                            # Pick appropriate female verbal filler based on function call
                            filler_payload = VERBAL_FILLER_GENERAL
                            for fn in response.tool_call.function_calls:
                                if fn.name == "get_available_slots":
                                    filler_payload = VERBAL_FILLER_CHECKING
                                elif fn.name == "book_appointment":
                                    filler_payload = VERBAL_FILLER_BOOKING

                            await websocket.send_text(json.dumps({
                                "event":     "media",
                                "streamSid": state["stream_sid"],
                                "media":     {"payload": filler_payload}
                            }))
                            logger.info(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Sent female Urdu verbal filler to Twilio")
                        except Exception as e:
                            logger.warning(f"[Voice] Verbal filler send warning: {e}")

                    for fn in response.tool_call.function_calls:
                        t_start = datetime.now()
                        logger.info(f"[{t_start.strftime('%H:%M:%S.%f')[:-3]}] Function call started: {fn.name}")
                        try:
                            # 5-second timeout safeguard so a slow API never hangs the call
                            result = await asyncio.wait_for(
                                _handle_tool(fn.name, dict(fn.args), state),
                                timeout=5.0
                            )
                        except asyncio.TimeoutError:
                            logger.error(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Function call timed out: {fn.name}")
                            result = "Action timed out, but proceeding with booking details."
                        
                        t_end = datetime.now()
                        duration_ms = (t_end - t_start).total_seconds() * 1000
                        logger.info(f"[{t_end.strftime('%H:%M:%S.%f')[:-3]}] Function call completed: {fn.name} (Took {duration_ms:.1f}ms)")

                        await session.send_tool_response(
                            function_responses=[
                                types.FunctionResponse(
                                    id=fn.id,
                                    name=fn.name,
                                    response={"result": result}
                                )
                            ]
                        )

    except Exception as e:
        logger.error(f"[Voice] send error: {e}")
    finally:
        stopped.set()


async def _handle_tool(
    name: str,
    args: dict,
    state: dict
) -> str:

    logger.info(f"[Tool] {name} \u2192 {args}")

    if name == "get_available_slots":
        try:
            slots = await asyncio.to_thread(get_open_slots)
            if slots:
                return f"Available slots this week:\n" + "\n".join(slots)
            return "No slots available this week."
        except Exception as e:
            return f"Could not fetch slots: {e}"

    elif name == "book_appointment":
        try:
            logger.info(f"[Tool] Booking: {args}")
            result = await asyncio.to_thread(
                create_booking,
                args.get("patient_name", "Unknown"),
                args.get("patient_phone", ""),
                args.get("date_str", ""),
                args.get("time_str", ""),
                args.get("procedure", "Dental Appointment")
            )
            logger.info(f"[Tool] create_booking returned: {result}")

            if result:  # create_booking returns True/False
                # Register patient in Supabase if new
                try:
                    patient = await asyncio.to_thread(
                        get_patient, args.get("patient_phone", "")
                    )
                    if not patient:
                        await asyncio.to_thread(
                            register_patient,
                            args.get("patient_name", "Unknown"),
                            args.get("patient_phone", "")
                        )
                        logger.info("[Tool] New patient registered in Supabase")
                except Exception as e:
                    logger.warning(f"[Tool] Patient DB registration failed: {e}")

                # Notify doctor in background task (non-blocking)
                def _bg_notify():
                    try:
                        notify_doctor(
                            f"NEW BOOKING via Voice Call:\n"
                            f"Patient: {args.get('patient_name', 'Unknown')}\n"
                            f"Phone: {args.get('patient_phone', '')}\n"
                            f"Date: {args.get('date_str', '')}\n"
                            f"Time: {args.get('time_str', '')}\n"
                            f"Procedure: {args.get('procedure', 'Dental Appointment')}"
                        )
                    except Exception as e:
                        logger.warning(f"[Tool] Doctor notification failed: {e}")

                asyncio.create_task(asyncio.to_thread(_bg_notify))

                return f"Appointment booked successfully! {args.get('patient_name', '')} ka appointment {args.get('date_str', '')} ko {args.get('time_str', '')} par book ho gaya."
            else:
                return "Booking failed — slot may already be taken or calendar error."
        except Exception as e:
            logger.error(f"[Tool] book_appointment error: {e}")
            return f"Booking failed: {e}"

    elif name == "cancel_appointment":
        try:
            logger.info(f"[Tool] Cancelling: {args}")
            result = await asyncio.to_thread(
                cancel_booking,
                args.get("patient_phone", ""),
                args.get("date_str", ""),
                args.get("time_str", "")
            )
            logger.info(f"[Tool] cancel_booking returned: {result}")
            if result:  # cancel_booking returns True/False
                return "Appointment cancelled successfully!"
            else:
                return "Could not find appointment to cancel — check phone number, date and time."
        except Exception as e:
            logger.error(f"[Tool] cancel_appointment error: {e}")
            return f"Cancellation failed: {e}"

    elif name == "transfer_to_doctor":
        doctor = args.get("doctor", "dr_mustafa")
        if doctor == "dr_mustafa":
            dest_number = DR_MUSTAFA_NUMBER
            doctor_name = "Dr. Mustafa"
        elif doctor == "dr_qasim":
            dest_number = DR_QASIM_NUMBER
            doctor_name = "Dr. Qasim"
        else:
            dest_number = EMERGENCY_NUMBER or DR_MUSTAFA_NUMBER
            doctor_name = "Emergency"

        logger.info(f"[Tool] Call transfer requested to {doctor_name} ({dest_number})")

        if state.get("call_sid") and dest_number:
            try:
                client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
                ws_url = NGROK_URL.replace("https://", "wss://")
                twiml_transfer = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Aditi" language="en-IN">Please hold while I transfer your call to {doctor_name}.</Say>
  <Dial callerId="{dest_number}">
    <Number>{dest_number}</Number>
  </Dial>
</Response>"""
                await asyncio.to_thread(
                    client.calls(state["call_sid"]).update,
                    twiml=twiml_transfer
                )
                return f"Call transfer initiated to {doctor_name}."
            except Exception as e:
                logger.error(f"[Tool] Transfer failed: {e}")
                return f"Transfer failed: {e}"

        return f"Could not transfer — phone number for {doctor_name} is missing."

    return "Unknown tool called."
