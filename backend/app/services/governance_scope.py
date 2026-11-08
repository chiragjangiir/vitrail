"""Périmètre effectif d'un programme gouverné — SOURCE UNIQUE (D-b, 2026-07-26).

Jusqu'ici une couche gouvernée s'appliquait à **tous** les écrans de son nœud, et les cibles
classiques du programme étaient purement ignorées (D2). Le cas « entrée + boucherie » d'Ed
(un magasin, 5 écrans, 2 playlists différentes sur 2 d'entre eux) obligeait alors à créer un
nœud par usage — ~400 nœuds pour 100 magasins.

**Règle D-b** : les cibles d'un programme gouverné **FILTRENT** le périmètre du nœud
(intersection). Elles ne peuvent que **restreindre**, jamais élargir — c'est ce qui garantit
qu'on ne rouvre pas la porte fermée par D2 (un programme gouverné ne rejoue jamais par le
chemin classique, cf. `ws.py`).

Décisions actées (Ed, 2026-07-26 soir) :
  · **D0** — un programme SANS cible couvre tout le nœud. Hypothèse forcée par le parc :
    les programmes gouvernés existants n'ont pas de cible, toute autre règle les éteindrait
    au déploiement.
  · **D2b** — un nœud inférieur ne restreint jamais une couche HÉRITÉE : les cibles ne
    valent que pour le programme auquel elles appartiennent, et on n'édite que les
    programmes des nœuds qu'on administre (garanti par `governance_access`).
  · **D3** — une cible qui résout à ZÉRO écran du périmètre est refusée **au moment du
    geste** ; jamais de ré-invalidation après coup (une cible devenue inerte est affichée,
    pas supprimée).

⚠️ **Deux directions, et les DEUX vivent ici** — c'est la leçon de l'audit du 2026-07-18
(cible acceptée à l'écriture, ignorée à la lecture : enregistrée, comptée dans l'aperçu, et
jamais diffusée sans la moindre erreur) :

1. **player-centrique** — `scoped_schedule_ids()` : « ce player reçoit-il ce programme ? »
   C'est le chemin qui décide de la DIFFUSION RÉELLE. Trois consommateurs, et ils ne passent
   pas tous par le même point : `gather_layers` (sync + aperçu compilé), `services.prefetch`
   et `services.player_inventory` re-sélectionnent les programmes gouvernés **en direct**.
   Un oubli chez ces deux-là ne casse pas la diffusion : il pré-télécharge et attend du
   contenu jamais joué (faux « média manquant »).
2. **nœud-centrique** — `resolved_players()` / `node_coverage()` : « qui est retenu ? »
   pour l'écran (compteur d'écrans résolus) et la validation D3.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.governance import (
    CmsGovernanceAssignment,
    CmsGovernanceNode,
    CmsGovernanceNodeAdmin,
)
from app.models.organization import CmsSite
from app.models.player import CmsPlayer
from app.models.player_group import CmsPlayerGroup, CmsPlayerGroupMember
from app.models.schedule import CmsSchedule, CmsScheduleTarget
from app.models.site_group import CmsSiteGroup, CmsSiteGroupMember
from app.models.user import CmsUser
from app.services import rbac
from app.services.targeting import Target, players_for_targets

_BYPASS_ROLES = {"CMS_SUPER_ADMIN", "CMS_ORG_ADMIN"}

# Alias historique de `cms_schedule_targets` (le vocabulaire canonique du noyau Targeting
# dit `group`, la table dit `player_group`) — cf. services/targeting.py.
_GROUP_TYPES = {"group", "player_group"}


async def node_perimeter_players(
    db: AsyncSession, id_org: int, node: CmsGovernanceNode
) -> set[int]:
    """Players du nœud ET de son sous-arbre (assignations directes + groupes + sites).

    C'est le périmètre que les cibles d'un programme viennent restreindre. Un nœud national
    couvre donc bien les écrans assignés à ses départements et à ses sites.
    """
    subtree_ids = (await db.execute(
        select(CmsGovernanceNode.id_node).where(
            CmsGovernanceNode.id_org == id_org,
            CmsGovernanceNode.path.like(f"{node.path}%"),
        )
    )).scalars().all()
    if not subtree_ids:
        return set()
    assigns = (await db.execute(
        select(CmsGovernanceAssignment).where(CmsGovernanceAssignment.id_node.in_(subtree_ids))
    )).scalars().all()
    return await players_for_targets(
        db, id_org, [Target(a.target_type, a.target_id) for a in assigns],
    )


# ── Périmètre UTILISATEUR (N8 / G1 / G2, audit 2026-07-27) ───────────────────
# G1 : un admin de nœud ne voit que les écrans de SES sous-arbres (union) ; les
# affectations vivant sur les nœuds bas, la remontée est déjà faite par
# `node_perimeter_players`. Un utilisateur SANS nœud administré n'est pas filtré
# (les rôles classiques — Viewer, Planificateur… — sont inchangés ; la sémantique
# de périmètre portée par le RÔLE, c'est G4, Phase 3).

async def user_admin_nodes(db: AsyncSession, user: CmsUser) -> list[CmsGovernanceNode] | None:
    """Nœuds que `user` administre. None = bypass (org-admin/super : jamais filtré)."""
    role_keys = await rbac.get_user_role_keys(db, user.id_user)
    if _BYPASS_ROLES.intersection(role_keys):
        return None
    return list((await db.execute(
        select(CmsGovernanceNode)
        .join(CmsGovernanceNodeAdmin,
              CmsGovernanceNodeAdmin.id_node == CmsGovernanceNode.id_node)
        .where(
            CmsGovernanceNodeAdmin.id_user == user.id_user,
            CmsGovernanceNode.id_org == user.id_org,
        )
    )).scalars().all())


async def user_player_scope(db: AsyncSession, user: CmsUser) -> set[int] | None:
    """Écrans visibles par `user` (G1). None = AUCUNE restriction.

    None couvre deux cas volontairement distincts de « ensemble vide » :
      · bypass (org-admin/super) ;
      · utilisateur sans aucun nœud administré — les rôles classiques gardent la
        visibilité d'org, on ne change pas leur comportement sans décision (G4 exclu).
    Un admin de nœud, lui, reçoit l'union des périmètres de ses sous-arbres — qui peut
    être VIDE (nœud sans écran) : c'est un vrai « il ne voit rien », pas un bypass.
    """
    nodes = await user_admin_nodes(db, user)
    if not nodes:  # None (bypass) OU aucun nœud administré → pas de restriction
        return None
    scope: set[int] = set()
    for n in nodes:  # 1-2 nœuds en pratique ; chaque appel fait la remontée du sous-arbre
        scope |= await node_perimeter_players(db, user.id_org, n)
    return scope


async def orphan_players(db: AsyncSession, id_org: int) -> set[int]:
    """Écrans rattachés à AUCUN nœud de gouvernance (G2 : « les oubliés »).

    = tous les players de l'org moins ceux que résout l'ensemble des assignations.
    """
    assigns = (await db.execute(
        select(CmsGovernanceAssignment)
        .join(CmsGovernanceNode,
              CmsGovernanceNode.id_node == CmsGovernanceAssignment.id_node)
        .where(CmsGovernanceNode.id_org == id_org)
    )).scalars().all()
    governed = await players_for_targets(
        db, id_org, [Target(a.target_type, a.target_id) for a in assigns],
    ) if assigns else set()
    all_ids = set((await db.execute(
        select(CmsPlayer.id_player).where(CmsPlayer.id_org == id_org)
    )).scalars().all())
    return all_ids - governed


async def player_scope(db: AsyncSession, id_player: int) -> tuple[set[int], int | None, set[int]]:
    """Contexte de ciblage d'un player : (groupes, site, groupes de sites).

    Résolu UNE fois par appelant : les chemins chauds (sync, prefetch, inventaire) tournent
    à chaque synchro de chaque player.
    """
    group_ids = set((await db.execute(
        select(CmsPlayerGroupMember.id_group).where(CmsPlayerGroupMember.id_player == id_player)
    )).scalars().all())
    id_site = (await db.execute(
        select(CmsPlayer.id_site).where(CmsPlayer.id_player == id_player)
    )).scalar_one_or_none()
    site_group_ids: set[int] = set()
    if id_site is not None:
        site_group_ids = set((await db.execute(
            select(CmsSiteGroupMember.id_site_group)
            .where(CmsSiteGroupMember.id_site == id_site)
        )).scalars().all())
    return group_ids, id_site, site_group_ids


def target_hits_player(
    target_type: str, target_id: int, id_player: int,
    group_ids: set[int], id_site: int | None, site_group_ids: set[int],
) -> bool:
    """« Cette cible vise-t-elle ce player ? » — matcher pur (pendant de `event_target_matches`).

    Un `target_type` inconnu ne vise personne : il ne doit pas élargir le périmètre par
    accident. La colonne est verrouillée par un `Literal` à l'écriture depuis l'audit du
    2026-07-18, donc ce cas ne devrait plus exister en base.
    """
    if target_type == "player":
        return target_id == id_player
    if target_type in _GROUP_TYPES:
        return target_id in group_ids
    if target_type == "site":
        return id_site is not None and target_id == id_site
    if target_type == "site_group":
        return target_id in site_group_ids
    return False


async def scoped_schedule_ids(
    db: AsyncSession, id_player: int, schedule_ids: set[int] | list[int],
    *, scope: tuple[set[int], int | None, set[int]] | None = None,
) -> set[int]:
    """Parmi des programmes GOUVERNÉS, ceux qui atteignent réellement ce player (D-b).

    Sans cible → conservé (D0, tout le nœud). Avec cibles → conservé si le player en
    satisfait au moins une. Une seule requête pour l'ensemble des programmes : cette
    fonction est sur le chemin chaud de chaque synchro.

    `scope` permet à l'appelant de réutiliser un contexte déjà résolu.
    """
    ids = set(schedule_ids)
    if not ids:
        return set()
    rows = (await db.execute(
        select(CmsScheduleTarget.id_schedule, CmsScheduleTarget.target_type,
               CmsScheduleTarget.target_id)
        .where(CmsScheduleTarget.id_schedule.in_(ids))
    )).all()
    if not rows:
        return ids  # aucun de ces programmes n'est ciblé → tout le nœud (D0)

    group_ids, id_site, site_group_ids = scope or await player_scope(db, id_player)

    targeted: set[int] = set()
    matched: set[int] = set()
    for id_schedule, ttype, tid in rows:
        targeted.add(id_schedule)
        if id_schedule in matched:
            continue
        if target_hits_player(ttype, tid, id_player, group_ids, id_site, site_group_ids):
            matched.add(id_schedule)
    return (ids - targeted) | matched


async def resolved_players(
    db: AsyncSession, id_org: int, node: CmsGovernanceNode,
    targets: list[tuple[str, int]],
    *, perimeter: set[int] | None = None,
) -> set[int]:
    """Écrans réellement retenus par un programme du nœud (nœud-centrique).

    Sans cible → tout le périmètre (D0). Avec cibles → **intersection** : une cible qui
    déborde du nœud (groupe de sites à cheval sur deux départements) n'apporte que sa part.
    """
    peri = perimeter if perimeter is not None else await node_perimeter_players(db, id_org, node)
    if not targets:
        return peri
    hit = await players_for_targets(db, id_org, [Target(tt, tid) for tt, tid in targets])
    return peri & hit


async def target_names(
    db: AsyncSession, targets: list[tuple[str, int]]
) -> dict[tuple[str, int], str]:
    """Libellés des cibles (pour nommer une cible refusée — un id nu n'aide personne)."""
    out: dict[tuple[str, int], str] = {}
    by_type: dict[str, list[int]] = {}
    for tt, tid in targets:
        by_type.setdefault("group" if tt in _GROUP_TYPES else tt, []).append(tid)

    if by_type.get("player"):
        for pid, name in (await db.execute(
            select(CmsPlayer.id_player, CmsPlayer.player_name)
            .where(CmsPlayer.id_player.in_(by_type["player"]))
        )).all():
            out[("player", pid)] = name
    if by_type.get("group"):
        for gid, name in (await db.execute(
            select(CmsPlayerGroup.id_group, CmsPlayerGroup.group_name)
            .where(CmsPlayerGroup.id_group.in_(by_type["group"]))
        )).all():
            out[("group", gid)] = name
            out[("player_group", gid)] = name
    if by_type.get("site"):
        for sid, name in (await db.execute(
            select(CmsSite.id_site, CmsSite.site_name).where(CmsSite.id_site.in_(by_type["site"]))
        )).all():
            out[("site", sid)] = name
    if by_type.get("site_group"):
        for sgid, name in (await db.execute(
            select(CmsSiteGroup.id_site_group, CmsSiteGroup.group_name)
            .where(CmsSiteGroup.id_site_group.in_(by_type["site_group"]))
        )).all():
            out[("site_group", sgid)] = name
    return out


async def out_of_scope_targets(
    db: AsyncSession, id_org: int, node: CmsGovernanceNode, targets: list[tuple[str, int]],
    *, perimeter: set[int] | None = None,
) -> list[dict]:
    """Cibles qui ne retiennent AUCUN écran du périmètre (D3 : refusées au geste).

    Chaque cible est jugée SÉPARÉMENT : un recouvrement partiel est accepté (on ne garde
    que la part du nœud), seule une cible qui ne touche rien est une erreur de saisie.
    """
    if not targets:
        return []
    peri = perimeter if perimeter is not None else await node_perimeter_players(db, id_org, node)
    names = await target_names(db, targets)
    bad: list[dict] = []
    for tt, tid in targets:
        hit = await players_for_targets(db, id_org, [Target(tt, tid)])
        if not (hit & peri):
            bad.append({"target_type": tt, "target_id": tid,
                        "target_name": names.get((tt, tid))})
    return bad


def lan_group_label(player: CmsPlayer) -> str | None:
    """Libellé du groupe de synchro LAN d'un player (None hors groupe).

    Même définition que `players._lan_group_label` — recopiée ici plutôt qu'importée pour
    ne pas créer un cycle service → endpoint ; toute évolution doit toucher les deux.
    """
    cfg = player.display_config or {}
    if not cfg.get("lan_sync_enabled"):
        return None
    return (cfg.get("lan_sync_group") or "").strip() or None


async def lan_sync_split(
    db: AsyncSession, id_org: int, kept: set[int]
) -> list[dict]:
    """Groupes de synchro LAN que ce ciblage **coupe en deux** (D4 : avertir, jamais bloquer).

    Décision Ed : « ces écrans sont synchronisés entre eux mais ne diffuseront plus la même
    chose » — on le dit et on laisse faire. Refuser aurait interdit le cas entrée/boucherie
    dans un magasin déjà câblé en un seul groupe, c'est-à-dire la situation la plus probable.
    Techniquement rien ne casse : la clé de synchro dérive des couches actives, donc chaque
    sous-ensemble se resynchronise pour son compte — mais personne ne peut le deviner devant
    l'écran, d'où l'avertissement.

    Un groupe n'est signalé que s'il a **au moins un** écran retenu ET **au moins un** écarté.
    """
    if not kept:
        return []
    players = (await db.execute(
        select(CmsPlayer).where(CmsPlayer.id_org == id_org)
    )).scalars().all()

    groups: dict[str, dict[str, list[str]]] = {}
    for p in players:
        label = lan_group_label(p)
        if label is None:
            continue
        bucket = groups.setdefault(label, {"kept": [], "excluded": []})
        bucket["kept" if p.id_player in kept else "excluded"].append(p.player_name)

    return [
        {"group": label, "kept": sorted(b["kept"]), "excluded": sorted(b["excluded"])}
        for label, b in sorted(groups.items())
        if b["kept"] and b["excluded"]
    ]


async def node_coverage(
    db: AsyncSession, id_org: int, node: CmsGovernanceNode
) -> dict:
    """Couverture du nœud par SES programmes (pas ceux hérités) — écran.

    Deux besoins en une seule lecture :
      · le compteur d'écrans résolus par programme (D3 : « on montre toujours le résultat
        résolu », pour que personne ne croie avoir ciblé un magasin qui ne recevra rien) ;
      · la **contrepartie assumée de D1** : un écran installé et oublié dans son groupe ne
        reçoit que l'héritage **sans que rien ne le signale**. On le signale ici.
    """
    perimeter = await node_perimeter_players(db, id_org, node)
    schedules = (await db.execute(
        select(CmsSchedule).where(
            CmsSchedule.id_governance_node == node.id_node,
            CmsSchedule.schedule_kind == "content",
            CmsSchedule.is_deleted == False,  # noqa: E712
        ).order_by(CmsSchedule.schedule_name)
    )).scalars().all()

    rows = (await db.execute(
        select(CmsScheduleTarget.id_schedule, CmsScheduleTarget.target_type,
               CmsScheduleTarget.target_id)
        .where(CmsScheduleTarget.id_schedule.in_([s.id_schedule for s in schedules] or [-1]))
    )).all()
    by_sched: dict[int, list[tuple[str, int]]] = {}
    for id_schedule, ttype, tid in rows:
        by_sched.setdefault(id_schedule, []).append((ttype, tid))

    out_sched: list[dict] = []
    covered: set[int] = set()
    for s in schedules:
        tgts = by_sched.get(s.id_schedule, [])
        players = await resolved_players(db, id_org, node, tgts, perimeter=perimeter)
        if s.is_active:
            covered |= players
        out_sched.append({
            "id_schedule": s.id_schedule,
            "schedule_name": s.schedule_name,
            "is_active": s.is_active,
            "target_count": len(tgts),
            "resolved_count": len(players),
        })

    uncovered = perimeter - covered
    names = dict((await db.execute(
        select(CmsPlayer.id_player, CmsPlayer.player_name)
        .where(CmsPlayer.id_player.in_(uncovered or {-1}))
    )).all())
    return {
        "id_node": node.id_node,
        "perimeter_count": len(perimeter),
        "schedules": out_sched,
        "uncovered": [{"id_player": pid, "player_name": names.get(pid)}
                      for pid in sorted(uncovered)],
    }
