from openai import OpenAI
import re
import os
from dotenv import load_dotenv
load_dotenv(override=True)

from database import supabase
import gcal
import httpx

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

CLINIC_NAME = os.getenv("CLINIC_NAME", "Smile Dental Clinic")

# Global memory to store the last few messages for each phone number
CONVERSATION_HISTORY = {}


# ─────────────────────────────────────────────────────────────────────────────
# Patient helpers (Supabase)
# ─────────────────────────────────────────────────────────────────────────────

def get_patient(phone: str) -> dict | None:
    """Look up a patient by phone number. Returns dict or None."""
    result = supabase.table("patients").select("*").eq("phone", phone).execute()
    return result.data[0] if result.data else None


def register_patient(phone: str, name: str) -> None:
    """Auto-register a new patient if they are not in the DB."""
    existing = supabase.table("patients").select("id").eq("phone", phone).execute()
    if not existing.data:
        supabase.table("patients").insert({"name": name, "phone": phone}).execute()


def notify_doctor(patient_name: str, patient_phone: str, date_str: str, time_str: str):
    """Sends an instant WhatsApp notification to the Doctor."""
    token = os.getenv("META_ACCESS_TOKEN")
    phone_id = os.getenv("META_PHONE_NUMBER_ID")
    doctor_phone = os.getenv("DOCTOR_PHONE_NUMBER", "923202042302")  # Using your testing number
    
    message = f"🔔 *NEW BOOKING ALERT* 🔔\n\n*Patient:* {patient_name}\n*Phone:* {patient_phone}\n*Date:* {date_str}\n*Time:* {time_str}\n\n✅ This has been automatically added to your Google Calendar."
    
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": doctor_phone,
        "type": "text",
        "text": {"body": message}
    }
    
    try:
        httpx.post(f"https://graph.facebook.com/v19.0/{phone_id}/messages", headers=headers, json=payload, timeout=10.0)
    except Exception as e:
        print(f"[Doctor Notification Failed] {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Gemini AI logic
# ─────────────────────────────────────────────────────────────────────────────

def build_system_prompt(patient: dict | None, open_slots: list[str], phone: str) -> str:
    slots_text = "\n".join(open_slots) if open_slots else "No slots available this week."

    patient_ctx = ""
    if patient:
        patient_ctx = f"""
Patient record found:
- Name: {patient['name']}
- Phone: {phone}
- Last procedure: {patient.get('last_proc') or 'not on record'}
- Notes: {patient.get('notes') or 'none'}
"""

    return f"""You are a warm, professional dental receptionist at {CLINIC_NAME}.
You help patients book, reschedule, or cancel appointments via WhatsApp.
Keep all replies SHORT — this is WhatsApp, not email. Max 3 sentences.
Never mention that you are an AI. Sound human and friendly.
Clinic hours are 5:00 PM to 10:00 PM.
{patient_ctx}
Available appointment slots this week:
{slots_text}

BOOKING RULE:
When a patient confirms a specific slot, end your reply with this hidden tag on a new line:
BOOK:YYYY-MM-DD:HH:MM
Example: BOOK:2025-04-20:10:00

CANCELLATION RULE:
When a patient cancels, end your reply with:
CANCEL:YYYY-MM-DD:HH:MM

Do not show these tags to the patient. They are parsed by the system."""


def handle_message(phone: str, incoming_message: str, patient_name: str = "Unknown Patient") -> str:
    """Main entry point. Takes the patient's phone + message, returns reply text."""
    patient = get_patient(phone)
    
    # If this is a completely brand new patient, register them automatically!
    if not patient:
        register_patient(phone, patient_name)
        patient = get_patient(phone) # Re-fetch so we have their dictionary properly loaded

    # Get available slots from Google Calendar
    open_slots = gcal.get_open_slots()

    # Initialize memory if new phone
    if phone not in CONVERSATION_HISTORY:
        CONVERSATION_HISTORY[phone] = []

    # Append the newest user message
    CONVERSATION_HISTORY[phone].append({"role": "user", "content": incoming_message})

    # Build standard OpenAI messages array
    messages = [{"role": "system", "content": build_system_prompt(patient, open_slots, phone)}]
    messages.extend(CONVERSATION_HISTORY[phone])

    # Send the entire recent history to OpenRouter
    try:
        response = client.chat.completions.create(
            model="inclusionai/ling-2.6-1t:free",
            messages=messages
        )
        reply: str = response.choices[0].message.content
    except Exception as e:
        print(f"[OpenRouter Error] {e}")
        # Remove the latest user message from history so it doesn't corrupt sequence
        CONVERSATION_HISTORY[phone].pop()
        return "I'm sorry, our AI booking assistant is currently unavailable. Please try again later."

    # ── Parse and act on BOOK tag ────────────────────────────────────────────
    book_match = re.search(r"BOOK:(\d{4}-\d{2}-\d{2}):(\d{2}:\d{2})", reply)
    if book_match and patient:
        date_str, time_str = book_match.group(1), book_match.group(2)
        success = gcal.create_booking(
            patient_name=patient["name"],
            phone=phone,
            date_str=date_str,
            time_str=time_str,
        )
        reply = reply[: book_match.start()].strip()
        if not success:
            reply += "\n\nSorry, that slot was just taken. Please choose another time."
        else:
            if not reply:
                reply = f"Perfect! Your appointment for {date_str} at {time_str} is confirmed. We look forward to seeing you!"
            # Ping the doctor on WhatsApp!
            notify_doctor(patient["name"], phone, date_str, time_str)

    # ── Parse and act on CANCEL tag ──────────────────────────────────────────
    cancel_match = re.search(r"CANCEL:(\d{4}-\d{2}-\d{2}):(\d{2}:\d{2})", reply)
    if cancel_match and patient:
        date_str, time_str = cancel_match.group(1), cancel_match.group(2)
        gcal.cancel_booking(phone=phone, date_str=date_str, time_str=time_str)
        reply = reply[: cancel_match.start()].strip()
        if not reply:
            reply = f"Your appointment on {date_str} at {time_str} has been canceled."

    # Save the final cleaned reply to the conversation history
    CONVERSATION_HISTORY[phone].append({"role": "assistant", "content": reply})
    
    # Keep only the last 6 messages (3 turns) so we don't accidentally exceed token limits
    CONVERSATION_HISTORY[phone] = CONVERSATION_HISTORY[phone][-6:]

    return reply
