import asyncio
import os
import bcrypt
import jwt as pyjwt
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, WebSocket, BackgroundTasks, HTTPException
from fastapi.responses import Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
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

# ── CORS — allow the admin portal (file:// and any origin) ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # lock this down to your domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── JWT config ────────────────────────────────────────────────────────────────
JWT_SECRET    = os.getenv("JWT_SECRET", "cmd-portal-secret-change-in-prod")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 12

# ── Supabase (service role — never exposed to frontend) ──────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")   # service role key

def get_supabase():
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Pydantic request models ───────────────────────────────────────────────────
class PinLoginRequest(BaseModel):
    pin: str

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


# ── Admin Portal: PIN Login ───────────────────────────────────────────────────
@app.post("/api/admin/auth/login")
async def admin_login(body: PinLoginRequest):
    """
    Verifies a 6-digit PIN against the bcrypt hash stored in the doctors table.
    Returns a signed JWT + doctor info on success, 401 on wrong PIN.
    """
    pin = body.pin.strip()

    if len(pin) != 6 or not pin.isdigit():
        raise HTTPException(status_code=400, detail="PIN must be exactly 6 digits.")

    try:
        sb = get_supabase()
        result = sb.table("doctors").select("id, name, display_name, role, pin_hash").execute()
        doctors = result.data or []
    except Exception as e:
        print(f"[Auth] Supabase error: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable.")

    # Check PIN against every doctor's bcrypt hash
    matched_doctor = None
    for doc in doctors:
        stored_hash = doc.get("pin_hash", "")
        try:
            if bcrypt.checkpw(pin.encode(), stored_hash.encode()):
                matched_doctor = doc
                break
        except Exception:
            continue

    if not matched_doctor:
        raise HTTPException(status_code=401, detail="Wrong PIN.")

    # Issue JWT valid for JWT_EXPIRE_HOURS
    payload = {
        "sub":  str(matched_doctor["id"]),
        "name": matched_doctor["name"],
        "role": matched_doctor["role"],
        "exp":  datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    token = pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

    doctor_info = {
        "id":           matched_doctor["id"],
        "name":         matched_doctor["name"],
        "display_name": matched_doctor.get("display_name") or matched_doctor["name"],
        "role":         matched_doctor["role"],
    }

    print(f"[Auth] ✅ Login: {doctor_info['name']}")
    return JSONResponse({"token": token, "doctor": doctor_info})


@app.get("/api/admin/auth/me")
async def admin_me(request: Request):
    """Verify a JWT and return the doctor payload. Used on page refresh to restore session."""
    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="No token provided.")
    try:
        payload = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return JSONResponse({"id": payload["sub"], "name": payload["name"], "role": payload["role"]})
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired.")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token.")
