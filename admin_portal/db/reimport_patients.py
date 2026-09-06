"""
reimport_patients.py - Re-imports ONLY the patients table after schema cache reload.
Run from AI-receptionist root: python admin_portal/db/reimport_patients.py
"""
import sys, io, re, math
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import pandas as pd
from supabase import create_client

SUPABASE_URL  = "https://jbiywybedhhhwspnrbfo.supabase.co"
SUPABASE_KEY  = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpiaXl3eWJlZGhoaHdzcG5yYmZvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzY3ODUxOTYsImV4cCI6MjA5MjM2MTE5Nn0.GvD-T0tGIdyptYP44OBjb938x_xwXc6fJ09b9fqYjyo"
EXCEL_PATH    = "Center for Modern Dentistry.xls"
BATCH_SIZE    = 50

client = create_client(SUPABASE_URL, SUPABASE_KEY)

def clean_str(val):
    if val is None: return None
    if isinstance(val, float) and math.isnan(val): return None
    s = str(val).strip()
    return s if s and s.lower() not in ('nan','none','nil','-') else None

def clean_num(val):
    if val is None: return None
    if isinstance(val, (int, float)):
        if isinstance(val, float) and math.isnan(val): return None
        return float(val)
    s = str(val).strip().replace(',','')
    m = re.search(r'[\d.]+', s)
    return float(m.group()) if m else None

def clean_date(val):
    if val is None: return None
    if isinstance(val, float) and math.isnan(val): return None
    if isinstance(val, datetime): return val.strftime('%Y-%m-%d')
    try: return pd.to_datetime(val).strftime('%Y-%m-%d')
    except: return None

def load_sheet_with_header(xl, sheet_name, header_marker):
    df = xl.parse(sheet_name)
    for i in range(min(10, len(df))):
        row_vals = [str(v).upper().strip() for v in df.iloc[i].tolist()]
        if header_marker.upper() in row_vals:
            df.columns = [str(c).strip() for c in df.iloc[i]]
            return df.iloc[i+1:].reset_index(drop=True)
    return df

def load_patients(xl, sheet_name, source_label):
    df = load_sheet_with_header(xl, sheet_name, 'S.no')
    patients = []
    for _, row in df.iterrows():
        name = clean_str(row.get('Patient Name'))
        if not name or name.upper() == 'PATIENT NAME': continue

        age_raw = clean_num(row.get('Age'))
        age = int(age_raw) if age_raw and age_raw > 0 else None

        contact = clean_str(row.get('Contact Number'))
        if contact:
            contact = re.sub(r'\s+', '', contact)
            if len(contact) == 10 and contact.startswith('3'):
                contact = '0' + contact

        is_ortho = False
        ortho_val = clean_str(row.get('ORTHO/CLEARPATH'))
        if ortho_val and ortho_val.lower() in ('yes','1','true','ortho','clearpath'):
            is_ortho = True

        patients.append({
            "serial_no":       int(clean_num(row.get('S.no') or row.get('S.No')) or 0) or None,
            "registered_date": clean_date(row.get('Date')),
            "name":            name,
            "age":             age,
            "contact_number":  contact,
            "is_ortho":        is_ortho,
            "visiting_doctor": clean_str(row.get('VISITING DOCTORS')),
            "source":          source_label,
        })
    return patients

print("===============================================")
print("  CMD - Patients Re-Import")
print("===============================================")

xl = pd.ExcelFile(EXCEL_PATH)
new_p = load_patients(xl, 'Patient Record New', 'new')
old_p = load_patients(xl, 'Patient Record Old', 'old')
all_patients = new_p + old_p

print(f"Found {len(all_patients)} patients to import ({len(new_p)} new + {len(old_p)} old)")
print("Inserting in batches...")

total = 0
errors = 0
for i in range(0, len(all_patients), BATCH_SIZE):
    batch = all_patients[i:i+BATCH_SIZE]
    done = min(i+BATCH_SIZE, len(all_patients))
    try:
        result = client.table("patients").insert(batch).execute()
        count = len(result.data) if result.data else 0
        total += count
        print(f"  {done}/{len(all_patients)} rows ... {total} inserted", end='\r')
    except Exception as e:
        errors += 1
        print(f"\n  WARN batch {i}-{done}: {str(e)[:100]}")

print(f"\n\nDone!")
print(f"  Inserted: {total} patients")
print(f"  Errors:   {errors} batches")
if errors > 0:
    print("\n  If errors persist, check Supabase: Project Settings -> API -> Reload schema cache")
