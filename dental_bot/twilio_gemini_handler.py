import os
import json
import base64
import asyncio
import audioop
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
    logger.info(f"[Voice] Incoming call from {caller_number}")
    ws_url = NGROK_URL.replace("https://", "wss://")
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
        "stream_sid":    None,
        "call_sid":      None,
        "caller_number": None,
    }

    try:
        open_slots = await asyncio.to_thread(get_open_slots)
        slots_text = "\n".join(open_slots) if open_slots \
                     else "No slots available this week."
    except Exception:
        slots_text = "Could not load slots."

    gemini_client = genai.Client(api_key=GEMINI_API_KEY)

    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
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
"Assalam u Alaikum! {CLINIC_NAME} mein khush aamdeed. Main Sana hoon. Aap ki kya madad kar sakti hoon?"

════ CLINIC INFO ════
Timings : Monday to Saturday, sham 5 baje se raat 10 baje tak
Closed  : Sunday
Doctors : Dr. Mustafa aur Dr. Qasim
Fees    : Consultation par bata denge

════ AVAILABLE SLOTS ════
{slots_text}

════ APPOINTMENT BOOKING ════
1. Pucho: kya masla hai?
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

════ RULES ════
1. SIRF Urdu ya Roman Urdu mein jawab do
2. Short jawab — max 2-3 sentences
3. Warm, natural aur professional raho
4. Apni AI identity mat batao"""
    )

    stopped = asyncio.Event()

    try:
        async with gemini_client.aio.live.connect(
            model="gemini-2.5-flash-native-audio-latest",
            config=config
        ) as session:
            logger.info("[Voice] Gemini Live session opened")

            # Trigger immediate Urdu greeting
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
                state["caller_number"] = params.get(
                    "caller", "unknown"
                )
                logger.info(
                    f"[Voice] Stream started | "
                    f"Caller: {state['caller_number']}"
                )

            elif event == "media":
                raw = base64.b64decode(
                    data["media"]["payload"]
                )
                pcm = audioop.ulaw2lin(raw, SAMPLE_WIDTH)
                pcm, _ = audioop.ratecv(
                    pcm, SAMPLE_WIDTH, 1,
                    TWILIO_RATE, GEMINI_IN, None
                )
                try:
                    await session.send_realtime_input(
                        audio=types.Blob(
                            data=pcm,
                            mime_type="audio/pcm;rate=16000"
                        )
                    )
                except Exception as e:
                    logger.error(f"[Gemini] send_audio error: {e}")
                    break

            elif event == "stop":
                logger.info("[Voice] Stream stopped")
                break

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
        async for response in session.receive():
            if stopped.is_set():
                break
            audio_bytes = None
            if hasattr(response, "data") and response.data is not None:
                try:
                    audio_bytes = response.data
                except Exception:
                    pass

            if not audio_bytes and hasattr(response, "server_content") and response.server_content:
                sc = response.server_content
                if hasattr(sc, "model_turn") and sc.model_turn and hasattr(sc.model_turn, "parts"):
                    for part in sc.model_turn.parts:
                        if hasattr(part, "inline_data") and part.inline_data and part.inline_data.data:
                            audio_bytes = part.inline_data.data
                            break

            if audio_bytes:
                pcm, _ = audioop.ratecv(
                    audio_bytes, SAMPLE_WIDTH, 1,
                    GEMINI_OUT, TWILIO_RATE, None
                )
                mulaw   = audioop.lin2ulaw(pcm, SAMPLE_WIDTH)
                payload = base64.b64encode(mulaw).decode()
                if state["stream_sid"]:
                    await websocket.send_text(json.dumps({
                        "event":     "media",
                        "streamSid": state["stream_sid"],
                        "media":     {"payload": payload}
                    }))

            if hasattr(response, "text") and response.text:
                logger.info(
                    f"[Voice] Transcript: {response.text}"
                )

            if (hasattr(response, "tool_call") and
                    response.tool_call is not None):
                for fn in response.tool_call.function_calls:
                    result = await _handle_tool(
                        fn.name,
                        dict(fn.args),
                        state
                    )
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
                return f"Available: {', '.join(slots)}"
            return "No slots available this week."
        except Exception as e:
            logger.error(f"[Tool] get_open_slots: {e}")
            return "Could not fetch slots."

    elif name == "book_appointment":
        try:
            patient_name  = args.get("patient_name", "Patient")
            patient_phone = args.get(
                "patient_phone",
                state["caller_number"]
            )
            date_str  = args["date_str"]
            time_str  = args["time_str"]
            procedure = args.get(
                "procedure", "Dental Appointment"
            )

            await asyncio.to_thread(
                register_patient,
                patient_phone,
                patient_name
            )

            success = await asyncio.to_thread(
                create_booking,
                patient_name=patient_name,
                phone=patient_phone,
                date_str=date_str,
                time_str=time_str,
                procedure=procedure
            )

            if success:
                slot_time = datetime.strptime(
                    f"{date_str} {time_str}",
                    "%Y-%m-%d %H:%M"
                ).replace(
                    tzinfo=ZoneInfo("Asia/Karachi")
                )
                supabase.table("appointments").insert({
                    "patient_phone": patient_phone,
                    "patient_name":  patient_name,
                    "procedure":     procedure,
                    "slot_time":     slot_time.isoformat(),
                    "booked":        True
                }).execute()

                await asyncio.to_thread(
                    notify_doctor,
                    patient_name,
                    patient_phone,
                    date_str,
                    time_str
                )

                logger.info(
                    f"[Tool] Booked: {patient_name} "
                    f"{date_str} {time_str}"
                )
                return (
                    f"Booked. {patient_name} on "
                    f"{date_str} at {time_str} "
                    f"for {procedure}."
                )
            else:
                return "Slot taken. Offer another time."

        except Exception as e:
            logger.error(f"[Tool] book_appointment: {e}")
            return "Booking failed. Try again."

    elif name == "cancel_appointment":
        try:
            phone    = args.get(
                "patient_phone",
                state["caller_number"]
            )
            date_str = args["date_str"]
            time_str = args["time_str"]

            await asyncio.to_thread(
                cancel_booking,
                phone=phone,
                date_str=date_str,
                time_str=time_str
            )

            logger.info(
                f"[Tool] Cancelled: {phone} "
                f"{date_str} {time_str}"
            )
            return f"Cancelled {date_str} at {time_str}."

        except Exception as e:
            logger.error(f"[Tool] cancel_appointment: {e}")
            return "Cancellation failed."

    elif name == "transfer_to_doctor":
        doctor = args.get("doctor", "emergency")
        await _transfer_call(state["call_sid"], doctor)
        return f"Transferring to {doctor}."

    return "Unknown tool."


async def _transfer_call(call_sid: str, doctor: str):
    numbers = {
        "dr_mustafa": DR_MUSTAFA_NUMBER,
        "dr_qasim":   DR_QASIM_NUMBER,
        "emergency":  EMERGENCY_NUMBER,
    }
    target = numbers.get(doctor, EMERGENCY_NUMBER)

    if not call_sid:
        logger.error("[Transfer] No call_sid")
        return
    if not target:
        logger.error(f"[Transfer] No number for {doctor}")
        return

    try:
        twilio = TwilioClient(
            TWILIO_ACCOUNT_SID,
            TWILIO_AUTH_TOKEN
        )
        await asyncio.to_thread(
            lambda: twilio.calls(call_sid).update(
                twiml=f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say language="ur-PK">
    Aap ko doctor se connect kar rahi hoon.
    Ek moment please.
  </Say>
  <Dial>{target}</Dial>
</Response>"""
            )
        )
        logger.info(
            f"[Transfer] {call_sid} \u2192 {doctor} {target}"
        )
    except Exception as e:
        logger.error(f"[Transfer] Failed: {e}")
