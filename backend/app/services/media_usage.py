"""Où un média est-il utilisé — et surtout : sur quels ÉCRANS diffuse-t-il ?

Demande d'Ed (audit du menu Média, 2026-07-28) : « quand on sélectionne ou survole un
média, il faudrait savoir dans quelle playlist, quel programme il est utilisé, et surtout
actif sur un ou des écrans ».

Ce service ne recalcule PAS ce qui existe : `media_deletion.analyze()` résout déjà les
playlists, les programmes et les événements qui portent le média, avec leur état de
diffusion (`active` / `future` / `past`). On lui ajoute la seule chose qui manquait — la
résolution des ÉCRANS — en passant par le service de ciblage canonique
(`targeting.players_for_targets`), jamais par une requête maison : c'est la leçon de D-b,
où deux chemins de résolution du parc avaient divergé.

⚠️ Un média peut atteindre un écran par deux voies : un PROGRAMME (via sa playlist) ou un
ÉVÉNEMENT. Les deux sont couvertes, et on dit par quoi — « actif sur 3 écrans » sans dire
d'où ça vient n'aide personne à corriger quoi que ce soit.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import CmsEvent
from app.models.media import CmsMedia
from app.models.organization import CmsSite
from app.models.player import CmsPlayer
from app.models.playlist import CmsPlaylistItem
from app.models.schedule import CmsSchedule, CmsScheduleTarget
from app.services import analytics, media_deletion
from app.services.targeting import Target, event_config_targets, players_for_targets


async def _targets_of_schedules(db: AsyncSession, ids: list[int]) -> list[Target]:
    if not ids:
        return []
    rows = (await db.execute(
        select(CmsScheduleTarget).where(CmsScheduleTarget.id_schedule.in_(ids))
    )).scalars().all()
    return [Target(t.target_type, t.target_id) for t in rows]


async def _targets_of_events(db: AsyncSession, ids: list[int]) -> list[Target]:
    """Les cibles d'un événement vivent dans le JSON `target_config`, pas dans une table
    de jointure comme celles des programmes — d'où ces deux chemins distincts.

    🔴 La version précédente lisait `cfg.get("target_id")` au SINGULIER alors qu'un
    événement stocke `target_ids` (liste) : toute cible non-org résolvait à ZÉRO écran,
    sans erreur — « où est utilisé » ignorait la voie événement (prouvé rouge le
    2026-07-30). Le normaliseur partagé lit désormais les deux formes, hétérogène comprise.
    """
    if not ids:
        return []
    rows = (await db.execute(
        select(CmsEvent.target_config).where(CmsEvent.id_event.in_(ids))
    )).scalars().all()
    out: list[Target] = []
    for cfg in rows:
        if not isinstance(cfg, dict):
            continue
        out.extend(event_config_targets(cfg))
    return out


async def usage(db: AsyncSession, media: CmsMedia, now=None) -> dict[str, Any]:
    """Playlists / programmes / événements portant le média + écrans réellement atteints."""
    impact = await media_deletion.analyze(db, media)

    # Programmes ACTIFS seulement : c'est « sur quels écrans ça passe EN CE MOMENT », pas
    # « quels écrans seraient concernés un jour ». Un programme futur ne diffuse rien.
    active_schedule_ids = [
        s["id_schedule"] for s in impact["schedules"] if s.get("broadcast") == "active"
    ]
    # `analyze` ne remonte que les programmes qui SERAIENT supprimés (playlist vidée) : on
    # complète avec tous ceux qui jouent une playlist portant le média, sinon un média
    # partagé avec d'autres contenus n'aurait jamais d'écran — le cas le plus courant.
    pl_ids = [p["id_playlist"] for p in impact["playlists"]]
    if pl_ids:
        rows = (await db.execute(
            select(CmsSchedule.id_schedule).where(
                CmsSchedule.id_playlist.in_(pl_ids),
                CmsSchedule.is_active.is_(True),
                CmsSchedule.is_deleted.is_(False),
            )
        )).scalars().all()
        active_schedule_ids = sorted({*active_schedule_ids, *rows})

    # Les NOMS des programmes viennent de la meme liste que les ecrans. `analyze()` ne
    # remonte que ceux qui SERAIENT SUPPRIMES par une suppression du media : s'en servir
    # pour l'affichage donnait « 8 ecrans via programme » au-dessus d'une liste de
    # programmes VIDE — mesure sur les donnees d'Ed juste apres le deploiement.
    schedules_out: list[dict[str, Any]] = []
    if active_schedule_ids:
        rows = (await db.execute(
            select(CmsSchedule.id_schedule, CmsSchedule.schedule_name)
            .where(CmsSchedule.id_schedule.in_(active_schedule_ids))
            .order_by(CmsSchedule.schedule_name)
        )).all()
        broadcast_by_id = {s["id_schedule"]: s.get("broadcast") for s in impact["schedules"]}
        schedules_out = [
            {"id_schedule": r.id_schedule, "schedule_name": r.schedule_name,
             "broadcast": broadcast_by_id.get(r.id_schedule, "active")}
            for r in rows
        ]

    active_event_ids = [
        e["id_event"] for e in impact["events"] if e.get("broadcast") in ("active", None)
    ]

    by_schedule = await players_for_targets(
        db, media.id_org, await _targets_of_schedules(db, active_schedule_ids))
    by_event = await players_for_targets(
        db, media.id_org, await _targets_of_events(db, active_event_ids))

    all_ids = by_schedule | by_event
    screens: list[dict[str, Any]] = []
    if all_ids:
        rows = (await db.execute(
            select(CmsPlayer.id_player, CmsPlayer.player_name, CmsPlayer.status,
                   CmsPlayer.last_seen_at, CmsSite.site_name)
            .join(CmsSite, CmsSite.id_site == CmsPlayer.id_site, isouter=True)
            .where(CmsPlayer.id_player.in_(all_ids), CmsPlayer.id_org == media.id_org)
            .order_by(CmsPlayer.player_name)
        )).all()
        now_dt = now or datetime.now(UTC)
        for r in rows:
            via = []
            if r.id_player in by_schedule:
                via.append("schedule")
            if r.id_player in by_event:
                via.append("event")
            screens.append({
                "id_player": r.id_player,
                "player_name": r.player_name,
                "site_name": r.site_name,
                # Statut EFFECTIF, comme le NOC et le Dashboard : un écran « online » dont
                # le battement est périmé est offline. Sinon la médiathèque annoncerait une
                # diffusion sur un écran qui ne répond plus.
                "status": analytics.effective_status(r.status, r.last_seen_at, now_dt),
                "via": via,
            })

    return {
        "media": impact["media"],
        "playlists": [
            {"id_playlist": p["id_playlist"], "playlist_name": p["playlist_name"],
             "items_using": p["items_using"], "broadcast": p["broadcast"]}
            for p in impact["playlists"]
        ],
        "schedules": schedules_out,
        "events": [
            {"id_event": e["id_event"], "event_name": e.get("event_name")}
            for e in impact["events"]
        ],
        "baskets": impact["baskets"],
        "screens": screens,
        "summary": {
            "playlists": len(impact["playlists"]),
            "schedules": len(schedules_out),
            "events": len(impact["events"]),
            "screens": len(screens),
            "is_live": any(p["broadcast"] == "active" for p in impact["playlists"]),
        },
    }


async def usage_summary(
    db: AsyncSession, id_org: int, id_media: list[int]
) -> dict[int, dict[str, int]]:
    """Résumé « combien de playlists / combien d'écrans » pour un LOT de médias.

    Pourquoi ce second chemin : Ed veut l'information affichée EN PERMANENCE sur chaque
    vignette, plus seulement au survol. Appeler `usage()` par média ferait une analyse de
    diffusion complète par ligne — une centaine sur une page de médiathèque. Ici on
    retourne le raisonnement : on résout les cibles UNE FOIS PAR PROGRAMME (il y en a
    quelques dizaines au plus), puis chaque média hérite de l'union des écrans de ses
    programmes. Coût : 2 requêtes + une résolution par programme actif, quel que soit le
    nombre de médias affichés.

    Le détail (NOMS des écrans, playlists, événements) reste servi par `usage()`, à la
    demande — c'est lui qu'on appelle au survol pour l'infobulle.
    """
    if not id_media:
        return {}

    # ① média → playlists qui le portent.
    rows = (await db.execute(
        select(CmsPlaylistItem.id_media, CmsPlaylistItem.id_playlist)
        .where(CmsPlaylistItem.id_media.in_(id_media))
    )).all()
    playlists_by_media: dict[int, set[int]] = {}
    for mid, pid in rows:
        playlists_by_media.setdefault(mid, set()).add(pid)

    all_playlists = {pid for pids in playlists_by_media.values() for pid in pids}
    schedules_by_playlist: dict[int, set[int]] = {}
    if all_playlists:
        srows = (await db.execute(
            select(CmsSchedule.id_playlist, CmsSchedule.id_schedule).where(
                CmsSchedule.id_playlist.in_(all_playlists),
                CmsSchedule.id_org == id_org,
                CmsSchedule.is_active.is_(True),
                CmsSchedule.is_deleted.is_(False),
            )
        )).all()
        for pid, sid in srows:
            schedules_by_playlist.setdefault(pid, set()).add(sid)

    # ② programme → écrans, résolu UNE SEULE FOIS par programme (le point coûteux).
    all_schedules = {sid for sids in schedules_by_playlist.values() for sid in sids}
    players_by_schedule: dict[int, set[int]] = {}
    for sid in all_schedules:
        players_by_schedule[sid] = await players_for_targets(
            db, id_org, await _targets_of_schedules(db, [sid]))

    out: dict[int, dict[str, int]] = {}
    for mid in id_media:
        pids = playlists_by_media.get(mid, set())
        screens: set[int] = set()
        for pid in pids:
            for sid in schedules_by_playlist.get(pid, set()):
                screens |= players_by_schedule.get(sid, set())
        out[mid] = {"playlists": len(pids), "screens": len(screens)}
    return out
