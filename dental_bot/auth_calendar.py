"""
auth_calendar.py — Dedicated Google Calendar OAuth Authenticator
=================================================================
Runs the Google OAuth flow, opens browser, and generates fresh token.json.
"""

import os
import sys
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDS_PATH = os.path.join(_BASE_DIR, "credentials.json")
TOKEN_PATH = os.path.join(_BASE_DIR, "token.json")
SCOPES = ["https://www.googleapis.com/auth/calendar"]

def main():
    print("=" * 60)
    print("🗓️  GOOGLE CALENDAR AUTHORIZATION")
    print("=" * 60)

    if not os.path.exists(CREDS_PATH):
        print(f"[FAIL] credentials.json not found at {CREDS_PATH}")
        sys.exit(1)

    print("Opening browser for Google Calendar authorization...")
    print("Log in with your Google Account and click Allow / Continue.")

    try:
        flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
        creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w") as f:
            token_json_str = creds.to_json()
            f.write(token_json_str)

        print("\n" + "=" * 60)
        print("✅ SUCCESS! Fresh token.json created!")
        print("=" * 60)
        print("\n📋 COPY THE JSON BELOW FOR RENDER 'GOOGLE_TOKEN_JSON':\n")
        print(token_json_str)
        print("\n" + "=" * 60)

        # Verify
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
        print(f"Verified connection: {len(events)} upcoming event(s) found.")

    except Exception as e:
        print(f"\n[FAIL] Authorization failed: {e}")

if __name__ == "__main__":
    main()
