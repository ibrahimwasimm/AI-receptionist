"""
gcal.py — Google Calendar Integration
======================================
Public functions:
  - get_open_slots()   → returns up to 10 free 1-hour slot strings
  - create_booking()   → atomically reserves slot in Supabase + creates GCal event
                         returns "success", "slot_taken", or "error"
  - cancel_booking()   → deletes a matching Calendar event + Supabase row
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
# Clinic hours (inclusive start, exclusive end)
CLINIC_START_HOUR = 17  # 5 pm (17:00)
CLINIC_END_HOUR   = 22  # 10 pm (22:00)
SLOT_DURATION_MINUTES = 45  # 45-minute slots back-to-back with no gap


# ─────────────────────────────────────────────────────────────────────────────
# Internal: build / refresh the Calendar service
# ─────────────────────────────────────────────────────────────────────────────

_SERVICE_CACHE = None

def _get_service():
    """Load credentials from token.json or GOOGLE_TOKEN_JSON env var, refresh if expired, return service."""
    global _SERVICE_CACHE
    import json as _json
    creds = None

    # 1. Try loading from file (local dev) if file exists and is non-empty
    if os.path.exists(TOKEN_PATH) and os.path.getsize(TOKEN_PATH) > 0:
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
        except Exception as e:
            print(f"[GCal] Warning: Failed to load local token.json: {e}")

    # 2. Fall back to environment variable (Render / cloud deployment)
    if not creds:
        token_env = os.getenv("GOOGLE_TOKEN_JSON", "").strip()
        if token_env:
            try:
                token_data = _json.loads(token_env)
                creds = Credentials.from_authorized_user_info(token_data, SCOPES)
            except Exception as e:
                raise RuntimeError(
                    f"GOOGLE_TOKEN_JSON environment variable on Render is invalid JSON: {e}"
                ) from e

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                # Write refreshed token back to file if possible
                try:
                    with open(TOKEN_PATH, "w") as f:
                        f.write(creds.to_json())
                except Exception:
                    pass  # On Render, disk may be read-only — that's OK
            except Exception as refresh_err:
                print(f"[GCal] Refresh token failed: {refresh_err}")
                creds = None

        if not creds or not creds.valid:
            # Cannot run browser-based auth on a cloud server
            raise RuntimeError(
                "Google Calendar token has expired or been revoked. "
                "Please run 'python run_auth.py' locally to generate a fresh token.json, "
                "then copy its contents into GOOGLE_TOKEN_JSON on Render."
            )
        _SERVICE_CACHE = None

    if _SERVICE_CACHE is None:
        _SERVICE_CACHE = build("calendar", "v3", credentials=creds)

    return _SERVICE_CACHE


# ─────────────────────────────────────────────────────────────────────────────
# Public: get free slots (45-minute intervals)
# ─────────────────────────────────────────────────────────────────────────────

def get_open_slots(days_ahead: int = 7, max_slots: int = 12) -> list[str]:
    """
    Return up to `max_slots` free 45-minute slots over the next `days_ahead` days
    during clinic hours (5:00 PM – 10:00 PM), Asia/Karachi time.
    Slots run back-to-back with no gap:
      5:00pm – 5:45pm (17:00)
      5:45pm – 6:30pm (17:45)
      6:30pm – 7:15pm (18:30)
      7:15pm – 8:00pm (19:15)
      8:00pm – 8:45pm (20:00)
      8:45pm – 9:30pm (20:45)
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

        # Parse busy periods into localized start/end ranges
        parsed_busy = []
        for period in busy_periods:
            b_start = datetime.fromisoformat(period["start"].replace("Z", "+00:00")).astimezone(TZ)
            b_end   = datetime.fromisoformat(period["end"].replace("Z", "+00:00")).astimezone(TZ)
            parsed_busy.append((b_start, b_end))

        open_slots: list[str] = []
        slot_delta = timedelta(minutes=SLOT_DURATION_MINUTES)

        for day_offset in range(0, days_ahead + 1):
            day_local = (now_local + timedelta(days=day_offset)).date()
            
            # Skip Sundays (Clinic is closed on Sunday)
            if day_local.weekday() == 6:
                continue

            clinic_open  = datetime(day_local.year, day_local.month, day_local.day, CLINIC_START_HOUR, 0, tzinfo=TZ)
            clinic_close = datetime(day_local.year, day_local.month, day_local.day, CLINIC_END_HOUR, 0, tzinfo=TZ)

            cursor = clinic_open
            while cursor + slot_delta <= clinic_close:
                slot_start = cursor
                slot_end   = cursor + slot_delta
                cursor     += slot_delta  # Back-to-back: next slot begins immediately when previous ends

                # Skip slots that are already in the past
                if slot_start <= now_local:
                    continue

                # Check if this 45-minute slot overlaps with any busy period
                is_busy = False
                for b_start, b_end in parsed_busy:
                    # Overlap condition: max(start1, start2) < min(end1, end2)
                    if max(slot_start, b_start) < min(slot_end, b_end):
                        is_busy = True
                        break

                if not is_busy:
                    # Format as: YYYY-MM-DD at HH:MM (e.g. 2026-09-04 at 17:45 (5:45 PM – 6:30 PM))
                    time_12h_start = slot_start.strftime("%I:%M %p").lstrip("0")
                    time_12h_end   = slot_end.strftime("%I:%M %p").lstrip("0")
                    slot_str = f"{slot_start.strftime('%Y-%m-%d')} at {slot_start.strftime('%H:%M')} ({time_12h_start} – {time_12h_end})"
                    open_slots.append(slot_str)

                    if len(open_slots) >= max_slots:
                        return open_slots

        return open_slots

    except Exception as e:
        print(f"[GCal] get_open_slots failed: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Public: create a booking event (45-minute duration)
# ─────────────────────────────────────────────────────────────────────────────

def create_booking(
    patient_name: str,
    phone: str,
    date_str: str,
    time_str: str,
    procedure: str = "Dental Appointment",
) -> bool:
    """
    Create a 45-minute Google Calendar event for the given slot.
    date_str: 'YYYY-MM-DD', time_str: 'HH:MM'
    Returns True on success, False on failure.
    """
    try:
        service = _get_service()

        start_local = datetime.strptime(
            f"{date_str} {time_str}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=TZ)
        end_local = start_local + timedelta(minutes=SLOT_DURATION_MINUTES)

        event = {
            "summary": f"{procedure} — {patient_name}",
            "description": (
                f"Patient: {patient_name}\n"
                f"Phone: {phone}\n"
                f"Procedure: {procedure}\n"
                f"Duration: 45 minutes"
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
        print(f"[GCal] Event created (45 min): {created.get('htmlLink')}")
        return True

    except HttpError as e:
        print(f"[GCal] create_booking HTTP error: {e}")
        return False
    except Exception as e:
        print(f"[GCal] create_booking failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Public: cancel a booking event (45-minute duration)
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
        end_local = start_local + timedelta(minutes=SLOT_DURATION_MINUTES)

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
