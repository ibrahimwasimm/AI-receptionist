"""
gcal.py — Google Calendar Integration
======================================
Two public functions:
  - get_open_slots()   → returns up to 10 free 1-hour slot strings
  - create_booking()   → creates a Calendar event and returns True/False
  - cancel_booking()   → deletes a matching Calendar event
"""

import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

SCOPES = ["https://www.googleapis.com/auth/calendar"]
CALENDAR_ID = "primary"
TIMEZONE_STR = os.getenv("TIMEZONE", "Asia/Karachi")
TZ = ZoneInfo(TIMEZONE_STR)

# Paths — same folder as this file
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(_BASE_DIR, "token.json")
CREDS_PATH = os.path.join(_BASE_DIR, "credentials.json")

# Clinic hours (inclusive start, exclusive end)
CLINIC_START_HOUR = 17  # 5 pm
CLINIC_END_HOUR   = 22  # 10 pm (last slot starts at 21:00)


# ─────────────────────────────────────────────────────────────────────────────
# Internal: build / refresh the Calendar service
# ─────────────────────────────────────────────────────────────────────────────

_SERVICE_CACHE = None

def _get_service():
    """Load credentials from token.json, refresh if expired, return service."""
    global _SERVICE_CACHE
    creds = None

    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
        _SERVICE_CACHE = None

    if _SERVICE_CACHE is None:
        _SERVICE_CACHE = build("calendar", "v3", credentials=creds)

    return _SERVICE_CACHE


# ─────────────────────────────────────────────────────────────────────────────
# Public: get free slots
# ─────────────────────────────────────────────────────────────────────────────

def get_open_slots(days_ahead: int = 7, max_slots: int = 10) -> list[str]:
    """
    Return up to `max_slots` free 1-hour slots over the next `days_ahead` days
    during clinic hours (CLINIC_START_HOUR – CLINIC_END_HOUR), Asia/Karachi time.

    Uses the Calendar freebusy API to skip already-busy times.
    Returns a list of human-readable strings like '2025-05-01 at 10:00'.
    """
    try:
        service = _get_service()

        now_local = datetime.now(TZ)
        time_min = now_local.isoformat()
        time_max = (now_local + timedelta(days=days_ahead)).isoformat()

        # Ask Google which times are busy
        body = {
            "timeMin": time_min,
            "timeMax": time_max,
            "timeZone": TIMEZONE_STR,
            "items": [{"id": CALENDAR_ID}],
        }
        freebusy = service.freebusy().query(body=body).execute()
        busy_periods = freebusy["calendars"][CALENDAR_ID]["busy"]

        # Build a set of busy hour-starts (local time, "YYYY-MM-DD HH:MM")
        busy_starts: set[str] = set()
        for period in busy_periods:
            start_utc = datetime.fromisoformat(period["start"].replace("Z", "+00:00"))
            end_utc   = datetime.fromisoformat(period["end"].replace("Z", "+00:00"))
            # Mark every hour that overlaps this busy block
            cursor = start_utc.astimezone(TZ).replace(minute=0, second=0, microsecond=0)
            end_local = end_utc.astimezone(TZ)
            while cursor < end_local:
                busy_starts.add(cursor.strftime("%Y-%m-%d %H:%M"))
                cursor += timedelta(hours=1)

        # Enumerate candidate slots
        open_slots: list[str] = []
        for day_offset in range(0, days_ahead + 1):
            day_local = (now_local + timedelta(days=day_offset)).date()
            for hour in range(CLINIC_START_HOUR, CLINIC_END_HOUR):
                slot_local = datetime(
                    day_local.year, day_local.month, day_local.day,
                    hour, 0, tzinfo=TZ
                )
                
                # Skip slots that are in the past
                if slot_local <= now_local:
                    continue
                    
                key = slot_local.strftime("%Y-%m-%d %H:%M")
                if key not in busy_starts:
                    open_slots.append(slot_local.strftime("%Y-%m-%d at %H:%M"))
                    if len(open_slots) >= max_slots:
                        return open_slots

        return open_slots

    except Exception as e:
        print(f"[GCal] get_open_slots failed: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Public: create a booking event
# ─────────────────────────────────────────────────────────────────────────────

def create_booking(
    patient_name: str,
    phone: str,
    date_str: str,
    time_str: str,
    procedure: str = "Dental Appointment",
) -> bool:
    """
    Create a 1-hour Google Calendar event for the given slot.
    date_str: 'YYYY-MM-DD', time_str: 'HH:MM'
    Returns True on success, False on failure.
    """
    try:
        service = _get_service()

        start_local = datetime.strptime(
            f"{date_str} {time_str}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=TZ)
        end_local = start_local + timedelta(hours=1)

        event = {
            "summary": f"{procedure} — {patient_name}",
            "description": (
                f"Patient: {patient_name}\n"
                f"Phone: {phone}\n"
                f"Procedure: {procedure}"
            ),
            "start": {
                "dateTime": start_local.isoformat(),
                "timeZone": TIMEZONE_STR,
            },
            "end": {
                "dateTime": end_local.isoformat(),
                "timeZone": TIMEZONE_STR,
            },
        }

        created = service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
        print(f"[GCal] Event created: {created.get('htmlLink')}")
        return True

    except HttpError as e:
        print(f"[GCal] create_booking HTTP error: {e}")
        return False
    except Exception as e:
        print(f"[GCal] create_booking failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Public: cancel a booking event
# ─────────────────────────────────────────────────────────────────────────────

def cancel_booking(phone: str, date_str: str, time_str: str) -> bool:
    """
    Find and delete the Calendar event that starts at the given slot
    and has the patient's phone in the description.
    Returns True if deleted, False if not found or error.
    """
    try:
        service = _get_service()

        start_local = datetime.strptime(
            f"{date_str} {time_str}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=TZ)
        end_local = start_local + timedelta(hours=1)

        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=start_local.isoformat(),
            timeMax=end_local.isoformat(),
            singleEvents=True,
        ).execute()

        events = events_result.get("items", [])
        for event in events:
            desc = event.get("description", "")
            if phone in desc:
                service.events().delete(
                    calendarId=CALENDAR_ID, eventId=event["id"]
                ).execute()
                print(f"[GCal] Event deleted: {event.get('summary')}")
                return True

        print(f"[GCal] No matching event found for {phone} at {date_str} {time_str}")
        return False

    except Exception as e:
        print(f"[GCal] cancel_booking failed: {e}")
        return False
