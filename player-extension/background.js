'use strict';

// Vitrail Player — MV3 background service worker (§3.10).
//
// The MV3 service worker is ephemeral (terminated when idle), so it holds NO long-lived state:
// everything persists in chrome.storage.local. The persistent WebSocket lives in the fullscreen
// player WINDOW (player/index.html) — far more reliable than a SW socket — exactly like the
// ChromeOS PWA. The background's jobs are narrow:
//   - register the player (provisioning token sfp_… → player JWT) so the player page never
//     re-registers (no duplicates),
//   - open / focus / close the fullscreen kiosk window,
//   - answer the popup's status queries,
//   - re-open the player window on browser startup (kiosk continuity).

const PLAYER_PAGE = 'player/index.html';
const PLAYER_OS = 'chrome_extension';
const PLAYER_VERSION = '2.0.12-ext';   // registration only (le heartbeat reporte __SF_PLAYER_VERSION__)

function normBackend(u) { return String(u || '').trim().replace(/\/+$/, ''); }

async function getCfg() {
  return chrome.storage.local.get(['backend_url', 'player_token', 'player_name', 'window_id']);
}

// Provisioning token (sfp_…) → player JWT via POST /players/register. A token that is NOT an sfp_
// is assumed to already be a player JWT (re-attaching an existing player) and stored as-is.
async function registerPlayer(backendUrl, token, name) {
  const backend = normBackend(backendUrl);
  if (!backend || !token) throw new Error('Backend URL and token are required');
  if (!token.startsWith('sfp_')) return token;   // already a player JWT
  const res = await fetch(`${backend}/api/v1/players/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      player_name: name || `chrome-ext-${Math.random().toString(36).slice(2, 8)}`,
      player_os: PLAYER_OS,
      player_version: PLAYER_VERSION,
      org_token: token,
    }),
  });
  if (!res.ok) throw new Error(`register ${res.status}: ${(await res.text()).slice(0, 200)}`);
  const data = await res.json();
  if (!data.player_token) throw new Error('register: no player_token in response');
  return data.player_token;
}

async function launchPlayer() {
  const cfg = await getCfg();
  if (!cfg.backend_url || !cfg.player_token) throw new Error('Not configured');
  // Reuse the existing player window if it is still open.
  if (cfg.window_id != null) {
    try {
      await chrome.windows.get(cfg.window_id);
      await chrome.windows.update(cfg.window_id, { focused: true, state: 'fullscreen' });
      return cfg.window_id;
    } catch { /* window is gone — fall through and recreate */ }
  }
  const win = await chrome.windows.create({
    url: chrome.runtime.getURL(PLAYER_PAGE),
    type: 'popup',
    state: 'fullscreen',
    focused: true,
  });
  await chrome.storage.local.set({ window_id: win.id });
  return win.id;
}

async function stopPlayer() {
  const { window_id } = await chrome.storage.local.get('window_id');
  if (window_id != null) { try { await chrome.windows.remove(window_id); } catch {} }
  await chrome.storage.local.remove('window_id');
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    try {
      if (msg.type === 'register') {
        const jwt = await registerPlayer(msg.backend_url, msg.token, msg.name);
        await chrome.storage.local.set({
          backend_url: normBackend(msg.backend_url), player_token: jwt, player_name: msg.name || '',
        });
        await launchPlayer();
        sendResponse({ ok: true });
      } else if (msg.type === 'launch') {
        await launchPlayer();
        sendResponse({ ok: true });
      } else if (msg.type === 'stop') {
        await stopPlayer();
        sendResponse({ ok: true });
      } else if (msg.type === 'reset') {
        await stopPlayer();
        await chrome.storage.local.clear();
        sendResponse({ ok: true });
      } else if (msg.type === 'status') {
        const cfg = await getCfg();
        let running = false;
        if (cfg.window_id != null) { try { await chrome.windows.get(cfg.window_id); running = true; } catch {} }
        sendResponse({
          ok: true,
          configured: !!(cfg.backend_url && cfg.player_token),
          running,
          backend_url: cfg.backend_url || '',
          player_name: cfg.player_name || '',
          is_jwt: !!(cfg.player_token && !cfg.player_token.startsWith('sfp_')),
        });
      } else {
        sendResponse({ ok: false, error: 'unknown message' });
      }
    } catch (e) {
      sendResponse({ ok: false, error: String((e && e.message) || e) });
    }
  })();
  return true;   // keep the message channel open for the async sendResponse
});

// Kiosk continuity: re-open the player window when Chrome starts, if already configured.
chrome.runtime.onStartup.addListener(async () => {
  const cfg = await getCfg();
  if (cfg.backend_url && cfg.player_token) {
    try { await launchPlayer(); } catch (e) { console.warn('autostart:', e.message); }
  }
});

// A periodic alarm wakes the ephemeral SW so onStartup/onMessage stay responsive.
chrome.alarms.create('keepalive', { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(() => { /* waking the worker is enough */ });

// Forget the tracked window id once it is closed (so the popup shows "stopped").
chrome.windows.onRemoved.addListener(async (id) => {
  const { window_id } = await chrome.storage.local.get('window_id');
  if (id === window_id) await chrome.storage.local.remove('window_id');
});
