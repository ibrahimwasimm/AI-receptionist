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
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

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
    print("[ERROR] NGROK_URL is not set in .env -- make sure ngrok is running and the URL is saved.")
    sys.exit(1)

# ── TwiML: answer → open media stream → connect to your voice agent ────────────
TWIML = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="wss://{NGROK_URL.replace('https://','').replace('http://','')}/media-stream">
      <Parameter name="caller" value="{TO_NUMBER}" />
    </Stream>
  </Connect>
</Response>"""

print(f"[CALLING] {TO_NUMBER} from {FROM_NUMBER} ...")
print(f"[WEBSOCKET] wss://{NGROK_URL.replace('https://','').replace('http://','')}/media-stream")

client = Client(ACCOUNT_SID, AUTH_TOKEN)

call = client.calls.create(
    to=TO_NUMBER,
    from_=FROM_NUMBER,
    twiml=TWIML,
)

print(f"[SUCCESS] Call initiated! SID: {call.sid}")
print(f"   Status: {call.status}")
print("\nPick up your phone — Sana will greet you in Urdu!")
