"""
Supabase Table Schemas
======================
Run these SQL statements ONCE in your Supabase project → SQL Editor.

-------------------------------------------------------------------
-- 1. Patients table
-------------------------------------------------------------------
create table patients (
    id         uuid primary key default gen_random_uuid(),
    name       text not null,
    phone      text unique not null,
    last_proc  text,
    notes      text,
    created_at timestamptz default now()
);

create index idx_patients_phone on patients(phone);

-------------------------------------------------------------------
-- 2. Appointments table  (replaces Google Calendar)
-------------------------------------------------------------------
create table appointments (
    id             uuid primary key default gen_random_uuid(),
    patient_phone  text not null,
    patient_name   text not null,
    procedure      text default 'Dental appointment',
    slot_time      timestamptz not null,
    booked         boolean default true,
    reminder_sent  boolean default false,
    created_at     timestamptz default now()
);

create index idx_appointments_slot_time on appointments(slot_time);
create index idx_appointments_phone     on appointments(patient_phone);

-------------------------------------------------------------------
-- Add a patient manually (run in SQL Editor or via add_patient.py)
-------------------------------------------------------------------
-- insert into patients (name, phone, last_proc, notes)
-- values ('Ahmed Khan', '+923001234567', 'Root canal', 'Allergic to penicillin');
"""
