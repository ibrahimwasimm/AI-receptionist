/* ═══════════════════════════════════════════════
   auth.js — PIN Login Logic
   Centre for Modern Dentistry Admin Portal
═══════════════════════════════════════════════ */

(function () {
  'use strict';

  // ── State ──────────────────────────────────────
  let currentPin     = '';
  let attemptCount   = 0;
  let isLocked       = false;
  let lockoutTimer   = null;
  let isVerifying    = false;

  // ── DOM References ─────────────────────────────
  const dots         = Array.from({ length: CONFIG.PIN_LENGTH }, (_, i) => document.getElementById(`dot-${i}`));
  const hintEl       = document.getElementById('pin-hint');
  const displayEl    = document.getElementById('pin-display');
  const keypadEl     = document.getElementById('pin-keypad');
  const lockoutEl    = document.getElementById('lockout-banner');
  const lockoutTimer_el = document.getElementById('lockout-timer');
  const loginScreen  = document.getElementById('screen-login');
  const appScreen    = document.getElementById('screen-app');

  // ── Render PIN dots ────────────────────────────
  function renderDots() {
    dots.forEach((dot, i) => {
      dot.classList.toggle('filled', i < currentPin.length);
      dot.classList.remove('error');
    });
  }

  // ── Append a digit ─────────────────────────────
  function appendDigit(digit) {
    if (isLocked || isVerifying)           return;
    if (currentPin.length >= CONFIG.PIN_LENGTH) return;

    currentPin += digit;
    renderDots();
    resetHint();

    if (currentPin.length === CONFIG.PIN_LENGTH) {
      submitPin();
    }
  }

  // ── Backspace ──────────────────────────────────
  function backspace() {
    if (isLocked || isVerifying) return;
    if (currentPin.length === 0) return;
    currentPin = currentPin.slice(0, -1);
    renderDots();
    resetHint();
  }

  // ── Reset hint to default ──────────────────────
  function resetHint() {
    hintEl.textContent = 'Enter your 6-digit PIN';
    hintEl.classList.remove('error');
  }

  // ── Show error state ───────────────────────────
  function showError(message) {
    hintEl.textContent = message;
    hintEl.classList.add('error');

    // Turn dots red
    dots.forEach(dot => {
      dot.classList.remove('filled');
      dot.classList.add('error');
    });

    // Shake the dot display
    displayEl.classList.remove('shake');
    void displayEl.offsetWidth; // force reflow to re-trigger animation
    displayEl.classList.add('shake');

    // Clear dots and error state after shake
    setTimeout(() => {
      currentPin = '';
      renderDots();
      displayEl.classList.remove('shake');
    }, 500);
  }

  // ── Submit & verify PIN ────────────────────────
  async function submitPin() {
    if (isVerifying) return;
    isVerifying = true;

    // Show loading state in hint
    hintEl.innerHTML = '<span class="pin-spinner"></span>';
    hintEl.classList.remove('error');

    try {
      const res = await fetch(`${CONFIG.RAILWAY_API_URL}/api/admin/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin: currentPin }),
      });

      if (res.ok) {
        const data = await res.json();
        onLoginSuccess(data);
      } else if (res.status === 401) {
        onWrongPin();
      } else {
        showError('Server error. Please try again.');
        currentPin = '';
        isVerifying = false;
      }

    } catch (err) {
      // Network error or backend not yet deployed — dev fallback
      console.warn('[AUTH] Backend unreachable. Using dev mode fallback.');
      handleDevFallback();
    }
  }

  // ── Dev fallback (Render server sleeping or unreachable) ──
  // Uses the REAL PINs so login still works during cold starts.
  function handleDevFallback() {
    // Real PINs — same as what's stored (bcrypt) in Supabase
    const devPins = {
      '112233': { name: 'Dr. Mustafa', display_name: 'Dr. Mustafa', role: 'doctor' },
      '445566': { name: 'Dr. Qasim',   display_name: 'Dr. Qasim',   role: 'doctor' },
    };

    const doctor = devPins[currentPin];
    if (doctor) {
      onLoginSuccess({ token: 'dev-token', doctor });
    } else {
      showError('Wrong PIN. (Server offline — try again in 30s)');
      currentPin  = '';
      isVerifying = false;
    }
    isVerifying = false;
  }

  // ── Handle successful login ────────────────────
  function onLoginSuccess(data) {
    // Save session to localStorage
    localStorage.setItem(CONFIG.SESSION_KEY,        data.token);
    localStorage.setItem(CONFIG.SESSION_DOCTOR_KEY, JSON.stringify(data.doctor));

    // Reset attempts
    attemptCount = 0;

    // Smooth transition to app shell
    loginScreen.style.opacity = '0';
    loginScreen.style.transform = 'scale(0.97)';
    loginScreen.style.transition = 'opacity 300ms ease, transform 300ms ease';

    setTimeout(() => {
      loginScreen.classList.remove('active');
      loginScreen.hidden = true;

      appScreen.hidden = false;
      appScreen.classList.add('active');
      appScreen.style.opacity = '0';

      requestAnimationFrame(() => {
        appScreen.style.transition = 'opacity 300ms ease';
        appScreen.style.opacity = '1';
      });

      // Fire app init (defined in app.js — built next step)
      if (typeof initApp === 'function') {
        initApp(data.doctor);
      }
    }, 300);

    isVerifying = false;
  }

  // ── Handle wrong PIN ───────────────────────────
  function onWrongPin() {
    attemptCount++;
    isVerifying = false;

    const remaining = CONFIG.MAX_PIN_ATTEMPTS - attemptCount;

    if (attemptCount >= CONFIG.MAX_PIN_ATTEMPTS) {
      startLockout();
    } else {
      showError(
        remaining === 1
          ? 'Incorrect PIN — 1 attempt remaining'
          : `Incorrect PIN — ${remaining} attempts remaining`
      );
    }
  }

  // ── Lockout (5 wrong attempts) ─────────────────
  function startLockout() {
    isLocked = true;
    keypadEl.style.opacity = '0.35';
    keypadEl.style.pointerEvents = 'none';

    lockoutEl.hidden = false;
    lockoutTimer_el.textContent = CONFIG.LOCKOUT_SECONDS;

    let remaining = CONFIG.LOCKOUT_SECONDS;

    lockoutTimer = setInterval(() => {
      remaining--;
      lockoutTimer_el.textContent = remaining;

      if (remaining <= 0) {
        clearInterval(lockoutTimer);
        endLockout();
      }
    }, 1000);

    showError('Too many attempts');
  }

  function endLockout() {
    isLocked      = false;
    attemptCount  = 0;
    currentPin    = '';

    keypadEl.style.opacity      = '1';
    keypadEl.style.pointerEvents = 'auto';
    lockoutEl.hidden = true;

    renderDots();
    resetHint();
  }

  // ── Check existing session on page load ────────
  function checkExistingSession() {
    const token  = localStorage.getItem(CONFIG.SESSION_KEY);
    const doctor = localStorage.getItem(CONFIG.SESSION_DOCTOR_KEY);

    if (token && doctor) {
      // TODO: optionally validate token with backend before auto-login
      const doctorData = JSON.parse(doctor);
      onLoginSuccess({ token, doctor: doctorData });
    }
  }

  // ── Keyboard support (for desktop/laptop use) ──
  document.addEventListener('keydown', (e) => {
    if (e.key >= '0' && e.key <= '9') appendDigit(e.key);
    if (e.key === 'Backspace')         backspace();
  });

  // ── Keypad click handler ───────────────────────
  keypadEl.addEventListener('click', (e) => {
    const btn = e.target.closest('.key-btn');
    if (!btn) return;

    if (btn.id === 'key-backspace') {
      backspace();
    } else {
      const digit = btn.dataset.digit;
      if (digit !== undefined) appendDigit(digit);
    }
  });

  // ── Init ───────────────────────────────────────
  checkExistingSession();

})();
