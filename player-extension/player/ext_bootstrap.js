'use strict';

// Extension bootstrap (§3.10) — bridges chrome.storage.local → the reused ChromeOS renderer.
//
// The renderer (ed25519.js + signflow.js + audio_player.js + player.js) is the SAME code as player-chromeos,
// reused verbatim. It reads provisioning from localStorage and connects via window.signflow.
// Differences vs the ChromeOS PWA:
//   - config comes from chrome.storage.local (written by the popup/background), not URL params,
//   - player_os is reported as 'chrome_extension' (via the __SF_* globals the bridge now reads),
//   - no Service Worker offline store: navigator.serviceWorker.register is unavailable on
//     chrome-extension:// pages, so the bridge's registerServiceWorker() fails gracefully and the
//     player streams online (spec §3.10: "Offline ✅ Partiel"). Online playback is unaffected.
//
// Ordering matters: signflow.js defers connect()/setup-required via setTimeout(0) so player.js can
// subscribe first. We therefore load all renderer scripts IN ORDER and only THEN call saveWizard()
// to connect — by which point player.js has subscribed to onSync/onConnected/etc.

(async function () {
  const LS_BACKEND = 'signflow_backend_url';
  const LS_TOKEN = 'signflow_player_token';

  // Platform identity for registration (read by the parameterized signflow.js).
  window.__SF_PLAYER_OS__ = 'chrome_extension';
  window.__SF_PLAYER_VERSION__ = '2.0.12-ext';   // bundle OTA-capable (handleWebOta) — bump = recharger l'extension

  let cfg = {};
  try {
    cfg = await chrome.storage.local.get(['backend_url', 'player_token', 'player_name']);
  } catch (e) {
    console.warn('[ext] chrome.storage read failed:', e && e.message);
  }
  if (cfg.player_name) window.__SF_PLAYER_NAME__ = cfg.player_name;

  // Mirror the JWT the bridge stores (sfp_ → JWT swap on first registration) back to chrome.storage
  // so a relaunch reuses the JWT and never re-registers (no duplicate players).
  function mirrorToken() {
    try {
      const tok = localStorage.getItem(LS_TOKEN) || '';
      if (tok && !tok.startsWith('sfp_')) chrome.storage.local.set({ player_token: tok });
    } catch {}
  }

  function load(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = src;
      s.async = false;
      s.onload = resolve;
      s.onerror = () => reject(new Error('failed to load ' + src));
      document.body.appendChild(s);
    });
  }

  try {
    await load('ed25519.js');      // window.SFEd25519 (noble) → PoP signature Ed25519, BEFORE signflow.js
    await load('signflow.js');     // defines window.signflow (no token yet → setup-required is a no-op)
    await load('audio_player.js'); // window.signflowAudio
    await load('player.js');       // subscribes to bridge events
    await load('setup.js');        // in-page setup fallback wiring

    if (window.signflow && window.signflow.onConnected) window.signflow.onConnected(mirrorToken);
    setInterval(mirrorToken, 5000);

    // Connect with player.js already subscribed. saveWizard() persists backend+token to localStorage
    // and calls connect() (which exchanges an sfp_ token for a JWT using the __SF_* globals).
    if (cfg.backend_url && cfg.player_token && window.signflow && window.signflow.saveWizard) {
      window.signflow.saveWizard({ backend_url: cfg.backend_url, player_token: cfg.player_token });
    } else {
      // Not configured (window opened manually) → reveal the in-page setup fallback.
      const el = document.getElementById('setup-screen');
      if (el) el.classList.add('show');
    }
  } catch (e) {
    console.error('[ext] bootstrap failed:', e);
    const el = document.getElementById('fallback-msg');
    if (el) el.textContent = 'Player bootstrap error: ' + (e && e.message);
  }
})();
