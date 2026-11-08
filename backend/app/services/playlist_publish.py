"""Application d'un brouillon de playlist → items publiés (diff), extraite de l'endpoint.

Un SEUL chemin d'application du brouillon, partagé par :
  · `POST /playlists/{id}/publish` (publication directe, contenu non modéré) ;
  · le hook d'APPROBATION §XXI (gouvernance §XVIII : quand un modérateur approuve la demande
    d'une playlist gouvernée sous modération, son brouillon est publié dans la même
    transaction — décision R15/C).

Applique les RÉGLAGES en attente (`draft_settings` : rotation — décision Ed 2026-07-25 ④)
puis les ITEMS par DIFF (update des items existants → `id_item` préservés donc les tags ;
insert des nouveaux ; delete des retirés), revalide les sous-playlists, puis remet
`draft_items`/`draft_settings` à NULL. NE COMMIT PAS et NE POUSSE PAS de sync : l'appelant garde ces responsabilités (il
connaît le contexte transactionnel et les effets de bord — conformité, force_sync).
"""

from __future__ import annotations

import json

import redis.asyncio as aioredis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.media import CmsMedia
from app.models.player import CmsPlayer
from app.models.playlist import CmsPlaylist, CmsPlaylistItem, CmsPlaylistItemRule
from app.schemas.playlist import ItemRuleCreate
from app.services import document_media
from app.services.playlist_rotation import validate_child_for_nesting


async def push_org_force_sync(db: AsyncSession, preemptive: bool = False) -> None:
    """Force-sync graceful de tous les players de l'org (RLS scope la session).

    Extrait pour être appelable hors de l'endpoint playlists (ex. quand l'approbation
    d'une playlist gouvernée publie son brouillon depuis le module d'approbation)."""
    player_ids = [row[0] for row in (await db.execute(select(CmsPlayer.id_player))).all()]
    if not player_ids:
        return
    r = aioredis.from_url(settings.REDIS_URL)
    payload = json.dumps({"type": "player:force_sync", "preemptive": preemptive})
    async with r:
        for pid in player_ids:
            await r.publish(f"signflow:player:{pid}:cmds", payload)


class DraftApplyError(ValueError):
    """Brouillon invalide au moment d'appliquer (ex. sous-playlist devenue invalide)."""


#: Réglages de playlist qui transitent par le brouillon (décision Ed 2026-07-25 ④).
DRAFT_SETTING_KEYS = ("rotation_mode", "items_per_turn", "no_ads_inside")


def has_draft(pl: CmsPlaylist) -> bool:
    """Y a-t-il quelque chose à publier ? Items ET/OU réglages.

    Définition UNIQUE : trois chemins gardaient auparavant `draft_items is not None`
    (publication, soumission à l'approbation, application à l'approbation). Une playlist
    dont seule la rotation a changé serait restée impubliable — et, sous modération,
    insoumettable.
    """
    return pl.draft_items is not None or pl.draft_settings is not None


def draft_setting(pl: CmsPlaylist, key: str):
    """Valeur d'un réglage telle que l'ÉDITEUR doit la voir : brouillon s'il existe,
    sinon valeur publiée."""
    settings = pl.draft_settings or {}
    return settings[key] if key in settings else getattr(pl, key)


async def apply_draft(db: AsyncSession, pl: CmsPlaylist) -> list[dict]:
    """Applique `pl.draft_settings` (réglages) puis `pl.draft_items` (contenus) sur la
    playlist publiée. Renvoie la liste des items du brouillon appliqué (pour la passe de
    conformité de l'appelant). NE COMMIT PAS.

    Lève `DraftApplyError` si une sous-playlist du brouillon est devenue invalide.
    No-op silencieux (renvoie []) si aucun brouillon.
    """
    if pl.draft_settings is not None:
        for key, value in pl.draft_settings.items():
            if key in DRAFT_SETTING_KEYS:
                setattr(pl, key, value)
        pl.draft_settings = None

    if pl.draft_items is None:
        return []
    draft = pl.draft_items
    id_playlist = pl.id_playlist

    # Re-validation des sous-playlists AU MOMENT d'appliquer (le brouillon a pu vieillir :
    # enfant supprimé, imbrication devenue invalide via un autre publish…).
    for e in draft:
        if e.get("id_child_playlist"):
            try:
                await validate_child_for_nesting(
                    db, pl.id_org, id_playlist, e["id_child_playlist"])
            except ValueError as exc:
                raise DraftApplyError(str(exc)) from exc

    live = {i.id_item: i for i in (await db.execute(
        select(CmsPlaylistItem).where(CmsPlaylistItem.id_playlist == id_playlist)
    )).scalars().all()}
    draft_uids = {e["uid"] for e in draft if e["uid"] > 0}

    # Documents multipages : nb de pages (pour dénormaliser doc_page_count).
    doc_media_ids = {e["id_media"] for e in draft if e.get("id_media") and e.get("doc_pages")}
    doc_counts: dict[int, int] = {}
    if doc_media_ids:
        for mid, pc in (await db.execute(
            select(CmsMedia.id_media, CmsMedia.page_count)
            .where(CmsMedia.id_media.in_(doc_media_ids))
        )).all():
            doc_counts[mid] = pc or 0

    def _doc_fields(e: dict) -> tuple[str | None, int | None]:
        spec = e.get("doc_pages") or None
        if not spec or not e.get("id_media"):
            return None, None
        pc = doc_counts.get(e["id_media"], 0)
        if not pc:
            return spec, None  # document pas (encore) converti : résolu par le worker
        return spec, document_media.selection_count(spec, pc)

    # 1. Supprimer les items publiés retirés du brouillon (+ leurs règles ; tags cascade).
    to_delete = [iid for iid in live if iid not in draft_uids]
    if to_delete:
        await db.execute(delete(CmsPlaylistItemRule).where(CmsPlaylistItemRule.id_item.in_(to_delete)))
        await db.execute(delete(CmsPlaylistItem).where(CmsPlaylistItem.id_item.in_(to_delete)))

    # 2. Update existants (id préservé → tags conservés) / insert nouveaux + règles.
    for e in draft:
        doc_pages, doc_page_count = _doc_fields(e)
        if e["uid"] > 0 and e["uid"] in live:
            it = live[e["uid"]]
            it.id_media = e.get("id_media")
            it.item_type = e.get("item_type", "media")
            it.id_child_playlist = e.get("id_child_playlist")
            it.sort_order = e["sort_order"]
            it.duration_ms = e.get("duration_ms")
            it.zone_index = e.get("zone_index", 0)
            it.transition_type = e.get("transition_type", "cut")
            it.doc_pages = doc_pages
            it.doc_page_count = doc_page_count
            # ⚠️ Recopier ici ET dans la branche d'insertion ci-dessous : un champ ajouté d'un
            # seul côté serait posé au brouillon puis PERDU à la publication, en silence.
            it.touch_navigation = bool(e.get("touch_navigation", False))
            it.touch_resume_after_s = e.get("touch_resume_after_s")
        else:
            it = CmsPlaylistItem(
                id_playlist=id_playlist, id_media=e.get("id_media"), sort_order=e["sort_order"],
                item_type=e.get("item_type", "media"),
                id_child_playlist=e.get("id_child_playlist"),
                duration_ms=e.get("duration_ms"), zone_index=e.get("zone_index", 0),
                transition_type=e.get("transition_type", "cut"),
                doc_pages=doc_pages, doc_page_count=doc_page_count,
                touch_navigation=bool(e.get("touch_navigation", False)),
                touch_resume_after_s=e.get("touch_resume_after_s"),
            )
            db.add(it)
            await db.flush()
        await db.execute(delete(CmsPlaylistItemRule).where(CmsPlaylistItemRule.id_item == it.id_item))
        for r in e.get("rules", []):
            db.add(CmsPlaylistItemRule(id_item=it.id_item, **ItemRuleCreate(**r).model_dump()))

    pl.draft_items = None
    return draft
