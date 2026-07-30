"""
twilio_helper.py — Call transfer to dentist
============================================
Handles emergency call transfers using the Twilio REST API.

Flow:
  1. Bot detects emergency → calls transfer_to_dentist(call_sid)
  2. Twilio REST API updates the active call with new TwiML:
       - Plays a hold message in Urdu + English
       - Dials DENTIST_PK_NUMBER with CLINIC_PK_NUMBER as caller ID
       - 20-second ring timeout
       - action URL → /voice/dial-fallback  (if dentist doesn't answer)
  3a. Dentist answers → patient and dentist are directly connected
  3b. Dentist doesn't answer → Twilio POSTs to /voice/dial-fallback
      → bot plays fallback message in Urdu + English → hangs up

Environment variables required:
  TWILIO_ACCOUNT_SID   — from console.twilio.com → Account Info
  TWILIO_AUTH_TOKEN    — from console.twilio.com → Account Info
  TWILIO_US_NUMBER     — your Twilio US number, e.g. +12025551234
  CLINIC_PK_NUMBER     — Pakistani clinic number shown as caller ID
  DENTIST_PK_NUMBER    — dentist's number that receives the transferred call
  NGROK_URL            — current ngrok HTTPS URL (for dial-fallback action)
"""

import asyncio
import logging
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("voice.transfer")

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN",  "")
TWILIO_US_NUMBER   = os.getenv("TWILIO_US_NUMBER",   "")
CLINIC_PK_NUMBER   = os.getenv("CLINIC_PK_NUMBER",   "")
DENTIST_PK_NUMBER  = os.getenv("DENTIST_PK_NUMBER",  "")
NGROK_URL          = os.getenv("NGROK_URL",           "").rstrip("/")

TRANSFER_TIMEOUT_SEC = 20   # seconds to ring dentist before fallback


def get_twilio_client():
    """Return a Twilio REST client. Raises if credentials are missing."""
    from twilio.rest import Client
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        raise ValueError(
            "TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set in .env"
        )
    return Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def _build_transfer_twiml() -> str:
    """
    TwiML that:
     1. Plays a hold message (Urdu + English)
     2. Dials the dentist with clinic caller ID, 20s timeout
     3. On no-answer → hits /voice/dial-fallback
    """
    fallback_url  = f"{NGROK_URL}/voice/dial-fallback"
    caller_id     = CLINIC_PK_NUMBER or TWILIO_US_NUMBER  # fall back to US number in testing
    dentist_num   = DENTIST_PK_NUMBER

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say language="ur-PK">
    Yeh emergency lagti hai. Aapko dentist se connect kar rahi hoon.
    Please hold karein.
  </Say>
  <Say>
    This is an emergency. Please hold while I connect you to the dentist.
  </Say>
  <Dial
    callerId="{caller_id}"
    timeout="{TRANSFER_TIMEOUT_SEC}"
    action="{fallback_url}"
    method="POST">
    <Number>{dentist_num}</Number>
  </Dial>
</Response>"""


async def transfer_to_dentist(call_sid: str) -> None:
    """
    Redirect the active call to the dentist using Twilio REST API.

    This interrupts the current TwiML (including the Media Stream WebSocket).
    Twilio will close the WebSocket connection automatically.

    Args:
        call_sid: The Twilio CallSid of the patient's active call.
    """
    if not call_sid:
        logger.error("[Transfer] No call_sid provided — cannot transfer")
        return

    if not DENTIST_PK_NUMBER:
        logger.error("[Transfer] DENTIST_PK_NUMBER not set in .env")
        return

    try:
        twilio  = get_twilio_client()
        twiml   = _build_transfer_twiml()

        logger.info(f"[Transfer] Redirecting call {call_sid} → {DENTIST_PK_NUMBER}")

        # Run synchronous Twilio SDK call in a thread pool
        await asyncio.to_thread(
            lambda: twilio.calls(call_sid).update(twiml=twiml)
        )

        logger.info(f"[Transfer] ✅ Call {call_sid} redirected to dentist")

    except Exception as e:
        logger.error(f"[Transfer] ❌ Failed to transfer call {call_sid}: {e}")
