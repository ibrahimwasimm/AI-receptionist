import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import Response
from dotenv import load_dotenv
load_dotenv()

from reminders import reminder_loop
from whatsapp_handler import verify_webhook, whatsapp_webhook


# ─────────────────────────────────────────────────────────────────────────────
# Lifespan: start / stop background reminder task
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the 24-hr reminder background coroutine
    task = asyncio.create_task(reminder_loop())
    yield
    # Graceful shutdown
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Dental Clinic AI Bot — WhatsApp", lifespan=lifespan)


@app.get("/")
def root():
    return {"status": "Dental bot is running ✅", "channel": "WhatsApp via Meta API"}


# ── WhatsApp webhook ─────────────────────────────────────────────────────────

@app.get("/webhook/whatsapp")
async def webhook_verify(request: Request) -> Response:
    """Meta webhook verification handshake (one-time setup)."""
    return await verify_webhook(request)


@app.post("/webhook/whatsapp")
async def webhook_receive(request: Request) -> Response:
    """Receive incoming WhatsApp messages from Meta."""
    return await whatsapp_webhook(request)


# ─────────────────────────────────────────────────────────────────────────────
# Run locally:  uvicorn main:app --reload --port 8000
# ─────────────────────────────────────────────────────────────────────────────
