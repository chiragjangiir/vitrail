"""Chartes de marque (P3.4) — résolution, application au thème, bloc de prompt.

Une charte déclare UNE fois ce qui se répétait à chaque visuel : couleurs, police, nom de marque,
logo, mentions légales, ton. Deux portées : l'**organisation** (le retailer) et l'**annonceur**.

🔑 **Trois règles qui tiennent tout le module :**

1. **Une charte ne remplace QUE ce qu'elle déclare.** Une valeur nulle laisse au template la
   sienne — sinon poser une seule couleur de marque effacerait en silence les quatre autres du
   template et rendrait un visuel incohérent.
2. **L'annonceur l'emporte sur l'organisation** — un visuel fait pour Brightwell ne porte pas les
   couleurs du magasin.
3. **La charte est un DÉFAUT, pas un verrou** : les overrides de style saisis par l'opérateur
   passent après elle et gagnent (`resolve_template` applique les overrides sur le thème déjà
   fusionné). L'ordre de précédence est donc *thème du template < charte < saisie de l'opérateur*.

⚠️ Ce que la charte NE fait PAS : elle ne demande jamais au modèle génératif de dessiner un logo,
un nom de marque ou des mentions légales. Ces trois-là sont posés **après**, par le compositing
déterministe, et le bloc de prompt le dit au modèle (`prompt_block`). Sans cette séparation
l'assistant promet une fidélité de marque que rien ne peut tenir, et l'écart se découvre sur le
visuel fini — trop tard.
"""

from __future__ import annotations

import re

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brand_kit import CmsBrandKit

# Clés de couleur du thème d'un template promo (`services/promo/templates.py`).
THEME_COLOR_KEYS = ("accent", "ink", "paper", "badge_bg", "badge_ink")

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def _hex_or_none(value) -> str | None:
    """Couleur sûre pour du CSS inline. La base porte déjà un CHECK — on re-valide ici parce que
    la valeur finit dans une page rendue par Chromium et qu'un second chemin d'écriture (import,
    script, API future) ne passerait pas forcément par le même contrôle."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    return v if _HEX_RE.match(v) else None


def kit_to_dict(kit: CmsBrandKit | None) -> dict | None:
    """Ligne ORM → dict pur (le reste du module ne touche jamais la DB)."""
    if kit is None:
        return None
    return {
        "id_brand_kit": kit.id_brand_kit,
        "id_advertiser": kit.id_advertiser,
        "kit_name": kit.kit_name,
        "accent": kit.accent,
        "ink": kit.ink,
        "paper": kit.paper,
        "badge_bg": kit.badge_bg,
        "badge_ink": kit.badge_ink,
        "font_family": kit.font_family,
        "brand_name": kit.brand_name,
        "id_logo_media": kit.id_logo_media,
        "legal_mentions": kit.legal_mentions,
        "tone": kit.tone,
    }


def pick(candidates: list[dict], id_advertiser: int | None) -> dict | None:
    """(pur) **LA** règle de résolution : la charte de l'annonceur d'abord, repli sur celle de
    l'organisation, None si aucune.

    Elle vit ici et nulle part ailleurs : l'API la consulte en ORM async, le worker de rendu en
    psycopg2 synchrone, et deux implémentations divergentes feraient rendre au worker autre chose
    que ce que l'écran annonce."""
    if id_advertiser is not None:
        for kit in candidates:
            if kit.get("id_advertiser") == id_advertiser:
                return kit
    for kit in candidates:
        if kit.get("id_advertiser") is None:
            return kit
    return None


async def resolve_brand_kit(
    db: AsyncSession, id_org: int, id_advertiser: int | None = None
) -> dict | None:
    """Charte EFFECTIVE (chemin API, ORM async).

    Renvoie None quand aucune n'est définie — c'est le cas au déploiement, et il doit laisser le
    rendu strictement inchangé."""
    rows = (
        await db.execute(
            select(CmsBrandKit).where(
                CmsBrandKit.id_org == id_org,
                or_(
                    CmsBrandKit.id_advertiser.is_(None),
                    CmsBrandKit.id_advertiser == id_advertiser,
                ),
            )
        )
    ).scalars().all()
    return pick([kit_to_dict(r) for r in rows], id_advertiser)


_SYNC_COLUMNS = (
    "id_brand_kit", "id_advertiser", "kit_name", "accent", "ink", "paper", "badge_bg",
    "badge_ink", "font_family", "brand_name", "id_logo_media", "legal_mentions", "tone",
)


def resolve_brand_kit_sync(conn, id_org: int, id_advertiser: int | None = None) -> dict | None:
    """Charte EFFECTIVE (chemin worker de rendu, psycopg2 synchrone). Même règle que ci-dessus —
    c'est `pick` qui décide dans les deux cas."""
    cur = conn.cursor()
    cur.execute(
        f"SELECT {', '.join(_SYNC_COLUMNS)} FROM cms_brand_kits "
        "WHERE id_org = %s AND (id_advertiser IS NULL OR id_advertiser = %s)",
        (id_org, id_advertiser),
    )
    rows = [dict(zip(_SYNC_COLUMNS, r, strict=True)) for r in cur.fetchall()]
    return pick(rows, id_advertiser)


def theme_overrides(kit: dict | None, font_catalog: dict | None = None) -> dict:
    """(pur) Ce que la charte déclare, et RIEN d'autre — prêt à fusionner sur le thème d'un
    template. Un dict vide signifie « le template garde tout ».

    `font_catalog` (facultatif) = catalogue de polices résolu pour l'organisation. S'il est fourni
    et que la famille de la charte n'y est PAS, on ne la déclare pas : une police supprimée depuis
    l'écriture de la charte ne doit pas casser un rendu, elle doit le laisser retomber sur son
    défaut (même raison que le `ON DELETE SET NULL` du logo)."""
    if not kit:
        return {}
    out: dict = {}
    for key in THEME_COLOR_KEYS:
        color = _hex_or_none(kit.get(key))
        if color:
            out[key] = color
    family = (kit.get("font_family") or "").strip()
    if family:
        known = font_catalog is None or any(
            (entry or {}).get("family") == family for entry in font_catalog.values()
        )
        if known:
            out["font"] = family
    return out


def apply_to_theme(theme: dict, kit: dict | None, font_catalog: dict | None = None) -> dict:
    """(pur) Thème du template + charte → thème effectif. Ne remplace QUE ce que la charte déclare."""
    return {**theme, **theme_overrides(kit, font_catalog)}


def prompt_block(kit: dict | None) -> str:
    """(pur) Bloc d'instructions « marque » ajouté au prompt système de l'assistant de rédaction.

    Donne la palette et le ton comme **atmosphère à viser**, et déclare explicitement que le logo,
    le nom de marque et les mentions légales sont posés APRÈS par le compositing — donc que le
    modèle ne doit dessiner ni texte ni logo.

    ⚠️ Le NOM de la marque n'est volontairement pas donné comme matière créative : un modèle à qui
    l'on nomme la marque peint son logo ou son produit, alors que le fond promo doit rester propre
    (`services/promo/backgrounds.py`). Il n'apparaît ici que dans la consigne de ne pas l'écrire.
    Renvoie "" quand aucune charte n'est définie — l'assistant reste alors exactement ce qu'il est
    aujourd'hui."""
    if not kit:
        return ""
    lines: list[str] = []
    palette = [f"{key}={kit[key]}" for key in THEME_COLOR_KEYS if _hex_or_none(kit.get(key))]
    if palette:
        lines.append(
            "Palette de la marque (ATMOSPHÈRE à viser, pas une consigne de colorimétrie exacte) : "
            + ", ".join(palette)
        )
    tone = (kit.get("tone") or "").strip()
    if tone:
        lines.append(f"Ton de la marque : {tone}")
    if not lines:
        return ""
    lines.append(
        "Le logo, le nom de la marque et les mentions légales sont ajoutés APRÈS par le "
        "compositing : ne les demande PAS au modèle et n'écris aucun texte dans le prompt "
        "(renforce-le dans le negative prompt s'il est supporté)."
    )
    return "Charte de marque —\n" + "\n".join(f"- {line}" for line in lines) + "\n"
