/* ═══════════════════════════════════════════════
   api.js — Supabase Data Layer
   All database calls in one place.
   Uses the native fetch() API against Supabase REST.
═══════════════════════════════════════════════ */

const API = (() => {
  'use strict';

  const BASE = CONFIG.SUPABASE_URL + '/rest/v1';
  const HEADERS = {
    'apikey':        CONFIG.SUPABASE_ANON_KEY,
    'Authorization': 'Bearer ' + CONFIG.SUPABASE_ANON_KEY,
    'Content-Type':  'application/json',
    'Prefer':        'return=representation',
  };

  async function request(path, options = {}) {
    const res = await fetch(BASE + path, {
      headers: HEADERS,
      ...options,
    });
    if (!res.ok) {
      const err = await res.text();
      throw new Error(`Supabase error ${res.status}: ${err}`);
    }
    const text = await res.text();
    return text ? JSON.parse(text) : [];
  }

  return {
    // ── Appointments ─────────────────────────────
    async getTodayAppointments(doctorId) {
      const today = new Date().toISOString().split('T')[0];
      let path = `/appointments?appointment_date=eq.${today}&order=appointment_time.asc.nullslast`;
      if (doctorId) path += `&doctor_id=eq.${doctorId}`;
      return request(path);
    },

    async getAllTodayAppointments() {
      const today = new Date().toISOString().split('T')[0];
      return request(`/appointments?appointment_date=eq.${today}&order=appointment_time.asc.nullslast`);
    },

    async createAppointment(data) {
      return request('/appointments', {
        method: 'POST',
        body: JSON.stringify(data),
      });
    },

    async updateAppointmentStatus(id, status) {
      return request(`/appointments?id=eq.${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ status }),
      });
    },

    async deleteAppointment(id) {
      return request(`/appointments?id=eq.${id}`, {
        method: 'DELETE',
      });
    },

    // ── Patients ─────────────────────────────────
    async searchPatients(query) {
      const q = encodeURIComponent(query);
      return request(`/patients?or=(name.ilike.*${q}*,contact_number.ilike.*${q}*)&order=name.asc&limit=50`);
    },

    async getPatient(id) {
      const rows = await request(`/patients?id=eq.${id}`);
      return rows[0] || null;
    },

    async getPatientsByNames(names) {
      if (!names || names.length === 0) return [];
      // Supabase in filter takes a comma separated list inside parens
      const list = names.map(n => `"${n}"`).join(',');
      return request(`/patients?name=in.(${encodeURIComponent(list)})&order=name.asc`);
    },

    async getTreatmentsByMonth(monthStr) {
      // monthStr is like "2022-02"
      const start = `${monthStr}-01`;
      // Get last day of the month
      const [y, m] = monthStr.split('-');
      const end = new Date(y, m, 0).toISOString().split('T')[0];
      return request(`/treatments?date=gte.${start}&date=lte.${end}&order=date.desc`);
    },

    async createPatient(data) {
      return request('/patients', { method: 'POST', body: JSON.stringify(data) });
    },

    async updatePatient(id, data) {
      return request(`/patients?id=eq.${id}`, { method: 'PATCH', body: JSON.stringify(data) });
    },

    async getPatientTreatments(patientName) {
      const n = encodeURIComponent(patientName);
      return request(`/treatments?patient_name=eq.${n}&order=date.desc`);
    },

    // ── Services (for autocomplete) ───────────────
    async getServices() {
      return request('/services?order=category.asc,service_name.asc');
    },

    // ── Doctors ───────────────────────────────────
    async getDoctors() {
      return request('/doctors?select=id,name,display_name,role');
    },

    // ── Lab Work ──────────────────────────────────
    async getLabWork(status) {
      let path = '/lab_work?order=sending_date.desc';
      if (status) path += `&status=eq.${status}`;
      return request(path);
    },

    async updateLabStatus(id, status, receivingDate) {
      const data = { status };
      if (receivingDate) data.receiving_date = receivingDate;
      return request(`/lab_work?id=eq.${id}`, { method: 'PATCH', body: JSON.stringify(data) });
    },

    // ── Clinic Settings ───────────────────────────
    async getSettings() {
      const rows = await request('/clinic_settings');
      const map = {};
      rows.forEach(r => { map[r.key] = r.value; });
      return map;
    },

    async updateSetting(key, value) {
      return request(`/clinic_settings?key=eq.${key}`, {
        method: 'PATCH',
        body: JSON.stringify({ value, updated_at: new Date().toISOString() }),
      });
    },
  };
})();
