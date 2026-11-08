"""Images de référence pour image→image / image→vidéo (§ génération).

Les modèles fal i2i/i2v acceptent une (ou des) image(s) d'entrée. On résout des `cms_media`
(de l'org, type image) en **data URIs** (`data:image/jpeg;base64,…`) — pas besoin que MinIO
soit public : on télécharge les octets côté serveur, on borne la taille (Pillow), on encode.

Deux entrées : `data_uris_for_media` (async, endpoint) et `data_uris_for_media_sync`
(psycopg2 + boto3, worker Celery).
"""

from __future__ import annotations

import base64
import io
import logging

import boto3
from botocore.config import Config
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.media import CmsMedia
from app.services.media import download_file

logger = logging.getLogger(__name__)

MAX_DIM = 1536          # borne la référence (payload data URI raisonnable)
MAX_REFS = 4            # garde-fou global


def resize_to_data_uri(content: bytes, max_dim: int = MAX_DIM) -> str:
    """Downscale (si besoin) + ré-encode JPEG → data URI base64. Best-effort."""
    try:
        img = Image.open(io.BytesIO(content))
        img = img.convert("RGB")
        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        data = buf.getvalue()
    except Exception as exc:  # noqa: BLE001 — image illisible → on tente l'octet brut
        logger.warning("resize_to_data_uri: %s, fallback brut", exc.__class__.__name__)
        data = content
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


async def data_uris_for_media(db: AsyncSession, id_org: int, media_ids: list[int]) -> list[str]:
    """(endpoint) Résout des médias image de l'org en data URIs, dans l'ordre fourni."""
    if not media_ids:
        return []
    ids = media_ids[:MAX_REFS]
    rows = (
        await db.execute(
            select(CmsMedia.id_media, CmsMedia.storage_key).where(
                CmsMedia.id_media.in_(ids),
                CmsMedia.id_org == id_org,
                CmsMedia.media_type == "image",
            )
        )
    ).all()
    by_id = {r.id_media: r.storage_key for r in rows}
    out: list[str] = []
    for mid in ids:
        key = by_id.get(mid)
        if key:
            out.append(resize_to_data_uri(await download_file(key)))
    return out


def _s3():
    return boto3.client(
        "s3",
        endpoint_url=f"{'https' if settings.MINIO_USE_SSL else 'http'}://{settings.MINIO_ENDPOINT}",
        aws_access_key_id=settings.MINIO_ACCESS_KEY,
        aws_secret_access_key=settings.MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def data_uris_for_media_sync(conn, id_org: int, media_ids: list[int]) -> list[str]:
    """(worker) Idem en SYNCHRONE (psycopg2 + boto3)."""
    if not media_ids:
        return []
    ids = list(media_ids)[:MAX_REFS]
    cur = conn.cursor()
    cur.execute(
        "SELECT id_media, storage_key FROM cms_media "
        "WHERE id_media = ANY(%s) AND id_org=%s AND media_type='image'",
        (ids, id_org),
    )
    by_id = {r[0]: r[1] for r in cur.fetchall()}
    s3 = _s3()
    out: list[str] = []
    for mid in ids:
        key = by_id.get(mid)
        if key:
            obj = s3.get_object(Bucket=settings.MINIO_BUCKET_MEDIA, Key=key)
            out.append(resize_to_data_uri(obj["Body"].read()))
    return out
