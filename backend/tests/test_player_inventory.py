"""Tests de l'inventaire média par player (F2).

- service `expected_media` : union des médias VIDÉO/IMAGE programmés (schedule + event),
  audio/supprimés/bloqués exclus.
- endpoint `GET /players/{id}/inventory` : croise le programme planifié avec le cache
  remonté (`capabilities.store`) → statut cached / downloading / missing + résumé.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.player import CmsPlayer
from app.models.playlist import CmsPlaylist, CmsPlaylistItem
from app.models.role import CmsPermission, CmsRole, CmsRolePermission, CmsUserRoleAssignment
from app.models.schedule import CmsSchedule, CmsScheduleTarget
from app.models.user import CmsUser
from app.services.player_inventory import expected_media


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="INV", org_slug=f"inv-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    return o


async def _media(db, org, name, mtype="video", deleted=False, blocked=False):
    m = CmsMedia(id_org=org.id_org, media_name=name, media_type=mtype,
                 mime_type=f"{mtype}/mp4", storage_key=f"k/{uuid.uuid4().hex}",
                 checksum_sha256=uuid.uuid4().hex, is_deleted=deleted, is_blocked=blocked)
    db.add(m)
    await db.flush()
    return m


async def _scene(db, org, medias):
    """Player + playlist (contenant `medias`) + schedule ciblant le player."""
    player = CmsPlayer(id_org=org.id_org, player_name="inv", player_os="linux")
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="Prog")
    db.add_all([player, pl])
    await db.flush()
    for i, m in enumerate(medias):
        db.add(CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=m.id_media,
                               sort_order=i, duration_ms=5000))
    sched = CmsSchedule(id_org=org.id_org, schedule_name="S", schedule_kind="content",
                        id_playlist=pl.id_playlist)
    db.add(sched)
    await db.flush()
    db.add(CmsScheduleTarget(id_schedule=sched.id_schedule, target_type="player",
                             target_id=player.id_player))
    await db.commit()
    return player, pl


@pytest.mark.asyncio
async def test_expected_media_video_image_only(db_session, org):
    vid1 = await _media(db_session, org, "a-vid", "video")
    vid2 = await _media(db_session, org, "b-vid", "video")
    img = await _media(db_session, org, "c-img", "image")
    aud = await _media(db_session, org, "d-aud", "audio")   # exclu (offline-first ne cache pas l'audio)
    player, _ = await _scene(db_session, org, [vid1, vid2, img, aud])

    exp = await expected_media(db_session, player.id_player)
    ids = {m["id_media"] for m in exp}
    assert ids == {vid1.id_media, vid2.id_media, img.id_media}      # audio absent
    assert all("Prog" in m["refs"] for m in exp)                    # source = playlist


@pytest.mark.asyncio
async def test_expected_media_includes_document(db_session, org):
    """Le PDF/document est caché par l'offline-first → doit figurer dans l'inventaire."""
    doc = await _media(db_session, org, "leaflet.pdf", "document")
    player, _ = await _scene(db_session, org, [doc])
    ids = {m["id_media"] for m in await expected_media(db_session, player.id_player)}
    assert doc.id_media in ids


@pytest.mark.asyncio
async def test_expected_media_excludes_blocked_and_deleted(db_session, org):
    ok = await _media(db_session, org, "ok", "video")
    blk = await _media(db_session, org, "blocked", "video", blocked=True)
    dele = await _media(db_session, org, "deleted", "video", deleted=True)
    player, _ = await _scene(db_session, org, [ok, blk, dele])

    ids = {m["id_media"] for m in await expected_media(db_session, player.id_player)}
    assert ids == {ok.id_media}


@pytest.mark.asyncio
async def test_expected_media_includes_basket_audio(db_session, org):
    from app.models.audio_basket import CmsAudioBasket, CmsAudioBasketItem
    from app.models.schedule import CmsScheduleBasket
    aud = await _media(db_session, org, "track", "audio")
    player = CmsPlayer(id_org=org.id_org, player_name="audio-pl", player_os="linux")
    basket = CmsAudioBasket(id_org=org.id_org, basket_name="Lounge", basket_type="music")
    db_session.add_all([player, basket])
    await db_session.flush()
    db_session.add(CmsAudioBasketItem(id_basket=basket.id_basket, id_media=aud.id_media))
    sched = CmsSchedule(id_org=org.id_org, schedule_name="AudioSched", schedule_kind="audio")
    db_session.add(sched)
    await db_session.flush()
    db_session.add(CmsScheduleBasket(id_schedule=sched.id_schedule, id_basket=basket.id_basket))
    db_session.add(CmsScheduleTarget(id_schedule=sched.id_schedule, target_type="player",
                                     target_id=player.id_player))
    await db_session.commit()

    exp = await expected_media(db_session, player.id_player)
    assert len(exp) == 1
    assert exp[0]["id_media"] == aud.id_media
    assert exp[0]["media_type"] == "audio"
    assert any("Lounge" in r for r in exp[0]["refs"])   # ref = nom du panier


@pytest.mark.asyncio
async def test_expected_media_includes_basket_of_site_targeted_audio_event(db_session, org):
    """Un event AUDIO ciblant un SITE doit faire pré-cacher son panier par les écrans du site.

    🔴 Prouvé rouge avant correctif (2026-07-30) : le matcher inline des events audio de
    `player_inventory` ne connaissait que org/player/group — `site` et `site_group` étaient
    ignorés EN SILENCE. Même classe de défaut que la cible `site` absente du résolveur de
    force_sync (29/07) : l'event aurait diffusé, mais sur un panier jamais pré-téléchargé
    (faux « média manquant »). Corrigé en déléguant au matcher canonique
    `targeting.event_target_matches`.
    """
    from app.models.audio_basket import CmsAudioBasket, CmsAudioBasketItem
    from app.models.event import CmsEvent
    from app.models.organization import CmsSite

    aud = await _media(db_session, org, "site-track", "audio")
    site = CmsSite(id_org=org.id_org, site_name="Magasin-Audio")
    db_session.add(site)
    await db_session.flush()
    player = CmsPlayer(id_org=org.id_org, id_site=site.id_site,
                       player_name="audio-site-pl", player_os="linux")
    basket = CmsAudioBasket(id_org=org.id_org, basket_name="Ambiance", basket_type="music")
    db_session.add_all([player, basket])
    await db_session.flush()
    db_session.add(CmsAudioBasketItem(id_basket=basket.id_basket, id_media=aud.id_media))
    db_session.add(CmsEvent(
        id_org=org.id_org, event_name="Audio-site", event_type="manual", event_kind="audio",
        status="active", id_basket=basket.id_basket,
        target_config={"target_type": "site", "target_ids": [site.id_site]},
    ))
    await db_session.commit()

    exp = await expected_media(db_session, player.id_player)
    ids = {m["id_media"] for m in exp}
    assert aud.id_media in ids
    assert any("Ambiance" in r for m in exp for r in m["refs"])


async def _tag(db, org, ns_key, value):
    """Namespace + valeur de tag (idempotent sur le namespace)."""
    from sqlalchemy import select

    from app.models.tag import CmsTagNamespace, CmsTagValue
    ns = (await db.execute(select(CmsTagNamespace).where(
        CmsTagNamespace.id_org == org.id_org, CmsTagNamespace.namespace_key == ns_key))).scalar_one_or_none()
    if ns is None:
        ns = CmsTagNamespace(id_org=org.id_org, namespace_key=ns_key, label=ns_key)
        db.add(ns)
        await db.flush()
    val = CmsTagValue(id_namespace=ns.id_namespace, tag_value=value, label=value)
    db.add(val)
    await db.flush()
    return ns, val


@pytest.mark.asyncio
async def test_expected_media_applies_player_tag_filter(db_session, org):
    """Mur left/right : contenu tagué pour l'AUTRE côté ne doit pas être « attendu »
    (sinon faux « manquant » alors que le player ne le joue/cache jamais)."""
    from app.models.tag import CmsMediaTagValue, CmsPlayerTagFilter

    left = await _media(db_session, org, "left_fhd30", "video")
    right = await _media(db_session, org, "right_fhd30", "video")
    untagged = await _media(db_session, org, "shared", "video")  # universel → passe partout
    _, t_left = await _tag(db_session, org, "side", "left")
    ns_side, t_right = await _tag(db_session, org, "side", "right")
    db_session.add_all([
        CmsMediaTagValue(id_media=left.id_media, id_tag=t_left.id_tag),
        CmsMediaTagValue(id_media=right.id_media, id_tag=t_right.id_tag),
    ])
    await db_session.flush()
    player, _ = await _scene(db_session, org, [left, right, untagged])
    # Profil de réception du player = côté gauche.
    db_session.add(CmsPlayerTagFilter(
        id_player=player.id_player, id_namespace=ns_side.id_namespace, id_tag=t_left.id_tag))
    await db_session.commit()

    ids = {m["id_media"] for m in await expected_media(db_session, player.id_player)}
    assert ids == {left.id_media, untagged.id_media}   # right exclu (tagué pour l'autre côté)


@pytest.mark.asyncio
async def test_expected_media_empty_for_unprogrammed_player(db_session, org):
    player = CmsPlayer(id_org=org.id_org, player_name="lonely", player_os="linux")
    db_session.add(player)
    await db_session.commit()
    assert await expected_media(db_session, player.id_player) == []


# ── Endpoint ────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def auth(client: AsyncClient, db_session: AsyncSession, org: CmsOrganization) -> str:
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(id_org=org.id_org, email=f"inv-{uid}@t.com",
                   password_hash=hash_password("Password1!"), is_active=True)
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_INV_{uid}", label="Inv", is_system=False)
    db_session.add_all([user, role])
    await db_session.flush()
    await db_session.execute(
        pg_insert(CmsPermission)
        .values(module="players", operation="read", label="players.read")
        .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation"))
    await db_session.flush()
    perm = (await db_session.execute(select(CmsPermission).where(
        CmsPermission.module == "players", CmsPermission.operation == "read"))).scalar_one()
    db_session.add(CmsRolePermission(id_role=role.id_role, id_permission=perm.id_permission))
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    resp = await client.post("/api/v1/auth/login",
                             json={"email": user.email, "password": "Password1!"})
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_inventory_endpoint_crosses_cache(client, db_session, org, auth):
    vid1 = await _media(db_session, org, "cached-one", "video")
    vid2 = await _media(db_session, org, "dl-one", "video")
    vid3 = await _media(db_session, org, "missing-one", "video")
    player, _ = await _scene(db_session, org, [vid1, vid2, vid3])
    # Cache remonté par le player
    player.capabilities = {"store": {
        "cached_ids": [vid1.id_media], "downloading_ids": [vid2.id_media],
        "disk_used_ratio": 0.42, "storage_pressure": False,
    }}
    await db_session.commit()

    r = await client.get(f"/api/v1/players/{player.id_player}/inventory",
                         headers={"Authorization": f"Bearer {auth}"})
    assert r.status_code == 200
    data = r.json()
    assert data["summary"] == {
        "expected": 3, "cached": 1, "downloading": 1, "missing": 1,
        "disk_used_ratio": 0.42, "storage_pressure": False, "reported": True,
    }
    by_id = {it["id_media"]: it["status"] for it in data["items"]}
    assert by_id[vid1.id_media] == "cached"
    assert by_id[vid2.id_media] == "downloading"
    assert by_id[vid3.id_media] == "missing"
    # les manquants remontent en tête (le plus actionnable)
    assert data["items"][0]["status"] == "missing"


@pytest.mark.asyncio
async def test_expected_media_excludes_completed_event(db_session, org):
    """Un event TERMINÉ (`completed` — vrai statut terminal, PAS « ended ») ne doit plus
    faire attendre son média (sinon « missing » à vie dans l'inventaire — bug Ed 2026-07-07).
    Un event actif/inactif (récurrent ré-armable) reste attendu."""
    from app.models.event import CmsEvent

    player = CmsPlayer(id_org=org.id_org, player_name="inv-ev", player_os="linux")
    m_done = await _media(db_session, org, "ev-completed")
    m_live = await _media(db_session, org, "ev-active")
    db_session.add(player)
    await db_session.flush()
    for media, status_ in ((m_done, "completed"), (m_live, "active")):
        db_session.add(CmsEvent(
            id_org=org.id_org, event_name=f"E-{status_}", event_type="manual", event_kind="content",
            status=status_, id_media=media.id_media,
            target_config={"target_type": "player", "target_ids": [player.id_player]},
        ))
    await db_session.commit()

    ids = {m["id_media"] for m in await expected_media(db_session, player.id_player)}
    assert m_live.id_media in ids
    assert m_done.id_media not in ids
