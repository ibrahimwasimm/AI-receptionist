-- ═══════════════════════════════════════════════════
-- CMD Admin Portal — Supabase Schema
-- Centre for Modern Dentistry
-- Run this in Supabase SQL Editor
-- Uses IF NOT EXISTS so it's safe to re-run anytime
-- ═══════════════════════════════════════════════════

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── 1. Doctors / Auth ──────────────────────────────
CREATE TABLE IF NOT EXISTS doctors (
  id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  name         TEXT        NOT NULL,
  display_name TEXT,
  pin_hash     TEXT        NOT NULL,
  role         TEXT        DEFAULT 'doctor',
  created_at   TIMESTAMPTZ DEFAULT now()
);

-- ── 2. Patients ────────────────────────────────────
CREATE TABLE IF NOT EXISTS patients (
  id              UUID  PRIMARY KEY DEFAULT gen_random_uuid(),
  serial_no       INTEGER,
  registered_date DATE,
  name            TEXT  NOT NULL,
  age             INTEGER,
  contact_number  TEXT,
  is_ortho        BOOLEAN DEFAULT FALSE,
  visiting_doctor TEXT,
  source          TEXT    DEFAULT 'new',
  notes           TEXT,
  created_at      TIMESTAMPTZ DEFAULT now()
);

-- ── 3. Treatments ──────────────────────────────────
CREATE TABLE IF NOT EXISTS treatments (
  id           UUID  PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id   UUID  REFERENCES patients(id) ON DELETE CASCADE,
  patient_name TEXT,
  date         DATE  NOT NULL,
  visit_type   TEXT  DEFAULT 'NEW',
  treatment    TEXT  NOT NULL,
  amount       NUMERIC(10,2),
  paid         NUMERIC(10,2),
  balance      NUMERIC(10,2),
  doctor_id    UUID  REFERENCES doctors(id),
  notes        TEXT,
  created_at   TIMESTAMPTZ DEFAULT now()
);

-- ── 4. Appointments ────────────────────────────────
CREATE TABLE IF NOT EXISTS appointments (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id        UUID REFERENCES patients(id),
  patient_name      TEXT NOT NULL,
  contact_number    TEXT,
  doctor_id         UUID REFERENCES doctors(id),
  appointment_date  DATE NOT NULL,
  appointment_time  TIME,
  status            TEXT DEFAULT 'Tentative Appt',
  treatment_planned TEXT,
  booked_by         TEXT DEFAULT 'manual',
  notes             TEXT,
  created_at        TIMESTAMPTZ DEFAULT now()
);

-- ── 5. Lab Work ────────────────────────────────────
CREATE TABLE IF NOT EXISTS lab_work (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id     UUID REFERENCES patients(id),
  patient_name   TEXT NOT NULL,
  sending_date   DATE,
  receiving_date DATE,
  lab_work_type  TEXT,
  work_detail    TEXT,
  shade          TEXT,
  lab_name       TEXT,
  status         TEXT DEFAULT 'Pending',
  remarks        TEXT,
  created_at     TIMESTAMPTZ DEFAULT now()
);

-- ── 6. Services & Fees ─────────────────────────────
CREATE TABLE IF NOT EXISTS services (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  category     TEXT,
  service_name TEXT NOT NULL,
  fee_pkr      NUMERIC(10,2),
  fee_range    TEXT,
  notes        TEXT
);

-- ── 7. Clinic Settings ─────────────────────────────
CREATE TABLE IF NOT EXISTS clinic_settings (
  key        TEXT PRIMARY KEY,
  value      TEXT,
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Seed default clinic settings (safe to re-run)
INSERT INTO clinic_settings (key, value)
VALUES
  ('clinic_open',           'true'),
  ('is_holiday',            'false'),
  ('custom_hours_message',  ''),
  ('dr_mustafa_available',  'true'),
  ('dr_qasim_available',    'true')
ON CONFLICT (key) DO NOTHING;
