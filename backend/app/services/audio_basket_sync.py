"""Qui écoute ce panier ? — résolution des écrans concernés par un panier audio (§XIX).

Sert deux besoins nés de l'audit du 2026-07-29 :
  · **A6** — pousser `force_sync` quand le contenu d'un panier change. Un panier n'a PAS de
    brouillon : toute modification est immédiatement autoritaire côté serveur, mais les
    players gardent l'ancienne config jusqu'à leur prochaine resynchro. Le moment où l'on
    pousse est donc la mutation elle-même — c'est l'équivalent, pour ce module, du geste
    « Publier » d'une playlist (décision d'Ed : « on pousse si publier comme pour les
    playlists »).
  · **A5** — dire à l'utilisateur ce qu'une suppression de panier emporterait, en NOMMANT
    les programmes et les événements concernés.

🔑 Source UNIQUE : la résolution passe par `targeting.players_for_targets`, jamais par un
matcher recopié. C'est la leçon de D-b — sur ce genre de module, le risque n'est pas la
règle mais la COUVERTURE (un consommateur oublié diffuse ou pré-charge autre chose que ce
que le reste du produit croit).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audio_basket import CmsPlayerBasketConfig
from app.models.event import CmsEvent
from app.models.schedule import CmsSchedule, CmsScheduleBasket, CmsScheduleTarget
from app.services.targeting import Target, event_config_targets, players_for_targets


async def schedules_using(db: AsyncSession, id_org: int, id_basket: int) -> list[CmsSchedule]:
    """Programmes audio (vivants) qui diffusent ce panier."""
    return list((await db.execute(
        select(CmsSchedule)
        .join(CmsScheduleBasket, CmsScheduleBasket.id_schedule == CmsSchedule.id_schedule)
        .where(
            CmsScheduleBasket.id_basket == id_basket,
            CmsSchedule.id_org == id_org,
            CmsSchedule.is_deleted == False,  # noqa: E712
        )
    )).scalars().all())


async def events_using(db: AsyncSession, id_org: int, id_basket: int) -> list[CmsEvent]:
    """Événements audio (non terminés) qui activent ce panier."""
    return list((await db.execute(
        select(CmsEvent).where(
            CmsEvent.id_basket == id_basket,
            CmsEvent.id_org == id_org,
            CmsEvent.status.notin_(("ended", "cancelled")),
        )
    )).scalars().all())


async def players_for_basket(db: AsyncSession, id_org: int, id_basket: int) -> list[int]:
    """Écrans susceptibles de jouer ce panier — union des 3 étages de la résolution.

    On ne cherche pas à savoir qui le joue *à cet instant* (fenêtres horaires, budget de
    mix) : `force_sync` doit atteindre tout écran dont la configuration PEUT changer, y
    compris celui pour qui le panier vient seulement de devenir jouable. Trop large est
    sans effet de bord (une resynchro) ; trop étroit laisse un écran sur l'ancienne config.
    """
    players: set[int] = set()

    # 1. Programmes audio qui portent le panier → leurs cibles.
    scheds = await schedules_using(db, id_org, id_basket)
    if scheds:
        targets = (await db.execute(
            select(CmsScheduleTarget).where(
                CmsScheduleTarget.id_schedule.in_([s.id_schedule for s in scheds])
            )
        )).scalars().all()
        players |= await players_for_targets(
            db, id_org,
            [Target(target_type=t.target_type, target_id=t.target_id) for t in targets],
        )

    # 2. Événements audio qui activent le panier → leur target_config (les deux formes,
    #    hétérogène comprise, via le normaliseur partagé).
    for ev in await events_using(db, id_org, id_basket):
        players |= await players_for_targets(
            db, id_org, event_config_targets(ev.target_config)
        )

    # 3. Écrans portant un override opérateur sur ce panier (Store Control Panel §19.3).
    players |= set((await db.execute(
        select(CmsPlayerBasketConfig.id_player).where(
            CmsPlayerBasketConfig.id_basket == id_basket
        )
    )).scalars().all())

    return sorted(players)
