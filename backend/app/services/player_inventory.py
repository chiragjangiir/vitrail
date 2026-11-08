"""Inventaire ATTENDU d'un player : union de TOUT le contenu cachable programmé pour ce
player (vidéo/image des playlists ET audio des paniers §XIX ciblant ce player), sans filtre
horaire.

Sert l'endpoint `GET /players/{id}/inventory` : on compare ce programme planifié au cache
réel remonté par le player (`capabilities.store.cached_ids/downloading_ids`) → statut
cached / downloading / missing par média.

Audio INCLUS depuis que l'offline-first le met en cache (cf. content_store) : on résout les
paniers audio via les schedules audio + events audio + config opérateur ciblant le player.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audio_basket import CmsAudioBasket, CmsAudioBasketItem, CmsPlayerBasketConfig
from app.models.event import CmsEvent
from app.models.media import CmsMedia
from app.models.player import CmsPlayer
from app.models.player_group import CmsPlayerGroupMember
from app.models.playlist import CmsPlaylist, CmsPlaylistItem
from app.models.schedule import CmsSchedule, CmsScheduleBasket, CmsScheduleTarget
from app.models.tag import (
    CmsMediaTagValue,
    CmsPlayerTagFilter,
    CmsPlaylistItemNsOverride,
    CmsPlaylistItemTag,
    CmsTagNamespace,
    CmsTagValue,
)
from app.models.vod import CmsVodConfig, CmsVodConfigMedia
from app.services.tags import compute_effective_tags, item_matches_player
from app.services.targeting import event_target_matches, player_site_group_ids
from app.services.vod_targeting import vod_config_ids_for_player

# Types réellement mis en cache local par l'offline-first (content_store). Le 'document'
# (PDF) est caché et rendu comme un visuel → inclus, sinon absent de l'inventaire alors que
# le player le télécharge.
_CACHEABLE = ("video", "image", "audio", "document")
_VISUAL = ("video", "image", "document")


async def _allowed_visual_media(
    db: AsyncSession, id_player: int, candidates: list[tuple[int, int | None]]
) -> set[int] | None:
    """Set des id_media VISUELS que le profil tag (réception) du player accepte.

    Mirroir de `ws._filter_items_by_tags` au niveau média : un média est gardé s'il passe
    le filtre via AU MOINS UN de ses contextes de diffusion `(id_media, id_item|None)` —
    sinon le contenu tagué pour un autre player (ex. mur left/right) apparaît à tort
    « manquant » dans l'inventaire. `None` = player sans filtre → tout passe (sortie rapide).
    Les paniers audio ne sont pas concernés (non tag-filtrés côté sync).
    """
    pf_rows = (await db.execute(
        select(CmsTagNamespace.namespace_key, CmsTagValue.tag_value)
        .join(CmsTagValue, CmsTagValue.id_namespace == CmsTagNamespace.id_namespace)
        .join(CmsPlayerTagFilter, CmsPlayerTagFilter.id_tag == CmsTagValue.id_tag)
        .where(CmsPlayerTagFilter.id_player == id_player)
    )).all()
    if not pf_rows:
        return None
    player_filters: dict[str, list[str]] = {}
    for ns_key, val in pf_rows:
        player_filters.setdefault(ns_key, []).append(val)

    media_ids = {mid for mid, _ in candidates}
    item_ids = {iid for _, iid in candidates if iid is not None}

    media_tags_map: dict[int, dict[str, list[str]]] = {}
    if media_ids:
        for mid, ns_key, val in (await db.execute(
            select(CmsMediaTagValue.id_media, CmsTagNamespace.namespace_key, CmsTagValue.tag_value)
            .join(CmsTagValue, CmsTagValue.id_tag == CmsMediaTagValue.id_tag)
            .join(CmsTagNamespace, CmsTagNamespace.id_namespace == CmsTagValue.id_namespace)
            .where(CmsMediaTagValue.id_media.in_(media_ids))
        )).all():
            media_tags_map.setdefault(mid, {}).setdefault(ns_key, []).append(val)

    item_tags_map: dict[int, dict[str, list[str]]] = {}
    item_ovr_map: dict[int, set[str]] = {}
    if item_ids:
        for iid, ns_key, val in (await db.execute(
            select(CmsPlaylistItemTag.id_item, CmsTagNamespace.namespace_key, CmsTagValue.tag_value)
            .join(CmsTagValue, CmsTagValue.id_tag == CmsPlaylistItemTag.id_tag)
            .join(CmsTagNamespace, CmsTagNamespace.id_namespace == CmsTagValue.id_namespace)
            .where(CmsPlaylistItemTag.id_item.in_(item_ids))
        )).all():
            item_tags_map.setdefault(iid, {}).setdefault(ns_key, []).append(val)
        for iid, ns_key in (await db.execute(
            select(CmsPlaylistItemNsOverride.id_item, CmsTagNamespace.namespace_key)
            .join(CmsTagNamespace, CmsTagNamespace.id_namespace == CmsPlaylistItemNsOverride.id_namespace)
            .where(CmsPlaylistItemNsOverride.id_item.in_(item_ids))
        )).all():
            item_ovr_map.setdefault(iid, set()).add(ns_key)

    allowed: set[int] = set()
    for mid, iid in candidates:
        eff = compute_effective_tags(
            media_tags_map.get(mid, {}),
            item_tags_map.get(iid, {}) if iid is not None else {},
            item_ovr_map.get(iid, set()) if iid is not None else set(),
        )
        if item_matches_player(eff, player_filters):
            allowed.add(mid)
    return allowed


async def _group_ids(db: AsyncSession, id_player: int) -> set[int]:
    rows = (await db.execute(
        select(CmsPlayerGroupMember.id_group).where(CmsPlayerGroupMember.id_player == id_player)
    )).all()
    return {r[0] for r in rows}


async def expected_media(db: AsyncSession, id_player: int) -> list[dict]:
    """Liste [{id_media, media_name, media_type, refs:[sources]}] des médias vidéo/image
    que ce player est programmé à jouer (toutes playlists/events/gouvernance le ciblant)."""
    player = (await db.execute(
        select(CmsPlayer).where(CmsPlayer.id_player == id_player)
    )).scalar_one_or_none()
    if not player:
        return []
    id_org = player.id_org
    group_ids = await _group_ids(db, id_player)
    site_group_ids = await player_site_group_ids(db, id_player)

    playlist_ids: set[int] = set()            # playlists programmées (toutes sources confondues)
    media_refs: dict[int, set[str]] = {}      # id_media -> libellés sources (playlist/event/panier)
    basket_media_ids: set[int] = set()        # médias issus des paniers audio (cachés en tant qu'audio)
    vod_media_ids: set[int] = set()           # médias VOD (pré-cache, affectation explicite → pas de filtre tag)
    visual_candidates: list[tuple[int, int | None]] = []  # (id_media, id_item|None) pour le filtre tag

    def _add_pl(pid: int | None) -> None:
        if pid:
            playlist_ids.add(pid)

    # ── 1. Schedules : cibles directes (player) + groupes + gouvernance ───────────
    sched_ids: set[int] = set()
    rows = (await db.execute(select(CmsScheduleTarget.id_schedule).where(
        CmsScheduleTarget.target_type == "player", CmsScheduleTarget.target_id == id_player))).all()
    sched_ids.update(r[0] for r in rows)
    if group_ids:
        rows = (await db.execute(select(CmsScheduleTarget.id_schedule).where(
            CmsScheduleTarget.target_type == "player_group",
            CmsScheduleTarget.target_id.in_(group_ids)))).all()
        sched_ids.update(r[0] for r in rows)
    if player.id_site is not None:
        rows = (await db.execute(select(CmsScheduleTarget.id_schedule).where(
            CmsScheduleTarget.target_type == "site",
            CmsScheduleTarget.target_id == player.id_site))).all()
        sched_ids.update(r[0] for r in rows)
    if site_group_ids:
        rows = (await db.execute(select(CmsScheduleTarget.id_schedule).where(
            CmsScheduleTarget.target_type == "site_group",
            CmsScheduleTarget.target_id.in_(site_group_ids)))).all()
        sched_ids.update(r[0] for r in rows)
    # Gouvernance §XVIII : schedules gouvernés rattachés aux nœuds ancrés au player.
    try:
        from app.api.v1.endpoints.governance import _anchor_nodes_for_player, _relevant_node_ids
        from app.services.governance_scope import scoped_schedule_ids
        anchors = await _anchor_nodes_for_player(db, id_org, id_player)
        relevant = await _relevant_node_ids(db, id_org, anchors) if anchors else set()
        if relevant:
            rows = (await db.execute(select(CmsSchedule.id_schedule).where(
                CmsSchedule.id_governance_node.in_(relevant)))).all()
            # D-b : mêmes cibles que la diffusion (ce chemin re-sélectionne par nœud et ne
            # passe pas par `gather_layers`). Sans ce filtre, `expected_media` serait gonflé
            # ⇒ de faux « média manquant » sur des contenus jamais diffusés ici.
            sched_ids.update(await scoped_schedule_ids(db, id_player, {r[0] for r in rows}))
    except Exception:  # noqa: BLE001 — la gouvernance ne doit jamais casser l'inventaire
        pass

    if sched_ids:
        scheds = (await db.execute(select(CmsSchedule).where(
            CmsSchedule.id_schedule.in_(sched_ids),
            CmsSchedule.schedule_kind == "content",
            CmsSchedule.is_active == True,    # noqa: E712
            CmsSchedule.is_deleted == False,  # noqa: E712
        ))).scalars().all()
        for s in scheds:
            _add_pl(s.id_playlist)

    # ── 2. Events ciblant le player (planifiés, non terminés) ─────────────────────
    # Statuts terminaux RÉELS du cycle de vie event : `completed` (one-shot terminé — un
    # récurrent repasse `inactive`), `cancelled`, `rejected` (approval refusé). « ended »
    # n'a jamais existé → un event completed restait « attendu » à vie dans l'inventaire
    # (média affiché missing alors qu'il ne sera plus jamais servi — constaté Ed 2026-07-07).
    events = (await db.execute(select(CmsEvent).where(
        CmsEvent.id_org == id_org,
        CmsEvent.event_kind == "content",
        CmsEvent.status.notin_(("completed", "cancelled", "rejected")),
    ))).scalars().all()
    for ev in events:
        if not event_target_matches(
            ev.target_config, id_player, group_ids, site_group_ids, id_site=player.id_site
        ):
            continue
        _add_pl(ev.id_playlist)
        if ev.id_media:
            media_refs.setdefault(ev.id_media, set()).add(ev.event_name)
            visual_candidates.append((ev.id_media, None))  # event single-media : tags média seuls

    # ── 2bis. Audio (§XIX) : paniers via schedules audio + events audio + config opérateur ─
    basket_ids: set[int] = set()
    if sched_ids:
        rows = (await db.execute(select(CmsScheduleBasket.id_basket)
            .join(CmsSchedule, CmsSchedule.id_schedule == CmsScheduleBasket.id_schedule)
            .where(CmsScheduleBasket.id_schedule.in_(sched_ids),
                   CmsSchedule.schedule_kind == "audio",
                   CmsSchedule.is_active == True,    # noqa: E712
                   CmsSchedule.is_deleted == False))).all()  # noqa: E712
        basket_ids.update(r[0] for r in rows)
    audio_events = (await db.execute(select(CmsEvent).where(
        CmsEvent.id_org == id_org, CmsEvent.event_kind == "audio",
        CmsEvent.status.notin_(("completed", "cancelled", "rejected"))))).scalars().all()
    for ev in audio_events:
        if ev.id_basket is None:
            continue
        # 🔴 Matcher CANONIQUE — l'inline précédent ne connaissait que org/player/group :
        # un event audio ciblant un SITE (ou un groupe de sites) ne faisait jamais
        # pré-cacher son panier — faux « média manquant » à l'activation (prouvé rouge le
        # 2026-07-30, même classe que la cible `site` absente du force_sync le 29/07).
        if event_target_matches(
            ev.target_config, id_player, group_ids, site_group_ids, id_site=player.id_site
        ):
            basket_ids.add(ev.id_basket)
    # Config opérateur (Store Control Panel) : paniers activés sur ce player.
    rows = (await db.execute(select(CmsPlayerBasketConfig.id_basket).where(
        CmsPlayerBasketConfig.id_player == id_player,
        CmsPlayerBasketConfig.is_active == True))).all()  # noqa: E712
    basket_ids.update(r[0] for r in rows)

    if basket_ids:
        bnames = dict((await db.execute(select(CmsAudioBasket.id_basket, CmsAudioBasket.basket_name)
            .where(CmsAudioBasket.id_basket.in_(basket_ids)))).all())
        bitems = (await db.execute(select(CmsAudioBasketItem.id_basket, CmsAudioBasketItem.id_media)
            .where(CmsAudioBasketItem.id_basket.in_(basket_ids),
                   CmsAudioBasketItem.is_active == True))).all()  # noqa: E712
        for bid, mid in bitems:
            media_refs.setdefault(mid, set()).add(f"♪ {bnames.get(bid, f'Basket {bid}')}")
            basket_media_ids.add(mid)

    # ── 2ter. VOD à la demande (Feature B) : médias pré-cachés des configs VOD ──────
    # Affectation du player → bypass du filtre tag (comme les paniers audio). Les médias
    # sont pré-distribués pour lecture instantanée. Cible EXPLICITE (cms_vod_config_players)
    # ou par SITE (target_mode='site', migr 0096) — résolution en source unique, sinon un
    # ciblage site serait accepté côté CMS et jamais pré-caché ici (bug type 2026-07-18).
    vod_ids = await vod_config_ids_for_player(db, id_org, id_player)
    if vod_ids:
        vnames = dict((await db.execute(select(CmsVodConfig.id_vod, CmsVodConfig.vod_name)
            .where(CmsVodConfig.id_vod.in_(vod_ids), CmsVodConfig.id_org == id_org))).all())
        for vid, mid in (await db.execute(select(CmsVodConfigMedia.id_vod, CmsVodConfigMedia.id_media)
            .where(CmsVodConfigMedia.id_vod.in_(vnames.keys())))).all():
            media_refs.setdefault(mid, set()).add(f"▶ {vnames.get(vid, f'VOD {vid}')}")
            vod_media_ids.add(mid)

    # ── 3. Playlists → items → médias (ref = nom de la playlist conteneur) ─────────
    if playlist_ids:
        # Sous-playlists (rotation) : les médias des enfants font partie de l'attendu.
        from app.services.playlist_rotation import child_playlist_ids
        for childs in (await child_playlist_ids(db, playlist_ids)).values():
            playlist_ids |= childs
        names = dict((await db.execute(
            select(CmsPlaylist.id_playlist, CmsPlaylist.playlist_name)
            .where(CmsPlaylist.id_playlist.in_(playlist_ids)))).all())
        items = (await db.execute(select(
            CmsPlaylistItem.id_item, CmsPlaylistItem.id_playlist, CmsPlaylistItem.id_media)
            .where(
                CmsPlaylistItem.id_playlist.in_(playlist_ids),
                CmsPlaylistItem.id_media.isnot(None),
            ))).all()
        for iid, pid, mid in items:
            media_refs.setdefault(mid, set()).add(names.get(pid, f"Playlist {pid}"))
            visual_candidates.append((mid, iid))

    if not media_refs:
        return []

    # Filtre tag de réception : un média visuel tagué pour un AUTRE player (ex. mur left/right)
    # n'est jamais envoyé/caché → l'exclure de l'attendu (sinon faux « manquant »). None=pas de filtre.
    allowed_visual = await _allowed_visual_media(db, id_player, visual_candidates)

    # ── 4. Médias cachables (vidéo/image/audio) non supprimés/bloqués ─────────────
    medias = (await db.execute(select(CmsMedia).where(
        CmsMedia.id_media.in_(media_refs.keys()),
        CmsMedia.media_type.in_(_CACHEABLE),
        CmsMedia.is_deleted == False,  # noqa: E712
        CmsMedia.is_blocked == False,  # noqa: E712
    ))).scalars().all()

    # L'audio n'est cachable que via les paniers (le renderer saute un audio en playlist) →
    # on n'inclut un média audio que s'il provient d'un panier (évite les faux « manquant »).
    # Le visuel est gardé seulement s'il passe le filtre tag du player (allowed_visual).
    out = [{
        "id_media": m.id_media,
        "media_name": m.media_name,
        "media_type": m.media_type,
        "refs": sorted(media_refs.get(m.id_media, set())),
    } for m in medias
        if m.id_media in basket_media_ids
        or m.id_media in vod_media_ids  # VOD = affectation explicite, pas de filtre tag
        or (m.media_type in _VISUAL
            and (allowed_visual is None or m.id_media in allowed_visual))]
    out.sort(key=lambda x: (x["media_name"] or "").lower())
    return out
