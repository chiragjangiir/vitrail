# SPIKE — URL Display (Sprint 2.8, §XXV.2)

🇫🇷 [Version française](SPIKE_url_display.fr.md)

> Architecture decision + implementation plan. Drawn up 2026-06.
> Validated scope: **webview first** (no Playwright pod), integration as **schedulable fullscreen AND
> template zone**, **offline-first + reachability probe + fallback/alert** included.

## Architecture decision: `url_display` = a MEDIA (reuses `cms_media`)

Rather than the spec's dedicated `cms_url_display_configs` table + a nullable `id_url_display`
on items (which would force wiring "media OR url" into playlists/events/draft/sync/
UI pickers), we model a website as **a native media**:

- `cms_media` row: `media_type = 'url_display'`, `storage_key = NULL` (no file),
  the URL + webview config live in `metadata` JSONB.
- **Maximum reuse**: it shows up in the media library, the playlist/event pickers,
  scheduling, targeting, sync — **without touching** those machineries (an item always
  references `id_media`). This is exactly the "like a media" that was asked for, and spec §25.1
  already presents it as "a native content type complementary to the existing types".
- RBAC: reuses the **`media`** module (create/read/edit/delete) → no new module.
- **No migration** for Phase 1 (`media_type` = free `String(30)`; no new permission).

Cost = **defensive guards** "if `media_type == 'url_display'`: no file" on the
paths that assume a MinIO object (transcode, conformance, renditions, replace, delete-files,
served size, prefetch/offline-first, visual LAN barrier). All trivial and localized.

`metadata` of a url_display:
```json
{
  "url": "https://example.com/dashboard",
  "render_mode": "webview",
  "refresh_interval_s": 0,
  "zoom": 1.0,
  "scroll_mode": "none",
  "scroll_speed_px_s": 50,
  "interaction_blocked": true,
  "custom_css": "",
  "hide_selectors": [],
  "reachability": { "enabled": true, "timeout_s": 8 }
}
```

> `screenshot_server` (next iteration): we will add the capture fields
> (`screenshot_s3`, `last_capture_at`, `last_error`, `status`) to `metadata` (or a side table
> `cms_url_display_captures` if it grows) + the Playwright service + `cms_screenshot` queue.

## Offline-first + reachability probe (requirement)

- **Offline-first**: the config travels in the **persisted** sync state on the player side → server
  down, the player **keeps displaying the site** (if it has access). Nothing to cache (no file).
- **Reachability probe** (player, webview): before display + at each refresh, an access test on the URL
  (`fetch` HEAD/no-cors bounded by `timeout_s`). **Unreachable → the item is skipped** (`onError` →
  next item of the playlist) **+ alert** `url_display_unreachable` to the server.
- **Alert** (v1, §XXII Notifications not yet built): incoming WS message
  `{type:'player:event', event:'url_display_unreachable', id_media, url}` → `cms_audit_log`
  (queued on the player side if the server is down, flushed on reconnection). Evolution = real notifications 2.11.

## Implementation plan

### Phase 1 — schedulable fullscreen (webview)
1. **Backend** `endpoints/url_display.py`: `GET/POST/PUT/DELETE /url-display` (perms `media:*`),
   creates/edits a `cms_media` of type `url_display` (https URL validation, metadata). Router registered.
2. **Guards**: transcode/conformance/renditions/replace/delete-files/served_size/prefetch/LAN-barrier
   skip `url_display` (no file).
3. **Sync** `ws.py`: in the item builders, a `url_display` branch → emits
   `{media_type:'url_display', url: metadata.url, url_config: metadata}` without `get_signed_url`/cache_key.
4. **Incoming alert** `ws.py`: handler `player:event url_display_unreachable` → audit log.
5. **Renderers (5)**: sandboxed iframe rendering (extends the `html_package` path) + refresh + scroll +
   `interaction_blocked` + **reachability probe → skip + WS alert**.
6. **Frontend**: `/url-display` page (list + drawer: name, url, mode, refresh, scroll, zoom,
   sandbox, probe timeout); the url_display media appears in the existing pickers. Nav + i18n.
7. **Tests**: url_display creation; sync emits the item with the live URL (no signed URL); transcode
   guard; alert handler writes the audit.

### Phase 2 — zone in the template editor (WYSIWYG)
Allow a template **zone** to host a `url_display` media. Touches the template
editor (§2.3) + the player's multi-zone rendering. Done **after** Phase 1 is validated.
