# Vitrail Player — ChromeOS PWA (§3.9)

🇫🇷 [Version française](README.fr.md)

> ⚠️ **The code lives in `frontend/public/player-chromeos/`, NOT here.** This folder now only
> contains this documentation. It previously hosted a `src/` copy that was supposed to be the
> source, but had in fact been **abandoned for months** (961 lines of difference on
> `signflow.js`, 445 on `player.js`): Next serves `public/` directly, so that copy is the one
> running on the Chromeboxes **and on the BrightSign players** (their `bootstrap.html` loads
> the same files). The duplicate has been removed — it caused fixes to be applied in the
> wrong place. **Every fix to the ChromeOS/BrightSign renderer goes into
> `frontend/public/player-chromeos/`.**

Vitrail digital signage player ported as a **Progressive Web App** for Chromebox /
Chromebook in **managed kiosk** mode (Google Admin console) or as a full-screen PWA.

## Principle

The native Electron shell (`main.js` + `preload.js`) is replaced by a PWA:
- `frontend/public/player-chromeos/signflow.js` — **bridge**: exposes the same `window.signflow` contract as the Electron
  preload, but fed by a **browser WebSocket** (`/api/v1/ws/player?token=…`) instead of
  Electron IPC. Provisioning, `player:status` heartbeat, backoff reconnection +
  liveness watchdog.
- `frontend/public/player-chromeos/player.js`, `frontend/public/player-chromeos/audio_player.js`, `frontend/public/player-chromeos/style.css` — **reused VERBATIM** from
  `player-linux/src/renderer/`. `player.js` does not expose `window.signflow.mpv` → video
  goes through the Chromium `<video>` element (ChromeOS decodes in HW natively).
- `frontend/public/player-chromeos/index.html` — shell + setup screen (browser fallback outside kiosk).
- `frontend/public/player-chromeos/manifest.webmanifest` + `frontend/public/player-chromeos/icon.svg` — PWA / kiosk installability.

> These files were DERIVED from `player-linux/src/renderer/` but have diverged since
> (BrightSign branches, local cache, LAN VOD…). **Do not overwrite them with a copy of the
> Electron renderer anymore**: apply fixes on both sides, as for the other rendering
> surfaces (the fleet has 7 of them).

## Scope by phase

| Phase | Content | Status |
|-------|---------|--------|
| **A** | PWA shell + WS + video/image/web/PDF rendering + in-store audio (Web Audio) | **done** |
| **B** | Service Worker (offline app shell) + Cache API for media (download-then-play) | **done** |
| C1 | Audio routing via `AudioContext.setSinkId` (building block shared with Windows/BrightSign) | to do |
| C2 | Backend-mediated Store Control Panel (no embedded HTTP server) | to do |
| C3 | RS232 via the WebSerial API | to do |
| D | UDP LAN sync = **impossible in the PWA sandbox** (players not frame-locked) | accepted limitation |

In Phase A, the LAN hooks (`onLanAdjust/onLanSwitch/onLanRelease`, `reportPlaybackPos`),
offline hook (`onStoreUpdate`) and control panel hook (`onControlApply`) are stubbed (never triggered).
The **maintenance overlay** (`toggle_overlay`) is fully supported.

## Deployment (served by the Next frontend, `public/`)

The PWA is served statically by Next from `frontend/public/player-chromeos/`, which is the
**single source** (no more deployment copy). Next serves `public/` at the root → the
public URL is:

```
http://cms.example.com:8080/player-chromeos/index.html
```

Update on the Ubuntu production server: `git pull` is enough (static files, **no** `.next`
purge or frontend restart needed in `npm run dev`).

Re-sync the copy after a source change:
```
```

## Provisioning / kiosk

1. Create the player in the CMS and get its **player token** (from the **backend**
   container, see the golden rules). An org provisioning token `sfp_…` is also accepted
   (the bridge exchanges it via `POST /players/register`).
2. **Managed kiosk (Google Admin)**: Devices > Chrome > Apps &
   extensions > **Kiosks** > add a **web app by URL**, with the token as a query parameter:
   ```
   http://cms.example.com:8080/player-chromeos/index.html?token=<JWT_PLAYER>
   ```
   The bridge reads `?token=` (and the optional `?backend=`; otherwise = the page origin), persists
   it in localStorage and purges the URL. Enable the **"Allow autoplay"** policy
   (otherwise in-store audio waits for a user gesture — a single tap is enough).
3. **Browser fallback** (without Admin): open the URL without a token → setup screen to enter
   backend + token, then F11 for full screen.

## Offline (Phase B)

> ⚠️ **Secure context prerequisite**: Service Workers only register over **HTTPS**
> (or `http://localhost`). On the current `http://cms.example.com:8080`,
> `navigator.serviceWorker` is `undefined` → Phase B **inactive**, **graceful** degradation
> (Phase A streaming unchanged, log `[SW] non supporté`). Phase B switches on as soon as the
> frontend moves to **HTTPS** (Caddy/Let's Encrypt or Cloudflare Tunnel — already on the infra roadmap).

- **`frontend/public/player-chromeos/sw.js`** (Service Worker): precaches the app shell (index/js/css/manifest) as
  **network-first** (fresh when online, cache fallback when offline → offline startup); serves
  cached media under `…/__sf_media__/<cache_key>` as **cache-first with Range support (206)**
  for the `<video>` element.
- **Page-side store** (in `signflow.js`): on each `player:sync`, media already cached
  have their url rewritten to the local path (served by the SW); missing ones are
  downloaded in the background (**download-then-play**), then `store-update` → `player.js` patches in
  place. Cache API for the bytes, IndexedDB (`signflow-store`) for the metadata + **LRU eviction
  by budget** (8 GB soft; media of the current sync are pinned). Offline boot replays
  the last sync from localStorage (local urls persisted).
- ⚠️ **CORS prerequisite**: the cacheable download does a cross-origin `fetch()` to MinIO
  → MinIO must return `Access-Control-Allow-Origin` (MinIO default = `*`, so usually OK).
  If CORS is missing: **graceful** fallback = the MinIO streaming url is kept (online works,
  no offline for that asset). Robust alternative (+ fixes WAN media) = same-origin backend
  proxy.

## Accepted limitations

- No frame-locked LAN sync (PWA sandbox = no UDP) — Phase D, not solvable.
- Native `screenshot`/`reboot_os` unavailable (reload as fallback).
- At-rest encryption of cached media (Cache API/IndexedDB): not implemented (see the ChromeOS
  security rule in CLAUDE.md) — to be addressed before production.
