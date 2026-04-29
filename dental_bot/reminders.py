import asyncio
import os
import httpx
from datetime import datetime, date, timedelta
from database import supabase
from dotenv import load_dotenv

load_dotenv()

META_ACCESS_TOKEN    = os.getenv("META_ACCESS_TOKEN")
META_PHONE_NUMBER_ID = os.getenv("META_PHONE_NUMBER_ID")
CLINIC_NAME          = os.getenv("CLINIC_NAME", "Smile Dental Clinic")

GRAPH_API_URL = f"https://graph.facebook.com/v19.0/{META_PHONE_NUMBER_ID}/messages"


# ─────────────────────────────────────────────────────────────────────────────
# Send a WhatsApp message (shared helper, same as in whatsapp_handler.py)
# ─────────────────────────────────────────────────────────────────────────────

async def send_whatsapp_message(to: str, text: str) -> None:
    """
    `to` — patient phone WITHOUT '+', e.g. '923001234567'
    """
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type":  "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type":    "individual",
        "to":                to,
        "type":              "text",
        "text":              {"body": text},
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(GRAPH_API_URL, headers=headers, json=payload)
        if resp.status_code != 200:
            print(f"[Reminder] ❌ Send failed for {to}: {resp.text}")


# ─────────────────────────────────────────────────────────────────────────────
# Core reminder logic
# ─────────────────────────────────────────────────────────────────────────────

async def send_reminders() -> None:
    """
    Query Supabase for all appointments tomorrow that haven't had a reminder sent.
    Send a WhatsApp reminder to each patient via Meta API and mark reminder_sent=True.
    """
    tomorrow = date.today() + timedelta(days=1)
    day_start = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0,  0).isoformat()
    day_end   = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 23, 59).isoformat()

    result = (
        supabase.table("appointments")
        .select("*")
        .gte("slot_time", day_start)
        .lte("slot_time", day_end)
        .eq("booked", True)
        .eq("reminder_sent", False)
        .execute()
    )

    if not result.data:
        print("[Reminder] No pending reminders for tomorrow.")
        return

    for appt in result.data:
        # Meta expects phone without '+'; Supabase stores it with '+'
        phone = appt["patient_phone"].lstrip("+")

        try:
            dt           = datetime.fromisoformat(appt["slot_time"].replace("Z", ""))
            time_display = dt.strftime("%I:%M %p")   # e.g. "10:00 AM"
            date_display = dt.strftime("%A, %B %d")  # e.g. "Monday, April 20"
        except Exception:
            time_display = appt["slot_time"]
            date_display = "tomorrow"

        message = (
            f"Hi {appt['patient_name']}! 👋 Reminder from {CLINIC_NAME}: "
            f"you have a dental appointment on {date_display} at {time_display}. "
            f"Please arrive 10 minutes early. Reply CANCEL if you need to reschedule."
        )

        await send_whatsapp_message(phone, message)

        # Mark reminder as sent so we don't send duplicates
        supabase.table("appointments").update({"reminder_sent": True}).eq(
            "id", appt["id"]
        ).execute()

        print(f"[Reminder] ✅ Sent to {appt['patient_name']} ({phone}) — {appt['slot_time']}")


# ─────────────────────────────────────────────────────────────────────────────
# Background loop  (started by FastAPI lifespan)
# ─────────────────────────────────────────────────────────────────────────────

async def reminder_loop() -> None:
    """Runs forever. Checks Supabase every hour and dispatches WhatsApp reminders."""
    print("[Reminder] 🔄 Background scheduler started — checking every hour.")
    while True:
        await asyncio.sleep(3600)  # wait 1 hour between checks
        try:
            await send_reminders()
        except Exception as e:
            print(f"[Reminder] ❌ Unexpected error: {e}")
