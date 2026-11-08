# Vitrail Player — Chrome Extension (§3.10)

A **Manifest V3** browser extension that turns any Chrome (Windows / macOS / Linux / ChromeOS)
into a Vitrail-managed player — **no native app** (no Electron, no APK). For corporate screens on
an existing PC, fast POCs, or meeting-room displays without dedicated hardware (§XXVI Workplace).

Registers as a `cms_player` with `player_os = 'chrome_extension'` and appears in the CMS dashboard
like any other player.

## Architecture

```
Chrome (any OS)
 └── Vitrail Player extension (MV3)
      ├── background.js     — service worker: register (sfp_ → JWT), open/close the
      │                       fullscreen kiosk window, status, re-open on startup
      ├── popup.html/.js    — register the player, status, launch / stop / reset
      └── player/index.html — fullscreen kiosk window; runs the SAME renderer as the
                              ChromeOS player (signflow.js + audio_player.js + player.js)
```

The persistent WebSocket lives in the **player window**, not the (ephemeral) MV3 service worker —
the same proven model as the ChromeOS PWA. The window is opened with
`chrome.windows.create({ type:'popup', state:'fullscreen' })`.

### Renderer reuse

`player/player.js`, `player/audio_player.js`, `player/signflow.js`, `player/style.css`,
`player/sw.js` are **byte-identical copies** of `frontend/public/player-chromeos/` (the served
renderer source — `player-chromeos/src/` was removed on 2026-07-19). The only platform
differences (player OS / name / version) are injected at runtime by `player/ext_bootstrap.js`
through the `window.__SF_PLAYER_OS__` / `__SF_PLAYER_NAME__` / `__SF_PLAYER_VERSION__` globals that
`signflow.js` reads (defaulting to ChromeOS values). **Keep these copies in sync with
`frontend/public/player-chromeos/` after any renderer change.**

`ext_bootstrap.js` reads `{backend_url, player_token}` from `chrome.storage.local` (written by the
popup), mirrors them into `localStorage` (where the reused bridge expects them), loads the renderer
scripts in order, then connects via `window.signflow.saveWizard()` (ordering preserves the bridge's
`setTimeout(0)` deferral so `player.js` subscribes before the WS connects).

## Install (developer / unpacked)

1. `chrome://extensions` → enable **Developer mode** → **Load unpacked** → select this folder.
2. Click the extension icon → enter the **Backend URL** and a **provisioning token** (CMS ›
   Players › Provisioning, `sfp_…`) → **Register & launch**. A fullscreen player window opens and
   the player appears in the dashboard. (You can also paste an existing player JWT to re-attach.)

Managed rollout: package as `.crx` and push via **Google Admin** (ChromeOS/Workspace) or **Group
Policy** `ExtensionInstallForcelist` (Windows). Enable Chrome's autoplay policy for the kiosk so
in-store audio starts without a gesture.

## Capabilities & limitations (§3.10)

| Capability | Support |
|------------|---------|
| Video H.264/HEVC, image, HTML/CSS, audio in-store | ✅ via `<video>` / Web Audio |
| URL Display (iframe), Feed Display | ✅ (Feed `video_feed` limited by Chrome autoplay policy) |
| Screenshot to CMS | ✅ in-page canvas capture (periodic, like ChromeOS) |
| Offline playback | ⚠️ **Partial / online streaming** — `navigator.serviceWorker.register` is
  not available on `chrome-extension://` pages, so the offline content store (SW + Cache API) is
  disabled; the bridge degrades gracefully to online streaming (`_swActive=false`). |
| LAN frame-sync (UDP) | ❌ not available in the browser sandbox |
| RS232 / screen control | ⚠️ WebSerial only on ChromeOS, blocked by policy on standard Win/macOS |

## Notes

- The player token is stored in `chrome.storage.local` (protected by the Chrome profile).
- `host_permissions` is `http://*/*` + `https://*/*` because the backend URL is user-configured
  (lets the player window reach the backend WS + MinIO media without CORS friction).
- Min Chrome 116.
