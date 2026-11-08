"""Recherche globale (barre de la topbar) — cross-entités, org-scoped (RLS).

GET /search?q=... — cherche dans médias, playlists, campagnes, players, sites,
templates, événements, annonceurs, programmations, paniers audio et configs VOD ;
renvoie jusqu'à 5 résultats par catégorie.

RBAC : ouvert à tout utilisateur authentifié, mais **chaque catégorie est filtrée
par la permission de lecture correspondante** (mêmes gates que les pages locales).
Un utilisateur ne voit donc dans la barre globale que ce qu'il peut déjà consulter
dans le menu. Avant 2026-07-18 l'endpoint était gaté `require_org_admin` : tout
non-admin recevait un 403 alors que ses barres de recherche locales fonctionnaient.
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.db.session import get_db_worker
from app.models.audio_basket import CmsAudioBasket
from app.models.campaign import CmsAdvertiser, CmsCampaign
from app.models.event import CmsEvent
from app.models.governance import CmsGovernanceNode
from app.models.media import CmsMedia
from app.models.media_folder import CmsMediaFolder
from app.models.organization import CmsSite
from app.models.player import CmsPlayer
from app.models.playlist import CmsPlaylist
from app.models.schedule import CmsSchedule
from app.models.template import CmsTemplate
from app.models.user import CmsUser
from app.models.vod import CmsVodConfig
from app.schemas.search import SearchGroup, SearchHit, SearchResponse
from app.services import rbac
from app.services.media_folders import folder_full_paths
from app.services.governance_access import content_visibility, media_visibility
from app.services.governance_scope import user_player_scope

router = APIRouter(prefix="/search", tags=["search"])

_PER = 5  # résultats max par catégorie


def _disambiguate(hits, rows, id_attr):
    """Dernier recours : deux résultats encore IDENTIQUES reçoivent leur date de création.

    🔑 Mesuré sur la production le 2026-08-05, et **ça a contredit l'hypothèse de départ** :
    les six médias « Fond promo IA » sont tous dans LE MÊME dossier (`AI Generate`) et deux
    « Vidéo IA » n'en ont aucun. Le contexte métier — dossier, site, nœud — ne les sépare
    donc pas : ils ont été générés par la même chaîne, au même endroit. Ce qui les
    distingue vraiment, c'est QUAND.

    Appliqué **seulement en cas de collision** : ajouter une date à chaque ligne alourdirait
    les 99 % de cas où le contexte suffit déjà. Format ISO — lisible dans les 5 locales, là
    où `%d/%m` serait ambigu pour la moitié d'entre elles.
    """
    seen: dict[tuple[str, str | None], list[int]] = {}
    for idx, h in enumerate(hits):
        seen.setdefault((h.label, h.sublabel), []).append(idx)
    by_id = {getattr(r, id_attr): r for r in rows}
    for indexes in seen.values():
        if len(indexes) < 2:
            continue
        for idx in indexes:
            created = getattr(by_id.get(hits[idx].id), "created_at", None)
            if created is None:
                continue
            stamp = created.strftime("%Y-%m-%d %H:%M")
            hits[idx].sublabel = f"{hits[idx].sublabel} · {stamp}" if hits[idx].sublabel else stamp
    return hits


@router.get("", response_model=SearchResponse)
async def global_search(
    current_user: Annotated[CmsUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    db_w: Annotated[AsyncSession, Depends(get_db_worker)],
    q: Annotated[str, Query(min_length=1, max_length=100)],
) -> SearchResponse:
    org = current_user.id_org
    like = f"%{q.strip()}%"
    groups: list[SearchGroup] = []

    # Permissions résolues UNE fois (le catalogue RBAC est en session worker/BYPASSRLS).
    role_keys = await rbac.get_user_role_keys(db_w, current_user.id_user)
    is_super = "CMS_SUPER_ADMIN" in role_keys
    perms = set() if is_super else await rbac.get_user_permissions(db_w, current_user.id_user)

    def can(module: str) -> bool:
        return is_super or f"{module}:read" in perms

    async def collect(
        kind, model, name_attr, id_attr, href, *,
        module, soft_delete=False, extra_fields=(), sublabel=None, sublabel_map=None,
        extra_where=(),
    ):
        """Une catégorie de résultats. `extra_fields` = colonnes secondaires cherchées en
        plus du nom (IP/MAC d'un player, description d'une playlist…) ; `sublabel` =
        callable(row) -> str|None quand le contexte est DANS la ligne ; `sublabel_map` =
        async callable(rows) -> {id: str|None} quand il faut aller le chercher ailleurs
        (dossier d'un média, site d'un écran, nœud d'une playlist) — résolu **en lot**,
        jamais une requête par résultat ; `extra_where` = clauses supplémentaires
        (périmètre de gouvernance des players, N8)."""
        if not can(module):
            return
        searchable = [getattr(model, name_attr).ilike(like)]
        for field in extra_fields:
            col = getattr(model, field, None)
            if col is None:
                continue
            # ip_address/wan_ip sont en INET et mac_address en MACADDR : Postgres n'a pas
            # d'opérateur ILIKE sur ces types → cast explicite en text (sinon 500).
            searchable.append(cast(col, String).ilike(like))
        stmt = select(model).where(model.id_org == org, or_(*searchable), *extra_where)
        if soft_delete:
            stmt = stmt.where(model.is_deleted.is_(False))
        stmt = stmt.order_by(getattr(model, name_attr)).limit(_PER)
        rows = list((await db.execute(stmt)).scalars().unique().all())
        if not rows:
            return
        extra = await sublabel_map(rows) if sublabel_map else {}
        hits = [
            SearchHit(
                id=getattr(r, id_attr),
                label=getattr(r, name_attr),
                sublabel=(
                    extra.get(getattr(r, id_attr))
                    or (sublabel(r) if sublabel else None)
                ),
                href=href(r),
            )
            for r in rows
        ]
        groups.append(SearchGroup(kind=kind, items=_disambiguate(hits, rows, id_attr)))

    # ── Désambiguïsation des homonymes (P2.5) ─────────────────────────────────
    # Mesuré en production le 2026-08-05 : les seuls homonymes RÉELS sont des médias
    # (« Fond promo IA » ×6) — et c'était justement la seule catégorie sans aucun
    # sous-titre. Les autres reçoivent leur contexte par principe : le cas multi-magasins
    # (une playlist « Entrée » par magasin) est la forme exacte que prend un paramétrage
    # de gouvernance, et il produira des homonymes le jour où il grandit.
    # ⛔ Surtout PAS une contrainte d'unicité : elle casserait précisément ce cas d'usage
    # (décision du 2026-07-27) et serait inapplicable aux médias déjà en base.
    # Chaque résolveur fait UNE requête pour les ≤ 5 lignes de sa catégorie.

    async def _names(model, id_col, name_col, ids: set[int]) -> dict[int, str]:
        if not ids:
            return {}
        rows = (await db.execute(
            select(id_col, name_col).where(id_col.in_(ids), model.id_org == org)
        )).all()
        return {i: n for i, n in rows if n}

    async def media_folder_paths(rows) -> dict[int, str]:
        """Média → chemin lisible de son dossier (« Video / Divers »).

        Charge TOUS les dossiers de l'organisation : il en faut les ancêtres pour
        composer le chemin, et ils se comptent en dizaines. Même fonction que le tiroir
        de classement (`services/media_folders`), donc aucune divergence possible.
        """
        if not any(r.id_folder for r in rows):
            return {}
        folders = list((await db.execute(
            select(CmsMediaFolder).where(CmsMediaFolder.id_org == org)
        )).scalars().all())
        paths = folder_full_paths(folders)
        return {
            r.id_media: paths[r.id_folder]
            for r in rows
            if r.id_folder and r.id_folder in paths
        }

    async def by_site(rows, id_attr: str) -> dict[int, str]:
        sites = await _names(
            CmsSite, CmsSite.id_site, CmsSite.site_name,
            {r.id_site for r in rows if r.id_site},
        )
        return {
            getattr(r, id_attr): sites[r.id_site]
            for r in rows if r.id_site and r.id_site in sites
        }

    async def by_node(rows, id_attr: str) -> dict[int, str]:
        """Contenu gouverné → nom de son nœud (« Magasin Lyon ») : c'est LUI qui distingue
        deux playlists « Entrée » d'un réseau multi-sites."""
        nodes = await _names(
            CmsGovernanceNode, CmsGovernanceNode.id_node, CmsGovernanceNode.node_name,
            {r.id_governance_node for r in rows if r.id_governance_node},
        )
        return {
            getattr(r, id_attr): nodes[r.id_governance_node]
            for r in rows
            if r.id_governance_node and r.id_governance_node in nodes
        }

    async def by_advertiser(rows) -> dict[int, str]:
        advs = await _names(
            CmsAdvertiser, CmsAdvertiser.id_advertiser, CmsAdvertiser.advertiser_name,
            {r.id_advertiser for r in rows if r.id_advertiser},
        )
        return {
            r.id_campaign: advs[r.id_advertiser]
            for r in rows if r.id_advertiser and r.id_advertiser in advs
        }

    # NB : le terme de recherche est propagé en `?q=` pour que la page d'arrivée
    # pré-remplisse sa barre locale (sauf deep-links directs vers une fiche).
    esc = quote(q.strip())

    # Gouvernance §XVIII (D6/G4) : la barre globale ne doit pas révéler par leur NOM des
    # contenus que la liste correspondante refuse. Seuls les écrans étaient filtrés (N8/G1) ;
    # médias, playlists et templates ne l'étaient pas — mesuré le 2026-07-28 : un template
    # d'un nœud frère répondait 404 au détail, était absent de la liste, et apparaissait
    # pourtant dans la recherche. Même clause que les listes, donc aucune divergence possible.
    gov_clause, _visible, _editable = await content_visibility(db, current_user)
    # Les MÉDIAS suivent leur propre règle depuis le 2026-07-29 (la médiathèque non gouvernée
    # est lisible par tous les rôles) : la barre globale doit dire la même chose que
    # `GET /media/`, sinon elle re-deviendrait plus restrictive que la liste qu'elle indexe.
    media_clause, _mv, _me = await media_visibility(db, current_user)

    def gov_where(column):
        clause = gov_clause(column)
        return () if clause is None else (clause,)

    _mc = media_clause(CmsMedia.id_governance_node)
    await collect(
        "media", CmsMedia, "media_name", "id_media",
        lambda r: f"/media?q={esc}", module="media", soft_delete=True,
        sublabel_map=media_folder_paths,
        extra_where=() if _mc is None else (_mc,),
    )
    await collect(
        "playlist", CmsPlaylist, "playlist_name", "id_playlist",
        lambda r: f"/playlists/{r.id_playlist}", module="playlists",
        soft_delete=True, extra_fields=("description",),
        sublabel_map=lambda rows: by_node(rows, "id_playlist"),
        extra_where=gov_where(CmsPlaylist.id_governance_node),
    )
    await collect(
        "campaign", CmsCampaign, "campaign_name", "id_campaign",
        lambda r: f"/campaigns?q={esc}", module="campaigns", soft_delete=True,
        sublabel_map=by_advertiser,
    )
    # Deep-link direct sur la FICHE (le drawer s'ouvre) : chaque resultat designe UN player
    # precis, une liste filtree a un element n'apporte rien (retour Ed 2026-07-19).
    # N8/G1 : la barre globale ne révèle pas un écran que /players refuserait.
    player_scope = await user_player_scope(db, current_user)
    await collect(
        "player", CmsPlayer, "player_name", "id_player",
        lambda r: f"/players?open={r.id_player}", module="players",
        extra_fields=("player_os", "ip_address", "wan_ip", "mac_address"),
        # Le SITE distingue deux « Vitrine » ; l'OS, lui, est souvent le meme partout —
        # il reste en repli quand l'ecran n'est rattache a aucun site.
        sublabel_map=lambda rows: by_site(rows, "id_player"),
        sublabel=lambda r: r.player_os or None,
        extra_where=(
            () if player_scope is None
            else (CmsPlayer.id_player.in_(player_scope or {-1}),)
        ),
    )
    await collect(
        "site", CmsSite, "site_name", "id_site",
        lambda r: f"/sites?q={esc}", module="players",
        extra_fields=("site_number", "country"),
        sublabel=lambda r: r.site_number or r.country or None,
    )
    await collect(
        "template", CmsTemplate, "template_name", "id_template",
        lambda r: f"/templates?q={esc}", module="templates", soft_delete=True,
        sublabel_map=lambda rows: by_node(rows, "id_template"),
        extra_where=gov_where(CmsTemplate.id_governance_node),
    )
    await collect(
        "event", CmsEvent, "event_name", "id_event",
        lambda r: f"/events?q={esc}", module="events",
        sublabel_map=lambda rows: by_node(rows, "id_event"),
    )
    await collect(
        "advertiser", CmsAdvertiser, "advertiser_name", "id_advertiser",
        lambda r: f"/campaigns/advertisers?q={esc}", module="campaigns", soft_delete=True,
    )
    await collect(
        "schedule", CmsSchedule, "schedule_name", "id_schedule",
        lambda r: f"/schedules?q={esc}", module="schedules", soft_delete=True,
        sublabel_map=lambda rows: by_node(rows, "id_schedule"),
        sublabel=lambda r: r.schedule_kind or None,
    )
    await collect(
        "audio_basket", CmsAudioBasket, "basket_name", "id_basket",
        lambda r: f"/audio-baskets?q={esc}", module="audio_baskets",
        sublabel=lambda r: r.basket_type or None,
    )
    # VOD : deep-link direct sur la config (le drawer s'ouvre) — la page n'a pas de barre locale.
    await collect(
        "vod", CmsVodConfig, "vod_name", "id_vod",
        lambda r: f"/vod?open={r.id_vod}", module="vod",
        extra_fields=("description",),
        sublabel_map=lambda rows: by_site(rows, "id_vod"),
    )

    return SearchResponse(query=q, groups=groups)
