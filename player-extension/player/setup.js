'use strict';

// In-page setup fallback (§3.10) — externalised from index.html (MV3 forbids inline scripts).
// Normally configuration arrives from the extension popup; this screen only appears if the player
// window is opened without a stored backend/token. Mirrors the ChromeOS index.html wiring.
(function () {
  var screen = document.getElementById('setup-screen');
  var save = document.getElementById('su-save');
  if (!window.signflow || !screen || !save) return;

  window.signflow.onSetupRequired(function () {
    document.getElementById('su-backend').value = localStorage.getItem('signflow_backend_url') || '';
    screen.classList.add('show');
  });
  window.signflow.onConnected(function () { screen.classList.remove('show'); });

  save.addEventListener('click', function () {
    var backend = document.getElementById('su-backend').value.trim();
    var token = document.getElementById('su-token').value.trim();
    if (!backend || !token) return;
    screen.classList.remove('show');
    // Persist for the background/popup too, then connect.
    try { chrome.storage.local.set({ backend_url: backend.replace(/\/+$/, ''), player_token: token }); } catch (e) {}
    window.signflow.saveWizard({ backend_url: backend, player_token: token });
  });
})();
