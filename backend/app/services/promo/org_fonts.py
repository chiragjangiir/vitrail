"""Polices personnalisées par organisation (§12.7) — catalogue + chargement des octets.

Une police custom = des lignes `cms_org_fonts` (1 par (family, weight)), fichier dans MinIO. On
construit un **catalogue** groupé par famille (id = `org-<slug>`) compatible avec `fonts.py`
(built-in + custom fusionnés). Le worker fournit un `custom_loader` qui télécharge les octets MinIO
et les embarque en data-URI — rendu déterministe identique aux polices built-in.

`ALLOWED_FORMATS` : formats web acceptés à l'upload (validés par magic-bytes côté endpoint).
"""

from __future__ import annotations

import base64
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org_font import CmsOrgFont
from app.services.promo.fonts import CUSTOM_PREFIX

ALLOWED_FORMATS = {"woff2", "woff", "ttf", "otf"}
MAX_FONT_BYTES = 4 * 1024 * 1024  # 4 Mo/fichier
# Magic bytes → format (détection fiable, ne se fie pas à l'extension fournie).
_MAGIC = [
    (b"wOF2", "woff2"),
    (b"wOFF", "woff"),
    (b"\x00\x01\x00\x00", "ttf"),
    (b"true", "ttf"),
    (b"OTTO", "otf"),
]


def slug(family: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (family or "").lower()).strip("-") or "font"


def detect_format(data: bytes) -> str | None:
    """Format réel d'après les magic-bytes (None si non reconnu → refus)."""
    head = data[:4]
    for sig, fmt in _MAGIC:
        if head == sig:
            return fmt
    return None


def _catalog_from_rows(rows: list[dict]) -> dict:
    """Regroupe les lignes (family, weight, key, format, id_font) par famille → catalogue."""
    cat: dict[str, dict] = {}
    for r in rows:
        fid = CUSTOM_PREFIX + slug(r["family"])
        entry = cat.setdefault(fid, {"family": r["family"], "weights": [], "source": "custom",
                                     "keys": {}, "formats": {}, "file_ids": {}})
        w = int(r["weight"])
        entry["weights"].append(w)
        entry["keys"][w] = r["storage_key"]
        entry["formats"][w] = r["font_format"]
        entry["file_ids"][w] = r["id_font"]
    for entry in cat.values():
        entry["weights"] = sorted(set(entry["weights"]))
    return cat


async def org_font_catalog(db: AsyncSession, id_org: int) -> dict:
    """Catalogue des polices custom de l'org (async, endpoint)."""
    rows = (await db.execute(
        select(CmsOrgFont.id_font, CmsOrgFont.family, CmsOrgFont.weight,
               CmsOrgFont.storage_key, CmsOrgFont.font_format)
        .where(CmsOrgFont.id_org == id_org)
    )).all()
    return _catalog_from_rows([
        {"id_font": r.id_font, "family": r.family, "weight": r.weight,
         "storage_key": r.storage_key, "font_format": r.font_format} for r in rows
    ])


def org_font_catalog_sync(conn, id_org: int) -> dict:
    """Catalogue des polices custom de l'org (sync psycopg2, worker de rendu)."""
    cur = conn.cursor()
    cur.execute(
        "SELECT id_font, family, weight, storage_key, font_format "
        "FROM cms_org_fonts WHERE id_org=%s", (id_org,),
    )
    rows = [{"id_font": a, "family": b, "weight": c, "storage_key": d, "font_format": e}
            for a, b, c, d, e in cur.fetchall()]
    return _catalog_from_rows(rows)


def make_custom_loader(s3, bucket: str):
    """Renvoie un `custom_loader(font_id, weight, entry) -> (b64, fmt) | None` pour `font_face_css`
    (télécharge les octets MinIO de la police custom)."""
    def loader(_font_id: str, weight: int, entry: dict):
        key = entry.get("keys", {}).get(weight)
        if not key:
            return None
        try:
            data = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        except Exception:  # noqa: BLE001 — police manquante = repli gracieux (stack de secours)
            return None
        return base64.b64encode(data).decode(), entry.get("formats", {}).get(weight, "woff2")
    return loader
