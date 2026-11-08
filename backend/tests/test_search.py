"""
Tests de la recherche globale (barre topbar) — GET /search.

Couvre les correctifs de l'audit 2026-07-18 :
  - RBAC : plus de gate org-admin ; chaque catégorie est filtrée par sa permission
    de lecture (un non-admin obtient 200 avec seulement ce qu'il peut consulter)
  - champs secondaires : IP / MAC / OS d'un player, description de playlist,
    numéro et pays d'un site (les colonnes INET/MACADDR exigent un cast text)
  - nouveau type `advertiser` + exclusion des annonceurs soft-deleted
  - propagation du terme en `?q=` dans le href (pré-remplissage de la barre locale)
  - isolation multi-tenant (une autre org ne remonte jamais)
"""

import uuid

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.campaign import CmsAdvertiser
from app.models.media import CmsMedia
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


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="SearchOrg", org_slug=f"search-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


async def _make_user(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization,
    perms: list[tuple[str, str]],
) -> str:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=org.id_org, email=f"s-{uid}@test.com",
        password_hash=hash_password("Password1!"), is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_S_{uid}", label="S", is_system=False)
    db_session.add(role)
    await db_session.flush()
    for module, operation in perms:
        await db_session.execute(
            pg_insert(CmsPermission)
            .values(module=module, operation=operation, label=f"{module}.{operation}")
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
        )
        await db_session.flush()
        perm = (await db_session.execute(
            select(CmsPermission).where(
                CmsPermission.module == module, CmsPermission.operation == operation)
        )).scalar_one()
        db_session.add(CmsRolePermission(id_role=role.id_role, id_permission=perm.id_permission))
    await db_session.flush()
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    resp = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "Password1!"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _kinds(payload: dict) -> set[str]:
    return {g["kind"] for g in payload["groups"]}


def _items(payload: dict, kind: str) -> list[dict]:
    for g in payload["groups"]:
        if g["kind"] == kind:
            return g["items"]
    return []


async def test_non_admin_gets_results_scoped_to_his_permissions(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization
) -> None:
    """Avant le fix : 403 (gate org-admin). Après : 200, mais seulement les catégories
    que l'utilisateur peut lire — ici players (donc players + sites), pas media."""
    token = await _make_user(client, db_session, org, [("players", "read")])

    site = CmsSite(id_org=org.id_org, site_name="Zephyr Store")
    db_session.add(site)
    await db_session.flush()
    db_session.add(CmsPlayer(
        id_org=org.id_org, id_site=site.id_site, player_name="Zephyr Player", status="online"))
    db_session.add(CmsMedia(
        id_org=org.id_org, media_name="Zephyr Clip", media_type="video",
        storage_key=f"test/{uuid.uuid4().hex}.mp4", checksum_sha256=uuid.uuid4().hex,
        transcode_status="done"))
    await db_session.commit()

    resp = await client.get(
        "/api/v1/search", params={"q": "Zephyr"},
        headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    kinds = _kinds(resp.json())
    assert "player" in kinds and "site" in kinds
    assert "media" not in kinds  # pas de media:read → catégorie absente, pas de 403


async def test_player_found_by_ip_and_mac(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization
) -> None:
    """ip_address est en INET et mac_address en MACADDR : sans cast text explicite,
    Postgres n'a pas d'opérateur ILIKE et l'endpoint renvoie 500."""
    token = await _make_user(client, db_session, org, [("players", "read")])
    headers = {"Authorization": f"Bearer {token}"}

    db_session.add(CmsPlayer(
        id_org=org.id_org, player_name="Caisse 3", status="online",
        player_os="linux", ip_address="192.168.1.138", mac_address="aa:bb:cc:dd:ee:ff"))
    await db_session.commit()

    by_ip = await client.get("/api/v1/search", params={"q": "192.168.1.138"}, headers=headers)
    assert by_ip.status_code == 200, by_ip.text
    assert [i["label"] for i in _items(by_ip.json(), "player")] == ["Caisse 3"]

    by_mac = await client.get("/api/v1/search", params={"q": "aa:bb:cc"}, headers=headers)
    assert by_mac.status_code == 200, by_mac.text
    assert [i["label"] for i in _items(by_mac.json(), "player")] == ["Caisse 3"]

    by_os = await client.get("/api/v1/search", params={"q": "linux"}, headers=headers)
    assert [i["label"] for i in _items(by_os.json(), "player")] == ["Caisse 3"]


async def test_playlist_found_by_description_and_site_by_number(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization
) -> None:
    token = await _make_user(
        client, db_session, org, [("playlists", "read"), ("players", "read")])
    headers = {"Authorization": f"Bearer {token}"}

    db_session.add(CmsPlaylist(
        id_org=org.id_org, playlist_name="Boucle A", description="promo rentree"))
    db_session.add(CmsSite(id_org=org.id_org, site_name="Lyon Part-Dieu", site_number="FR-042"))
    await db_session.commit()

    by_desc = await client.get("/api/v1/search", params={"q": "rentree"}, headers=headers)
    assert [i["label"] for i in _items(by_desc.json(), "playlist")] == ["Boucle A"]

    by_num = await client.get("/api/v1/search", params={"q": "FR-042"}, headers=headers)
    items = _items(by_num.json(), "site")
    assert [i["label"] for i in items] == ["Lyon Part-Dieu"]
    assert items[0]["sublabel"] == "FR-042"  # désambiguïsation des homonymes


async def test_advertiser_kind_and_soft_delete_excluded(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization
) -> None:
    token = await _make_user(client, db_session, org, [("campaigns", "read")])
    headers = {"Authorization": f"Bearer {token}"}

    db_session.add(CmsAdvertiser(id_org=org.id_org, advertiser_name="Brightwell France"))
    db_session.add(CmsAdvertiser(
        id_org=org.id_org, advertiser_name="Brightwell Legacy", is_deleted=True))
    await db_session.commit()

    resp = await client.get("/api/v1/search", params={"q": "Brightwell"}, headers=headers)
    assert resp.status_code == 200, resp.text
    labels = [i["label"] for i in _items(resp.json(), "advertiser")]
    assert labels == ["Brightwell France"]  # le soft-deleted ne remonte pas


async def test_href_carries_query_for_local_prefill(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization
) -> None:
    """Le terme est propagé en ?q= (url-encodé) pour que la page d'arrivée
    pré-remplisse sa barre locale au lieu d'une liste nue."""
    token = await _make_user(client, db_session, org, [("players", "read")])
    db_session.add(CmsPlayer(id_org=org.id_org, player_name="Hall Nord", status="online"))
    # Un site homonyme : c'est LUI qui doit porter le `?q=` (categorie qui mene a une LISTE),
    # le player deep-linkant desormais sur sa fiche.
    db_session.add(CmsSite(id_org=org.id_org, site_name="Hall Nord"))
    await db_session.commit()

    resp = await client.get(
        "/api/v1/search", params={"q": "Hall N"},
        headers={"Authorization": f"Bearer {token}"})
    # Le player deep-linke sur sa FICHE (2026-07-19) : le `?q=` reste la regle pour les
    # categories qui atterrissent sur une LISTE (media, campagnes, sites, templates...).
    assert _items(resp.json(), "player")[0]["href"].startswith("/players?open=")
    assert _items(resp.json(), "site")[0]["href"] == "/sites?q=Hall%20N"


async def test_other_org_never_leaks(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization
) -> None:
    token = await _make_user(client, db_session, org, [("players", "read")])

    other = CmsOrganization(org_name="Other", org_slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other)
    await db_session.flush()
    db_session.add(CmsPlayer(
        id_org=other.id_org, player_name="Secret Player", status="online"))
    await db_session.commit()

    resp = await client.get(
        "/api/v1/search", params={"q": "Secret"},
        headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["groups"] == []


async def test_search_covers_schedules_baskets_and_vod(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization
) -> None:
    """Types ajoutés le 2026-07-19 (demande Ed) : programmations, paniers audio, configs VOD.
    La VOD deep-linke sur sa FICHE (`?open=`) : sa page n'a pas de barre de recherche locale."""
    from app.models.audio_basket import CmsAudioBasket
    from app.models.schedule import CmsSchedule
    from app.models.vod import CmsVodConfig

    token = await _make_user(client, db_session, org, [
        ("schedules", "read"), ("audio_baskets", "read"), ("vod", "read")])
    db_session.add_all([
        CmsSchedule(id_org=org.id_org, schedule_name="Zephyr programmation",
                    schedule_kind="content"),
        CmsAudioBasket(id_org=org.id_org, basket_name="Zephyr ambiance", basket_type="music"),
        CmsVodConfig(id_org=org.id_org, vod_name="Zephyr VOD"),
    ])
    await db_session.commit()

    resp = await client.get(
        "/api/v1/search", params={"q": "Zephyr"},
        headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    kinds = {g["kind"] for g in resp.json()["groups"]}
    assert {"schedule", "audio_basket", "vod"} <= kinds, sorted(kinds)
    assert _items(resp.json(), "schedule")[0]["label"] == "Zephyr programmation"
    assert _items(resp.json(), "audio_basket")[0]["sublabel"] == "music"
    # VOD = deep-link vers la FICHE (ouvre le drawer), pas un filtre de liste.
    assert "?open=" in _items(resp.json(), "vod")[0]["href"]
    assert _items(resp.json(), "schedule")[0]["href"].startswith("/schedules?q=")
    assert _items(resp.json(), "audio_basket")[0]["href"].startswith("/audio-baskets?q=")


async def test_new_kinds_respect_their_own_permission(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization
) -> None:
    """Chaque catégorie reste filtrée par SA permission : un utilisateur qui ne peut lire que
    les programmations ne voit ni les paniers audio ni les VOD (même gate que les pages)."""
    from app.models.audio_basket import CmsAudioBasket
    from app.models.schedule import CmsSchedule
    from app.models.vod import CmsVodConfig

    token = await _make_user(client, db_session, org, [("schedules", "read")])
    db_session.add_all([
        CmsSchedule(id_org=org.id_org, schedule_name="Kappa prog", schedule_kind="content"),
        CmsAudioBasket(id_org=org.id_org, basket_name="Kappa panier", basket_type="music"),
        CmsVodConfig(id_org=org.id_org, vod_name="Kappa VOD"),
    ])
    await db_session.commit()

    resp = await client.get(
        "/api/v1/search", params={"q": "Kappa"},
        headers={"Authorization": f"Bearer {token}"})
    kinds = {g["kind"] for g in resp.json()["groups"]}
    assert "schedule" in kinds
    assert "audio_basket" not in kinds and "vod" not in kinds, sorted(kinds)
