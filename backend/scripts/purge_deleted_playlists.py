"""Purge les playlists restées en suppression LOGIQUE (héritage d'avant « quand on efface,
on efface »).

Décision d'Ed du 2026-07-29, dans le prolongement de celle prise pour les templates la
veille. Mesuré sur la prod ce jour-là : **22 playlists fantômes pour 20 actives** — ni
visibles, ni listées, ni restaurables.

    docker compose exec -T backend python scripts/purge_deleted_playlists.py          # inventaire
    docker compose exec -T backend python scripts/purge_deleted_playlists.py --apply  # purge

⚠️ SANS `--apply` il n'écrit RIEN.

Une playlist est ÉPARGNÉE et signalée si quoi que ce soit de VIVANT la référence encore.
Les six clés étrangères qui pointent `cms_playlists` sont toutes vérifiées, parce qu'en
oublier une ne donnerait pas une erreur franche mais une contrainte violée au milieu de la
purge — ou pire, un objet qui pointe dans le vide :

  · `cms_schedules.id_playlist`            — un programme la diffuse
  · `cms_events.id_playlist`               — un événement la déclenche
  · `cms_event_ai_suggestions.id_playlist` — une suggestion IA la propose
  · `cms_players.current_playlist_id`      — un écran la joue en ce moment
  · `cms_playlist_items.id_child_playlist` — un parent l'imbrique en rotation
  · `cms_playlist_items.id_playlist`       — ses PROPRES items, eux, sont supprimés avec elle

🔑 Un fantôme référencé par un autre FANTÔME ne bloque pas : le cas existe en prod (la
playlist 29, supprimée, imbrique la 28, supprimée aussi). Ne compter que les références
VIVANTES, sinon deux fantômes se protégeraient mutuellement pour toujours.

⚠️ MAIS **une clé étrangère, elle, ignore `is_deleted`** — leçon prise en exécutant ce
script sur la prod le 2026-07-29 : il annonçait « 22 purgeables, 0 épargnée » et la
transaction a échoué sur `cms_schedules_id_playlist_fkey`, **15 programmes eux-mêmes
supprimés** pointant encore ces playlists. Ne pas confondre « plus personne ne s'en sert »
(règle métier) et « plus rien ne pointe dessus » (règle de base). Les références portées
par des lignes SUPPRIMÉES sont donc DÉTACHÉES (mises à NULL) avant la purge : ces lignes ne
sont plus lues par personne, et les purger elles-mêmes serait une autre décision — celle
du menu Programmes, qu'Ed n'a pas encore tranchée.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, "/app")

from sqlalchemy import delete, select, update

from app.db.session import WorkerSessionLocal
from app.models.event import CmsEvent, CmsEventAiSuggestion
from app.models.player import CmsPlayer
from app.models.playlist import CmsPlaylist, CmsPlaylistItem
from app.models.schedule import CmsSchedule

APPLY = "--apply" in sys.argv


async def _dangling_refs(db, ids: list[int]) -> dict[str, int]:
    """Références portées par des lignes elles-mêmes SUPPRIMÉES (à détacher avant purge)."""
    out: dict[str, int] = {}
    n = (await db.execute(
        select(CmsSchedule.id_schedule).where(
            CmsSchedule.id_playlist.in_(ids), CmsSchedule.is_deleted.is_(True))
    )).scalars().all()
    if n:
        out["programmes supprimés"] = len(n)
    return out


async def _live_refs(db, pid: int) -> list[str]:
    """Références VIVANTES vers la playlist `pid` (vide = purgeable)."""
    refs: list[str] = []

    for name in (await db.execute(
        select(CmsPlaylist.playlist_name)
        .join(CmsPlaylistItem, CmsPlaylistItem.id_playlist == CmsPlaylist.id_playlist)
        .where(CmsPlaylistItem.id_child_playlist == pid,
               CmsPlaylist.is_deleted.is_(False))
    )).scalars().all():
        refs.append(f"sous-playlist de « {name} »")

    for name in (await db.execute(
        select(CmsSchedule.schedule_name).where(
            CmsSchedule.id_playlist == pid, CmsSchedule.is_deleted.is_(False))
    )).scalars().all():
        refs.append(f"programme « {name} »")

    for name in (await db.execute(
        select(CmsEvent.event_name).where(CmsEvent.id_playlist == pid)
    )).scalars().all():
        refs.append(f"événement « {name} »")

    for name in (await db.execute(
        select(CmsPlayer.player_name).where(CmsPlayer.current_playlist_id == pid)
    )).scalars().all():
        refs.append(f"en cours de lecture sur « {name} »")

    n = (await db.execute(
        select(CmsEventAiSuggestion.id_suggestion)
        .where(CmsEventAiSuggestion.id_playlist == pid).limit(1)
    )).scalar_one_or_none()
    if n is not None:
        refs.append("suggestion IA d'événement")

    return refs


async def main() -> None:
    async with WorkerSessionLocal() as db:
        rows = list((await db.execute(
            select(CmsPlaylist).where(CmsPlaylist.is_deleted.is_(True))
            .order_by(CmsPlaylist.id_org, CmsPlaylist.id_playlist)
        )).scalars().all())
        if not rows:
            print("Aucune playlist en suppression logique — rien à faire.")
            return

        print(f"{len(rows)} playlist(s) en suppression logique :\n")
        purgeable, kept = [], []
        for p in rows:
            refs = await _live_refs(db, p.id_playlist)
            n_items = (await db.execute(
                select(CmsPlaylistItem.id_item).where(CmsPlaylistItem.id_playlist == p.id_playlist)
            )).scalars().all()
            flag = f"   ⚠️ RÉFÉRENCÉE : {', '.join(refs)}" if refs else ""
            print(f"  org {p.id_org} · #{p.id_playlist} « {p.playlist_name} » "
                  f"({len(n_items)} item(s), créée le {p.created_at:%Y-%m-%d}){flag}")
            (kept if refs else purgeable).append(p)

        print(f"\n  purgeables : {len(purgeable)}   épargnées (référencées) : {len(kept)}")

        ids = [p.id_playlist for p in purgeable]
        dangling = await _dangling_refs(db, ids) if ids else {}
        for label, n in dangling.items():
            print(f"  ⤷ {n} {label} pointent encore dessus : ils seront DÉTACHÉS "
                  f"(la clé étrangère, elle, ignore is_deleted)")

        if not APPLY:
            print("\nSimulation — relancer avec --apply pour purger.")
            return

        if ids:
            # Détacher d'abord les références portées par des lignes SUPPRIMÉES : elles ne
            # sont plus lues par personne, mais la contrainte, elle, bloque toujours.
            await db.execute(
                update(CmsSchedule).where(
                    CmsSchedule.id_playlist.in_(ids), CmsSchedule.is_deleted.is_(True)
                ).values(id_playlist=None)
            )
            # Les items de la playlist partent avec elle ; les RÈGLES d'item suivent en
            # cascade (`ON DELETE CASCADE` sur cms_playlist_item_rules.id_item).
            await db.execute(delete(CmsPlaylistItem).where(CmsPlaylistItem.id_playlist.in_(ids)))
            # Un item d'un AUTRE fantôme peut encore l'imbriquer : le retirer, sinon la clé
            # étrangère bloquerait la purge de la playlist enfant.
            await db.execute(delete(CmsPlaylistItem).where(CmsPlaylistItem.id_child_playlist.in_(ids)))
            await db.execute(delete(CmsPlaylist).where(CmsPlaylist.id_playlist.in_(ids)))
            await db.commit()
        print(f"\n{len(ids)} playlist(s) purgée(s) définitivement.")
        print("Le journal d'audit est CONSERVÉ : la ligne disparaît, la trace reste.")


asyncio.run(main())
