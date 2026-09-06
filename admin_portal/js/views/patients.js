/* ═══════════════════════════════════════════════
   patients.js — Patients & Treatment History
   Handles searching patients, listing them, and 
   showing their full treatment timeline in a sheet.
═══════════════════════════════════════════════ */

const PatientsView = (() => {
  'use strict';

  let debounceTimer = null;

  // DOM Elements
  const searchInput  = document.getElementById('patient-search');
  const searchClear  = document.getElementById('search-clear');
  const listEl       = document.getElementById('patient-list');
  const emptyEl      = document.getElementById('patients-empty');
  
  // Profile Sheet Elements
  const modalProfile = document.getElementById('modal-patient-profile');
  const profName     = document.getElementById('profile-name');
  const profPhone    = document.getElementById('profile-phone');
  const profAge      = document.getElementById('profile-age');
  const profGender   = document.getElementById('profile-gender');
  const treatList    = document.getElementById('treatment-list');
  const treatEmpty   = document.getElementById('treatments-empty');

  // Format Date (e.g. "6 Sept 2026")
  function formatDate(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return `${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear()}`;
  }

  // Calculate age from Dob or return existing age
  function getAgeDisplay(age) {
    if (!age) return '';
    return `${age} yrs`;
  }

  // ── Render single patient card ─────────────────────
  function renderPatientCard(p) {
    const card = document.createElement('div');
    card.className = 'patient-card';
    
    card.innerHTML = `
      <div class="patient-name-row">
        <span class="patient-name">${p.name}</span>
        <span class="patient-phone">${p.contact_number || ''}</span>
      </div>
      <div class="patient-meta-row">
        ${p.gender ? `<span>${p.gender}</span>` : ''}
        ${p.age ? `<span>${getAgeDisplay(p.age)}</span>` : ''}
      </div>
    `;

    card.addEventListener('click', () => openPatientProfile(p));
    return card;
  }

  // ── Render treatment item ──────────────────────────
  function renderTreatment(t) {
    const item = document.createElement('div');
    item.className = 'treatment-item';
    
    // Some treatments have amounts and balances
    const amtInfo = [];
    if (t.amount) amtInfo.push(`Total: Rs ${t.amount}`);
    if (t.paid) amtInfo.push(`Paid: Rs ${t.paid}`);
    if (t.balance) amtInfo.push(`Bal: Rs ${t.balance}`);
    
    item.innerHTML = `
      <div class="treatment-header">
        <span class="treatment-date">${formatDate(t.date)}</span>
        <span class="treatment-doctor">${t.visit_type || 'Visit'}</span>
      </div>
      <div class="treatment-details">${t.treatment || 'No details recorded'}</div>
      ${amtInfo.length > 0 ? `<div class="treatment-tooth">${amtInfo.join(' • ')}</div>` : ''}
      ${t.notes ? `<div class="treatment-notes">${t.notes}</div>` : ''}
    `;
    return item;
  }

  // ── Perform Search ─────────────────────────────────
  async function search(query) {
    listEl.innerHTML = '';
    
    if (!query) {
      emptyEl.hidden = false;
      emptyEl.querySelector('.empty-title').textContent = 'Search Patients';
      emptyEl.querySelector('.empty-sub').textContent = 'Type a name or phone number above to find patient records and history.';
      return;
    }

    emptyEl.hidden = true;
    listEl.innerHTML = '<div class="coming-soon">Searching...</div>';

    try {
      const results = await API.searchPatients(query);
      listEl.innerHTML = '';
      
      if (results.length === 0) {
        emptyEl.hidden = false;
        emptyEl.querySelector('.empty-title').textContent = 'No patients found';
        emptyEl.querySelector('.empty-sub').textContent = `No records matching "${query}"`;
        return;
      }

      results.forEach(p => {
        listEl.appendChild(renderPatientCard(p));
      });
    } catch (err) {
      console.error('[PATIENTS] Search failed:', err);
      listEl.innerHTML = '<div class="coming-soon" style="color:var(--status-noshow-text)">Search failed. Please try again.</div>';
    }
  }

  // ── Open Profile & Load Treatments ─────────────────
  async function openPatientProfile(patient) {
    // Populate header
    profName.textContent   = patient.name;
    profPhone.textContent  = patient.contact_number || 'No Phone';
    profAge.textContent    = patient.age ? getAgeDisplay(patient.age) : 'Unknown Age';
    profGender.textContent = patient.gender || 'Unknown Gender';

    // Reset list
    treatList.innerHTML = '<div class="coming-soon">Loading history...</div>';
    treatEmpty.hidden = true;
    modalProfile.hidden = false;

    // Fetch treatments
    try {
      // The API uses ILIKE on patient_name to find treatments
      const treatments = await API.getPatientTreatments(patient.name);
      treatList.innerHTML = '';

      if (treatments.length === 0) {
        treatEmpty.hidden = false;
      } else {
        treatments.forEach(t => {
          treatList.appendChild(renderTreatment(t));
        });
      }
    } catch (err) {
      console.error('[PATIENTS] Failed to load treatments:', err);
      treatList.innerHTML = '<div class="coming-soon" style="color:var(--status-noshow-text)">Could not load treatment history.</div>';
    }
  }

  function closePatientProfile() {
    modalProfile.hidden = true;
  }

  const monthInput   = document.getElementById('patient-month-filter');
  const monthClear   = document.getElementById('month-clear');

  // ── Perform Month Filter ──────────────────────────
  async function filterByMonth(monthStr) {
    listEl.innerHTML = '';
    
    if (!monthStr) {
      search(searchInput.value.trim()); // Revert to text search
      return;
    }

    // If browser doesn't support <input type="month"> and user types plain text
    if (!monthStr.match(/^\d{4}-\d{2}$/)) {
      emptyEl.hidden = false;
      emptyEl.querySelector('.empty-title').textContent = 'Invalid Format';
      emptyEl.querySelector('.empty-sub').textContent = 'Please use YYYY-MM format (e.g. 2026-09) or search by name above.';
      return;
    }

    // Clear text search when filtering by month
    searchInput.value = '';
    searchClear.hidden = true;

    emptyEl.hidden = true;
    listEl.innerHTML = '<div class="coming-soon">Loading patients for this month...</div>';

    try {
      // 1. Fetch all treatments for the selected month
      const treatments = await API.getTreatmentsByMonth(monthStr);
      
      if (treatments.length === 0) {
        listEl.innerHTML = '';
        emptyEl.hidden = false;
        emptyEl.querySelector('.empty-title').textContent = 'No visits found';
        emptyEl.querySelector('.empty-sub').textContent = `No patients visited in ${monthStr}.`;
        return;
      }

      // 2. Extract unique patient names
      const uniqueNames = [...new Set(treatments.map(t => t.patient_name))].filter(Boolean);
      
      // 3. Fetch patient details for these names (in chunks if too many, but Supabase handles up to a limit. We'll slice 100 for safety)
      const patients = await API.getPatientsByNames(uniqueNames.slice(0, 100));

      listEl.innerHTML = '';
      if (patients.length === 0) {
        listEl.innerHTML = '<div class="coming-soon">Patients found in treatments but records missing.</div>';
        return;
      }

      patients.forEach(p => {
        listEl.appendChild(renderPatientCard(p));
      });
      
      // Show total count at the top of the list
      const countEl = document.createElement('div');
      countEl.style.fontSize = 'var(--font-size-xs)';
      countEl.style.color = 'var(--text-muted)';
      countEl.style.fontWeight = '600';
      countEl.style.padding = '0 4px 8px';
      countEl.textContent = `Showing ${patients.length} patients who visited in this month`;
      listEl.prepend(countEl);

    } catch (err) {
      console.error('[PATIENTS] Month filter failed:', err);
      listEl.innerHTML = '<div class="coming-soon" style="color:var(--status-noshow-text)">Filter failed. Please try again.</div>';
    }
  }

  // ── Event Listeners ────────────────────────────────
  searchInput.addEventListener('input', e => {
    const val = e.target.value.trim();
    searchClear.hidden = val.length === 0;
    
    // Clear month filter when typing text
    if (val.length > 0 && monthInput.value) {
      monthInput.value = '';
      monthClear.hidden = true;
    }

    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      search(val);
    }, 300); // 300ms debounce
  });

  monthInput.addEventListener('change', e => {
    const val = e.target.value;
    monthClear.hidden = !val;
    filterByMonth(val);
  });

  monthClear.addEventListener('click', () => {
    monthInput.value = '';
    monthClear.hidden = true;
    search(searchInput.value.trim());
  });

  searchClear.addEventListener('click', () => {
    searchInput.value = '';
    searchClear.hidden = true;
    search('');
    searchInput.focus();
  });

  modalProfile.addEventListener('click', e => {
    if (e.target === modalProfile) closePatientProfile();
  });

  // Initial empty search (just shows default prompt)
  search('');

  // ── Public API ─────────────────────────────────────
  return {
    init() {
      // Setup runs on load, but we can re-trigger if needed
    },
    // If we want to auto-search on view change
    reload() {
      if (searchInput.value.trim() === '') {
        // Maybe fetch recent 10 patients instead of empty state later
      }
    }
  };

})();
