"""Analyse d'impact + cascade de suppression d'un média (§ retour terrain 2026-06-13, Ed).

Avant de supprimer un contenu, on calcule OÙ il est utilisé et son état de DIFFUSION
(en cours / futur / passé), pour afficher une confirmation explicite :

  - **Playlists** qui contiennent le média (chaîne visuelle).
  - **Programmes** (schedules `content`) qui diffusent ces playlists.
  - **Événements** (overrides §XX) qui pointent le média directement (mono-média) ou via
    une playlist impactée.
  - **Paniers audio** qui contiennent le média (informatif — pas de cascade auto en v1).

À la VALIDATION (`cascade_delete`) on applique la cascade décrite par Ed :
  - on retire le média de toutes les playlists (suppression des `cms_playlist_items`) ;
  - une playlist qui n'avait QUE ce média (devenue vide) est supprimée (soft-delete) ;
  - un programme dont la playlist vient d'être supprimée est supprimé (soft-delete) ;
  - un événement mono-média (ou pointant une playlist supprimée) est annulé (`cancelled`) ;
  - le média est retiré des paniers audio (`cms_audio_basket_items`) ; un panier vidé N'est
    PAS supprimé (conteneur géré par l'utilisateur, contrairement à une playlist) ;
  - le média + ses renditions sont supprimés (le média en soft-delete, les objets MinIO
    par le worker, géré par l'appelant).

Comme le média est en **soft-delete** (la ligne reste), aucune contrainte FK n'est violée :
la cascade est une question de PROPRETÉ (ne pas laisser de playlists/programmes vides),
pas d'intégrité.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audio_basket import CmsAudioBasket, CmsAudioBasketItem
from app.models.event import CmsEvent
from app.models.media import CmsMedia
from app.models.playlist import CmsPlaylist, CmsPlaylistItem
from app.models.schedule import CmsSchedule, CmsScheduleRule
from app.models.vod import CmsVodConfig, CmsVodConfigMedia
from app.services import scheduling


# ── Classification de l'état de diffusion d'un programme ──────────────────────────

def _classify_schedule(rules: list[CmsScheduleRule], valid_from, valid_until,
                       is_active: bool, now) -> str:
    """active (diffuse maintenant) | scheduled (futur) | expired (passé) | inactive."""
    if not is_active:
        return "inactive"
    trules = [scheduling.time_rule_from_schedule(r) for r in rules]
    if not trules:
        return "inactive"
    if any(scheduling.schedule_active_at(r, valid_from, valid_until, now) for r in trules):
        return "active"
    if scheduling.next_start_at(trules, valid_from, valid_until, now) is not None:
        return "scheduled"
    return "expired"


def _agg_broadcast(states: list[str]) -> str:
    """Agrège plusieurs états de diffusion en un seul (le plus « chaud » l'emporte)."""
    for level in ("active", "scheduled", "expired", "inactive"):
        if level in states:
            return level
    return "none"


async def _schedule_states(
    db: AsyncSession, schedule_ids: list[int], now
) -> dict[int, str]:
    """État de diffusion par id_schedule (charge les règles en un seul aller-retour)."""
    if not schedule_ids:
        return {}
    scheds = (await db.execute(
        select(CmsSchedule).where(CmsSchedule.id_schedule.in_(schedule_ids))
    )).scalars().all()
    rules_by_sched: dict[int, list[CmsScheduleRule]] = {s.id_schedule: [] for s in scheds}
    for r in (await db.execute(
        select(CmsScheduleRule).where(CmsScheduleRule.id_schedule.in_(schedule_ids))
    )).scalars().all():
        rules_by_sched.setdefault(r.id_schedule, []).append(r)
    return {
        s.id_schedule: _classify_schedule(
            rules_by_sched.get(s.id_schedule, []), s.valid_from, s.valid_until, s.is_active, now
        )
        for s in scheds
    }


# ── Analyse (lecture seule) ───────────────────────────────────────────────────────

def public_impact(impact: dict[str, Any]) -> dict[str, Any]:
    """Retire les clés internes (`_…`) avant exposition au front."""
    return {k: v for k, v in impact.items() if not k.startswith("_")}


def empty_impact(media_name: str = "") -> dict[str, Any]:
    """Arbre d'impact vide (ex. feed sans média pointeur) — même forme que `analyze`."""
    return {
        "media": {"id_media": None, "media_name": media_name, "media_type": None},
        "playlists": [],
        "schedules": [],
        "events": [],
        "baskets": [],
        "vod_configs": [],
        "summary": {
            "playlists_total": 0,
            "playlists_deleted": 0,
            "schedules_deleted": 0,
            "events_cancelled": 0,
            "baskets_affected": 0,
            "vod_configs_affected": 0,
            "has_live_broadcast": False,
        },
    }


async def analyze(db: AsyncSession, media: CmsMedia) -> dict[str, Any]:
    """Calcule l'arbre d'impact de la suppression de `media` (aucune écriture)."""
    # Instant SERVEUR volontairement (P2.2) : la question porte sur un MÉDIA, dont les
    # écrans peuvent s'étaler sur plusieurs fuseaux — il n'existe pas d'heure locale
    # unique ici, et « diffuse en ce moment » n'a de sens qu'approché.
    now = scheduling.local_now()
    mid = media.id_media

    # 1. Playlists contenant le média + nombre d'items concernés / total.
    using_counts = dict((await db.execute(
        select(CmsPlaylistItem.id_playlist, func.count())
        .where(CmsPlaylistItem.id_media == mid)
        .group_by(CmsPlaylistItem.id_playlist)
    )).all())
    pl_ids = list(using_counts.keys())

    total_counts: dict[int, int] = {}
    playlists_by_id: dict[int, CmsPlaylist] = {}
    if pl_ids:
        total_counts = dict((await db.execute(
            select(CmsPlaylistItem.id_playlist, func.count())
            .where(CmsPlaylistItem.id_playlist.in_(pl_ids))
            .group_by(CmsPlaylistItem.id_playlist)
        )).all())
        playlists_by_id = {p.id_playlist: p for p in (await db.execute(
            select(CmsPlaylist).where(
                CmsPlaylist.id_playlist.in_(pl_ids),
                CmsPlaylist.is_deleted == False,  # noqa: E712
            )
        )).scalars().all()}

    # Playlists vivantes seulement (une playlist déjà supprimée n'est pas un impact).
    live_pl_ids = [pid for pid in pl_ids if pid in playlists_by_id]
    deleted_pl_ids = [
        pid for pid in live_pl_ids
        if (total_counts.get(pid, 0) - using_counts.get(pid, 0)) <= 0
    ]

    # 2. Programmes (content) qui diffusent ces playlists.
    sched_rows = []
    if live_pl_ids:
        sched_rows = (await db.execute(
            select(CmsSchedule).where(
                CmsSchedule.id_playlist.in_(live_pl_ids),
                CmsSchedule.schedule_kind == "content",
                CmsSchedule.is_deleted == False,  # noqa: E712
            )
        )).scalars().all()
    sched_states = await _schedule_states(db, [s.id_schedule for s in sched_rows], now)
    # État de diffusion agrégé par playlist (depuis ses programmes).
    pl_sched_states: dict[int, list[str]] = {pid: [] for pid in live_pl_ids}
    schedules_out = []
    for s in sched_rows:
        st = sched_states.get(s.id_schedule, "inactive")
        pl_sched_states.setdefault(s.id_playlist, []).append(st)
        will_delete = s.id_playlist in deleted_pl_ids
        if will_delete:
            schedules_out.append({
                "id_schedule": s.id_schedule,
                "schedule_name": s.schedule_name,
                "broadcast": st,
                "will_be_deleted": True,
            })

    # 3. Événements : mono-média (id_media) OU via une playlist impactée.
    ev_cond = CmsEvent.id_media == mid
    if live_pl_ids:
        ev_cond = ev_cond | CmsEvent.id_playlist.in_(live_pl_ids)
    ev_rows = (await db.execute(
        select(CmsEvent).where(ev_cond, CmsEvent.status != "cancelled")
    )).scalars().all()
    events_out = []
    for e in ev_rows:
        reason = "media" if e.id_media == mid else "playlist"
        # Annulé si mono-média de ce média, ou si sa playlist va être supprimée.
        will_cancel = (reason == "media") or (e.id_playlist in deleted_pl_ids)
        events_out.append({
            "id_event": e.id_event,
            "event_name": e.event_name,
            "status": e.status,
            "reason": reason,
            "will_be_cancelled": will_cancel,
        })
        if e.id_playlist in live_pl_ids:
            pl_sched_states.setdefault(e.id_playlist, []).append(
                "active" if e.status == "active" else "scheduled"
            )

    # 4. Paniers audio (informatif).
    basket_counts = dict((await db.execute(
        select(CmsAudioBasketItem.id_basket, func.count())
        .where(CmsAudioBasketItem.id_media == mid)
        .group_by(CmsAudioBasketItem.id_basket)
    )).all())
    baskets_out = []
    if basket_counts:
        names = dict((await db.execute(
            select(CmsAudioBasket.id_basket, CmsAudioBasket.basket_name)
            .where(CmsAudioBasket.id_basket.in_(list(basket_counts.keys())))
        )).all())
        baskets_out = [
            {"id_basket": bid, "basket_name": names.get(bid, f"#{bid}"),
             "items_using": cnt}
            for bid, cnt in basket_counts.items() if bid in names
        ]

    # 5. Configs VOD (informatif) — elles pré-cachent le média sur des écrans et le
    # rendent déclenchable en plein écran. 🔴 Elles étaient TOTALEMENT absentes de cette
    # analyse (audit du 2026-07-29) : on supprimait un média sans jamais dire qu'il était
    # pré-chargé sur des écrans, et sa référence restait dans la config.
    vod_rows = (await db.execute(
        select(CmsVodConfig.id_vod, CmsVodConfig.vod_name)
        .join(CmsVodConfigMedia, CmsVodConfigMedia.id_vod == CmsVodConfig.id_vod)
        .where(CmsVodConfigMedia.id_media == mid)
        .distinct()
    )).all()
    vod_out = [{"id_vod": vid, "vod_name": vname} for vid, vname in vod_rows]

    # Playlists (avec état de diffusion agrégé).
    playlists_out = []
    for pid in live_pl_ids:
        playlists_out.append({
            "id_playlist": pid,
            "playlist_name": playlists_by_id[pid].playlist_name,
            "items_using": using_counts.get(pid, 0),
            "remaining_items": max(0, total_counts.get(pid, 0) - using_counts.get(pid, 0)),
            "will_be_deleted": pid in deleted_pl_ids,
            "broadcast": _agg_broadcast(pl_sched_states.get(pid, [])),
        })

    all_states = (
        [p["broadcast"] for p in playlists_out]
        + [s["broadcast"] for s in schedules_out]
    )
    return {
        "media": {
            "id_media": mid,
            "media_name": media.media_name,
            "media_type": media.media_type,
        },
        "playlists": playlists_out,
        "schedules": schedules_out,
        "events": events_out,
        "baskets": baskets_out,
        "vod_configs": vod_out,
        "summary": {
            "playlists_total": len(playlists_out),
            "playlists_deleted": len(deleted_pl_ids),
            "schedules_deleted": len(schedules_out),
            "events_cancelled": sum(1 for e in events_out if e["will_be_cancelled"]),
            "baskets_affected": len(baskets_out),
            "vod_configs_affected": len(vod_out),
            "has_live_broadcast": "active" in all_states,
        },
        # IDs internes (réutilisés par la cascade pour éviter un 2e calcul).
        "_deleted_playlist_ids": deleted_pl_ids,
        "_deleted_schedule_ids": [s["id_schedule"] for s in schedules_out],
        "_cancelled_event_ids": [e["id_event"] for e in events_out if e["will_be_cancelled"]],
    }


# ── Cascade (écritures) ───────────────────────────────────────────────────────────

async def cascade_delete(db: AsyncSession, media: CmsMedia) -> dict[str, Any]:
    """Applique la cascade (playlists/programmes/événements). NE soft-delete PAS le média
    ni ses renditions (l'appelant s'en charge avec la purge MinIO) et NE commit PAS
    (l'appelant commit puis déclenche le force_sync). Renvoie l'impact calculé."""
    impact = await analyze(db, media)
    mid = media.id_media

    # Retirer le média de TOUTES les playlists (items publiés).
    await db.execute(delete(CmsPlaylistItem).where(CmsPlaylistItem.id_media == mid))

    # Supprimer les playlists devenues vides.
    if impact["_deleted_playlist_ids"]:
        await db.execute(
            update(CmsPlaylist)
            .where(CmsPlaylist.id_playlist.in_(impact["_deleted_playlist_ids"]))
            .values(is_deleted=True)
        )
    # Supprimer les programmes dont la playlist a disparu.
    if impact["_deleted_schedule_ids"]:
        await db.execute(
            update(CmsSchedule)
            .where(CmsSchedule.id_schedule.in_(impact["_deleted_schedule_ids"]))
            .values(is_deleted=True)
        )
    # Annuler les événements concernés.
    if impact["_cancelled_event_ids"]:
        await db.execute(
            update(CmsEvent)
            .where(CmsEvent.id_event.in_(impact["_cancelled_event_ids"]))
            .values(status="cancelled")
        )
    # Retirer le média des paniers audio (items utilisant ce média). On NE supprime PAS un
    # panier devenu vide : contrairement à une playlist, un panier est un conteneur géré par
    # l'utilisateur (il peut vouloir y ré-ajouter des pistes). Le force_sync de l'appelant
    # fera dropper l'item retiré côté players audio.
    await db.execute(delete(CmsAudioBasketItem).where(CmsAudioBasketItem.id_media == mid))

    # Retirer le média des configs VOD — même raisonnement que les paniers : on retire
    # l'item, jamais la config. 🔴 Cette purge n'existait pas (audit 2026-07-29) : la
    # référence survivait à la suppression du média, si bien que la config listait un
    # contenu que le pré-cache écarte (il filtre `is_deleted`) et que rien ne jouerait
    # jamais — un déclenchement sur ce média répondait « média introuvable ou bloqué ».
    await db.execute(delete(CmsVodConfigMedia).where(CmsVodConfigMedia.id_media == mid))
    return impact
