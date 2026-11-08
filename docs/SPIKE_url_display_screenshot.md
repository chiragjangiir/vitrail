# SPIKE — URL Display mode `screenshot_server` + vignettes (Sprint 2.8 #2)

> Décision Ed : worker Celery **dédié** `celery-screenshot` (Playwright/Chromium), isolé des
> workers media/event. Règle les sites non-framables (YouTube…) + fournit la vignette d'accueil.

## Principe
- `url_config.render_mode = 'screenshot_server'` → le serveur charge la page avec Playwright,
  en fait une **capture**, l'upload sur MinIO ; le player affiche une **image** (pas l'iframe).
- **Vignette** : on capture aussi une miniature de la page → `cms_media.thumbnail_url` → la grille
  médiathèque l'affiche automatiquement (remplace le placeholder Globe), pour les DEUX modes.

## Infra
- Nouveau service `celery-screenshot` (base `python:3.12-slim` + `playwright install --with-deps
  chromium`, ~1 Go), monte `./backend:/app`, consomme la file **`cms_screenshot`**, concurrency 2.
- `Dockerfile.screenshot`. Ajouté à `docker-compose.yml` (pas de port) + à l'install prod.

## Backend
- `app/workers/screenshot_worker.py` :
  - `capture_url_display(id_media)` — **import Playwright LAZY (dans la fonction)** pour que les
    autres workers (media/event/backend/beat) puissent importer le module sans Chromium. Charge la
    page (viewport, zoom, custom_css, hide_selectors, timeout), screenshot pleine page + thumbnail,
    upload MinIO (`url_display/{id}/latest.png` + `.../thumb.png`), met à jour `cms_media`
    (`thumbnail_url`, `media_metadata.screenshot_key`/`last_capture_at`/`capture_status`/`last_error`),
    puis `_push_sync` graceful aux players (si screenshot_server).
  - `capture_due_url_displays()` — léger (pas de Playwright) : trouve les url_display
    `screenshot_server` dont `last_capture_at` > `refresh_interval_s` (ou jamais capturés) et
    enqueue `capture_url_display`. Routé queue **default** (tourne sur celery-worker), Beat 60s.
- `celery_app` : `include` += screenshot_worker ; `task_routes` `capture_url_display`→`cms_screenshot` ;
  `beat_schedule` `capture-due-url-displays-60s`.
- `endpoints/url_display.py` : à la création ET à l'édition, enqueue `capture_url_display` (vignette
  pour tous les modes + image pour screenshot_server). `render_mode` accepté dans la config.
- `ws._url_display_media_dict` : si `render_mode=='screenshot_server'` ET capture prête → émet
  `image_url` (URL signée MinIO) + `cache_key`/`cache_checksum` (offline-first comme une image) +
  `render_mode`. Sinon (webview, ou capture pas encore prête) → comportement iframe actuel.

## Player (5 renderers)
- Branche `url_display` : si `url_config.render_mode === 'screenshot_server'` ET `media.image_url` →
  rend un **`<img>`** (caché offline-first via le content store, comme une image normale → robuste
  hors-ligne). Sinon → **iframe** webview (actuel). Le mode screenshot marche donc AUSSI sur
  Android WebView / ChromeOS PWA (pas de contrainte de framing sur une image).

## Frontend
- `UrlDisplayDrawer` : sélecteur **Webview / Capture serveur** (`render_mode`) + (la vignette
  s'affiche déjà via `thumbnail_url` dans la grille). Hint sur le mode capture (sites non-framables).

## Migration
Aucune : `render_mode`/capture meta dans `media_metadata` ; `thumbnail_url` = colonne existante.

## Déploiement (plus impliqué)
Build de la nouvelle image (`docker compose build celery-screenshot`) + `up -d celery-screenshot`
sur le prod ; pull backend + restart ; déployer les 5 renderers ; pas de migration.
