/* ═══════════════════════════════════════════════
   today.js — Today's Patients Screen
   Loads appointments for the logged-in doctor,
   renders cards, handles status changes and the
   Add Appointment bottom sheet.
═══════════════════════════════════════════════ */

const TodayView = (() => {
  'use strict';

  // ── State ───────────────────────────────────────
  let appointments  = [];
  let doctorData    = null;
  let activeCard    = null; // currently expanded card id
  let statusTarget  = null; // appt id awaiting status pick

  // ── DOM Refs ────────────────────────────────────
  const listEl       = document.getElementById('appt-list');
  const emptyEl      = document.getElementById('today-empty');
  const statTotal    = document.getElementById('stat-num-total');
  const statShow     = document.getElementById('stat-num-show');
  const statPending  = document.getElementById('stat-num-pending');
  const statNoShow   = document.getElementById('stat-num-noshow');

  // Add Appointment modal
  const modalAdd     = document.getElementById('modal-add-appt');
  const formAdd      = document.getElementById('form-add-appt');
  const btnFab       = document.getElementById('fab-add');
  const inputName    = document.getElementById('appt-patient-name');
  const inputPhone   = document.getElementById('appt-phone');
  const inputDate    = document.getElementById('appt-date');
  const inputTime    = document.getElementById('appt-time');
  const inputTreat   = document.getElementById('appt-treatment');
  const servicesList = document.getElementById('services-list');
  const btnSave      = document.getElementById('btn-save-appt');
  const docBtns      = document.querySelectorAll('.doctor-btn');

  // Status picker modal
  const modalStatus  = document.getElementById('modal-status');
  const statusName   = document.getElementById('status-sheet-name');
  const statusOpts   = document.getElementById('status-options');

  // ── Format helpers ──────────────────────────────
  function formatTime(timeStr) {
    if (!timeStr) return { h: '--', ampm: '' };
    const [h, m] = timeStr.split(':').map(Number);
    const ampm = h >= 12 ? 'PM' : 'AM';
    const h12  = h % 12 || 12;
    return { h: h12 + ':' + String(m).padStart(2, '0'), ampm };
  }

  function badgeClass(status) {
    if (!status) return 'badge-tentative';
    const s = status.toLowerCase();
    if (s === 'show')    return 'badge-show';
    if (s === 'no show') return 'badge-noshow';
    if (s.includes('cancel') || s.includes('postpone')) return 'badge-cancel';
    return 'badge-tentative';
  }

  function badgeLabel(status) {
    if (!status) return 'Tentative';
    const s = status.toLowerCase();
    if (s === 'show')    return 'Show';
    if (s === 'no show') return 'No Show';
    if (s.includes('cancel') || s.includes('postpone')) return 'Cancelled';
    return 'Tentative';
  }

  // ── Render appointment card ─────────────────────
  function renderCard(appt) {
    const t     = formatTime(appt.appointment_time);
    const badge = badgeClass(appt.status);
    const label = badgeLabel(appt.status);
    const isOpen = activeCard === appt.id;

    const card = document.createElement('div');
    card.className  = 'appt-card';
    card.dataset.id = appt.id;

    card.innerHTML = `
      <div class="appt-card-main">
        <div class="appt-time-col">
          <div class="appt-time">${t.h}</div>
          <div class="appt-time-ampm">${t.ampm}</div>
        </div>
        <div class="appt-divider"></div>
        <div class="appt-info">
          <div class="appt-name">${appt.patient_name}</div>
          <div class="appt-treatment">${appt.treatment_planned || 'No treatment specified'}</div>
        </div>
        <button class="status-badge ${badge}" data-appt-id="${appt.id}" aria-label="Change status">
          ${label}
        </button>
      </div>
      ${isOpen ? renderDetail(appt) : ''}
    `;

    // Tap card body → expand detail
    card.querySelector('.appt-card-main').addEventListener('click', e => {
      // If tapped on the status badge, open status picker instead
      if (e.target.closest('.status-badge')) return;
      toggleCard(appt.id);
    });

    // Tap status badge → open status picker
    card.querySelector('.status-badge').addEventListener('click', e => {
      e.stopPropagation();
      openStatusPicker(appt);
    });

    return card;
  }

  function renderDetail(appt) {
    const phone = appt.contact_number;
    return `
      <div class="appt-detail">
        ${phone ? `
          <div class="detail-phone">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 12 19.79 19.79 0 0 1 1.63 3.38 2 2 0 0 1 3.6 1.22h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L7.91 8.82a16 16 0 0 0 6.27 6.27l1.18-1.18a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/></svg>
            <a href="tel:${phone}">${phone}</a>
          </div>` : '<div class="detail-phone" style="color:var(--text-muted)">No phone number</div>'}
        ${appt.notes ? `<div class="detail-notes">${appt.notes}</div>` : ''}
        <div class="detail-actions">
          <button class="btn-detail" onclick="TodayView.deleteAppt('${appt.id}')">Delete</button>
        </div>
      </div>
    `;
  }

  // ── Toggle card expand ──────────────────────────
  function toggleCard(id) {
    activeCard = activeCard === id ? null : id;
    render(); // re-render to open/close detail
  }

  // ── Update stats bar ────────────────────────────
  function updateStats() {
    const total   = appointments.length;
    const show    = appointments.filter(a => a.status === 'Show').length;
    const noshow  = appointments.filter(a => a.status === 'No Show').length;
    const pending = appointments.filter(a =>
      !a.status || a.status === 'Tentative Appt').length;

    statTotal.textContent   = total;
    statShow.textContent    = show;
    statNoShow.textContent  = noshow;
    statPending.textContent = pending;
  }

  // ── Render full list ────────────────────────────
  function render() {
    listEl.innerHTML = '';

    if (appointments.length === 0) {
      emptyEl.hidden = false;
      updateStats();
      return;
    }

    emptyEl.hidden = true;
    appointments.forEach(appt => {
      listEl.appendChild(renderCard(appt));
    });
    updateStats();
  }

  // ── Show skeleton loaders ───────────────────────
  function showSkeletons() {
    listEl.innerHTML = `
      <div class="appt-skeleton"></div>
      <div class="appt-skeleton"></div>
      <div class="appt-skeleton"></div>
    `;
    emptyEl.hidden = true;
  }

  // ── Load today's appointments from Supabase ─────
  async function load() {
    showSkeletons();
    try {
      appointments = await API.getAllTodayAppointments();
      render();
    } catch (err) {
      console.error('[TODAY] Load error:', err);
      listEl.innerHTML = `<p style="padding:1rem;color:#EF4444;text-align:center;">
        Could not load appointments. Check your connection.</p>`;
    }
  }

  // ── Status Picker ───────────────────────────────
  function openStatusPicker(appt) {
    statusTarget = appt;
    statusName.textContent = appt.patient_name;
    modalStatus.hidden = false;
  }

  function closeStatusPicker() {
    modalStatus.hidden = true;
    statusTarget = null;
  }

  statusOpts.addEventListener('click', async e => {
    const btn = e.target.closest('.status-opt');
    if (!btn || !statusTarget) return;

    const newStatus = btn.dataset.status;
    const id        = statusTarget.id;

    closeStatusPicker();

    // Optimistic UI — update immediately without waiting for server
    const appt = appointments.find(a => a.id === id);
    if (appt) {
      appt.status = newStatus;
      render(); // instant visual update
    }

    // Save to Supabase in background
    try {
      await API.updateAppointmentStatus(id, newStatus);
    } catch (err) {
      console.error('[TODAY] Status update failed:', err);
      // Revert on failure
      await load();
    }
  });

  // Close status modal on backdrop tap
  modalStatus.addEventListener('click', e => {
    if (e.target === modalStatus) closeStatusPicker();
  });

  // ── Add Appointment ─────────────────────────────
  function openAddModal() {
    // Pre-fill today's date
    inputDate.value = new Date().toISOString().split('T')[0];
    inputName.value = '';
    inputPhone.value = '';
    inputTime.value = '';
    inputTreat.value = '';
    modalAdd.hidden = false;

    // Pre-select the logged-in doctor
    if (doctorData) {
      const isDrMustafa = doctorData.name.toLowerCase().includes('mustafa');
      document.getElementById('doc-btn-mustafa').classList.toggle('active', isDrMustafa);
      document.getElementById('doc-btn-qasim').classList.toggle('active', !isDrMustafa);
    }

    setTimeout(() => inputName.focus(), 300);
  }

  function closeAddModal() {
    modalAdd.hidden = true;
    formAdd.reset();
  }

  btnFab.addEventListener('click', openAddModal);
  modalAdd.addEventListener('click', e => {
    if (e.target === modalAdd) closeAddModal();
  });

  // Doctor toggle buttons
  docBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      docBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
    });
  });

  // Form submit — save appointment
  formAdd.addEventListener('submit', async e => {
    e.preventDefault();

    const name = inputName.value.trim();
    if (!name) { inputName.focus(); return; }

    btnSave.disabled    = true;
    btnSave.textContent = 'Saving...';

    try {
      const activeDoc = document.querySelector('.doctor-btn.active');
      const docName   = activeDoc ? activeDoc.textContent.trim() : null;

      const data = {
        patient_name:      name,
        contact_number:    inputPhone.value.trim() || null,
        appointment_date:  inputDate.value,
        appointment_time:  inputTime.value || null,
        treatment_planned: inputTreat.value.trim() || null,
        status:            'Tentative Appt',
        booked_by:         'manual',
      };

      // Find doctor id by name
      const doctors = await API.getDoctors();
      const doc = doctors.find(d => d.name === docName);
      if (doc) data.doctor_id = doc.id;

      await API.createAppointment(data);
      closeAddModal();
      await load(); // refresh list

    } catch (err) {
      console.error('[TODAY] Save appointment failed:', err);
      btnSave.textContent = 'Error — Try again';
    } finally {
      btnSave.disabled    = false;
      btnSave.textContent = 'Save Appointment';
    }
  });

  // ── Delete appointment ──────────────────────────
  async function deleteAppt(id) {
    if (!confirm('Delete this appointment?')) return;
    appointments = appointments.filter(a => a.id !== id);
    render();
    try {
      await API.deleteAppointment(id);
    } catch (err) {
      console.error('[TODAY] Delete failed:', err);
      await load();
    }
  }

  // ── Load services for autocomplete ─────────────
  async function loadServices() {
    try {
      const services = await API.getServices();
      services.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s.service_name;
        servicesList.appendChild(opt);
      });
    } catch (e) {
      console.warn('[TODAY] Could not load services for autocomplete');
    }
  }

  // ── Listen for view switch ──────────────────────
  window.addEventListener('viewchange', e => {
    if (e.detail.view === 'today') load();
  });

  // ── Public API ──────────────────────────────────
  return {
    init(doctor) {
      doctorData = doctor;
      loadServices();
      load();
    },
    reload: load,
    deleteAppt,
  };

})();
