"""Tests Retail Media AUDIO S2 (§2.8 × §XIX, migr 0094) — campagnes de spots audio.

- `audio_spot_basket` : panier synthétique (id -100, jingle/minutes), cadence
  trigger = ceil(60/total spots vendus), poids proportionnels aux spots/h,
  opt-out player, campagne visuelle ignorée, fenêtre quotidienne.
- Greffe payload sync : présent si panier MUSICAL actif, absent sinon ; absent
  pour un player 'content'.
- Cloisonnement : une campagne audio ne sort JAMAIS dans la boucle visuelle
  (campaign_ad_slots) ni dans l'occupation SOV visuelle.
- Inventaire : occupancy-check kind=audio (plafond org défaut 12, spots par ligne,
  achievable_spots_per_hour), devis au tarif audio, publish 409 surbooking +
  overbook_override.
- Créatifs : campagne audio = médias AUDIO uniquement (vidéo → 422) ; visual
  refuse l'audio.
- Rapport : section `spots` (servis vs attendus ; site sans horaires = 24 h/j).
"""

import uuid
from datetime import date, datetime, time as dt_time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.audio_basket import CmsAudioBasket, CmsAudioBasketItem
from app.models.campaign import CmsAdvertiser, CmsCampaign, CmsCampaignCreative, CmsCampaignTarget
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.player import CmsPlayer
from app.models.pop import CmsProofOfPlay
from app.models.role import CmsPermission, CmsRole, CmsRolePermission, CmsUserRoleAssignment
from app.models.schedule import CmsSchedule, CmsScheduleBasket, CmsScheduleRule, CmsScheduleTarget
from app.models.user import CmsUser
from app.services.campaign_audio import AD_BASKET_ID, audio_spot_basket
from app.services.campaign_delivery import campaign_ad_slots
from app.services.campaign_inventory import occupancy_by_player
from app.services.campaign_report import build_campaign_report


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="AudOrg", org_slug=f"aud-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    return o


@pytest_asyncio.fixture
async def headers(db_session: AsyncSession, org: CmsOrganization) -> dict:
    """User avec permissions campaigns:* (la base de test n'a pas le seed 0002)."""
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(id_org=org.id_org, email=f"aud-{uid}@t.com",
                   password_hash=hash_password("Password1!"), is_active=True)
    db_session.add(user)
    await db_session.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_AUD_{uid}", label="Aud", is_system=False)
    db_session.add(role)
    await db_session.flush()
    for op in ("create", "read", "edit", "delete", "publish", "report"):
        await db_session.execute(
            pg_insert(CmsPermission)
            .values(module="campaigns", operation=op, label=f"campaigns.{op}")
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation"))
        await db_session.flush()
        perm = (await db_session.execute(
            select(CmsPermission).where(
                CmsPermission.module == "campaigns", CmsPermission.operation == op)
        )).scalar_one()
        db_session.add(CmsRolePermission(id_role=role.id_role, id_permission=perm.id_permission))
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    return {"Authorization": f"Bearer {create_access_token(user.id_user)}"}


@pytest_asyncio.fixture
async def player(db_session: AsyncSession, org: CmsOrganization) -> CmsPlayer:
    """Player à vocation audio (inventaire audio = player_role audio|mixed)."""
    p = CmsPlayer(id_org=org.id_org, player_name="AudP", player_os="linux",
                  player_role="mixed")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


async def _audio_media(db: AsyncSession, org: CmsOrganization, name: str,
                       dur_ms: int = 20_000) -> CmsMedia:
    m = CmsMedia(id_org=org.id_org, media_name=name, media_type="audio",
                 mime_type="audio/ogg", storage_key=f"audio/{uuid.uuid4().hex}.ogg",
                 checksum_sha256=uuid.uuid4().hex, duration_ms=dur_ms,
                 source="upload", transcode_status="done")
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m


async def _audio_campaign(
    db: AsyncSession, org: CmsOrganization, *, spots: int, status: str = "approved",
    daily_hours: dict | None = None, creative_dur: int = 20_000,
    target: tuple = ("org", None), name: str = "Radio spot",
):
    adv = CmsAdvertiser(id_org=org.id_org, advertiser_name=f"Aud-{uuid.uuid4().hex[:6]}")
    db.add(adv)
    await db.flush()
    camp = CmsCampaign(
        id_org=org.id_org, id_advertiser=adv.id_advertiser, campaign_name=name,
        status=status, campaign_kind="audio", spots_per_hour=spots,
        starts_on=date.today() - timedelta(days=1),
        ends_on=date.today() + timedelta(days=7),
        daily_hours=daily_hours,
    )
    db.add(camp)
    await db.flush()
    media = await _audio_media(db, org, f"spot-{camp.id_campaign}", creative_dur)
    db.add(CmsCampaignCreative(id_org=org.id_org, id_campaign=camp.id_campaign,
                               id_media=media.id_media, weight=1))
    db.add(CmsCampaignTarget(id_org=org.id_org, id_campaign=camp.id_campaign,
                             target_type=target[0], target_id=target[1]))
    await db.commit()
    await db.refresh(camp)
    return camp, media


async def _music_scene(db: AsyncSession, org: CmsOrganization, player: CmsPlayer) -> None:
    """Panier musical actif programmé sur le player (inventaire de diffusion)."""
    m = await _audio_media(db, org, "track", 180_000)
    b = CmsAudioBasket(id_org=org.id_org, basket_name="Fond", basket_type="music")
    db.add(b)
    await db.flush()
    db.add(CmsAudioBasketItem(id_basket=b.id_basket, id_media=m.id_media, weight=1))
    s = CmsSchedule(id_org=org.id_org, schedule_name="Audio prog", schedule_kind="audio")
    db.add(s)
    await db.flush()
    db.add_all([
        CmsScheduleBasket(id_schedule=s.id_schedule, id_basket=b.id_basket, mix_ratio=80),
        CmsScheduleRule(id_schedule=s.id_schedule, rule_type="always"),
        CmsScheduleTarget(id_schedule=s.id_schedule, target_type="player",
                          target_id=player.id_player),
    ])
    await db.commit()


# ⚠️ RELATIF à aujourd'hui, jamais une date en dur : `_audio_campaign` crée la campagne sur
# [today-1, today+7] → un NOW figé sort de la fenêtre dès le lendemain de l'écriture du test
# (constaté le 2026-07-19 : 3 tests rouges depuis le 18/07 avec un NOW au 2026-07-17).
NOW = datetime.combine(date.today(), dt_time(11, 0))
# Même journée, dans la plage horaire 14:00-18:00 des tests de garde `daily_hours`.
NOW_AFTERNOON = datetime.combine(date.today(), dt_time(15, 0))


# ── Compilation du panier synthétique ─────────────────────────────────────────────

async def test_spot_basket_single_campaign(db_session, org, player) -> None:
    camp, media = await _audio_campaign(db_session, org, spots=6)
    basket = await audio_spot_basket(db_session, org.id_org, player.id_player, NOW)
    assert basket is not None
    assert basket["id_basket"] == AD_BASKET_ID
    assert basket["basket_type"] == "jingle"
    assert basket["trigger_mode"] == "minutes"
    assert basket["trigger_value"] == 10          # ceil(60/6)
    assert len(basket["items"]) == 1
    it = basket["items"][0]
    assert it["id_media"] == media.id_media
    assert it["weight"] == 6
    assert it["media_type"] == "audio"
    assert it["campaign"]["id_campaign"] == camp.id_campaign
    assert basket["ducking_config"]["enabled"] is True


async def test_spot_basket_two_campaigns_share_cadence(db_session, org, player) -> None:
    await _audio_campaign(db_session, org, spots=6, name="A")
    await _audio_campaign(db_session, org, spots=3, name="B")
    basket = await audio_spot_basket(db_session, org.id_org, player.id_player, NOW)
    assert basket["trigger_value"] == 7           # ceil(60/9)
    weights = sorted(i["weight"] for i in basket["items"])
    assert weights == [3, 6]                      # parts proportionnelles aux spots/h


async def test_spot_basket_guards(db_session, org, player) -> None:
    # Campagne visuelle → jamais dans le panier audio
    adv = CmsAdvertiser(id_org=org.id_org, advertiser_name="Vis")
    db_session.add(adv)
    await db_session.flush()
    vis = CmsCampaign(id_org=org.id_org, id_advertiser=adv.id_advertiser,
                      campaign_name="Visu", status="approved", campaign_kind="visual",
                      starts_on=date.today() - timedelta(days=1),
                      ends_on=date.today() + timedelta(days=7))
    db_session.add(vis)
    await db_session.flush()
    db_session.add(CmsCampaignTarget(id_org=org.id_org, id_campaign=vis.id_campaign,
                                     target_type="org", target_id=None))
    await db_session.commit()
    assert await audio_spot_basket(db_session, org.id_org, player.id_player, NOW) is None

    # Fenêtre quotidienne : spot hors fenêtre → absent
    await _audio_campaign(db_session, org, spots=6,
                          daily_hours={"start": "14:00", "end": "18:00"})
    assert await audio_spot_basket(db_session, org.id_org, player.id_player, NOW) is None
    assert (await audio_spot_basket(
        db_session, org.id_org, player.id_player, NOW_AFTERNOON)) is not None

    # Opt-out player → rien
    player.campaigns_optout = True
    await db_session.commit()
    assert await audio_spot_basket(
        db_session, org.id_org, player.id_player, NOW_AFTERNOON) is None


async def test_audio_campaign_never_in_visual_paths(db_session, org, player) -> None:
    camp, _ = await _audio_campaign(db_session, org, spots=6)
    # Boucle visuelle : aucune injection
    slots = await campaign_ad_slots(db_session, org.id_org, player.id_player, NOW, 120_000)
    assert slots == []
    # Occupation SOV visuelle : la campagne audio ne compte pas
    occ = await occupancy_by_player(db_session, org.id_org,
                                    camp.starts_on, camp.ends_on)
    assert occ.get(player.id_player) is None


# ── Greffe dans le payload sync ───────────────────────────────────────────────────

async def test_sync_payload_grafts_spot_basket_with_music(db_session, org, player) -> None:
    from app.api.v1.endpoints.ws import _build_sync_payload

    await _music_scene(db_session, org, player)
    await _audio_campaign(db_session, org, spots=6)
    payload = await _build_sync_payload(db_session, player.id_player)
    ids = [b["id_basket"] for b in payload["audio_baskets"]]
    assert AD_BASKET_ID in ids                    # panier spots greffé (musique présente)

    # Sans panier musical (schedule supprimé) → panier spots ABSENT
    await db_session.execute(
        CmsSchedule.__table__.update().values(is_active=False)
        .where(CmsSchedule.id_org == org.id_org))
    await db_session.commit()
    payload = await _build_sync_payload(db_session, player.id_player)
    assert all(b["id_basket"] != AD_BASKET_ID for b in payload["audio_baskets"])


async def test_sync_payload_content_player_gets_nothing(db_session, org) -> None:
    from app.api.v1.endpoints.ws import _build_sync_payload

    p = CmsPlayer(id_org=org.id_org, player_name="Visu", player_os="linux",
                  player_role="content")
    db_session.add(p)
    await db_session.commit()
    await _audio_campaign(db_session, org, spots=6)
    payload = await _build_sync_payload(db_session, p.id_player)
    assert payload["audio_baskets"] == []


# ── Inventaire / occupancy-check / devis / publish ────────────────────────────────

async def test_occupancy_check_audio(client: AsyncClient, db_session, org, headers, player) -> None:
    camp, _ = await _audio_campaign(db_session, org, spots=8)   # 8/12 déjà vendus
    body = {
        "starts_on": date.today().isoformat(),
        "ends_on": (date.today() + timedelta(days=3)).isoformat(),
        "campaign_kind": "audio",
        "spots_per_hour": 6,
        "targets": [{"target_type": "org"}],
    }
    r = await client.post("/api/v1/campaigns/occupancy-check", headers=headers, json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["blocked"] is True                # 8 + 6 = 14 > 12 (plafond org défaut)
    row = data["players"][0]
    assert row["current_spots"] == 8 and row["projected_spots"] == 14
    assert row["cap_spots"] == 12
    assert data["achievable_spots_per_hour"] == 4  # 12 - 8
    assert data["price"] is None                   # aucun tarif audio configuré

    # Tarif audio org → devis = rate × spots × jours × écrans
    org.campaign_audio_spot_daily_rate = 2.5
    await db_session.commit()
    r = await client.post("/api/v1/campaigns/occupancy-check", headers=headers, json={
        **body, "spots_per_hour": 4})
    data = r.json()
    assert data["blocked"] is False
    assert data["price"]["estimated_price"] == 2.5 * 4 * 4   # 4 jours, 1 player


async def test_publish_audio_overbook_409_and_override(
    client: AsyncClient, db_session, org, headers, player,
) -> None:
    await _audio_campaign(db_session, org, spots=8)                       # approved
    camp2, _ = await _audio_campaign(db_session, org, spots=6, status="draft")
    r = await client.post(f"/api/v1/campaigns/{camp2.id_campaign}/status",
                          headers=headers, json={"action": "publish"})
    assert r.status_code == 409                    # 8 + 6 > 12
    assert "spots" in r.json()["detail"]
    camp2.overbook_override = True
    await db_session.commit()
    r = await client.post(f"/api/v1/campaigns/{camp2.id_campaign}/status",
                          headers=headers, json={"action": "publish"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] in ("approved", "live")


async def test_creative_type_gates(client: AsyncClient, db_session, org, headers, player) -> None:
    camp, _ = await _audio_campaign(db_session, org, spots=6, status="draft")
    video = CmsMedia(id_org=org.id_org, media_name="clip", media_type="video",
                     storage_key=f"v/{uuid.uuid4().hex}.mp4", checksum_sha256="v",
                     transcode_status="done", duration_ms=15_000)
    db_session.add(video)
    await db_session.commit()
    r = await client.post(f"/api/v1/campaigns/{camp.id_campaign}/creatives",
                          headers=headers, json={"id_media": video.id_media})
    assert r.status_code == 422                    # vidéo interdite en campagne audio
    audio = await _audio_media(db_session, org, "jingle-ok", 15_000)
    r = await client.post(f"/api/v1/campaigns/{camp.id_campaign}/creatives",
                          headers=headers, json={"id_media": audio.id_media})
    assert r.status_code == 201, r.text
    # Et une campagne VISUELLE refuse un média audio
    adv = CmsAdvertiser(id_org=org.id_org, advertiser_name="V2")
    db_session.add(adv)
    await db_session.flush()
    vis = CmsCampaign(id_org=org.id_org, id_advertiser=adv.id_advertiser,
                      campaign_name="V", status="draft", campaign_kind="visual",
                      starts_on=date.today(), ends_on=date.today() + timedelta(days=3))
    db_session.add(vis)
    await db_session.commit()
    r = await client.post(f"/api/v1/campaigns/{vis.id_campaign}/creatives",
                          headers=headers, json={"id_media": audio.id_media})
    assert r.status_code == 422


async def test_create_audio_campaign_requires_spots(
    client: AsyncClient, db_session, org, headers,
) -> None:
    adv = CmsAdvertiser(id_org=org.id_org, advertiser_name="ReqSpots")
    db_session.add(adv)
    await db_session.commit()
    body = {
        "id_advertiser": adv.id_advertiser, "campaign_name": "NoSpots",
        "starts_on": date.today().isoformat(),
        "ends_on": (date.today() + timedelta(days=3)).isoformat(),
        "campaign_kind": "audio",
        "targets": [{"target_type": "org"}],
    }
    r = await client.post("/api/v1/campaigns/", headers=headers, json=body)
    assert r.status_code == 422                    # spots_per_hour requis
    r = await client.post("/api/v1/campaigns/", headers=headers,
                          json={**body, "spots_per_hour": 6})
    assert r.status_code == 201, r.text
    assert r.json()["campaign_kind"] == "audio"
    assert r.json()["spots_per_hour"] == 6


# ── Rapport : spots servis vs attendus ────────────────────────────────────────────

async def test_report_spots_section(db_session, org, player) -> None:
    camp, media = await _audio_campaign(db_session, org, spots=2)
    when = datetime.now(timezone.utc) - timedelta(hours=2)
    for _ in range(5):
        db_session.add(CmsProofOfPlay(id_org=org.id_org, id_player=player.id_player,
                                      id_media=media.id_media, played_at=when,
                                      duration_ms=20_000, merkle_hash="h"))
    await db_session.commit()
    rep = await build_campaign_report(db_session, camp, ZoneInfo("Europe/Paris"))
    sp = rep["spots"]
    assert sp is not None
    assert sp["sold_per_hour"] == 2 and sp["served"] == 5
    # Player sans site (pas d'horaires) = 24 h/j → 2 spots/h × 24 h × nb jours écoulés
    days = (min(camp.ends_on, date.today()) - camp.starts_on).days + 1
    assert sp["expected"] == 2 * 24 * days
    assert rep["campaign"]["campaign_kind"] == "audio"
