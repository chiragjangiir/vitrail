# SPIKE — Intel/Linux HW decoding via mpv, enabled per player

🇫🇷 [Version française](SPIKE_mpv_hwdecode_linux.fr.md)

> Status: **DESIGN** (2026-06-09). Follows up on the note « Décodage HW Intel/Linux via mpv »
> and the verdict: **VA-API is unreachable in stock Electron on
> Intel/Linux** (frame pool cannot be allocated, DO NOT retry the flags — see `vaapi_profiles.js`),
> whereas **mpv decodes 4K H.264 in HW VAAPI** on the same hardware. Trigger: a possible customer
> request (heavy video on an Intel fleet). Goal: offer HW decoding **as an option enabled per
> player**, without breaking the existing Chromium pipeline.

## 1. Starting constraint

| Player | Video decoding | HW path |
|--------|----------------|---------|
| RPi 4/5 | HW | V4L2 (cage, already wired) |
| Windows | HW | D3D11 (default) |
| **Intel/Linux (NUC and Intel test players)** | **SW (~FHD30)** | **VAAPI — but ONLY outside Electron → mpv** |

mpv (`--hwdec=vaapi --vo=gpu`) plays 4K H.264 smoothly on this HW (`intel_gpu_top`: Video engine ~70%).
player-linux runs under **X11 + openbox + lightdm** (≠ RPi under cage/Wayland). This matters:
the z-order of two X11 windows can be controlled (openbox/wmctrl/`_NET_WM_STATE_ABOVE`).

## 2. Current integration surface (what mpv must take over)

Everything is currently attached to the renderer's `<video>` element (`player-linux/src/renderer/player.js`):

| Function | Current `<video>` coupling | mpv equivalent |
|----------|---------------------------|----------------|
| Video playback | `createElement('video')`, `src`, `autoplay` | `loadfile <path|url>` via IPC |
| Offline-first source | `signflow://<cache_key>` (Electron protocol) | **disk path** `contentStore.fileFor(key).path` OR MinIO http URL (mpv reads both) |
| LAN sync — report | `_activeVideo.currentTime` | mpv property `time-pos` (IPC `get_property`) |
| LAN sync — nudge | `_activeVideo.playbackRate = 1.05/0.95` | mpv property `speed` |
| LAN sync — hard resync | `_activeVideo.currentTime = …` | mpv command `seek <t> absolute` |
| End of item | `video.onended` → `scheduleAdvance` | mpv event `end-file` |
| Content mute | `video.muted` | mpv property `mute` |
| Audio output (Windows) | `setSinkId` | mpv `--audio-device` |
| Subtitles §7 | injected WebVTT `<track>` | mpv `sub-add <url>` (WebVTT supported) |
| Maintenance overlay | reads `_activeVideo.currentTime/duration` | mpv `time-pos` / `duration` |
| Precache #2a | hidden double-buffer `<video>` | **not mappable** onto 1 mpv instance (see v1 limits) |
| Played resolution (overlay) | `videoWidth×videoHeight` | mpv properties `dwidth/dheight` |

Images, PDF, web pages, templates, status bar, **overlay** = remain rendered by **Chromium**.
mpv ONLY takes over video.

## 3. Chosen architecture — **Option A** (mpv sibling window + IPC)

Reminder of the options from the EVOLUTIONS note:
- **(A) fullscreen mpv X11 window driven by Electron over IPC** ← **CHOSEN**
- (B) offscreen mpv `--vo=gpu` → dma-buf re-injected into Chromium (clean but heavy GL/EGL interop, out of budget)
- (C) pure non-Electron video player (loses templates/images/web — too limiting for the current fleet)

**Why A**: preserves 100% of the Chromium pipeline (templates, images, web, subtitles of the
other types, overlay); mpv only intercepts video items; the cost is the **z-order** between
2 windows (the only real risk, isolated in Phase 0).

### 3.1 How it works

```
┌─ openbox (X11) ───────────────────────────────────────────┐
│  Fenêtre Electron (kiosk, fullscreen)   ── UI, images,     │
│     ▲ z-order piloté                       web, templates, │
│     │                                      overlay, status │
│  Fenêtre mpv (fullscreen, --no-border)  ── VIDÉO HW VAAPI  │
│     ▲ remontée AU-DESSUS pendant un item vidéo,            │
│       redescendue pour image/web/template/overlay          │
└────────────────────────────────────────────────────────────┘
        main.js  ──spawn + JSON IPC (socket UNIX)──► mpv --idle
```

(Diagram: the Electron window (kiosk, fullscreen) renders UI, images, web, templates, overlay and status, with its z-order controlled; the mpv window (fullscreen, `--no-border`) renders HW VAAPI video and is raised ABOVE during a video item, lowered for image/web/template/overlay.)

- **Video** item → main: `loadfile`, then raises mpv on top (`wmctrl`/`_NET_WM_STATE_ABOVE` or
  `mpv --ontop` + Electron `setAlwaysOnTop(false)`).
- **Non-video** item → main: lowers mpv (Electron goes back on top), Chromium renders the item.
- **Overlay** requested → lower mpv for the duration of the display (v1 limit, see §6).

### 3.2 The toggle (enabled per player)

- Key `display_config.video_renderer`: `'auto' | 'chromium' | 'mpv'`. **Default `auto` = chromium**
  (current behavior unchanged). `mpv` = routes video to mpv.
- **Capability guard**: the UI only offers the `mpv` option if the player has reported
  `capabilities.mpv_vaapi = true` (detected at install: mpv binary present + `vainfo` lists an
  H.264/HEVC decode profile). Otherwise the option is greyed out + tooltip "mpv/VAAPI unavailable".
- **Platform gating**: offered **only** on `player_os = linux-x64` (Intel). RPi (V4L2) and
  Windows (D3D11) keep Chromium — no toggle.
- Consistent with `gpu_enabled` (commit `1d82f6f`): same display_config mechanism + front-end platform guard.

## 4. Renderer split — `VideoSurface` abstraction

To avoid duplicating all the playback/sync logic, we introduce an abstraction on the renderer side:

```
VideoSurface (interface)
 ├─ HtmlVideoSurface   → wrappe l'actuel <video> (comportement par défaut, zéro régression)
 └─ MpvSurface         → proxy IPC vers mpv (via window.signflow.mpv.* exposé par preload)

API : load(src, {seekMs, subtitles, muted}), play(), pause(), get currentTime(),
      get duration(), set playbackRate(r), seek(ms), get videoSize(),
      on('ready'|'ended'|'error', cb), release()
```

(`HtmlVideoSurface` wraps the current `<video>` — default behavior, zero regression; `MpvSurface` is an IPC proxy to mpv via `window.signflow.mpv.*` exposed by the preload.)

`reportPlaybackPos`, the LAN nudge, `onLanSwitch`, the overlay and `_getContentFP` talk to
`VideoSurface` instead of `_activeVideo` directly. **`_activeVideo` becomes
`_activeSurface`**; `HtmlVideoSurface` keeps exactly the current code (mechanical refactor, testable
without mpv). The implementation is chosen in `playCurrentItem` based on `video_renderer` + item type.

> Cross-cutting benefit: this abstraction would also make a future port (another engine) trivial,
> and clarifies the renderer (today `_activeVideo` is touched in ~15 places).

## 5. Easy points (mpv > Electron)

- **offline-first**: mpv reads the cache **disk path** directly (`fileFor().path`) → no
  `signflow://`, no Range issues. Fallback to the MinIO http URL if not cached. **Simpler** than Electron.
- **Subtitles**: native mpv WebVTT `sub-add`.
- **Dual audio**: video in mpv, **audio baskets stay in Electron (Web Audio)** → the two
  mix at the PipeWire/Pulse level. Output routing = mpv `--audio-device`.
- **Decoding**: `--hwdec=vaapi --vo=gpu --gpu-context=x11egl` (to be frozen in Phase 0).

## 6. Accepted v1 limits (to document in the matrix)

1. **Electron UI not composited over the mpv video** (separate windows): maintenance overlay,
   status bar, fallback screen. Mitigations: the overlay **lowers mpv** for the duration of the display;
   the **"Reconnecting" indicator is duplicated via the native mpv OSD** (`show-text`, visible on top of
   the video) — ✅ implemented. Remaining: a "no content" fallback screen in mpv mode would end up behind
   (rare, the mpv content covers it).
2. **Transitions / precache #2a**: 1 mpv instance → no video→video double-buffer; small gap on
   item change (loadfile). Future option: a 2nd preloaded mpv instance.
3. **Templates with embedded video** (video INSIDE an HTML template): stay in Chromium (mpv only handles
   fullscreen video). The toggle only applies to fullscreen video items.
4. **Intel/Linux x64 only.**

## 7. Phased plan

| Phase | Content | Where to validate |
|-------|---------|-----------|
| **0 — PoC (throwaway)** ✅ **PASSED 2026-06-09 (Intel test player, UHD600 Gemini Lake)** | Clear the 3 unknowns BEFORE any integration. **(a) decode** ✅ mpv plays H.264 1080p in VAAPI (`Using hardware decoding (vaapi)`, dmabuf EGL; HEVC+VP9 also available). **(c) IPC** ✅ 6/6 via `mpv-poc-ipc.mjs`: loadfile/hwdec-current=vaapi/dwidth+dheight+codec/time-pos/`speed` (LAN nudge)/`seek` (LAN resync). **(b) z-order** ✅ with an **explicit raise `wmctrl -a <titre>`** on the target window at each switch. **Scripts**: `player-linux/scripts/mpv-poc.sh <video>` + `mpv-poc-ipc.mjs` + `mpv-poc-zorder.sh` (slow labeled confirmation). Prerequisite: `sudo apt install -y mpv socat wmctrl`. Run in a graphical session with `DISPLAY=:0` (from SSH is fine, no XAUTHORITY needed for the user who owns the session). | **Intel test players** (throwaway scripts) |
| **1 — Detection + toggle** | `install.sh`: `apt install mpv` + `vainfo` decode detection → `capabilities.mpv_vaapi`. Backend reports the capability. Front: option `video_renderer=mpv` (capability + OS guard) + i18n. | local + Intel test player |
| **2 — mpv rendering (without LAN)** ✅ **DONE + HW VALIDATED (Intel test player, 2026-06-09)** | `mpv_controller.js` (mpv `--idle` process + JSON IPC + wmctrl raise/lower + orphan cleanup); main.js wiring (ipcMain + `signflow://`→disk resolution + lifecycle); preload bridge; renderer = mpv branch in `renderItem` (mode `video_renderer=mpv`), `mpvHide()` for non-video items. **Pragmatic approach**: no formal `VideoSurface` class — mpv vs `<video>` branch in `renderItem` (advance stays timer-driven → mpv = a simple display surface, zero regression on the Chromium path). **Validated**: video routed to mpv, `hwdec-current=vaapi`, GPU Video engine (VCS) ~28%, offline cache resolved, smooth fullscreen above the kiosk, mpv CPU ~5%. Commit `4fb68e1`. | **Intel test player** ✅ |
| **3 — LAN sync** ✅ **CODED (commit `f6f5196`)**, ⏳ validate on HW | Re-wired via renderer abstraction (`videoActive`/`videoOffsetMs`/`setVideoRate`/`seekVideoMs` → `<video>` or mpv): `time-pos` poll ~250ms extrapolated, `speed` nudge, `seek` resync. `onLanSwitch` #2b already agnostic. **To validate**: wall of two Intel players in mpv + LAN, drift via `[LAN] Rate nudge`. | two Intel test players (wall) |
| **4 — Finishing touches** ✅ **CODED (commit `f6f5196`)**, ⏳ validate on HW | Overlay lowers mpv then raises it again; played resolution + position = mpv dims/time-pos; **fallback to Chromium `<video>` if mpv fails** (`renderVideoChromium`). Fade transitions not applied to mpv (cut, accepted limit). | fleet |

> Project rule respected: **the default Chromium path stays intact** (zero regression as long
> as `video_renderer != mpv`). RPi/Windows untouched.

## 8. Risks & mitigations

| Risk | Mitigation |
|--------|--------|
| **Kiosk z-order** | ✅ **RESOLVED in Phase 0**: player-linux is NOT always-on-top (plain `fullscreen:true` under Openbox) → no fight. Chosen mechanism = **explicit raise `wmctrl -a <titre-fenêtre>`** on the target at each switch (mpv gets a unique `--title`). ⚠️ **DO NOT rely on the mpv `ontop` property** (`_NET_WM_STATE_ABOVE`): it does not restack an already-mapped window once the kiosk has come back to the front. Runtime dependency: `wmctrl` (to install via install.sh). |
| mpv missing / VAAPI failing on a player | capability guard (option not offered) + runtime fallback to `<video>` if spawning mpv fails |
| Coarser LAN drift via IPC (socket latency) | mpv `time-pos` is accurate; UNIX socket IPC <1ms; keep the same dead-zone/nudge |
| A 2nd rendering path to maintain | the `VideoSurface` abstraction isolates the cost; Chromium remains the reference |

## 9. Verdict

**✅ WORKSTREAM VALIDATED ON HW (two Intel test players, UHD600, 2026-06-09).** Phases 0→4 delivered and validated:
HW VAAPI decoding (VCS ~28%), LAN sync via mpv (drift ~50ms = NTP skew, same as Chromium),
**server reboot DOWN → offline boot-cache in mpv HW + LAN sync without server + audio OK**, mpv mode
reports `hw_decode_active=true` ("Hardware" badge + lifts the rendition cap → **4K on a 4K screen**),
Chromium fallback if mpv fails, overlay + "Reconnecting" via mpv OSD. Enabled per player
(`display_config.video_renderer=mpv`, guarded by `mpv_vaapi`+linux-x64). Commits `ec3232c`→`e44469d`.
**Optional remainder**: fade transitions on mpv (cut for now), "best practices" matrix doc,
real 4K validation (4K screen required; the test players have 1080 screens).

### (history) Phase 0
**GO on Option A — Phase 0 ✅ PASSED ON HW (Intel test player, UHD600, 2026-06-09).** The 3 unknowns are
cleared: real VAAPI decode, full IPC (including `speed` nudge + `seek` resync), reliable z-order via
`wmctrl -a`. The rest is wiring framed by the `VideoSurface` abstraction. **Next step =
Phase 1** (mpv/VAAPI detection at install → `capabilities.mpv_vaapi` + dependencies `mpv socat wmctrl`
in install.sh; front-end toggle `video_renderer` guarded by capability+OS).

**Confirmed runtime dependencies** (Debian 12): `mpv` (stock 0.35.1 OK), `socat` (IPC from bash),
`wmctrl` (z-order raise). To add to `install.sh`.

**Product decision to confirm**: do we accept the v1 limits (overlay/transitions, §6) in exchange for
HW decoding, or should we aim for option B (dma-buf, no limits but heavy GL interop)? Recommendation:
**A with documented limits** — the overlay is occasional and video→video transitions are rare in signage.
