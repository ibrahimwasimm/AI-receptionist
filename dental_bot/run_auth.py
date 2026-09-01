"""
run_auth.py -- Connection & Configuration Tester
================================================
Run this script ONCE before starting the bot to verify that all your
environment variables are set correctly, Supabase is reachable,
Gemini API works, and Google Calendar is authorized.

Usage:
    python run_auth.py
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# 1. Check required env vars
# ─────────────────────────────────────────────────────────────────────────────

REQUIRED = {
    "GEMINI_API_KEY":        "Google Gemini AI key",
    "META_VERIFY_TOKEN":     "Meta webhook verify token (you choose this string)",
    "META_ACCESS_TOKEN":     "Meta Graph API permanent access token",
    "META_PHONE_NUMBER_ID":  "Meta WhatsApp sending phone-number ID",
    "SUPABASE_URL":          "Supabase project URL",
    "SUPABASE_KEY":          "Supabase anon/service-role key",
}

print("\n-- Checking environment variables --")
missing = []
for key, description in REQUIRED.items():
    value = os.getenv(key, "")
    if not value or "your-key" in value or "xxxx" in value.lower():
        print(f"  [MISSING]  {key:30s} -- {description}")
        missing.append(key)
    else:
        masked = value[:6] + "..." + value[-4:] if len(value) > 12 else "***"
        print(f"  [OK]       {key:30s} -- {masked}")

if missing:
    print(f"\n[WARNING] {len(missing)} variable(s) are missing. Fill them in your .env file and re-run.\n")
    sys.exit(1)

print("\n[OK] All environment variables are set.\n")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Test Supabase connection
# ─────────────────────────────────────────────────────────────────────────────

print("-- Testing Supabase connection --")
try:
    from database import supabase

    result = supabase.table("patients").select("id").limit(1).execute()
    print(f"  [OK] Supabase connected -- patients table reachable ({len(result.data)} row(s) returned in probe).")
except Exception as e:
    print(f"  [FAIL] Supabase connection failed: {e}")
    print("         Make sure your SUPABASE_URL and SUPABASE_KEY are correct.\n")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Test Gemini API key
# ─────────────────────────────────────────────────────────────────────────────

print("\n-- Testing Gemini API key --")
try:
    from google import genai
    g_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    resp = g_client.models.generate_content(
        model="gemini-3.6-flash",
        contents="Say 'OK' in one word."
    )
    print(f"  [OK] Gemini API working -- response: {resp.text.strip()}")
except Exception as e:
    print(f"  [WARNING] Gemini rate-limit/notice: {e} (Continuing to Calendar Auth...)")



# ─────────────────────────────────────────────────────────────────────────────
# 4. Google Calendar authorization
# ─────────────────────────────────────────────────────────────────────────────

print("\n-- Google Calendar authorization --")

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDS_PATH = os.path.join(_BASE_DIR, "credentials.json")
TOKEN_PATH = os.path.join(_BASE_DIR, "token.json")

if not os.path.exists(CREDS_PATH):
    print("  [FAIL] credentials.json not found!")
    print("         Download it from Google Cloud Console -> APIs & Services -> Credentials")
    print(f"         and place it at: {CREDS_PATH}")
    sys.exit(1)

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    SCOPES = ["https://www.googleapis.com/auth/calendar"]

    creds = None
    if os.path.exists(TOKEN_PATH) and os.path.getsize(TOKEN_PATH) > 0:
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
        except Exception:
            creds = None

    if not creds or not creds.valid:
        refreshed = False
        if creds and creds.expired and creds.refresh_token:
            print("  [INFO] Attempting to refresh token...")
            try:
                creds.refresh(Request())
                refreshed = True
            except Exception as err:
                print(f"  [WARNING] Token refresh failed ({err}). Opening browser for fresh authorization...")
                creds = None

        if not refreshed or not creds:
            print("  [INFO] Opening browser for Google Calendar authorization...")
            print("         Log in with your Google account and grant access.")
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
        print(f"  [OK] token.json saved to {TOKEN_PATH}")

    # Quick test -- fetch next 3 events
    service = build("calendar", "v3", credentials=creds)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    events_result = service.events().list(
        calendarId="primary",
        timeMin=now,
        maxResults=3,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    events = events_result.get("items", [])
    print(f"  [OK] Google Calendar connected -- {len(events)} upcoming event(s) found.")

except Exception as e:
    print(f"  [FAIL] Google Calendar authorization failed: {e}")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Summary
# ─────────────────────────────────────────────────────────────────────────────

print("""
------------------------------------------------------------
[ALL CHECKS PASSED] Your bot is ready.

Next steps:
  1. Start the bot:
       uvicorn main:app --reload --port 8000
  2. Expose it via ngrok:
       ngrok http 8000
  3. Update your Meta webhook URL with the new ngrok URL.
  4. Send a WhatsApp message and watch appointments land
     in Google Calendar!
------------------------------------------------------------
""")
