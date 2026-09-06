/* ═══════════════════════════════════════════════
   config.js — CMD Admin Portal
   All environment constants in one place.
   Update RAILWAY_API_URL when deploying to Railway.
═══════════════════════════════════════════════ */

const CONFIG = {
  // Backend URL — Render production server
  RAILWAY_API_URL: 'https://ai-receptionist-ru2r.onrender.com',

  // Supabase (public anon key — safe to expose in frontend)
  SUPABASE_URL:      'https://jbiywybedhhhwspnrbfo.supabase.co',
  SUPABASE_ANON_KEY: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpiaXl3eWJlZGhoaHdzcG5yYmZvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzY3ODUxOTYsImV4cCI6MjA5MjM2MTE5Nn0.GvD-T0tGIdyptYP44OBjb938x_xwXc6fJ09b9fqYjyo',

  // PIN auth settings
  PIN_LENGTH:          6,
  MAX_PIN_ATTEMPTS:    5,
  LOCKOUT_SECONDS:     30,

  // Session
  SESSION_KEY:         'cmd_session',   // localStorage key for JWT token
  SESSION_DOCTOR_KEY:  'cmd_doctor',    // localStorage key for doctor info
};
