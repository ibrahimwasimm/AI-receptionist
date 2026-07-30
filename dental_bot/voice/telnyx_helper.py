"""
telnyx_helper.py — Telnyx Call Control REST API helper
=======================================================
Handles emergency call transfers using the Telnyx REST API.

Flow:
  1. Emergency detected → transfer_to_dentist(call_control_id) called
  2. Telnyx REST API transfers the active call to DENTIST_NUMBER
  3. Caller ID shown to dentist = CLINIC_NUMBER (or Telnyx number in testing)
  4. 20-second ring timeout configured
  5a. Dentist answers → patient and dentist are directly bridged
  5b. No answer → Telnyx fires call.machine.detection.ended or hangup
      → our /telnyx/transfer-result webhook plays the fallback message

Telnyx transfer vs Twilio:
  Twilio: update call twiml → <Dial action="fallback">
  Telnyx: POST /v2/calls/{call_control_id}/actions/transfer
          with webhook_url for result events

Environment variables required (add to .env):
  TELNYX_API_KEY       — from telnyx.com → API Keys (already in .env ✅)
  TELNYX_NUMBER        — your Telnyx phone number e.g. +12025551234
  CLINIC_NUMBER        — shown as caller ID on transfer (can be same as TELNYX_NUMBER in testing)
  DENTIST_NUMBER       — dentist's number that receives emergency transfers
  NGROK_URL            — current ngrok HTTPS URL
"""

import asyncio
import logging
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("voice.telnyx_helper")

TELNYX_API_KEY  = os.getenv("TELNYX_API_KEY",  "")
TELNYX_NUMBER   = os.getenv("TELNYX_NUMBER",   "")
CLINIC_NUMBER   = os.getenv("CLINIC_NUMBER",   "")
DENTIST_NUMBER  = os.getenv("DENTIST_NUMBER",  "")
NGROK_URL       = os.getenv("NGROK_URL",       "").rstrip("/")

TELNYX_API_BASE    = "https://api.telnyx.com/v2"
TRANSFER_TIMEOUT   = 20   # seconds to ring dentist before giving up


def _headers() -> dict:
    """Telnyx API auth header."""
    return {
        "Authorization": f"Bearer {TELNYX_API_KEY}",
        "Content-Type":  "application/json",
    }


async def speak_text(call_control_id: str, text: str, language: str = "en-US") -> None:
    """
    Make the bot speak a message on the active call using Telnyx TTS.
    Used to say the hold message before transferring, or the fallback message.

    language: "en-US" for English, "ur-PK" for Urdu (if supported by Telnyx TTS)
    """
    url = f"{TELNYX_API_BASE}/calls/{call_control_id}/actions/speak"
    payload = {
        "payload":           text,
        "voice":             "female",
        "language":          language,
        "payload_type":      "text",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, headers=_headers(), json=payload)
            logger.info(f"[Telnyx] speak → {r.status_code}")
    except Exception as e:
        logger.error(f"[Telnyx] speak_text failed: {e}")


async def transfer_to_dentist(call_control_id: str) -> None:
    """
    Transfer the active patient call to the dentist via Telnyx REST API.

    Steps:
      1. Speak hold message (Urdu + English)
      2. Call the transfer action — Telnyx dials DENTIST_NUMBER
      3. webhook_url on the transfer receives the result event
         → our /telnyx/transfer-result endpoint handles no-answer fallback

    Args:
        call_control_id: Telnyx call_control_id for the patient's active call
    """
    if not call_control_id:
        logger.error("[Telnyx] No call_control_id — cannot transfer")
        return
    if not DENTIST_NUMBER:
        logger.error("[Telnyx] DENTIST_NUMBER not set in .env")
        return

    # Step 1 — play hold message while we dial the dentist
    hold_message = (
        "Yeh emergency lagti hai. "
        "Aapko dentist se connect kar rahi hoon. "
        "Please hold karein. "
        "This is an emergency. Please hold while I connect you to the dentist."
    )

    await speak_text(call_control_id, hold_message, language="en-US")

    # Give TTS a moment to start playing before we initiate the transfer
    await asyncio.sleep(4)

    # Step 2 — initiate transfer
    caller_id    = CLINIC_NUMBER or TELNYX_NUMBER  # use Telnyx number as fallback in testing
    result_url   = f"{NGROK_URL}/telnyx/transfer-result"

    url     = f"{TELNYX_API_BASE}/calls/{call_control_id}/actions/transfer"
    payload = {
        "to":               DENTIST_NUMBER,
        "from":             caller_id,
        "timeout_secs":     TRANSFER_TIMEOUT,
        "webhook_url":      result_url,
        "webhook_url_method": "POST",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(url, headers=_headers(), json=payload)
            if r.status_code in (200, 201, 202):
                logger.info(
                    f"[Telnyx] ✅ Transfer initiated: {call_control_id} → {DENTIST_NUMBER}"
                )
            else:
                logger.error(
                    f"[Telnyx] ❌ Transfer failed {r.status_code}: {r.text}"
                )
    except Exception as e:
        logger.error(f"[Telnyx] transfer_to_dentist error: {e}")


async def hangup_call(call_control_id: str) -> None:
    """Hang up the call gracefully."""
    url = f"{TELNYX_API_BASE}/calls/{call_control_id}/actions/hangup"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, headers=_headers(), json={})
            logger.info(f"[Telnyx] hangup → {r.status_code}")
    except Exception as e:
        logger.error(f"[Telnyx] hangup_call error: {e}")
