"""La recherche globale distingue les homonymes (P2.5).

Mesuré en production le 2026-08-05 : les seuls homonymes RÉELS sont des **médias**
(« Fond promo IA » ×6) — et c'était précisément la seule catégorie que la barre globale
rendait sans le moindre sous-titre. Deux lignes identiques, aucun moyen de choisir.

⛔ La solution N'EST PAS une contrainte d'unicité (décision du 2026-07-27) : elle
casserait le multi-sites — chaque magasin veut sa playlist « Entrée » — et serait de
toute façon inapplicable aux médias déjà en base. On donne donc à chaque résultat le
CONTEXTE qui le distingue : le dossier d'un média, le site d'un écran, le nœud d'un
contenu gouverné, l'annonceur d'une campagne.

⚠️ Ces tests portent sur le `sublabel` SERVI, pas sur le rendu : c'est le contrat que
l'écran consomme (`GlobalSearch.tsx` l'affiche déjà sous le nom).
"""

import uuid

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.campaign import CmsAdvertiser, CmsCampaign
from app.models.governance import CmsGovernanceNode, CmsGovernanceNodeAdmin
from app.models.media import CmsMedia
from app.models.media_folder import CmsMediaFolder
from app.models.organization import CmsOrganization, CmsOrgAuthSettings, CmsSite
from app.models.player import CmsPlayer
from app.models.playlist import CmsPlaylist
from app.models.role import (
    CmsPermission,
    CmsRole,
    CmsRolePermission,
    CmsUserRoleAssignment,
)
from app.models.user import CmsUser
from app.services.media_folders import folder_full_paths


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="HomonymOrg", org_slug=f"hom-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


async def _user_and_token(client: AsyncClient, db: AsyncSession, org: CmsOrganization,
                          perms: list[tuple[str, str]]) -> tuple[CmsUser, str]:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(id_org=org.id_org, email=f"h-{uid}@test.com",
                   password_hash=hash_password("Password1!"), is_active=True)
    db.add(user)
    await db.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_H_{uid}", label="H", is_system=False)
    db.add(role)
    await db.flush()
    for module, operation in perms:
        await db.execute(
            pg_insert(CmsPermission)
            .values(module=module, operation=operation, label=f"{module}.{operation}")
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
        )
        await db.flush()
        perm = (await db.execute(select(CmsPermission).where(
            CmsPermission.module == module, CmsPermission.operation == operation))).scalar_one()
        db.add(CmsRolePermission(id_role=role.id_role, id_permission=perm.id_permission))
    await db.flush()
    db.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db.commit()
    r = await client.post("/api/v1/auth/login",
                          json={"email": user.email, "password": "Password1!"})
    assert r.status_code == 200, r.text
    return user, r.json()["access_token"]


async def _token(client: AsyncClient, db: AsyncSession, org: CmsOrganization,
                 perms: list[tuple[str, str]]) -> str:
    _u, tok = await _user_and_token(client, db, org, perms)
    return tok


def _items(payload: dict, kind: str) -> list[dict]:
    for g in payload["groups"]:
        if g["kind"] == kind:
            return g["items"]
    return []


def _media(org, name, id_folder=None) -> CmsMedia:
    return CmsMedia(
        id_org=org.id_org, media_name=name, media_type="video",
        storage_key=f"test/{uuid.uuid4().hex}.mp4", checksum_sha256=uuid.uuid4().hex,
        transcode_status="done", id_folder=id_folder,
    )


# ── Médias : LE cas mesuré en production ────────────────────────────────────────

async def test_two_media_with_the_same_name_are_told_apart_by_their_folder(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization
) -> None:
    """ROUGE AVANT : les deux résultats étaient rigoureusement identiques — même nom,
    aucun sous-titre, même lien. Impossible de choisir."""
    token = await _token(client, db_session, org, [("media", "read")])

    video = CmsMediaFolder(id_org=org.id_org, folder_name="Video", depth=0, path="1")
    db_session.add(video)
    await db_session.flush()
    # Deux sous-dossiers de PARENTS DIFFÉRENTS : le nom seul du dossier ne suffirait pas,
    # c'est le CHEMIN qui distingue (même leçon que le tiroir de classement, 28/07).
    promo = CmsMediaFolder(id_org=org.id_org, folder_name="Promo", parent_id=video.id_folder,
                           depth=1, path=f"{video.id_folder}.1")
    archive = CmsMediaFolder(id_org=org.id_org, folder_name="Archive", depth=0, path="2")
    db_session.add_all([promo, archive])
    await db_session.flush()
    db_session.add_all([
        _media(org, "Fond promo IA", promo.id_folder),
        _media(org, "Fond promo IA", archive.id_folder),
    ])
    await db_session.commit()

    r = await client.get("/api/v1/search", params={"q": "Fond promo IA"},
                         headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    items = _items(r.json(), "media")
    assert len(items) == 2
    subs = sorted(i["sublabel"] for i in items)
    assert subs == ["Archive", "Video / Promo"]


async def test_unclassified_media_has_no_sublabel_and_does_not_break(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization
) -> None:
    """Un média à la racine n'a pas de dossier : pas de sous-titre, et surtout pas d'erreur.
    Le contexte manquant vaut mieux qu'un contexte inventé."""
    token = await _token(client, db_session, org, [("media", "read")])
    db_session.add(_media(org, "Orphelin ZZQ"))
    await db_session.commit()

    r = await client.get("/api/v1/search", params={"q": "Orphelin ZZQ"},
                         headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    items = _items(r.json(), "media")
    assert len(items) == 1 and items[0]["sublabel"] is None


async def test_same_name_in_the_SAME_folder_falls_back_to_the_creation_date(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization
) -> None:
    """🔑 LE VRAI CAS D'ED, mesuré en production le 05/08 — et il contredit l'hypothèse de
    départ : ses six « Fond promo IA » sont tous dans LE MÊME dossier (`AI Generate`),
    parce qu'ils sortent de la même chaîne de génération. Le dossier ne les distingue donc
    PAS. Ce qui les distingue, c'est QUAND ils ont été créés.

    ROUGE AVANT le complément : sous-titres identiques (« AI Generate » ×2), donc le
    problème restait entier là où il se pose réellement."""
    from datetime import UTC, datetime

    token = await _token(client, db_session, org, [("media", "read")])
    dossier = CmsMediaFolder(id_org=org.id_org, folder_name="AI Generate", depth=0, path="7")
    db_session.add(dossier)
    await db_session.flush()
    a = _media(org, "Fond promo VWX", dossier.id_folder)
    b = _media(org, "Fond promo VWX", dossier.id_folder)
    a.created_at = datetime(2026, 7, 28, 14, 32, tzinfo=UTC)
    b.created_at = datetime(2026, 8, 2, 9, 5, tzinfo=UTC)
    db_session.add_all([a, b])
    await db_session.commit()

    r = await client.get("/api/v1/search", params={"q": "Fond promo VWX"},
                         headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    subs = sorted(i["sublabel"] for i in _items(r.json(), "media"))
    assert subs == ["AI Generate · 2026-07-28 14:32", "AI Generate · 2026-08-02 09:05"]


async def test_unclassified_homonyms_are_told_apart_by_the_date_alone(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization
) -> None:
    """Le second cas réel : deux « Vidéo IA » SANS dossier. Pas de contexte métier du tout
    — la date reste, et elle suffit."""
    from datetime import UTC, datetime

    token = await _token(client, db_session, org, [("media", "read")])
    a, b = _media(org, "Video IA TUV"), _media(org, "Video IA TUV")
    a.created_at = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
    b.created_at = datetime(2026, 7, 1, 8, 30, tzinfo=UTC)
    db_session.add_all([a, b])
    await db_session.commit()

    r = await client.get("/api/v1/search", params={"q": "Video IA TUV"},
                         headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    subs = sorted(i["sublabel"] for i in _items(r.json(), "media"))
    assert subs == ["2026-07-01 08:00", "2026-07-01 08:30"]


async def test_a_lone_result_keeps_a_clean_sublabel(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization
) -> None:
    """La date n'apparaît QU'EN CAS DE COLLISION : sans homonyme, le contexte métier suffit
    et alourdir chaque ligne d'une date serait une régression d'affichage."""
    token = await _token(client, db_session, org, [("media", "read")])
    dossier = CmsMediaFolder(id_org=org.id_org, folder_name="Solo", depth=0, path="8")
    db_session.add(dossier)
    await db_session.flush()
    db_session.add(_media(org, "Unique RST", dossier.id_folder))
    await db_session.commit()

    r = await client.get("/api/v1/search", params={"q": "Unique RST"},
                         headers={"Authorization": f"Bearer {token}"})
    items = _items(r.json(), "media")
    assert len(items) == 1 and items[0]["sublabel"] == "Solo"


# ── Le cas multi-magasins : deux playlists « Entrée » ───────────────────────────

async def test_two_playlists_with_the_same_name_are_told_apart_by_their_node(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization
) -> None:
    """La forme exacte du paramétrage de gouvernance d'Ed : une playlist « Entrée » par
    magasin. C'est le NŒUD qui les distingue, et c'est pour ce cas qu'on a refusé une
    contrainte d'unicité le 27/07."""
    user, token = await _user_and_token(client, db_session, org, [("playlists", "read")])

    lyon = CmsGovernanceNode(id_org=org.id_org, node_name="Magasin Lyon",
                             node_level=2, path="1.2")
    paris = CmsGovernanceNode(id_org=org.id_org, node_name="Magasin Paris",
                              node_level=2, path="1.3")
    db_session.add_all([lyon, paris])
    await db_session.flush()
    # ⚠️ Sans ces deux nominations, la gouvernance masque le contenu des nœuds — et elle a
    # RAISON : mon premier jet cherchait avec un compte n'administrant aucun nœud et
    # recevait 0 résultat. Le filet fonctionnait, c'est le test qui décrivait mal le cas.
    db_session.add_all([
        CmsGovernanceNodeAdmin(id_node=lyon.id_node, id_user=user.id_user),
        CmsGovernanceNodeAdmin(id_node=paris.id_node, id_user=user.id_user),
    ])
    db_session.add_all([
        CmsPlaylist(id_org=org.id_org, playlist_name="Entree QRS",
                    id_governance_node=lyon.id_node),
        CmsPlaylist(id_org=org.id_org, playlist_name="Entree QRS",
                    id_governance_node=paris.id_node),
    ])
    await db_session.commit()

    r = await client.get("/api/v1/search", params={"q": "Entree QRS"},
                         headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    items = _items(r.json(), "playlist")
    assert len(items) == 2
    assert sorted(i["sublabel"] for i in items) == ["Magasin Lyon", "Magasin Paris"]


# ── Écrans : le SITE distingue, pas l'OS ───────────────────────────────────────

async def test_players_are_told_apart_by_their_site_not_their_os(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization
) -> None:
    """ROUGE AVANT : le sous-titre était l'OS — identique sur tout un parc homogène, donc
    inutile pour choisir. Le site répond à « lequel ? » ; l'OS reste en repli quand
    l'écran n'est rattaché à aucun site."""
    token = await _token(client, db_session, org, [("players", "read")])

    lyon = CmsSite(id_org=org.id_org, site_name="Boutique Lyon")
    paris = CmsSite(id_org=org.id_org, site_name="Boutique Paris")
    db_session.add_all([lyon, paris])
    await db_session.flush()
    db_session.add_all([
        CmsPlayer(id_org=org.id_org, player_name="Vitrine XKD", player_os="linux",
                  id_site=lyon.id_site, status="online"),
        CmsPlayer(id_org=org.id_org, player_name="Vitrine XKD", player_os="linux",
                  id_site=paris.id_site, status="online"),
        CmsPlayer(id_org=org.id_org, player_name="Vitrine XKD stock", player_os="linux",
                  status="online"),
    ])
    await db_session.commit()

    r = await client.get("/api/v1/search", params={"q": "Vitrine XKD"},
                         headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    subs = sorted(i["sublabel"] for i in _items(r.json(), "player"))
    assert subs == ["Boutique Lyon", "Boutique Paris", "linux"]  # repli sur l'OS sans site


# ── Campagnes : l'annonceur ────────────────────────────────────────────────────

async def test_campaigns_are_told_apart_by_their_advertiser(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization
) -> None:
    """« Soldes été » chez deux annonceurs : c'est le nom de l'annonceur qui tranche."""
    token = await _token(client, db_session, org, [("campaigns", "read")])

    a1 = CmsAdvertiser(id_org=org.id_org, advertiser_name="Dyson")
    a2 = CmsAdvertiser(id_org=org.id_org, advertiser_name="Nespresso")
    db_session.add_all([a1, a2])
    await db_session.flush()
    from datetime import date, timedelta
    today = date.today()
    for adv in (a1, a2):
        db_session.add(CmsCampaign(
            id_org=org.id_org, id_advertiser=adv.id_advertiser,
            campaign_name="Soldes WXY", starts_on=today,
            ends_on=today + timedelta(days=7),
        ))
    await db_session.commit()

    r = await client.get("/api/v1/search", params={"q": "Soldes WXY"},
                         headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert sorted(i["sublabel"] for i in _items(r.json(), "campaign")) == ["Dyson", "Nespresso"]


# ── Le chemin lisible est partagé, il ne peut pas diverger ─────────────────────

def test_folder_paths_are_computed_by_the_shared_service() -> None:
    """`folder_full_paths` sert au tiroir de classement ET à la recherche : deux
    implémentations finiraient par afficher deux chemins différents pour le même dossier.
    On fige aussi le garde-fou : un parent absent rend le nom seul, jamais une exception."""
    racine = CmsMediaFolder(id_folder=1, id_org=1, folder_name="Video", depth=0, path="1")
    enfant = CmsMediaFolder(id_folder=2, id_org=1, folder_name="Promo", parent_id=1,
                            depth=1, path="1.2")
    orphelin = CmsMediaFolder(id_folder=3, id_org=1, folder_name="Perdu", parent_id=99,
                              depth=1, path="99.3")
    paths = folder_full_paths([racine, enfant, orphelin])
    assert paths == {1: "Video", 2: "Video / Promo", 3: "Perdu"}
