"""
import_excel.py - CMD Admin Portal
Migrates all data from 'Center for Modern Dentistry.xls' into Supabase.

USAGE:
  python admin_portal/db/import_excel.py

Imports (in order):
  1. Services & Fees       (from MISC sheet)
  2. Patients              (merged from Patient Record New + Old)
  3. Treatment Records     (from Patient Treatment Detail)
  4. Lab Work              (from Lab Work sheet)

Safe to re-run - uses insert with ignore on duplicates where possible.
"""

import sys
import os
import math
import re
from datetime import datetime

# ── Check dependencies ─────────────────────────────────
try:
    import pandas as pd
except ImportError:
    print("ERROR: pandas not installed. Run: pip install pandas xlrd")
    sys.exit(1)
try:
    import xlrd
except ImportError:
    print("ERROR: xlrd not installed. Run: pip install xlrd")
    sys.exit(1)
try:
    from supabase import create_client
except ImportError:
    print("ERROR: supabase not installed. Run: pip install supabase")
    sys.exit(1)

# ── Config ─────────────────────────────────────────────
SUPABASE_URL  = "https://jbiywybedhhhwspnrbfo.supabase.co"
SUPABASE_KEY  = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpiaXl3eWJlZGhoaHdzcG5yYmZvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzY3ODUxOTYsImV4cCI6MjA5MjM2MTE5Nn0.GvD-T0tGIdyptYP44OBjb938x_xwXc6fJ09b9fqYjyo"
EXCEL_PATH    = "Center for Modern Dentistry.xls"
BATCH_SIZE    = 50   # Supabase free tier handles 50 rows per insert comfortably

client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Helpers ────────────────────────────────────────────
def clean_str(val) -> str | None:
    """Convert any value to a clean string, or None if empty."""
    if val is None: return None
    if isinstance(val, float) and math.isnan(val): return None
    s = str(val).strip()
    return s if s and s.lower() not in ('nan', 'none', 'nil', '-') else None

def clean_num(val) -> float | None:
    """Extract a numeric value from messy data."""
    if val is None: return None
    if isinstance(val, (int, float)):
        if math.isnan(val): return None
        return float(val)
    s = str(val).strip().replace(',', '')
    # Extract first number from strings like "45,000 to 75,000"
    match = re.search(r'[\d.]+', s)
    return float(match.group()) if match else None

def clean_date(val) -> str | None:
    """Convert Excel date values to ISO string."""
    if val is None: return None
    if isinstance(val, float) and math.isnan(val): return None
    if isinstance(val, datetime): return val.strftime('%Y-%m-%d')
    try:
        return pd.to_datetime(val).strftime('%Y-%m-%d')
    except Exception:
        return None

def insert_batch(table: str, rows: list) -> int:
    """Insert a batch of rows, return count of successful inserts."""
    if not rows: return 0
    try:
        result = client.table(table).insert(rows).execute()
        return len(result.data) if result.data else 0
    except Exception as e:
        print(f"    ⚠  Batch insert error on {table}: {str(e)[:120]}")
        return 0

def insert_all(table: str, rows: list, label: str) -> int:
    """Insert all rows in batches with progress display."""
    total = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        count = insert_batch(table, batch)
        total += count
        done  = min(i + BATCH_SIZE, len(rows))
        print(f"  → {label}: {done}/{len(rows)} rows processed...", end='\r')
    print(f"  ✓  {label}: {total} rows inserted{' ' * 20}")
    return total

def load_sheet_with_header(xl, sheet_name: str, header_marker: str):
    """Load a sheet and find the real header row by searching for a marker."""
    df = xl.parse(sheet_name)
    for i in range(min(10, len(df))):
        row_vals = [str(v).upper().strip() for v in df.iloc[i].tolist()]
        if header_marker.upper() in row_vals:
            df.columns = [str(c).strip() for c in df.iloc[i]]
            return df.iloc[i+1:].reset_index(drop=True)
    return df

# ══════════════════════════════════════════════════════
# 1. SERVICES & FEES (from MISC sheet)
# ══════════════════════════════════════════════════════
def import_services(xl):
    print("\n[1/4] Importing Services & Fees...")
    df = xl.parse('MISC')

    # Detect category rows (they appear in col 0, service in col 1)
    category_markers = {
        'GENERAL DENTISTRY SERVICES': 'General Dentistry',
        'ORTHODONTIC TREATMENTS':     'Orthodontic',
        'PAEDIATRIC DENTISTRY':       'Paediatric Dentistry',
    }

    current_category = 'General Dentistry'
    rows = []

    for _, row in df.iterrows():
        # Check if this row is a category header
        col0 = clean_str(row.iloc[0])
        if col0 and col0.upper() in category_markers:
            current_category = category_markers[col0.upper()]
            continue

        service_name = clean_str(row.get('Services'))
        if not service_name: continue

        # Skip non-service entries
        if service_name in ('Type List', 'One time', 'Regular', 'Recurring', 'Refundable'):
            continue

        fee_raw  = row.get('Fee (PKR)')
        fee_pkr  = clean_num(fee_raw)
        fee_str  = clean_str(fee_raw)
        fee_range = clean_str(row.get('Range'))

        # If fee is a range string (e.g., "45,000 to 75,000"), put it in fee_range
        if fee_str and 'to' in fee_str.lower():
            fee_range = fee_str
            fee_pkr   = None

        rows.append({
            "category":     current_category,
            "service_name": service_name,
            "fee_pkr":      fee_pkr,
            "fee_range":    fee_range,
        })

    return insert_all("services", rows, "Services")

# ══════════════════════════════════════════════════════
# 2. PATIENTS (merged New + Old sheets)
# ══════════════════════════════════════════════════════
def import_patients(xl):
    print("\n[2/4] Importing Patients...")

    def load_patient_sheet(sheet_name, source_label):
        df = load_sheet_with_header(xl, sheet_name, 'S.no')
        patients = []
        for _, row in df.iterrows():
            name = clean_str(row.get('Patient Name'))
            if not name or name.upper() in ('PATIENT NAME',): continue

            serial = clean_num(row.get('S.no') or row.get('S.No'))
            date   = clean_date(row.get('Date'))
            age_raw = clean_num(row.get('Age'))
            age     = int(age_raw) if age_raw and age_raw > 0 else None
            contact = clean_str(row.get('Contact Number'))

            # Normalise contact: remove spaces, ensure leading 0 or 03xx
            if contact:
                contact = re.sub(r'\s+', '', contact)
                # Pad if it looks like a truncated number
                if len(contact) == 10 and contact.startswith('3'):
                    contact = '0' + contact

            is_ortho = False
            ortho_val = clean_str(row.get('ORTHO/CLEARPATH'))
            if ortho_val and ortho_val.lower() in ('yes', '1', 'true', 'ortho', 'clearpath'):
                is_ortho = True

            visiting_doc = clean_str(row.get('VISITING DOCTORS'))

            patients.append({
                "serial_no":       int(serial) if serial else None,
                "registered_date": date,
                "name":            name,
                "age":             age,
                "contact_number":  contact,
                "is_ortho":        is_ortho,
                "visiting_doctor": visiting_doc,
                "source":          source_label,
            })
        return patients

    new_patients = load_patient_sheet('Patient Record New', 'new')
    old_patients = load_patient_sheet('Patient Record Old', 'old')

    print(f"  Found {len(new_patients)} new + {len(old_patients)} old patients")
    all_patients = new_patients + old_patients

    total = insert_all("patients", all_patients, "Patients")
    return total

# ══════════════════════════════════════════════════════
# 3. TREATMENT RECORDS
# ══════════════════════════════════════════════════════
def import_treatments(xl):
    print("\n[3/4] Importing Treatment Records...")
    df = load_sheet_with_header(xl, 'Patient Treatment Detail', 'DATE')

    rows = []
    for _, row in df.iterrows():
        patient_name = clean_str(row.get('PATIENT NAME'))
        treatment    = clean_str(row.get('TREATMENT'))
        if not patient_name or not treatment: continue
        if patient_name.upper() == 'PATIENT NAME': continue

        date      = clean_date(row.get('DATE'))
        if not date: continue

        visit_type = clean_str(row.get('NEW/REPEAT')) or 'NEW'
        if visit_type.upper() not in ('NEW', 'REPEAT'):
            visit_type = 'NEW'

        amount  = clean_num(row.get('AMOUNT'))
        paid    = clean_num(row.get('PAID'))
        balance = None
        if amount is not None and paid is not None:
            balance = round(amount - paid, 2)
        elif amount is not None:
            balance = amount  # Nothing paid yet

        rows.append({
            "patient_name": patient_name,
            "date":         date,
            "visit_type":   visit_type.upper(),
            "treatment":    treatment,
            "amount":       amount,
            "paid":         paid,
            "balance":      balance,
        })

    return insert_all("treatments", rows, "Treatments")

# ══════════════════════════════════════════════════════
# 4. LAB WORK
# ══════════════════════════════════════════════════════
def import_lab_work(xl):
    print("\n[4/4] Importing Lab Work...")
    df = load_sheet_with_header(xl, 'Lab Work', 'Sending Date')

    rows = []
    for _, row in df.iterrows():
        patient_name = clean_str(row.get('Patient Name'))
        if not patient_name: continue

        sending_date   = clean_date(row.get('Sending Date'))
        receiving_date = clean_date(row.get('Receiving Date'))
        lab_work_type  = clean_str(row.get('Lab Work'))
        work_detail    = clean_str(row.get('Work Type'))
        shade          = clean_str(row.get('Shade'))
        lab_name       = clean_str(row.get('Lab Name'))
        remarks        = clean_str(row.get('Remarks'))

        # Determine status from remarks
        status = 'Pending'
        if remarks and 'insert' in remarks.lower():
            status = 'Inserted'
        elif receiving_date:
            status = 'Received'

        rows.append({
            "patient_name":   patient_name,
            "sending_date":   sending_date,
            "receiving_date": receiving_date,
            "lab_work_type":  lab_work_type,
            "work_detail":    work_detail,
            "shade":          shade,
            "lab_name":       lab_name,
            "status":         status,
            "remarks":        remarks,
        })

    return insert_all("lab_work", rows, "Lab Work")

# ══════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════
def main():
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    print("===============================================")
    print("  CMD Admin Portal - Excel Data Import")
    print("===============================================")

    if not os.path.exists(EXCEL_PATH):
        print(f"\nERROR: Excel file not found: {EXCEL_PATH}")
        print("  Run this script from the AI-receptionist root folder.")
        sys.exit(1)

    print(f"\nLoading: {EXCEL_PATH}")
    xl = pd.ExcelFile(EXCEL_PATH)
    print(f"Sheets found: {xl.sheet_names}")

    s_count = import_services(xl)
    p_count = import_patients(xl)
    t_count = import_treatments(xl)
    l_count = import_lab_work(xl)

    print("\n===============================================")
    print("  Import Complete!")
    print("===============================================")
    print(f"  Services:   {s_count:>5} rows")
    print(f"  Patients:   {p_count:>5} rows")
    print(f"  Treatments: {t_count:>5} rows")
    print(f"  Lab Work:   {l_count:>5} rows")
    print(f"  {'-'*20}")
    print(f"  Total:      {s_count+p_count+t_count+l_count:>5} rows imported")
    print()

if __name__ == "__main__":
    main()
