
"""
make_call.py
============
Run this script to have Twilio call your phone and connect it
to the Gemini Live voice agent.

Usage:
    python make_call.py +923XXXXXXXXX
    -- or leave blank to call CLINIC_PK_NUMBER from .env --
"""

import sys
import os
import httpx
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv(override=True)

ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN")
FROM_NUMBER = os.getenv("TWILIO_US_NUMBER")   # your Twilio US number
NGROK_URL   = os.getenv("NGROK_URL", "").rstrip("/")

# ── Who to call ────────────────────────────────────────────────────────────────
# Pass a number on the command line, e.g.:  python make_call.py +923001234567
# Otherwise falls back to CLINIC_PK_NUMBER in .env
TO_NUMBER = sys.argv[1] if len(sys.argv) > 1 else os.getenv("CLINIC_PK_NUMBER")

if not TO_NUMBER:
    print("[ERROR] No target number found. Either pass it as an argument or set CLINIC_PK_NUMBER in .env")
    sys.exit(1)

if not NGROK_URL:
    print("[ERROR] NGROK_URL is not set in .env -- make sure NGROK_URL is saved in .env.")
    sys.exit(1)

# ── Server Health / Auto-Wake Ping ─────────────────────────────────────────────
print(f"[CHECK] Pinging server to ensure it is awake ({NGROK_URL}) ...")
try:
    with httpx.Client(timeout=30.0) as http_client:
        resp = http_client.get(NGROK_URL)
        if resp.status_code == 200:
            print("[CHECK] Server is awake and ready! ✅")
        else:
            print(f"[WARNING] Server returned status code {resp.status_code}")
except Exception as e:
    print(f"[WARNING] Server ping check: {e}")

# ── TwiML: answer → open media stream → connect to your voice agent ────────────
clean_domain = NGROK_URL.replace("https://", "").replace("http://", "")
TWIML = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="wss://{clean_domain}/media-stream">
      <Parameter name="caller" value="{TO_NUMBER}" />
    </Stream>
  </Connect>
</Response>"""

print(f"[CALLING] {TO_NUMBER} from {FROM_NUMBER} ...")
print(f"[WEBSOCKET] wss://{clean_domain}/media-stream")

client = Client(ACCOUNT_SID, AUTH_TOKEN)

call = client.calls.create(
    to=TO_NUMBER,
    from_=FROM_NUMBER,
    twiml=TWIML,
)

print(f"[SUCCESS] Call initiated! SID: {call.sid}")
print(f"   Status: {call.status}")
print("\nPick up your phone — Sana will greet you in Urdu!")
