"""
Documents multipages (PDF / PPT / PPTX) — §3.2 « rendu page par page ».

Le worker (`media_worker._process_document`) convertit le document à l'upload en
1 image JPEG par page (PPT/PPTX → PDF via LibreOffice, puis pdftoppm) et pose :
- `cms_media.page_count` + `metadata["document"] = {page_count, pages:[{key, checksum,
  width, height}], source}` ;
- la vignette médiathèque (page 1).

La diffusion est DÉROULÉE PAR LE SERVEUR (même principe que la rotation de
playlists) : un item de playlist `document` devient N items image dans le payload
de sync (ws.py) — durée par page = `item.duration_ms` (défaut 10 s), sélection de
pages optionnelle `item.doc_pages` ("2-5,8", ordre respecté). Zéro modification
player : wall-clock, LAN sync, PoP et injection campagnes fonctionnent tels quels.

`item.doc_page_count` (colonne dénormalisée, maintenue à l'écriture + re-calculée
par le worker au replace) ne sert QUE les agrégats SQL (durée totale de playlist,
simulation, feasibility) ; le payload re-parse toujours `doc_pages` contre les
pages réellement converties (exact même si le document a changé entre-temps).
"""

from __future__ import annotations

from sqlalchemy import case, func

from app.models.media import CmsMedia
from app.models.playlist import CmsPlaylistItem

DEFAULT_PAGE_DURATION_MS = 10000


def parse_page_selection(spec: str | None, page_count: int) -> list[int]:
    """"2-5,8" → [2,3,4,5,8] (1-based, borné à page_count, ordre de saisie respecté,
    doublons ignorés). None / vide / invalide → toutes les pages dans l'ordre."""
    all_pages = list(range(1, max(0, page_count) + 1))
    if not spec or page_count <= 0:
        return all_pages
    out: list[int] = []
    seen: set[int] = set()
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                a_s, b_s = part.split("-", 1)
                a, b = int(a_s.strip()), int(b_s.strip())
                if b < a:
                    a, b = b, a
                rng = range(max(1, a), min(page_count, b) + 1)
            else:
                n = int(part)
                rng = range(n, n + 1) if 1 <= n <= page_count else range(0)
        except ValueError:
            return all_pages  # sélection illisible → repli sûr : tout le document
        for n in rng:
            if n not in seen:
                seen.add(n)
                out.append(n)
    return out or all_pages


def selection_count(spec: str | None, page_count: int) -> int:
    return len(parse_page_selection(spec, page_count))


def document_pages(media_metadata: dict | None) -> list[dict] | None:
    """Pages converties d'un média document ([{key, checksum, width, height}]) —
    None si le document n'a pas (encore) été converti."""
    doc = (media_metadata or {}).get("document") or {}
    pages = doc.get("pages")
    if isinstance(pages, list) and pages:
        return pages
    return None


def selected_pages(pages: list[dict], spec: str | None) -> list[tuple[int, dict]]:
    """[(numéro 1-based, meta de page)] selon la sélection (ordre de saisie)."""
    return [(n, pages[n - 1]) for n in parse_page_selection(spec, len(pages))]


# ── Expressions SQL partagées (agrégats de durée) ────────────────────────────────
# Un document converti contribue durée(par page) × pages sélectionnées ; sa durée
# n'est JAMAIS « manquante » (résolue par défaut 10 s/page). Les autres types
# gardent le fallback historique COALESCE(item, media, 10000).

def item_duration_sql():
    """Durée effective d'un item (nécessite un join CmsMedia, outer accepté)."""
    return case(
        (
            CmsMedia.page_count.isnot(None),
            func.coalesce(CmsPlaylistItem.duration_ms, DEFAULT_PAGE_DURATION_MS)
            * func.coalesce(CmsPlaylistItem.doc_page_count, CmsMedia.page_count),
        ),
        else_=func.coalesce(
            CmsPlaylistItem.duration_ms, CmsMedia.duration_ms, DEFAULT_PAGE_DURATION_MS
        ),
    )


def item_duration_missing_sql():
    """1 si la durée de l'item est irrésoluble (casse sync_ready), sinon 0."""
    return case(
        (CmsMedia.page_count.isnot(None), 0),
        (func.coalesce(CmsPlaylistItem.duration_ms, CmsMedia.duration_ms).is_(None), 1),
        else_=0,
    )


def effective_duration_py(
    item_duration_ms: int | None,
    media_duration_ms: int | None,
    media_page_count: int | None,
    doc_pages: str | None = None,
    doc_page_count: int | None = None,
) -> int | None:
    """Pendant Python de item_duration_sql (chemins brouillon / walk d'items).
    Renvoie None quand la durée est irrésoluble (média non-document sans durée)."""
    if media_page_count:
        pages = doc_page_count or selection_count(doc_pages, media_page_count)
        return (item_duration_ms or DEFAULT_PAGE_DURATION_MS) * max(1, pages)
    if item_duration_ms is not None:
        return item_duration_ms
    return media_duration_ms
