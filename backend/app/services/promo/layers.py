"""Calques libres (Phase B, §12.4) — résolution + sanitisation.

Des calques **texte / image / forme** se superposent au template (les slots garantis prix/mentions
sont conservés). PUR : sanitise TOUTES les valeurs (couleurs hex ou `none`, police ∈ catalogue,
nombres bornés, type/forme/align en enum) → **aucune injection CSS**. Les calques image portent un
`media_id` ; leur data-URI est injecté par le worker (I/O). Ordre de superposition = `z` croissant.
"""

from __future__ import annotations

import re

from app.services.promo import fonts

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_ALIGN = {"left", "center", "right"}
_SHAPES = {"rect", "ellipse", "line"}
_TYPES = {"text", "image", "shape"}
MAX_LAYERS = 40


def _num(v, lo: float, hi: float, default: float) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def _color(v, default: str | None = None) -> str | None:
    """Couleur sûre : hex (#rgb/#rrggbb/#rrggbbaa) ou littéral `none`. Sinon `default`."""
    if isinstance(v, str):
        s = v.strip()
        if s == "none" or _HEX_RE.match(s):
            return s
    return default


def resolve_layers(raw, theme: dict, catalog: dict) -> list[dict]:
    """(pur) Liste brute (UI) → calques résolus + sanitisés, triés par z. Plafonné à MAX_LAYERS."""
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for i, ly in enumerate(raw[:MAX_LAYERS]):
        if not isinstance(ly, dict) or ly.get("type") not in _TYPES:
            continue
        t = ly["type"]
        base = {
            "type": t,
            "x": _num(ly.get("x"), -50, 150, 10),
            "y": _num(ly.get("y"), -50, 150, 10),
            "w": _num(ly.get("w"), 1, 200, 30),
            "h": _num(ly.get("h"), 1, 200, 20),
            "rotation": _num(ly.get("rotation"), -360, 360, 0),
            "z": int(_num(ly.get("z"), 0, 999, i + 1)),
            "opacity": _num(ly.get("opacity"), 0, 1, 1),
        }
        if t == "text":
            fid = ly.get("font")
            fam = fonts.resolve_family(catalog, fid) if fid else None
            w = int(_num(ly.get("weight"), 100, 900, 600))
            base.update({
                "text": str(ly.get("text") or ""),
                "font": fam,
                "font_id": fid if fam else None,
                "size_vh": _num(ly.get("size_vh"), 1, 60, 6),
                "color": _color(ly.get("color"), theme.get("ink", "#1D2B3A")),
                "weight": fonts.nearest_weight_in(catalog, fid, w) if fam else w,
                "align": ly.get("align") if ly.get("align") in _ALIGN else "left",
            })
        elif t == "image":
            try:
                base["media_id"] = int(ly.get("media_id"))
            except (TypeError, ValueError):
                continue
            base["fit"] = "cover" if ly.get("fit") == "cover" else "contain"
        else:  # shape
            base.update({
                "shape": ly.get("shape") if ly.get("shape") in _SHAPES else "rect",
                "fill": _color(ly.get("fill"), theme.get("accent", "#4875B4")),
                "stroke": _color(ly.get("stroke"), "none"),
                "stroke_width": _num(ly.get("stroke_width"), 0, 20, 0),
                "radius": _num(ly.get("radius"), 0, 50, 0),
            })
        out.append(base)
    out.sort(key=lambda layer: layer["z"])
    return out
