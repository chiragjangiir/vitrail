"""Look-ahead / prefetch programmé (offline-first).

Pour un player, énumère le contenu cachable programmé sur les prochaines semaines et
l'annote de sa **date de diffusion la plus proche** (`play_at`) → priorité de
téléchargement anticipé + éviction disque-aware côté player (le plus proche d'abord, le
passé / le lointain évincé en premier sous pression).

Réutilise `player_inventory.expected_media` comme ENSEMBLE autoritaire de médias (déjà
tag-filtré, paniers audio + events + gouvernance inclus). On y ajoute uniquement la
dimension temporelle via les schedules content (`next_start_at`). Médias non datables
(events, paniers, ou schedule actif maintenant) → `play_at = now` (priorité max, sûr).

La résolution de variante (rendition) + l'URL signée se font côté `ws.py` au moment de
construire le payload (là où vivent `_resolve_variant_key` et `get_signed_url`).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.player import CmsPlayer
from app.models.playlist import CmsPlaylistItem
from app.models.schedule import CmsSchedule, CmsScheduleRule, CmsScheduleTarget
from app.services.player_inventory import _group_ids, expected_media
from app.services.scheduling import next_start_at, time_rule_from_schedule
from app.services.targeting import player_site_group_ids, player_site_id

# Horizon de prefetch par défaut (4 semaines). Au-delà, on ne télécharge pas à l'avance.
PREFETCH_HORIZON_DAYS = 28


async def _content_schedule_ids(
    db: AsyncSession, id_org: int, id_player: int, group_ids: set[int]
) -> set[int]:
    """Schedules ciblant le player : directs + groupes + groupes de sites + gouvernance
    (même logique que l'inventaire). Le filtrage content/actif/non-supprimé se fait par
    l'appelant."""
    sched_ids: set[int] = set()
    rows = (await db.execute(select(CmsScheduleTarget.id_schedule).where(
        CmsScheduleTarget.target_type == "player", CmsScheduleTarget.target_id == id_player))).all()
    sched_ids.update(r[0] for r in rows)
    if group_ids:
        rows = (await db.execute(select(CmsScheduleTarget.id_schedule).where(
            CmsScheduleTarget.target_type == "player_group",
            CmsScheduleTarget.target_id.in_(group_ids)))).all()
        sched_ids.update(r[0] for r in rows)
    id_site = await player_site_id(db, id_player)
    if id_site is not None:
        rows = (await db.execute(select(CmsScheduleTarget.id_schedule).where(
            CmsScheduleTarget.target_type == "site",
            CmsScheduleTarget.target_id == id_site))).all()
        sched_ids.update(r[0] for r in rows)
    site_group_ids = await player_site_group_ids(db, id_player)
    if site_group_ids:
        rows = (await db.execute(select(CmsScheduleTarget.id_schedule).where(
            CmsScheduleTarget.target_type == "site_group",
            CmsScheduleTarget.target_id.in_(site_group_ids)))).all()
        sched_ids.update(r[0] for r in rows)
    try:  # Gouvernance §XVIII — ne doit jamais casser le prefetch.
        from app.api.v1.endpoints.governance import _anchor_nodes_for_player, _relevant_node_ids
        from app.services.governance_scope import scoped_schedule_ids
        anchors = await _anchor_nodes_for_player(db, id_org, id_player)
        relevant = await _relevant_node_ids(db, id_org, anchors) if anchors else set()
        if relevant:
            rows = (await db.execute(select(CmsSchedule.id_schedule).where(
                CmsSchedule.id_governance_node.in_(relevant)))).all()
            # D-b : les cibles du programme FILTRENT le périmètre du nœud. Ce chemin ne
            # passe pas par `gather_layers` : sans ce filtre, on pré-téléchargerait du
            # contenu que cet écran ne jouera jamais.
            sched_ids.update(await scoped_schedule_ids(db, id_player, {r[0] for r in rows}))
    except Exception:  # noqa: BLE001
        pass
    return sched_ids


async def upcoming_media(
    db: AsyncSession, id_player: int, now: datetime, horizon_days: int = PREFETCH_HORIZON_DAYS
) -> dict[int, datetime]:
    """`{id_media: play_at}` pour tout le contenu programmé futur (<= horizon) du player.

    L'ensemble des clés = exactement `expected_media` (cohérence inventaire ↔ prefetch).
    `play_at` = date de diffusion la plus proche via les schedules content datés ; défaut
    `now` pour le reste (events / paniers / schedule actif / non datable).
    """
    expected = await expected_media(db, id_player)
    if not expected:
        return {}
    wanted = {m["id_media"] for m in expected}

    player = (await db.execute(
        select(CmsPlayer).where(CmsPlayer.id_player == id_player)
    )).scalar_one_or_none()
    if not player:
        return {}
    group_ids = await _group_ids(db, id_player)
    sched_ids = await _content_schedule_ids(db, player.id_org, id_player, group_ids)

    play_at: dict[int, datetime] = {}
    if sched_ids:
        scheds = (await db.execute(select(CmsSchedule).where(
            CmsSchedule.id_schedule.in_(sched_ids),
            CmsSchedule.schedule_kind == "content",
            CmsSchedule.is_active == True,    # noqa: E712
            CmsSchedule.is_deleted == False,  # noqa: E712
        ))).scalars().all()
        if scheds:
            rules_by_sched: dict[int, list] = {}
            for r in (await db.execute(select(CmsScheduleRule).where(
                CmsScheduleRule.id_schedule.in_([s.id_schedule for s in scheds])
            ))).scalars().all():
                rules_by_sched.setdefault(r.id_schedule, []).append(r)

            # Date de diffusion la plus proche par PLAYLIST (min sur les schedules l'utilisant).
            pl_play_at: dict[int, datetime] = {}
            for s in scheds:
                if not s.id_playlist:
                    continue
                trs = [time_rule_from_schedule(r) for r in rules_by_sched.get(s.id_schedule, [])]
                ns = next_start_at(trs, s.valid_from, s.valid_until, now, horizon_days)
                if ns is None:
                    continue  # ne joue pas dans l'horizon → pas de prefetch anticipé
                cur = pl_play_at.get(s.id_playlist)
                pl_play_at[s.id_playlist] = ns if cur is None else min(cur, ns)

            if pl_play_at:
                # Sous-playlists (rotation) : les médias des enfants héritent de la
                # date de diffusion du parent qui les imbrique.
                from app.services.playlist_rotation import child_playlist_ids
                for parent, childs in (await child_playlist_ids(db, set(pl_play_at.keys()))).items():
                    for c in childs:
                        cur = pl_play_at.get(c)
                        pl_play_at[c] = pl_play_at[parent] if cur is None else min(cur, pl_play_at[parent])
                for pid, mid in (await db.execute(select(
                    CmsPlaylistItem.id_playlist, CmsPlaylistItem.id_media
                ).where(CmsPlaylistItem.id_playlist.in_(pl_play_at.keys())))).all():
                    if mid is None or mid not in wanted:
                        continue
                    pa = pl_play_at[pid]
                    cur = play_at.get(mid)
                    play_at[mid] = pa if cur is None else min(cur, pa)

    # Les médias non datés (events/paniers/actif) → now (priorité max, téléchargés d'abord).
    return {mid: play_at.get(mid, now) for mid in wanted}
