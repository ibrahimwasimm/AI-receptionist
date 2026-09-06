/* ═══════════════════════════════════════════════
   app.js — Main App Init
   Called after successful PIN login.
═══════════════════════════════════════════════ */

function initApp(doctor) {
  'use strict';

  // ── Update top bar ──────────────────────────────
  const displayName = (doctor && doctor.display_name) || (doctor && doctor.name) || 'Doctor';
  document.getElementById('top-bar-doctor').textContent = displayName;

  // Format date: "Fri, 5 Sep"
  const now = new Date();
  const dateStr = now.toLocaleDateString('en-GB', {
    weekday: 'short', day: 'numeric', month: 'short'
  });
  document.getElementById('top-bar-date').textContent = dateStr;

  // ── Logout ──────────────────────────────────────
  document.getElementById('btn-logout').addEventListener('click', () => {
    if (!confirm('Log out?')) return;
    localStorage.removeItem(CONFIG.SESSION_KEY);
    localStorage.removeItem(CONFIG.SESSION_DOCTOR_KEY);
    location.reload();
  });

  // ── Initialise first view (Today) ───────────────
  TodayView.init(doctor);

  // ── Show FAB only on Today and Lab views ────────
  const fab = document.getElementById('fab-add');
  window.addEventListener('viewchange', e => {
    const v = e.detail.view;
    fab.style.display = (v === 'today' || v === 'lab') ? 'flex' : 'none';
  });

  console.log('[APP] Initialised for', displayName);
}
