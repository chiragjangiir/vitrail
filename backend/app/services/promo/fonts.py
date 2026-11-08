"""Catalogue de polices promo (Phase A styling) + builder `@font-face` base64.

Deux sources, unifiées par un **catalogue** `{font_id: {family, weights, source}}` :
- **built-in** : 6 familles OFL auto-hébergées (woff2 dans `./fonts/`) — embarquées en data-URI ;
- **custom (§12.7)** : polices uploadées par l'organisation, stockées dans MinIO (`cms_org_fonts`)
  → le worker fournit un `custom_loader` qui télécharge les octets et les embarque de même.

Rendu **déterministe/offline** dans les deux cas (data-URI). Les mêmes fichiers sont servis au
frontend (built-in via `frontend/public/fonts/promo/`, custom via `/promo/fonts/{id}/file`) → aperçu
WYSIWYG = rendu.

Sécurité : les valeurs de style saisies (police/couleur/poids/align) sont **validées contre le
catalogue / des regex** avant d'entrer dans le CSS (cf. `templates._apply_style`).

⚠️ Le NOM DE FAMILLE lui-même est une valeur saisie (upload de police §12.7, charte de marque
P3.4) : il traverse `css_family()` avant d'entrer dans le CSS. Un `'` échappé en `&#39;` par Jinja
est **redécodé par l'analyseur HTML** dans un attribut `style="…"` avant que le CSS ne soit lu —
l'échappement HTML ne protège donc pas d'une injection CSS à cet endroit.
"""

from __future__ import annotations

import base64
import re
from functools import lru_cache
from pathlib import Path

_FONTS_DIR = Path(__file__).parent / "fonts"

# Caractères admis dans un nom de famille CSS : lettres (accentuées comprises), chiffres, espace,
# tiret, underscore, point. Tout le reste est retiré — un nom de police n'a aucun besoin
# légitime d'une apostrophe, d'un point-virgule ou d'une parenthèse.
_FAMILY_STRIP_RE = re.compile(r"[^0-9A-Za-zÀ-ɏ \-_.]")

# id → {family CSS, catégorie, poids embarqués (faces exactes → pas de synthèse), label UI}.
FONTS: dict[str, dict] = {
    "inter": {"family": "Inter", "category": "sans",
              "weights": [400, 500, 600, 700, 800, 900], "label": "Inter"},
    "montserrat": {"family": "Montserrat", "category": "sans",
                   "weights": [400, 600, 800], "label": "Montserrat"},
    "poppins": {"family": "Poppins", "category": "sans",
                "weights": [400, 600, 700], "label": "Poppins"},
    "oswald": {"family": "Oswald", "category": "condensed",
               "weights": [400, 500, 700], "label": "Oswald"},
    "bebas-neue": {"family": "Bebas Neue", "category": "display",
                   "weights": [400], "label": "Bebas Neue"},
    "playfair-display": {"family": "Playfair Display", "category": "serif",
                         "weights": [400, 700, 900], "label": "Playfair Display"},
}

DEFAULT_FONT_ID = "inter"
DEFAULT_FAMILY = "Inter"
CUSTOM_PREFIX = "org-"


def list_fonts() -> list[dict]:
    """Catalogue built-in exposé à l'UI (id, label, family, category, weights)."""
    return [{"id": fid, "label": f["label"], "family": f["family"],
             "category": f["category"], "weights": f["weights"]}
            for fid, f in FONTS.items()]


def builtin_catalog() -> dict[str, dict]:
    """Catalogue interne {font_id: {family, weights, source:'builtin'}}."""
    return {fid: {"family": f["family"], "weights": list(f["weights"]), "source": "builtin"}
            for fid, f in FONTS.items()}


def css_family(family: str | None) -> str | None:
    """(pur) Nom de famille sûr pour du CSS inline, ou None si rien d'exploitable ne subsiste.

    **Point de passage unique** avant toute écriture d'un `font-family` : le rendu ne doit pas
    pouvoir émettre du CSS arbitraire, quelle que soit la valeur en base (des lignes antérieures
    au contrôle de saisie existent). Le contrôle à l'écriture, lui, REFUSE le nom au lieu de le
    mutiler en silence — les deux se complètent."""
    if not isinstance(family, str):
        return None
    cleaned = _FAMILY_STRIP_RE.sub("", family).strip()
    return cleaned or None


def is_safe_family(family: str | None) -> bool:
    """Le nom est-il utilisable TEL QUEL en CSS ? (contrôle à la saisie — on refuse plutôt que de
    modifier discrètement ce que l'opérateur a écrit)."""
    if not isinstance(family, str):
        return False
    value = family.strip()
    return bool(value) and css_family(value) == value


def resolve_family(catalog: dict, font_id: str | None) -> str | None:
    """Famille CSS d'un id connu du catalogue, sinon None (id inconnu ignoré = sécurité)."""
    entry = catalog.get(font_id) if font_id else None
    return entry["family"] if entry else None


def nearest_weight_in(catalog: dict, font_id: str, weight: int) -> int:
    """Poids embarqué le plus proche pour cette police (faces exactes → 0 synthèse)."""
    weights = (catalog.get(font_id) or {}).get("weights") or [weight]
    return min(weights, key=lambda w: abs(w - weight))


def id_of_family_in(catalog: dict, family: str | None) -> str:
    """id de police depuis un nom de famille (repli sur Inter)."""
    for fid, entry in catalog.items():
        if entry["family"] == family:
            return fid
    return DEFAULT_FONT_ID


def used_font_faces(resolved: dict, catalog: dict | None = None) -> set[tuple[str, int]]:
    """(pur) Paires (font_id, poids) réellement utilisées par l'arbre résolu → à embarquer.

    La police d'un slot = son override (`font_id`) sinon celle du thème (Inter). Poids snappé."""
    catalog = catalog or builtin_catalog()
    theme_id = id_of_family_in(catalog, (resolved.get("theme") or {}).get("font"))
    pairs: set[tuple[str, int]] = set()
    for slot in (resolved.get("slots") or {}).values():
        if not slot or "font_vh" not in slot:
            continue
        fid = slot.get("font_id") or theme_id
        pairs.add((fid, nearest_weight_in(catalog, fid, int(slot.get("weight") or 600))))
    for layer in (resolved.get("layers") or []):  # calques texte (Phase B)
        if layer.get("type") != "text":
            continue
        fid = layer.get("font_id") or theme_id
        pairs.add((fid, nearest_weight_in(catalog, fid, int(layer.get("weight") or 600))))
    return pairs


@lru_cache(maxsize=64)
def _builtin_b64(font_id: str, weight: int) -> str | None:
    path = _FONTS_DIR / f"{font_id}-{weight}.woff2"
    return base64.b64encode(path.read_bytes()).decode() if path.exists() else None


def _face_rule(family: str, weight: int, b64: str, fmt: str = "woff2") -> str:
    """Règle `@font-face`. La famille est sanitisée par `css_family` — ici pour deux raisons :
    ce bloc est injecté en `| safe` dans un `<style>` (une famille malformée pourrait le refermer),
    et surtout la famille DÉCLARÉE ici doit être **identique** à celle utilisée plus bas ; deux
    sanitisations divergentes donneraient une police embarquée que rien n'appelle."""
    safe = css_family(family) or DEFAULT_FAMILY
    mime = {"woff2": "font/woff2", "woff": "font/woff", "ttf": "font/ttf",
            "otf": "font/otf"}.get(fmt, "font/woff2")
    return (f"@font-face{{font-family:'{safe}';font-style:normal;font-weight:{weight};"
            f"font-display:block;src:url(data:{mime};base64,{b64}) format('{fmt}');}}")


def font_face_css(pairs: set[tuple[str, int]], catalog: dict | None = None,
                  custom_loader=None) -> str:
    """@font-face base64 pour l'ensemble (font_id, poids). Built-in → woff2 local ; custom →
    `custom_loader(font_id, weight, entry) -> (b64, fmt) | None` (fourni par le worker, lit MinIO).
    Paires non résolues ignorées silencieusement (repli sur le stack de secours au rendu)."""
    catalog = catalog or builtin_catalog()
    out: list[str] = []
    for fid, weight in sorted(pairs):
        entry = catalog.get(fid)
        if not entry:
            continue
        w = nearest_weight_in(catalog, fid, weight)
        if entry["source"] == "builtin":
            b64, fmt = _builtin_b64(fid, w), "woff2"
        elif custom_loader:
            loaded = custom_loader(fid, w, entry)
            b64, fmt = (loaded if loaded else (None, "woff2"))
        else:
            continue
        if b64:
            out.append(_face_rule(entry["family"], w, b64, fmt))
    return "".join(out)
