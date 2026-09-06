/* ═══════════════════════════════════════════════
   router.js — Hash-based SPA Router
   Switches between views without page reloads.
═══════════════════════════════════════════════ */

const Router = (() => {
  'use strict';

  const VIEWS = ['today', 'patients', 'lab', 'settings'];
  let currentView = 'today';

  function switchView(viewName) {
    if (!VIEWS.includes(viewName)) return;
    if (viewName === currentView) return;

    // Hide current view
    const oldView = document.getElementById('view-' + currentView);
    if (oldView) oldView.classList.remove('active-view'), oldView.hidden = true;

    // Deactivate old nav btn
    const oldNav = document.querySelector('.nav-btn.active');
    if (oldNav) oldNav.classList.remove('active');

    // Show new view
    const newView = document.getElementById('view-' + viewName);
    if (newView) { newView.hidden = false; newView.classList.add('active-view'); }

    // Activate new nav btn
    const newNav = document.getElementById('nav-' + viewName);
    if (newNav) newNav.classList.add('active');

    // Trigger view-specific load
    currentView = viewName;
    window.dispatchEvent(new CustomEvent('viewchange', { detail: { view: viewName } }));
  }

  // Wire up bottom nav buttons
  document.getElementById('bottom-nav').addEventListener('click', e => {
    const btn = e.target.closest('.nav-btn');
    if (!btn) return;
    switchView(btn.dataset.view);
  });

  return { switchView, getCurrent: () => currentView };
})();
