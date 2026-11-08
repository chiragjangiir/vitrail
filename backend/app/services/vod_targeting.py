"""Résolution de la cible d'une config VOD — SOURCE UNIQUE (migr 0096).

Une config VOD cible soit une liste FIGÉE de players (`target_mode='players'`, historique),
soit **tous les players d'un site** (`target_mode='site'`, dynamique : un player ajouté au
site plus tard hérite automatiquement du pré-cache et des triggers).

⚠️ Deux directions sont nécessaires, et les DEUX doivent vivre ici :

1. **config-centrique** — `vod_player_ids(cfg)` : « quels players cette config vise ? »
   → détail/affichage, force_sync, dispatch `play_now`.
2. **player-centrique** — `vod_config_ids_for_player(id_player)` : « quelles configs visent
   ce player ? » → pré-cache (`player_inventory`), le chemin qui décide ce qui est
   RÉELLEMENT distribué au device.

L'audit du 2026-07-18 a montré qu'une cible `site` gérée uniquement côté config-centrique
est **acceptée, comptée à l'aperçu, et jamais diffusée** : le chemin player-centrique ne la
connaît pas, et rien n'échoue. Toute évolution du ciblage VOD doit donc toucher CE fichier,
jamais une requête ad-hoc recopiée chez l'appelant.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vod import CmsVodConfig, CmsVodConfigMedia, CmsVodConfigPlayer
from app.services.targeting import Target, player_site_id, players_for_target


async def vod_player_ids(db: AsyncSession, cfg: CmsVodConfig) -> set[int]:
    """Players visés par cette config (config-centrique).

    Mode 'site' → délègue à `players_for_target` (même tuyau que campagnes/schedules/OTA :
    pas de clone de la résolution de site). Mode 'players' → la liste explicite.
    """
    if cfg.target_mode == "site":
        if cfg.id_site is None:  # verrouillé par le CHECK 0096 — ceinture et bretelles
            return set()
        return await players_for_target(
            db, cfg.id_org, Target(target_type="site", target_id=cfg.id_site)
        )
    rows = (await db.execute(
        select(CmsVodConfigPlayer.id_player).where(CmsVodConfigPlayer.id_vod == cfg.id_vod)
    )).scalars().all()
    return set(rows)


async def vod_config_ids_for_player(
    db: AsyncSession, id_org: int, id_player: int
) -> set[int]:
    """Configs VOD visant ce player (player-centrique) — chemin du PRÉ-CACHE.

    Union des deux modes :
      - configs qui listent explicitement le player ;
      - configs en mode 'site' dont le site est celui du player.
    Un player sans site ne peut matcher aucune config 'site' (id_site NULL ne matche rien).
    """
    explicit = {r[0] for r in (await db.execute(
        select(CmsVodConfigPlayer.id_vod).where(CmsVodConfigPlayer.id_player == id_player)
    )).all()}

    id_site = await player_site_id(db, id_player)
    by_site: set[int] = set()
    if id_site is not None:
        by_site = {r[0] for r in (await db.execute(
            select(CmsVodConfig.id_vod).where(
                CmsVodConfig.id_org == id_org,
                CmsVodConfig.target_mode == "site",
                CmsVodConfig.id_site == id_site,
            )
        )).all()}

    return explicit | by_site


async def vod_configs_for_site(
    db: AsyncSession, id_org: int, id_site: int | None
) -> list[CmsVodConfig]:
    """Toutes les configs VOD d'un SITE — portée du PANNEAU DE CONTRÔLE LOCAL.

    À ne pas confondre avec `vod_config_ids_for_player` : celui-ci répond « que puis-je
    JOUER ? » (configs qui me ciblent, pré-cache), celui-là « que puis-je PILOTER ? »
    (décision Ed 2026-07-19 : un player de contrôle peut ne cibler aucune VOD et devoir
    quand même les déclencher chez les autres).

    Le filtre par `id_site` couvre d'office les trois formes de ciblage — une config visant
    un player du site, un groupe, ou le site entier — puisque `id_site` est renseigné dans
    les deux modes (explicite en 'site', déduit du site commun en 'players').
    Site NULL → aucune config (un player sans site ne pilote rien).
    """
    if id_site is None:
        return []
    return list((await db.execute(
        select(CmsVodConfig)
        .where(CmsVodConfig.id_org == id_org, CmsVodConfig.id_site == id_site)
        .order_by(CmsVodConfig.vod_name)
    )).scalars().all())


async def vod_players_for_config_ids(
    db: AsyncSession, id_org: int, vod_ids: set[int]
) -> set[int]:
    """Union des cibles résolues de plusieurs configs (pairs LAN, dispatch groupé)."""
    if not vod_ids:
        return set()
    configs = (await db.execute(
        select(CmsVodConfig).where(
            CmsVodConfig.id_vod.in_(vod_ids), CmsVodConfig.id_org == id_org
        )
    )).scalars().all()
    out: set[int] = set()
    for cfg in configs:
        out |= await vod_player_ids(db, cfg)
    return out


async def players_with_vod_media(
    db: AsyncSession, id_org: int, player_ids: list[int] | set[int], id_media: int
) -> set[int]:
    """Parmi `player_ids`, ceux qu'une config VOD contenant `id_media` vise réellement.

    Remplace le JOIN direct sur cms_vod_config_players : ce JOIN ignore le ciblage par
    site, donc un player ciblé par site aurait été jugé « pas concerné » par ce média.
    """
    if not player_ids:
        return set()
    with_media = {r[0] for r in (await db.execute(
        select(CmsVodConfigMedia.id_vod)
        .join(CmsVodConfig, CmsVodConfig.id_vod == CmsVodConfigMedia.id_vod)
        .where(CmsVodConfigMedia.id_media == id_media, CmsVodConfig.id_org == id_org)
    )).all()}
    if not with_media:
        return set()
    out: set[int] = set()
    for pid in player_ids:
        if await vod_config_ids_for_player(db, id_org, pid) & with_media:
            out.add(pid)
    return out
