import re
import os
from dotenv import load_dotenv
load_dotenv(override=True)

from database import supabase
import gcal
import httpx
from google import genai
from google.genai import types

gemini_api_key = os.getenv("GEMINI_API_KEY")
gemini_client = genai.Client(api_key=gemini_api_key) if gemini_api_key else None

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


import json
from datetime import datetime

# ─────────────────────────────────────────────────────────────────────────────
# Doctor Notification Lookup & Registry
# ─────────────────────────────────────────────────────────────────────────────
# Test stand-in doctor number: 0331-1286436 -> "923311286436"
DOCTOR_WHATSAPP_NUMBER = os.getenv("DOCTOR_WHATSAPP_NUMBER", "923311286436")

# Lookup mapping doctor_id -> WhatsApp configuration
# When ready for Dr. Musafer and Dr. Kassa, update phone numbers here or in .env
DOCTOR_REGISTRY = {
    "default": {
        "name": "Dr. on Duty",
        "whatsapp_number": DOCTOR_WHATSAPP_NUMBER,
    },
    "dr_musafer": {
        "name": "Dr. Musafer",
        "whatsapp_number": os.getenv("DR_MUSAFER_WHATSAPP", DOCTOR_WHATSAPP_NUMBER),
    },
    "dr_kassa": {
        "name": "Dr. Kassa",
        "whatsapp_number": os.getenv("DR_KASSA_WHATSAPP", DOCTOR_WHATSAPP_NUMBER),
    },
}


def send_doctor_notification(booking: dict) -> bool:
    """
    Sends an instant WhatsApp notification to the assigned doctor right after
    a booking is successfully created in Supabase.
    """
    doctor_id = booking.get("doctor_id", "default")
    doctor_info = DOCTOR_REGISTRY.get(doctor_id, DOCTOR_REGISTRY["default"])
    doctor_name = doctor_info["name"]
    doctor_phone = doctor_info["whatsapp_number"]

    token = os.getenv("META_ACCESS_TOKEN")
    phone_id = os.getenv("META_PHONE_NUMBER_ID")

    if not token or not phone_id:
        print("[Doctor Notification] META credentials missing in .env — skipping doctor alert.")
        return False

    patient_name = booking.get("patient_name", "Unknown Patient")
    patient_phone = booking.get("patient_phone", "")
    date_str = booking.get("date_str", "")
    time_str = booking.get("time_str", "")
    procedure = booking.get("procedure", "Dental Consultation")
    notes = booking.get("notes") or "Booked via WhatsApp AI Receptionist"

    message = (
        f"🔔 *NEW BOOKING ALERT* 🔔\n\n"
        f"👨‍⚕️ *Doctor:* {doctor_name}\n"
        f"👤 *Patient:* {patient_name}\n"
        f"📞 *Phone:* +{patient_phone}\n"
        f"📅 *Date:* {date_str}\n"
        f"⏰ *Time:* {time_str}\n"
        f"🦷 *Procedure:* {procedure}\n"
        f"📝 *Notes:* {notes}\n\n"
        f"✅ *Status:* Automatically recorded in Google Calendar & Supabase."
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": doctor_phone,
        "type": "text",
        "text": {"body": message}
    }

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[Doctor Notification] [{timestamp}] Sending alert to {doctor_name} ({doctor_phone})")
    print(f"[Doctor Notification] Outgoing Payload:\n{json.dumps(payload, indent=2)}")

    try:
        url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
        resp = httpx.post(url, headers=headers, json=payload, timeout=12.0)
        if resp.status_code == 200:
            msg_id = resp.json().get("messages", [{}])[0].get("id", "OK")
            print(f"[Doctor Notification] [{timestamp}] ✅ Sent successfully to {doctor_phone} (Message ID: {msg_id})")
            return True
        else:
            print(f"[Doctor Notification] [{timestamp}] ❌ Meta API Error {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        print(f"[Doctor Notification] [{timestamp}] ❌ Failed: {e}")
        return False


def notify_doctor(patient_name: str, patient_phone: str, date_str: str, time_str: str):
    """Backwards-compatible wrapper for existing callers."""
    return send_doctor_notification({
        "patient_name": patient_name,
        "patient_phone": patient_phone,
        "date_str": date_str,
        "time_str": time_str,
        "procedure": "Dental Appointment"
    })



# ─────────────────────────────────────────────────────────────────────────────
# Gemini AI logic
# ─────────────────────────────────────────────────────────────────────────────

def build_system_prompt(patient: dict | None, open_slots: list[str], phone: str) -> str:
    slots_text = "\n".join(open_slots) if open_slots else "No slots available this week."

    patient_ctx = ""
    if patient:
        patient_ctx = f"""
=== RETURNING PATIENT RECORD ===
- Name       : {patient['name']}
- Phone      : {phone}
- Last Visit : {patient.get('last_proc') or 'not on record'}
- Notes      : {patient.get('notes') or 'none'}
================================
"""
    else:
        patient_ctx = "\n=== NEW PATIENT (no record found — greet warmly and ask for name) ===\n"

    return f"""You are Sana, a warm and professional dental receptionist at {CLINIC_NAME}.
You assist patients via WhatsApp — booking, rescheduling, or canceling appointments,
answering questions about procedures and fees, and providing general clinic information.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CLINIC INFORMATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Clinic Name    : {CLINIC_NAME}
Working Hours  : Monday to Saturday, 5:00 PM – 10:00 PM
Off Days       : Sunday (closed)
Location       : Grey Skyline, Block 13, Jauhar Chowrangi Road, Gulistan-e-Johar, Karachi (786 Medical Store se jo andar road ja rahi hai, us road par seedha andar Hussaini Blood Bank hai, wahan hi clinic hai). Google Maps: https://maps.app.goo.gl/7NfZMQEBh1HTo5bw8
Language       : Respond in the same language the patient uses.
                 If they write in Urdu (Roman or script), reply in Urdu.
                 If English, reply in English.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DENTAL SERVICES & PROCEDURES OFFERED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
If a patient asks about fees, tell them fees and customized treatment plans are confirmed during the in-person consultation.

1. CONSULTATION
   - Comprehensive dental check-up, oral examination, and doctor advice for new and follow-up patients.

2. ROOT CANAL (RCT)
   - Root canal treatment for decayed, infected, or painful teeth to save the natural tooth.

3. ORAL CLEANING (SCALING & POLISHING)
   - Professional teeth scaling and polishing for plaque/tartar removal, gum health, and stain cleaning.

4. WHITENING (TEETH WHITENING)
   - Professional in-clinic teeth whitening treatment for a brighter, cleaner smile.

5. IMPLANT & BRIDGE
   - Dental Implants (permanent artificial tooth roots) and Dental Bridges (fixed prosthetics) to replace missing teeth.

6. BRACES (ORTHODONTICS)
   - Orthodontic braces for teeth alignment, fixing gaps, and bite correction.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PATIENT CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{patient_ctx}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AVAILABLE APPOINTMENT SLOTS THIS WEEK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{slots_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BEHAVIOR RULES (STRICTLY FOLLOW THESE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. IDENTITY      : Never reveal you are an AI. You are Sana, a human receptionist.
                   If asked, say "I'm Sana from {CLINIC_NAME}, how can I help you?"

2. WHATSAPP TONE : Keep replies SHORT and conversational. Max 3–4 sentences per reply.
                   No long paragraphs. Use line breaks for clarity.
                   Use emojis sparingly (1–2 max) to stay friendly.

3. BOOKING FLOW  :
   Step 1 → Ask what procedure/issue the patient needs help with.
   Step 2 → Share available slots (already listed above).
   Step 3 → Ask the patient to confirm a specific slot.
   Step 4 → Confirm the booking warmly.
   → Once confirmed, add the hidden BOOK tag (see below). Never show the tag.

4. RESCHEDULING  : Ask which appointment they want to change, cancel the old one
                   (CANCEL tag), then help them pick a new slot (BOOK tag).

5. NEW PATIENTS  : If no patient record exists, warmly introduce yourself, ask for
                   their name, then proceed with booking.

6. PROCEDURE INFO: If a patient asks about a procedure or cost, give a brief
                   friendly summary using the procedure list above.
                   Always say "exact fees are confirmed at your consultation".

7. OUT-OF-SCOPE  : If asked about something unrelated to the clinic or dentistry,
                   politely say "I can only help with clinic appointments and dental
                   info. For any other inquiries, please leave a message here and our staff will assist you."

8. EMERGENCIES   : If patient mentions severe pain, swelling, or trauma, prioritize
                   them. Say "This sounds urgent — we can see you today or tomorrow.
                   Which slot works for you?" and list same-day slots first.

9. LANGUAGE      : Match the patient's language at all times. If they switch, you switch.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SYSTEM TAGS (HIDDEN — NEVER SHOW TO PATIENT)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BOOKING TAG    : When a patient confirms a slot, append on a new line at the very end:
                 BOOK:YYYY-MM-DD:HH:MM:Procedure Name
                 Example: BOOK:2025-04-20:17:00:Root Canal

CANCELLATION TAG: When a patient cancels an appointment, append on a new line:
                 CANCEL:YYYY-MM-DD:HH:MM
                 Example: CANCEL:2025-04-20:17:00

IMPORTANT: These tags are parsed by the system. They must appear on their own line
at the very end of your message. Never explain or mention them to the patient."""


GEMINI_MODELS = [
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-2.5-flash-lite",
    "gemini-flash-latest"
]

def get_chat_completion(system_prompt: str, conversation_history: list) -> str:
    """Generate response using Google Gemini API exclusively."""
    if not gemini_client:
        print("[Gemini] ERROR: GEMINI_API_KEY is not configured.")
        return "Assalam o Alaikum! Our system is currently being updated. A clinic representative will assist you shortly."

    # Format multi-turn conversation history for Gemini
    contents = []
    for turn in conversation_history:
        role = "user" if turn["role"] == "user" else "model"
        contents.append(types.Content(
            role=role,
            parts=[types.Part.from_text(text=turn["content"])]
        ))

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=0.7,
    )

    for g_model in GEMINI_MODELS:
        try:
            resp = gemini_client.models.generate_content(
                model=g_model,
                contents=contents,
                config=config
            )
            if resp.text:
                return resp.text.strip()
        except Exception as e:
            print(f"[Gemini] Model {g_model} failed: {e}. Trying next Gemini model...")

    return "Assalam o Alaikum! We are currently experiencing a brief technical delay. A clinic representative will assist you shortly."


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

    # Build system prompt and fetch completion
    system_prompt = build_system_prompt(patient, open_slots, phone)
    reply = get_chat_completion(system_prompt, CONVERSATION_HISTORY[phone])

    # ── Parse and act on BOOK tag ────────────────────────────────────────────
    book_match = re.search(r"BOOK:(\d{4}-\d{2}-\d{2}):(\d{2}:\d{2})(?::(.+))?", reply)
    if book_match and patient:
        date_str, time_str = book_match.group(1), book_match.group(2)
        procedure_name = book_match.group(3).strip() if book_match.group(3) else "Dental Appointment"
        success = gcal.create_booking(
            patient_name=patient["name"],
            phone=phone,
            date_str=date_str,
            time_str=time_str,
            procedure=procedure_name,
        )
        reply = reply[: book_match.start()].strip()
        if not success:
            reply += "\n\nSorry, that slot was just taken. Please choose another time."
        else:
            if not reply:
                reply = f"Perfect! Your appointment for {date_str} at {time_str} is confirmed. We look forward to seeing you!"

            # 1. Save the appointment to Supabase
            from datetime import datetime
            from zoneinfo import ZoneInfo
            slot_time = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("Asia/Karachi"))
            
            # Assigned doctor (defaults to 'default' test number; extensible per procedure or doctor selection)
            assigned_doctor_id = "default"

            supabase_res = supabase.table("appointments").insert({
                "patient_phone": phone,
                "patient_name": patient["name"],
                "procedure": procedure_name,
                "slot_time": slot_time.isoformat(),
                "booked": True
            }).execute()

            # 2. Right after the Supabase write succeeds, send a dedicated WhatsApp notification to the Doctor
            if supabase_res.data:
                booking_record = {
                    "patient_name": patient["name"],
                    "patient_phone": phone,
                    "date_str": date_str,
                    "time_str": time_str,
                    "procedure": procedure_name,
                    "doctor_id": assigned_doctor_id,
                    "notes": patient.get("notes") or "Booked via WhatsApp AI Receptionist",
                    "appointment_id": supabase_res.data[0].get("id")
                }
                send_doctor_notification(booking_record)
            else:
                print(f"[Booking Flow] Warning: Supabase insert returned no data for patient {patient['name']}. Doctor alert skipped.")

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
