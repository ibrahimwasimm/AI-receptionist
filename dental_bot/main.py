import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, WebSocket, BackgroundTasks
from fastapi.responses import Response, JSONResponse
from dotenv import load_dotenv
load_dotenv()

from reminders import reminder_loop
from whatsapp_handler import verify_webhook, whatsapp_webhook

# Optional voice handler (gracefully disabled in messaging-only mode)
try:
    from twilio_gemini_handler import voice_webhook, media_stream
    VOICE_AVAILABLE = True
except Exception as e:
    print(f"[Server] Running in Messaging-Only mode (Voice handler skipped: {e})")
    VOICE_AVAILABLE = False

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start automated WhatsApp appointment reminder background scheduler
    task = asyncio.create_task(reminder_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

app = FastAPI(
    title="Dental Clinic AI Receptionist — WhatsApp Messaging",
    description="Automated AI receptionist for patient inquiries, appointments, and reminders on WhatsApp.",
    lifespan=lifespan
)

@app.get("/")
def root():
    return {
        "status": "Dental Clinic AI Receptionist is running ✅",
        "channel": "WhatsApp Cloud API",
        "features": [
            "AI Patient Inquiries & FAQs",
            "Real-time Google Calendar Booking & Rescheduling",
            "Supabase Patient Records Sync",
            "Instant Doctor WhatsApp Alerts",
            "Automated Daily Appointment Reminders"
        ],
        "voice_calling_enabled": VOICE_AVAILABLE
    }

@app.get("/webhook/whatsapp")
async def webhook_verify(request: Request) -> Response:
    return await verify_webhook(request)

@app.post("/webhook/whatsapp")
async def webhook_receive(
    request: Request,
    background_tasks: BackgroundTasks
) -> Response:
    return await whatsapp_webhook(request, background_tasks)

# Optional voice endpoints (kept dormant or fallback if voice called)
@app.post("/webhook/voice")
@app.post("/voice")
async def twilio_voice(request: Request) -> Response:
    if VOICE_AVAILABLE:
        return await voice_webhook(request)
    return Response(content="<Response><Say>Voice calling is currently disabled. Please contact us on WhatsApp.</Say></Response>", media_type="application/xml")

@app.websocket("/media-stream")
async def websocket_endpoint(websocket: WebSocket):
    if VOICE_AVAILABLE:
        await media_stream(websocket)
    else:
        await websocket.close()

