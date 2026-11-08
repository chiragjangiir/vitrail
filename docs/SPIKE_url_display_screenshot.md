# SPIKE — URL Display `screenshot_server` mode + thumbnails (Sprint 2.8 #2)

🇫🇷 [Version française](SPIKE_url_display_screenshot.fr.md)

> Decision: a **dedicated** Celery worker `celery-screenshot` (Playwright/Chromium), isolated from the
> media/event workers. Solves non-framable sites (YouTube…) + provides the home thumbnail.

## Principle
- `url_config.render_mode = 'screenshot_server'` → the server loads the page with Playwright,
  takes a **capture**, uploads it to MinIO; the player displays an **image** (not the iframe).
- **Thumbnail**: we also capture a miniature of the page → `cms_media.thumbnail_url` → the media
  library grid displays it automatically (replaces the Globe placeholder), for BOTH modes.

## Infra
- New service `celery-screenshot` (base `python:3.12-slim` + `playwright install --with-deps
  chromium`, ~1 GB), mounts `./backend:/app`, consumes the **`cms_screenshot`** queue, concurrency 2.
- `Dockerfile.screenshot`. Added to `docker-compose.yml` (no port) + to the production install.

## Backend
- `app/workers/screenshot_worker.py`:
  - `capture_url_display(id_media)` — **LAZY Playwright import (inside the function)** so that the
    other workers (media/event/backend/beat) can import the module without Chromium. Loads the
    page (viewport, zoom, custom_css, hide_selectors, timeout), full-page screenshot + thumbnail,
    MinIO upload (`url_display/{id}/latest.png` + `.../thumb.png`), updates `cms_media`
    (`thumbnail_url`, `media_metadata.screenshot_key`/`last_capture_at`/`capture_status`/`last_error`),
    then a graceful `_push_sync` to the players (if screenshot_server).
  - `capture_due_url_displays()` — lightweight (no Playwright): finds `screenshot_server` url_displays
    whose `last_capture_at` > `refresh_interval_s` (or never captured) and
    enqueues `capture_url_display`. Routed to the **default** queue (runs on celery-worker), Beat 60s.
- `celery_app`: `include` += screenshot_worker; `task_routes` `capture_url_display`→`cms_screenshot`;
  `beat_schedule` `capture-due-url-displays-60s`.
- `endpoints/url_display.py`: on creation AND on edit, enqueues `capture_url_display` (thumbnail
  for all modes + image for screenshot_server). `render_mode` accepted in the config.
- `ws._url_display_media_dict`: if `render_mode=='screenshot_server'` AND capture ready → emits
  `image_url` (signed MinIO URL) + `cache_key`/`cache_checksum` (offline-first like an image) +
  `render_mode`. Otherwise (webview, or capture not ready yet) → current iframe behavior.

## Player (5 renderers)
- `url_display` branch: if `url_config.render_mode === 'screenshot_server'` AND `media.image_url` →
  renders an **`<img>`** (cached offline-first via the content store, like a normal image → robust
  offline). Otherwise → webview **iframe** (current). The screenshot mode therefore ALSO works on
  Android WebView / ChromeOS PWA (no framing constraint on an image).

## Frontend
- `UrlDisplayDrawer`: **Webview / Server capture** selector (`render_mode`) + (the thumbnail
  already shows via `thumbnail_url` in the grid). Hint on the capture mode (non-framable sites).

## Migration
None: `render_mode`/capture meta in `media_metadata`; `thumbnail_url` = existing column.

## Deployment (more involved)
Build the new image (`docker compose build celery-screenshot`) + `up -d celery-screenshot`
on production; pull backend + restart; deploy the 5 renderers; no migration.
