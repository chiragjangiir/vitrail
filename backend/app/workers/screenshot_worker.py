"""Worker Celery dédié aux captures URL Display (§XXV.2, mode screenshot_server).

Tourne dans le conteneur **celery-screenshot** (Playwright/Chromium, file `cms_screenshot`).
Deux tâches :
  - `capture_url_display(id_media)` : rend la page avec Playwright → capture pleine page + vignette
    → MinIO → met à jour cms_media (thumbnail_url + meta capture) → force_sync si screenshot_server.
    **Import Playwright LAZY** (dans la fonction) → les autres workers (media/event/backend/beat)
    importent ce module sans Chromium, ils ne consomment juste pas la file `cms_screenshot`.
  - `capture_due_url_displays()` : léger (sans Playwright), enqueue les captures à rafraîchir.

Pas de migration : l'URL + la config + la meta de capture vivent dans `cms_media.metadata` ;
la vignette dans la colonne `thumbnail_url`. cf. docs/SPIKE_url_display_screenshot.md.
"""

import io
import json
import logging
from datetime import datetime, timezone

import boto3
import psycopg2
from botocore.config import Config
from PIL import Image

from app.core.config import settings
from app.core.ssrf import host_is_safe
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_THUMB_WIDTH = 480           # largeur de la vignette médiathèque
_DEFAULT_VW, _DEFAULT_VH = 1920, 1080


def _s3():
    return boto3.client(
        "s3",
        endpoint_url=f"{'https' if settings.MINIO_USE_SSL else 'http'}://{settings.MINIO_ENDPOINT}",
        aws_access_key_id=settings.MINIO_ACCESS_KEY,
        aws_secret_access_key=settings.MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def _db_conn():
    url = settings.db_worker_url.replace("postgresql+asyncpg://", "postgresql://")
    return psycopg2.connect(url)


def _push_force_sync_org(id_org: int) -> None:
    """Resync graceful des players de l'org (nouvelle capture servie en mode screenshot_server)."""
    try:
        import redis as _redis
        conn = _db_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT id_player FROM cms_players WHERE id_org = %s", (id_org,))
            ids = [r[0] for r in cur.fetchall()]
        finally:
            conn.close()
        if not ids:
            return
        r = _redis.from_url(settings.REDIS_URL)
        msg = json.dumps({"type": "player:force_sync", "preemptive": False})
        for pid in ids:
            r.publish(f"signflow:player:{pid}:cmds", msg)
    except Exception as exc:  # noqa: BLE001
        logger.warning("force_sync screenshot échec org %s: %s", id_org, exc)


@celery_app.task(name="app.workers.screenshot_worker.capture_url_display", bind=True, max_retries=2)
def capture_url_display(self, id_media: int) -> None:
    """Capture la page d'un url_display → image pleine page + vignette → MinIO + cms_media."""
    conn = _db_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id_org, metadata FROM cms_media "
            "WHERE id_media = %s AND media_type = 'url_display' AND is_deleted = false",
            (id_media,),
        )
        row = cur.fetchone()
        if not row:
            return
        id_org, meta = row[0], (row[1] or {})
        url = meta.get("url")
        if not url:
            return
        # Anti-SSRF (audit 2026-06-24) : Chromium rendrait n'importe quelle URL fournie par
        # l'utilisateur (services internes en HTTPS, DNS rebinding) et exfiltrerait le rendu via
        # la capture. On refuse les hôtes résolvant vers une IP non publique.
        from urllib.parse import urlparse as _urlparse
        _h = _urlparse(url).hostname or ""
        if not host_is_safe(_h):
            logger.warning("capture %s : hôte non autorisé (%s), capture ignorée", id_media, _h)
            return
        vw = int(meta.get("viewport_width") or _DEFAULT_VW)
        vh = int(meta.get("viewport_height") or _DEFAULT_VH)
        zoom = float(meta.get("zoom") or 1.0)
        custom_css = meta.get("custom_css") or ""
        hide_selectors = meta.get("hide_selectors") or []
        timeout_ms = max(1000, int(meta.get("reachability_timeout_s") or 15) * 1000)
        render_mode = meta.get("render_mode") or "webview"
    finally:
        conn.close()

    # Import Playwright LAZY (seul ce worker a Chromium).
    from playwright.sync_api import sync_playwright

    png: bytes
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            ctx = browser.new_context(viewport={"width": vw, "height": vh}, device_scale_factor=1)
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            except Exception:
                # networkidle peut ne jamais arriver (pubs, sockets) → on tente quand même la capture
                logger.info("capture %s: networkidle non atteint, capture best-effort", id_media)
            if zoom and zoom != 1.0:
                try:
                    page.evaluate(f"document.documentElement.style.zoom = '{zoom}'")
                except Exception:
                    pass
            if custom_css:
                try:
                    page.add_style_tag(content=custom_css)
                except Exception:
                    pass
            for sel in hide_selectors:
                try:
                    page.eval_on_selector_all(sel, "els => els.forEach(e => e.style.display='none')")
                except Exception:
                    pass
            png = page.screenshot(type="png")
            browser.close()
    except Exception as exc:  # noqa: BLE001
        logger.error("capture %s échec: %s", id_media, exc)
        _mark_capture_error(id_media, str(exc)[:500])
        raise self.retry(exc=exc, countdown=30)

    s3 = _s3()
    shot_key = f"url_display/{id_media}/latest.png"
    thumb_key = f"url_display/{id_media}/thumb.png"
    s3.put_object(Bucket=settings.MINIO_BUCKET_MEDIA, Key=shot_key, Body=png, ContentType="image/png")

    # Vignette (largeur fixe, ratio conservé) pour la grille médiathèque.
    try:
        img = Image.open(io.BytesIO(png)).convert("RGB")
        ratio = _THUMB_WIDTH / img.width
        thumb = img.resize((_THUMB_WIDTH, max(1, int(img.height * ratio))))
        buf = io.BytesIO()
        thumb.save(buf, format="PNG")
        s3.put_object(Bucket=settings.MINIO_BUCKET_MEDIA, Key=thumb_key, Body=buf.getvalue(), ContentType="image/png")
    except Exception as exc:  # noqa: BLE001
        logger.warning("vignette %s échec: %s", id_media, exc)
        thumb_key = shot_key  # repli : la grille utilisera la capture pleine

    now_iso = datetime.now(timezone.utc).isoformat()
    conn = _db_conn()
    try:
        cur = conn.cursor()
        # Fusionne la meta de capture dans le JSONB existant + pose thumbnail_url.
        cur.execute(
            "UPDATE cms_media SET thumbnail_url = %s, "
            "metadata = metadata || %s::jsonb, updated_at = now() "
            "WHERE id_media = %s",
            (thumb_key, json.dumps({
                "screenshot_key": shot_key,
                "last_capture_at": now_iso,
                "capture_status": "ready",
                "last_error": None,
            }), id_media),
        )
        conn.commit()
    finally:
        conn.close()

    if render_mode == "screenshot_server":
        _push_force_sync_org(id_org)


def _mark_capture_error(id_media: int, err: str) -> None:
    conn = _db_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE cms_media SET metadata = metadata || %s::jsonb WHERE id_media = %s",
            (json.dumps({"capture_status": "error", "last_error": err}), id_media),
        )
        conn.commit()
    except Exception:  # noqa: BLE001
        pass
    finally:
        conn.close()


@celery_app.task(name="app.workers.screenshot_worker.capture_due_url_displays")
def capture_due_url_displays() -> None:
    """Enqueue le rafraîchissement des url_display screenshot_server arrivés à échéance.

    Léger (pas de Playwright) → tourne sur la file `default` (celery-worker). Le calcul de
    fraîcheur se fait en Python (la date de capture est une chaîne ISO dans le JSONB)."""
    conn = _db_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id_media, metadata FROM cms_media "
            "WHERE media_type = 'url_display' AND is_deleted = false "
            "AND metadata->>'render_mode' = 'screenshot_server'"
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    now = datetime.now(timezone.utc)
    for id_media, meta in rows:
        meta = meta or {}
        refresh = int(meta.get("refresh_interval_s") or 0)
        if refresh <= 0:
            continue  # capture unique (à la création/édition), pas de refresh périodique
        last = meta.get("last_capture_at")
        due = True
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                due = (now - last_dt).total_seconds() >= refresh
            except Exception:  # noqa: BLE001
                due = True
        if due:
            capture_url_display.delay(id_media)
