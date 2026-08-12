import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response
from fastapi import BackgroundTasks
from dotenv import load_dotenv
load_dotenv()

from reminders import reminder_loop
from whatsapp_handler import verify_webhook, whatsapp_webhook
from twilio_gemini_handler import voice_webhook, media_stream

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(reminder_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

app = FastAPI(
    title="Dental Clinic AI Bot — WhatsApp + Voice",
    lifespan=lifespan
)


@app.get("/")
def root():
    return {
        "status": "Dental bot is running ✅",
        "channels": "WhatsApp + Voice"
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

@app.post("/webhook/voice")
@app.post("/voice")
async def twilio_voice(request: Request) -> Response:
    return await voice_webhook(request)

@app.websocket("/media-stream")
async def websocket_endpoint(websocket: WebSocket):
    await media_stream(websocket)
