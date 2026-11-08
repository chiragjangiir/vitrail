# SPIKE — Offline-first players / Local Content Store (download-then-play)

🇫🇷 [Version française](SPIKE_offline_first_local_content_store.fr.md)

> Design spike (2026-06-07). Frames the epic from `EVOLUTIONS.md § « Players offline-first / Local Content Store »` in the **actual code** and settles the architecture decisions **before coding**. Same approach as `SPIKE_scheduling_targeting_core.md`.
>
> **Verdict: GO**, in phases, starting with the **store + single-player download manager (Linux/RPi)** with a **graceful streaming fallback** (zero regression). Q5 (quarantine/purge) already delivered (migration 0031).

---

## 1. Goal

Move the **Electron** players (linux / rpi / windows) from the **streaming** model (each media read from MinIO via a signed URL, bytes in the Chromium HTTP cache) to the **download-then-play** model (bytes downloaded into a **local on-disk store**, playback from disk).

**Why:**
- **Offline resilience** (the player survives a network outage beyond the volatile HTTP cache).
- **Robust LAN sync**: a video wall must not depend on a network fetch at every item boundary.
- **Fixes the contention seeks on the Windows player** (synchronized wall → 4 players re-fetch at the same instant at every boundary; see field note on the 4-screen wall). With a local store, no more fetches at boundaries.
- **Foundation for Q4** = proof of distribution (useful for Retail Media).

## 2. Current state (checked in the code, 2026-06-07)

| Building block | Reality in code |
|---|---|
| Server payload | `ws._resolve_sync_payload` → items with **`url`** (`get_signed_url(storage_key, 86400)` = 24 h), **`checksum_sha256`**, `duration`, subtitles (signed `url`), audio baskets (`url`). Rendition variant resolved by `_resolve_variant_key` (storage_key of the rendition). |
| Integrity | **`checksum_sha256` already in the payload** per item → download verification **for free**. `file_size_bytes` exists on `cms_media` + renditions (`file_meta`) → can be exposed for QoS/disk. |
| Offline manifest | `player.js::saveSync(payload)` persists the **manifest** (localStorage); `loadSync()` at boot → the player replays the **program** offline, but **not the bytes** (signed MinIO `url`s are dead offline / after 24 h). |
| Media playback | `player.js`: `video.src = media.url` (direct MinIO stream). Double-buffer **precache** (`precacheNext`/`clearPreload`, hidden container) = warms up the HTTP cache for the next item. |
| Position / resync | `main.js::lastSyncState` `{id_playlist,currentIndex,currentOffsetMs,syncedAt}` → graceful wall-clock resume. |
| Q5 purge | `main.js` handler `player:purge_media` → `session.clearCache()` (**HTTP cache**, best-effort). `_blockedMedia` (payload + offline) → `playCurrentItem` skips blocked ids even offline. |
| Storage | `app.getPath('userData')` (config.json, display_config.json, capabilities.json, logs/). **No content store.** |
| Capabilities / heartbeat | `capabilities` (decode + display_modes) merged into `player:status` → the backend **replaces** the dict (pattern to reuse for the Q4 inventory: a single object). |

**Conclusion**: manifest + checksums + file_size + precache + position already exist. What is missing = **bytes on disk** and **a download manager**. The change is **mostly on the player side**; the server changes **little** (expose `file_size`, and later a pinned set + alerts).

## 3. Target architecture

```
┌─ main.js (Node) ──────────────────────────────────────────────┐
│  ContentStore (<userData>/content_store/)                      │
│   - fichiers nommés par checksum : <sha256>.<ext>              │
│   - index.json : {id_media|variant_key -> {checksum,size,      │
│                    last_used, pinned, status}}                  │
│   - écriture atomique : .part -> fsync -> rename               │
│   - vérif checksum après download (sinon rejet + re-DL)        │
│  DownloadManager                                               │
│   - file d'attente (épinglé d'abord, look-ahead ensuite)       │
│   - HTTP range résumable, N concurrents, token-bucket (Q3)     │
│   - fenêtres autorisées = TimeRule du noyau scheduling (Q3)    │
│  protocol signflow:// (registerFileProtocol/protocol.handle)   │
│   - sert les octets locaux au renderer AVEC support Range      │
│     (seek vidéo pour la sync) ; 404 si pas encore en cache     │
└───────────────────────────────────────────────────────────────┘
        │ IPC (preload)                       ▲
        ▼                                     │ 'cache:status' (inventaire Q4)
┌─ player.js (renderer) ────────────────────────────────────────┐
│  resolveSrc(media) :                                           │
│    local prêt  -> signflow://media/<checksum>                  │
│    sinon        -> media.url (REPLI STREAMING gracieux)        │
│  (précache inchangé, mais pointe sur le local quand prêt)      │
│  LAN : barrière de readiness par empreinte + garde d'index (Q1)│
└───────────────────────────────────────────────────────────────┘
```

(Diagram, in English: **ContentStore** — files named by checksum `<sha256>.<ext>`; `index.json` mapping `id_media|variant_key` to `{checksum,size,last_used,pinned,status}`; atomic write `.part` → fsync → rename; checksum verified after download (otherwise rejected + re-downloaded). **DownloadManager** — queue (pinned first, look-ahead next); resumable HTTP range, N concurrent, token-bucket (Q3); allowed windows = `TimeRule` from the scheduling core (Q3). **`signflow://` protocol** — serves local bytes to the renderer WITH Range support (video seek for sync); 404 if not cached yet. **Renderer `resolveSrc(media)`** — local ready → `signflow://media/<checksum>`, otherwise `media.url` (graceful STREAMING FALLBACK); precache unchanged but points to the local copy when ready; LAN: readiness barrier per fingerprint + index guard (Q1).)

**Non-regression principle**: as long as a byte is not in the verified local cache, the renderer **streams** (`media.url`). The store fills up in the background; at the next sync, ready items switch to `signflow://`. **The current streaming player never breaks.**

## 4. Design decisions to settle (with recommendation)

1. **Mechanism for serving local bytes to the renderer** →
   **Rec: `protocol.handle('signflow', …)` (Electron ≥ 25) returning an `fs.ReadStream`** (or `registerFileProtocol` as a fallback). Handles **Range** natively (essential for the video seek used by sync), no network port (vs a localhost server), no `file://`+CORS hassle. *Rejected alternative: localhost HTTP server (one more port, security); `file://` (Range/seek unreliable under Chromium).*
2. **Store naming** →
   **Rec: content-addressed (`<checksum_sha256>.<ext>`)** + `index.json` (mapping id_media/variant_key → checksum). Automatic dedup (same bytes shared across playlists), immutable, trivial integrity, a re-encoded rendition = new checksum = new file (the old one is evicted). *Rejected alternative: naming by id_media (silent re-download if content changes under the same id).*
3. **Pinned set (never evicted)** →
   **Rec P0: the whole current manifest is pinned** (simple). **P1+: the server computes a `pinned:[…]`** (current program + schedules/events look-ahead) sent in the payload → the cache manager protects this set and evicts the rest LRU. *The scheduling core already provides the "who+when" for look-ahead.*
4. **P0 server changes** →
   **Rec: minimal** — add **`file_size_bytes`** per item to the payload (disk planning + Q3 token-bucket). The rest of the payload is already sufficient (url + checksum). No migration. (`pinned`, disk alerts and inventory come in P1/P4.)
5. **Target hardware & order** →
   **Rec: Linux/RPi first** (trivial Node file store, NUC/RPi test fleet + Intel test players for sync), **then Windows** (same Node code, validates the anti-seek gain), **then Android** (MediaCodec + scoped storage, store via OkHttp + `FileProvider`/WebView protocol — separate workstream), **ChromeOS = Cache API/Service Worker** (different model, to be built with the PWA).

## 5. Phasing plan

- **P0 — Store + single-player download (Linux/RPi)** *(core, standalone deliverable)*
  `ContentStore` + `DownloadManager` (sequential, no QoS) + `signflow://` protocol + `resolveSrc` with **streaming fallback** + **Q5 purge = actual file deletion** + minimal `cache:status` IPC. **Criterion**: cut the network after filling → the player keeps going; NUC+RPi wall with no re-fetch at boundaries.
- **P1 — Cache manager / eviction (Q2)**: 85/70% watermarks, LRU on non-pinned, server `pinned`, **server alert "insufficient disk for the assigned playlist"** (no silent drop). Reuses the decode-health alert channel.
- **P2 — LAN sync-readiness barrier (Q1)**: `ready_for <fingerprint>` signaling on the LAN channel (UDP `sync_lan.js`/`LanSyncController`), the master only fires `switch_at`/wall-clock when all expected members are ready; **index guard** (only advances to N+1 if everyone has it); **timeout/degraded mode** (a powered-off slave doesn't freeze the wall → "desynchronized" alert). Validation on the test fleets.
- **P3 — QoS / download windows (Q3)**: windows = `TimeRule` from the scheduling core, bandwidth cap (token-bucket), N concurrent, look-ahead of upcoming programs, resumable downloads (HTTP range), emergency bypass. Preserves the customer's line during opening hours.
- **P4 — Inventory UI (Q4)**: the player reports `{cache:[{id,checksum,size,last_used,status}], disk_free}` in the heartbeat (same capabilities object) → per-player UI (disk, ready/partial/missing) + reverse view per playlist/campaign (proof of distribution).
- **Porting**: Windows (P0 replayed), then Android (native store), then ChromeOS (Service Worker).

## 6. Hard points / risks

- **Video seek via `signflow://`**: validate that Range works for the LAN sync `currentTime` (otherwise nudge/seek breaks). → test early in P0.
- **Atomicity**: never serve a `.part`. Write `.part` → checksum → `rename`. A crash mid-way = re-download.
- **SD card wear (RPi)**: a store on SD wears the flash. → prefer a USB SSD (already the case for the LUKS-encrypted RPi SSD) or limit rewrites (content-addressing helps: no re-download if the checksum is identical).
- **Windows player with 4 GB RAM / limited storage**: watermarks + alert essential (P1).
- **LAN fingerprint (Q1)**: **authoritative** member list (should-be-there vs online) — reuse server group membership, not UDP auto-discovery alone.
- **Fleet transition**: P0 must coexist with players still streaming (progressive rollout) → the server imposes nothing, the player switches to local **when** it has the bytes.

## 7. Verdict

**GO.** The epic is well framed, the payload already carries checksum + (soon) file_size, the capabilities/scheduling/quarantine pattern is reusable. The risk is **contained by the streaming fallback** (P0 cannot regress). Start with **P0 on Linux/RPi**, validate the NUC+RPi wall (anti-seek), then roll out P1→P4 and the porting.
