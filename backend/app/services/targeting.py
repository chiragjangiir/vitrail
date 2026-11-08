"""
Noyau Targeting — résolution de cible étendue (partagé).

Brique (b) du noyau Scheduling & Targeting (cf. docs/SPIKE_scheduling_targeting_core.md).
Factorise les 3 vocabulaires de cible divergents (schedules `player_group`, events `group`,
gouvernance `group|site`) en UN vocabulaire canonique : player | group | site | tags | org.

`group` accepte l'alias historique `player_group` (cf. cms_schedule_targets) → ZÉRO
migration de données. Le résolveur normalise.

Deux sens :
  - players_for_target   : cible → ensemble d'id_player (expansion, ex. _push_sync).
  - player_matches_target : « ce player est-il visé ? » (chemin chaud player-centrique).

Tags comme CIBLE (audience) réutilise la taxonomie §XVII mais répond à une autre question
que le filtre de RÉCEPTION (`_filter_items_by_tags`) : ici « ce player porte-t-il ces tags ».
Aujourd'hui les attributs de tag d'un player = ses `cms_player_tag_filters`.

Consommateurs : schedules, item-rules (§ retours clients item 4), Gouvernance §XVIII,
Retail Media (ciblage de campagne, Phase 3).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.player import CmsPlayer
from app.models.player_group import CmsPlayerGroupMember
from app.models.site_group import CmsSiteGroupMember
from app.models.tag import CmsPlayerTagFilter, CmsTagNamespace, CmsTagValue

# Vocabulaire canonique + alias acceptés en entrée.
_GROUP_ALIASES = {"group", "player_group"}


@dataclass(frozen=True)
class Target:
    """Cible canonique. `tag_expr` = {namespace_key: [values]} (AND inter-ns, OR intra-ns)."""

    target_type: str  # player | group | site | site_group | tags | org
    target_id: int | None = None
    tag_expr: dict[str, list[str]] = field(default_factory=dict)


def _norm_type(t: str) -> str:
    return "group" if t in _GROUP_ALIASES else t


async def _players_with_tags(db: AsyncSession, id_org: int, tag_expr: dict[str, list[str]]) -> set[int]:
    """IDs des players de l'org dont les tags satisfont l'expression (AND inter-ns, OR intra-ns).

    Expression vide → aucun player (un ciblage 'tags' sans critère ne vise personne).
    """
    if not tag_expr:
        return set()
    result: set[int] | None = None
    for ns_key, values in tag_expr.items():
        if not values:
            continue
        rows = (await db.execute(
            select(CmsPlayerTagFilter.id_player)
            .join(CmsTagValue, CmsTagValue.id_tag == CmsPlayerTagFilter.id_tag)
            .join(CmsTagNamespace, CmsTagNamespace.id_namespace == CmsTagValue.id_namespace)
            .join(CmsPlayer, CmsPlayer.id_player == CmsPlayerTagFilter.id_player)
            .where(
                CmsPlayer.id_org == id_org,
                CmsTagNamespace.namespace_key == ns_key,
                CmsTagValue.tag_value.in_(values),
            )
        )).scalars().all()
        ns_players = set(rows)
        result = ns_players if result is None else (result & ns_players)
        if not result:
            return set()
    return result or set()


async def players_for_target(db: AsyncSession, id_org: int, target: Target) -> set[int]:
    """Étend une cible canonique en ensemble d'id_player (org-scoped)."""
    ttype = _norm_type(target.target_type)

    if ttype == "org":
        return set((await db.execute(
            select(CmsPlayer.id_player).where(CmsPlayer.id_org == id_org)
        )).scalars().all())

    if ttype == "player":
        if target.target_id is None:
            return set()
        # Garde org : un id_player étranger ne doit pas fuir.
        exists = (await db.execute(
            select(CmsPlayer.id_player).where(
                CmsPlayer.id_player == target.target_id, CmsPlayer.id_org == id_org
            )
        )).scalar_one_or_none()
        return {target.target_id} if exists is not None else set()

    if ttype == "group":
        if target.target_id is None:
            return set()
        rows = (await db.execute(
            select(CmsPlayerGroupMember.id_player)
            .join(CmsPlayer, CmsPlayer.id_player == CmsPlayerGroupMember.id_player)
            .where(CmsPlayerGroupMember.id_group == target.target_id, CmsPlayer.id_org == id_org)
        )).scalars().all()
        return set(rows)

    if ttype == "site":
        if target.target_id is None:
            return set()
        rows = (await db.execute(
            select(CmsPlayer.id_player).where(
                CmsPlayer.id_site == target.target_id, CmsPlayer.id_org == id_org
            )
        )).scalars().all()
        return set(rows)

    if ttype == "site_group":
        # site_group → sites membres → players. Un player posé APRÈS la création du
        # groupe est adressé automatiquement (le groupe vit au niveau site).
        if target.target_id is None:
            return set()
        rows = (await db.execute(
            select(CmsPlayer.id_player)
            .join(CmsSiteGroupMember, CmsSiteGroupMember.id_site == CmsPlayer.id_site)
            .where(
                CmsSiteGroupMember.id_site_group == target.target_id,
                CmsPlayer.id_org == id_org,
            )
        )).scalars().all()
        return set(rows)

    if ttype == "tags":
        return await _players_with_tags(db, id_org, target.tag_expr)

    return set()


async def players_for_targets(db: AsyncSession, id_org: int, targets: list[Target]) -> set[int]:
    """Union de plusieurs cibles."""
    out: set[int] = set()
    for tg in targets:
        out |= await players_for_target(db, id_org, tg)
    return out


async def player_site_group_ids(db: AsyncSession, id_player: int) -> set[int]:
    """Groupes de sites contenant le site du player (chemin player-centrique).

    Pour les matchers manuels de cibles (ws.py, prefetch, inventory…) qui ne passent
    pas par players_for_target : à combiner avec les group_ids du player.
    """
    rows = (await db.execute(
        select(CmsSiteGroupMember.id_site_group)
        .join(CmsPlayer, CmsPlayer.id_site == CmsSiteGroupMember.id_site)
        .where(CmsPlayer.id_player == id_player)
    )).scalars().all()
    return set(rows)


async def player_site_id(db: AsyncSession, id_player: int) -> int | None:
    """Site du player (chemin player-centrique, pendant de `player_site_group_ids`).

    Pour les matchers manuels qui doivent honorer une cible `site` sans passer par
    `players_for_target`. Renvoie None si le player n'est rattaché à aucun site.
    """
    return (await db.execute(
        select(CmsPlayer.id_site).where(CmsPlayer.id_player == id_player)
    )).scalar_one_or_none()


def event_target_entries(target_config: dict | None) -> list[tuple[str, list[int]]]:
    """Normalise les DEUX formes de `target_config` d'un événement en liste d'entrées.

    Forme héritée (mono-type)      : {"target_type": t, "target_ids": [...]}
    Forme hétérogène (2026-07-30)  : {"targets": [{"target_type": t, "target_ids": [...]}, …]}
    La sémantique de la forme hétérogène est l'UNION des entrées — « ce site » + « ces 3
    écrans » dans un seul événement, comme le font déjà les campagnes.

    🔑 Fonction PURE, sans base : c'est ce qui permet au worker Celery SYNCHRONE
    (`event_worker.py`, psycopg) de partager LA MÊME définition que l'API async — la copie
    assumée du worker ne porte plus que le SQL, jamais la lecture du JSON. C'est
    précisément la zone où la cible `site` avait été oubliée deux fois (29/07).

    Tout lecteur de `target_config` DOIT passer par ici : un lecteur qui déballe le dict
    lui-même ignorera la forme hétérogène en silence.
    """
    tc = target_config or {}
    if "targets" in tc:
        out: list[tuple[str, list[int]]] = []
        for entry in tc.get("targets") or []:
            if not isinstance(entry, dict):
                continue
            out.append((
                _norm_type(entry.get("target_type", "player")),
                list(entry.get("target_ids") or []),
            ))
        return out
    return [(_norm_type(tc.get("target_type", "player")), list(tc.get("target_ids") or []))]


def event_target_config_without(
    target_config: dict | None, t_type: str, target_id: int
) -> dict | None:
    """Copie du `target_config` sans l'identifiant donné, ou None si rien ne change.

    Sert aux purges d'orphelins à la suppression d'un player / groupe / groupe de sites
    (players.py, player_groups.py, site_groups.py) : trois sites d'appel qui déballaient
    chacun la forme héritée — la forme hétérogène doit être purgée au même endroit.
    """
    tc = target_config or {}
    wanted = _norm_type(t_type)
    if "targets" in tc:
        changed = False
        entries: list[dict] = []
        for entry in tc.get("targets") or []:
            if not isinstance(entry, dict):
                entries.append(entry)
                continue
            ids = list(entry.get("target_ids") or [])
            if _norm_type(entry.get("target_type", "player")) == wanted and target_id in ids:
                changed = True
                ids = [i for i in ids if i != target_id]
                if not ids:
                    continue          # entrée vidée → retirée (une entrée sans id ne vise rien)
                entries.append({**entry, "target_ids": ids})
            else:
                entries.append(entry)
        return {**tc, "targets": entries} if changed else None
    ids = list(tc.get("target_ids") or [])
    if _norm_type(tc.get("target_type", "player")) == wanted and target_id in ids:
        return {**tc, "target_ids": [i for i in ids if i != target_id]}
    return None


def event_config_targets(target_config: dict | None) -> list[Target]:
    """`target_config` (les deux formes) → liste de cibles canoniques prêtes pour
    `players_for_targets`. Une entrée `org` devient une cible org (ids ignorés)."""
    out: list[Target] = []
    for t_type, ids in event_target_entries(target_config):
        if t_type == "org":
            out.append(Target(target_type="org"))
        else:
            out.extend(Target(target_type=t_type, target_id=i) for i in ids)
    return out


def event_target_matches(
    target_config: dict,
    id_player: int,
    group_ids: set[int],
    site_group_ids: set[int],
    *,
    id_site: int | None,
) -> bool:
    """Match player-centrique d'un target_config d'event (org/player/group/site/site_group).

    Factorise les matchers inline historiques (ws.py, players.py, player_inventory…) —
    tout nouveau target_type d'event s'ajoute ICI, une seule fois. Comprend les deux
    formes via `event_target_entries` (hétérogène = OR sur les entrées).

    `id_site` est **keyword-only obligatoire** (et non défaillant à None par défaut) : la
    cible `site` était acceptée à l'écriture mais ignorée à la lecture — un event ciblant
    un site n'atteignait jamais ses players, sans la moindre erreur (audit 2026-07-18).
    Le rendre obligatoire garantit qu'un appelant oublié casse au lieu de re-créer
    silencieusement le bug. `None` = player sans site → ne matche aucune cible `site`.
    """
    for t_type, ids in event_target_entries(target_config):
        t_ids = set(ids)
        if (
            t_type == "org"
            or (t_type == "player" and id_player in t_ids)
            or (t_type == "group" and bool(t_ids & group_ids))
            or (t_type == "site" and id_site is not None and id_site in t_ids)
            or (t_type == "site_group" and bool(t_ids & site_group_ids))
        ):
            return True
    return False


async def player_has_tags(db: AsyncSession, id_player: int, tag_expr: dict[str, list[str]]) -> bool:
    """True si le player porte les tags requis (AND inter-ns, OR intra-ns). Expr vide → False."""
    if not tag_expr:
        return False
    player_tags: dict[str, set[str]] = {}
    for ns_key, val in (await db.execute(
        select(CmsTagNamespace.namespace_key, CmsTagValue.tag_value)
        .join(CmsTagValue, CmsTagValue.id_namespace == CmsTagNamespace.id_namespace)
        .join(CmsPlayerTagFilter, CmsPlayerTagFilter.id_tag == CmsTagValue.id_tag)
        .where(CmsPlayerTagFilter.id_player == id_player)
    )).all():
        player_tags.setdefault(ns_key, set()).add(val)

    for ns_key, values in tag_expr.items():
        if not values:
            continue
        if not (player_tags.get(ns_key, set()) & set(values)):
            return False
    return True


async def player_matches_target(
    db: AsyncSession, id_org: int, id_player: int, target: Target
) -> bool:
    """« Ce player est-il visé par la cible ? » — chemin player-centrique (évite de
    matérialiser tout l'org pour 'org'/'tags')."""
    ttype = _norm_type(target.target_type)

    if ttype == "org":
        return True
    if ttype == "player":
        return target.target_id == id_player
    if ttype == "group":
        if target.target_id is None:
            return False
        hit = (await db.execute(
            select(CmsPlayerGroupMember.id_player).where(
                CmsPlayerGroupMember.id_group == target.target_id,
                CmsPlayerGroupMember.id_player == id_player,
            )
        )).scalar_one_or_none()
        return hit is not None
    if ttype == "site":
        if target.target_id is None:
            return False
        hit = (await db.execute(
            select(CmsPlayer.id_player).where(
                CmsPlayer.id_player == id_player, CmsPlayer.id_site == target.target_id
            )
        )).scalar_one_or_none()
        return hit is not None
    if ttype == "site_group":
        if target.target_id is None:
            return False
        hit = (await db.execute(
            select(CmsPlayer.id_player)
            .join(CmsSiteGroupMember, CmsSiteGroupMember.id_site == CmsPlayer.id_site)
            .where(
                CmsPlayer.id_player == id_player,
                CmsSiteGroupMember.id_site_group == target.target_id,
            )
        )).scalar_one_or_none()
        return hit is not None
    if ttype == "tags":
        return await player_has_tags(db, id_player, target.tag_expr)
    return False
