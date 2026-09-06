-- ═══════════════════════════════════════════════════════
-- CMD Admin Portal — Row Level Security Policies
-- Run this in Supabase SQL Editor AFTER schema.sql
--
-- Context: This portal is private (2 doctors only).
-- Authentication is handled by our own PIN + JWT system
-- on Railway — NOT Supabase Auth. So the anon role needs
-- full access to all tables (security comes from Railway
-- and the Cloudflare Pages URL being private/unlisted).
-- ═══════════════════════════════════════════════════════

-- ── doctors ────────────────────────────────────────────
ALTER TABLE doctors ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "anon_all_doctors" ON doctors;
CREATE POLICY "anon_all_doctors" ON doctors
  FOR ALL TO anon USING (true) WITH CHECK (true);

-- ── patients ───────────────────────────────────────────
ALTER TABLE patients ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "anon_all_patients" ON patients;
CREATE POLICY "anon_all_patients" ON patients
  FOR ALL TO anon USING (true) WITH CHECK (true);

-- ── treatments ─────────────────────────────────────────
ALTER TABLE treatments ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "anon_all_treatments" ON treatments;
CREATE POLICY "anon_all_treatments" ON treatments
  FOR ALL TO anon USING (true) WITH CHECK (true);

-- ── appointments ───────────────────────────────────────
ALTER TABLE appointments ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "anon_all_appointments" ON appointments;
CREATE POLICY "anon_all_appointments" ON appointments
  FOR ALL TO anon USING (true) WITH CHECK (true);

-- ── lab_work ───────────────────────────────────────────
ALTER TABLE lab_work ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "anon_all_lab_work" ON lab_work;
CREATE POLICY "anon_all_lab_work" ON lab_work
  FOR ALL TO anon USING (true) WITH CHECK (true);

-- ── services ───────────────────────────────────────────
ALTER TABLE services ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "anon_all_services" ON services;
CREATE POLICY "anon_all_services" ON services
  FOR ALL TO anon USING (true) WITH CHECK (true);

-- ── clinic_settings ────────────────────────────────────
ALTER TABLE clinic_settings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "anon_all_clinic_settings" ON clinic_settings;
CREATE POLICY "anon_all_clinic_settings" ON clinic_settings
  FOR ALL TO anon USING (true) WITH CHECK (true);
