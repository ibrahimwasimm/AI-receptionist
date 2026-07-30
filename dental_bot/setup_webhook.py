"""
setup_webhook.py
================
Automatically sets the Twilio voice webhook to your current ngrok URL.
Run this script every time ngrok restarts.

Usage:
    python setup_webhook.py
"""

import os
import requests
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

ACCOUNT_SID  = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN   = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.getenv("TWILIO_US_NUMBER")   # +12405038179
NGROK_URL    = os.getenv("NGROK_URL", "").rstrip("/")

def get_ngrok_url_live():
    """Try to get the latest ngrok URL from the local ngrok API."""
    try:
        resp = requests.get("http://localhost:4040/api/tunnels", timeout=3)
        tunnels = resp.json().get("tunnels", [])
        for t in tunnels:
            if t.get("proto") == "https":
                return t["public_url"].rstrip("/")
    except Exception:
        pass
    return None

def update_twilio_webhook(voice_url: str):
    """Update the Twilio phone number's incoming voice webhook."""
    client = Client(ACCOUNT_SID, AUTH_TOKEN)

    # Find the phone number SID
    numbers = client.incoming_phone_numbers.list(phone_number=TWILIO_NUMBER)
    if not numbers:
        print(f"[ERROR] Phone number {TWILIO_NUMBER} not found in your Twilio account.")
        return

    phone = numbers[0]
    phone.update(
        voice_url=voice_url,
        voice_method="POST",
    )
    print(f"[SUCCESS] Webhook updated successfully!")
    print(f"   Phone Number : {TWILIO_NUMBER}")
    print(f"   Voice URL    : {voice_url}")
    print(f"   Method       : POST")

if __name__ == "__main__":
    # Try live ngrok API first, then fall back to .env
    live_url = get_ngrok_url_live()

    if live_url:
        print(f"[DETECTED] Live ngrok URL: {live_url}")
        ngrok_url = live_url
    elif NGROK_URL:
        print(f"[ENV] Using NGROK_URL from .env: {NGROK_URL}")
        ngrok_url = NGROK_URL
    else:
        print("[ERROR] No ngrok URL found. Start ngrok first: ngrok http 8000")
        exit(1)

    webhook_url = f"{ngrok_url}/voice"
    print(f"\n[SETTING] Twilio webhook to: {webhook_url}\n")

    update_twilio_webhook(webhook_url)
    print("\n[DONE] You can now call your Twilio number to test the bot:")
    print(f"   Call: {TWILIO_NUMBER}")
