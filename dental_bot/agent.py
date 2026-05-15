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
Location       : Please ask patients to contact the clinic for the address
Language       : Respond in the same language the patient uses.
                 If they write in Urdu (Roman or script), reply in Urdu.
                 If English, reply in English.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DENTAL PROCEDURES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
If a patient asks about fees, tell them fees are discussed at the consultation.

PREVENTIVE & GENERAL
  D1110  –  Dental Cleaning / Scaling & Polishing
  D1206  –  Fluoride Treatment
  D0150  –  Comprehensive Oral Examination (New Patient)
  D0120  –  Periodic Oral Examination (Follow-up)
  D0210  –  Full Mouth X-Rays (OPG/FMX)

RESTORATIVE (FILLINGS)
  D2140  –  Amalgam Filling (1 surface)
  D2330  –  Composite (Tooth-Colored) Filling (1 surface)
  D2740  –  Porcelain / Ceramic Crown
  D2710  –  Temporary Crown
  D2950  –  Core Build-Up / Post & Core

ROOT CANAL TREATMENT (RCT)
  D3310  –  RCT – Anterior Tooth (Front)
  D3320  –  RCT – Premolar Tooth
  D3330  –  RCT – Molar Tooth
  (Note: Crown is recommended after RCT and is charged separately)

EXTRACTIONS
  D7140  –  Simple Extraction (Loose/Decayed Tooth)
  D7210  –  Surgical Extraction (Impacted Tooth)
  D7240  –  Wisdom Tooth Removal (Surgical)

ORTHODONTICS (BRACES)
  D8080  –  Comprehensive Orthodontic Treatment – Metal Braces
  D8090  –  Comprehensive Orthodontic Treatment – Ceramic Braces
  D8660  –  Orthodontic Consultation & X-Rays
  (Braces require multiple visits over 12–24 months)

COSMETIC DENTISTRY
  D9975  –  Teeth Whitening (In-Clinic)
  D2961  –  Dental Veneer (Composite, per tooth)
  D2962  –  Dental Veneer (Porcelain, per tooth)

PROSTHETICS (DENTURES & BRIDGES)
  D5110  –  Complete Denture (Full Set – Upper or Lower)
  D5213  –  Partial Denture (Removable)
  D6240  –  Dental Bridge (3-Unit Porcelain)

DENTAL IMPLANTS
  D6010  –  Endosseous Implant (per implant)
  D6065  –  Implant Crown (per crown)
  (Implant treatment takes 3–6 months in total)

CHILDREN'S DENTISTRY (PEDODONTICS)
  D1351  –  Dental Sealants (per tooth)
  D2930  –  Stainless Steel Crown (Milk Tooth)
  D3230  –  Pulpotomy (Baby Root Canal)
  D8010  –  Space Maintainer

GUM TREATMENT (PERIODONTICS)
  D4341  –  Deep Cleaning / Scaling & Root Planing (per quadrant)
  D4260  –  Bone Graft (Periodontal)
  D4210  –  Gingivectomy (Gum Surgery)

EMERGENCY & PAIN RELIEF
  D9110  –  Emergency Exam & Palliative Treatment
  D9930  –  Treatment of Complications / Dry Socket

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
                   info. For anything else, please call us directly."

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


MODELS = [
    "inclusionai/ring-2.6-1t:free",
    "meta-llama/llama-3-8b-instruct:free",
    "mistralai/mistral-7b-instruct:free",
    "google/gemma-2-9b-it:free",
    "qwen/qwen-2-7b-instruct:free",
    "microsoft/phi-3-mini-128k-instruct:free"
]

import time
import datetime
import threading

CURRENT_MODEL_INDEX = 0
LAST_RESET_TIME = datetime.datetime.now()
model_lock = threading.Lock()

def get_chat_completion(messages: list) -> str:
    global CURRENT_MODEL_INDEX, LAST_RESET_TIME
    
    attempts = 0
    while attempts < len(MODELS) * 2:  # Prevent infinite loops
        # Reset tracker if 60 minutes have passed
        now = datetime.datetime.now()
        with model_lock:
            if (now - LAST_RESET_TIME).total_seconds() > 3600:
                CURRENT_MODEL_INDEX = 0
                LAST_RESET_TIME = now
            
            # Safely get the index so it never crashes
            safe_index = CURRENT_MODEL_INDEX % len(MODELS)
            current_model = MODELS[safe_index]

        try:
            print(f"[Agent] Trying model: {current_model}")
            response = client.chat.completions.create(
                model=current_model,
                messages=messages,
                timeout=10.0
            )
            return response.choices[0].message.content
        except Exception as e:
            error_str = str(e).lower()
            print(f"[OpenRouter Error] Model {current_model} failed: {error_str}")
            
            with model_lock:
                # Move to next model
                CURRENT_MODEL_INDEX = (CURRENT_MODEL_INDEX + 1) % len(MODELS)
                
            attempts += 1
            
            # If we've tried all models in the list once, wait 60 seconds
            if attempts % len(MODELS) == 0:
                print("[Agent] All models failed. Waiting 30s in background before retrying...")
                time.sleep(30)
            continue
            
    return "I am sorry, our system is currently offline due to high traffic. We will get back to you shortly."

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

    # Send the entire recent history to OpenRouter using our intelligent router
    reply = get_chat_completion(messages)

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
            # Ping the doctor on WhatsApp!
            notify_doctor(patient["name"], phone, date_str, time_str)
            
            # Save the appointment to Supabase so it shows up in your dashboard and works with reminders
            from datetime import datetime
            from zoneinfo import ZoneInfo
            # Create a localized timestamp for Supabase
            slot_time = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("Asia/Karachi"))
            supabase.table("appointments").insert({
                "patient_phone": phone,
                "patient_name": patient["name"],
                "procedure": procedure_name,
                "slot_time": slot_time.isoformat(),
                "booked": True
            }).execute()

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
