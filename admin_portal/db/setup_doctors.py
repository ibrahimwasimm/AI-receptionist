"""
setup_doctors.py — CMD Admin Portal
Inserts Dr. Mustafa and Dr. Qasim into Supabase with hashed PINs.

USAGE:
  python admin_portal/db/setup_doctors.py

PINs used (change these before going live):
  Dr. Mustafa → 112233
  Dr. Qasim   → 445566

After running, each doctor can change their PIN from the Settings screen.
"""

import bcrypt
import os
import sys

# ── Credentials ────────────────────────────────────────
SUPABASE_URL     = "https://jbiywybedhhhwspnrbfo.supabase.co"
SUPABASE_KEY     = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpiaXl3eWJlZGhoaHdzcG5yYmZvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzY3ODUxOTYsImV4cCI6MjA5MjM2MTE5Nn0.GvD-T0tGIdyptYP44OBjb938x_xwXc6fJ09b9fqYjyo"

# ── Doctor PINs (change before going live) ─────────────
DOCTORS = [
    {
        "name":         "Dr. Mustafa",
        "display_name": "Dr. Mustafa",
        "pin":          "112233",
        "role":         "doctor",
    },
    {
        "name":         "Dr. Qasim",
        "display_name": "Dr. Qasim",
        "pin":          "445566",
        "role":         "doctor",
    },
]

def hash_pin(pin: str) -> str:
    """bcrypt hash a 6-digit PIN."""
    return bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()

def main():
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    try:
        from supabase import create_client
    except ImportError:
        print("ERROR: supabase package not installed. Run: pip install supabase")
        sys.exit(1)

    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    print("=======================================")
    print("  CMD Admin Portal -- Doctor Setup")
    print("=======================================\n")

    for doc in DOCTORS:
        pin_hash = hash_pin(doc["pin"])
        row = {
            "name":         doc["name"],
            "display_name": doc["display_name"],
            "pin_hash":     pin_hash,
            "role":         doc["role"],
        }

        # Check if doctor already exists
        existing = client.table("doctors").select("id").eq("name", doc["name"]).execute()
        if existing.data:
            print(f"SKIP {doc['name']} already exists in database")
            continue

        result = client.table("doctors").insert(row).execute()

        if result.data:
            print(f"OK   {doc['name']} inserted  |  PIN: {doc['pin']}")
        else:
            print(f"WARN {doc['name']} -- unexpected response: {result}")


    print("\nDone! Both doctors are ready to log in.")
    print("\n  Dr. Mustafa PIN: 112233")
    print("  Dr. Qasim   PIN: 445566")
    print("\n  NOTE: Change these PINs before showing the portal to the doctors.")


if __name__ == "__main__":
    main()
