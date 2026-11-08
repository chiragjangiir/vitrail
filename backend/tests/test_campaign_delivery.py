"""Tests Retail Media S3 (§2.8) — diffusion : compilation campagnes → boucle de sync.

- in_daily_window : pas de fenêtre / dedans / dehors / à cheval sur minuit.
- splice_ad_items : positions fractionnaires, renumérotation, reliquat en fin de boucle.
- campaign_ad_slots : campagne live ciblant le player → slots (≥1, positions [0,1)) ;
  paused / hors fenêtre / hors cible / sans créatif → rien ; rotation pondérée
  déterministe par jour ; plafond max_plays_per_hour.
- intégration _resolve_sync_payload : créatifs intercalés dans la boucle du schedule
  (marqueur `campaign`, PoP-ready), wall-clock calculé sur la liste FINALE ; un event
  actif (takeover) n'est PAS pollué par la pub.
"""

import uuid
from datetime import date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.v1.endpoints.ws as ws
from app.api.v1.endpoints.ws import _resolve_sync_payload
from app.models.campaign import CmsAdvertiser, CmsCampaign, CmsCampaignCreative, CmsCampaignTarget
from app.models.event import CmsEvent
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.player import CmsPlayer
from app.models.playlist import CmsPlaylist, CmsPlaylistItem
from app.models.schedule import CmsSchedule, CmsScheduleRule, CmsScheduleTarget
from app.services.campaign_delivery import (
    AdSlot,
    campaign_ad_slots,
    in_daily_window,
    splice_ad_items,
)


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="RMD", org_slug=f"rmd-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    return o


async def _scene(db: AsyncSession, org: CmsOrganization):
    """Player + playlist maison (2 vidéos de 30 s) + schedule always ciblant le player."""
    player = CmsPlayer(id_org=org.id_org, player_name="P", player_os="linux")
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="PL", sync_mode="wall_clock")
    db.add_all([player, pl])
    await db.flush()
    m1 = CmsMedia(id_org=org.id_org, media_name="home1", media_type="video",
                  storage_key=f"t/{uuid.uuid4().hex}.mp4", checksum_sha256="a",
                  transcode_status="done", duration_ms=30_000)
    m2 = CmsMedia(id_org=org.id_org, media_name="home2", media_type="video",
                  storage_key=f"t/{uuid.uuid4().hex}.mp4", checksum_sha256="b",
                  transcode_status="done", duration_ms=30_000)
    db.add_all([m1, m2])
    await db.flush()
    db.add_all([
        CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=m1.id_media, sort_order=0,
                        duration_ms=30_000),
        CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=m2.id_media, sort_order=1,
                        duration_ms=30_000),
    ])
    sched = CmsSchedule(id_org=org.id_org, schedule_name="S", schedule_kind="content",
                        id_playlist=pl.id_playlist, is_active=True)
    db.add(sched)
    await db.flush()
    db.add_all([
        CmsScheduleRule(id_schedule=sched.id_schedule, rule_type="always"),
        CmsScheduleTarget(id_schedule=sched.id_schedule, target_type="player",
                          target_id=player.id_player),
    ])
    await db.commit()
    return player, m1, m2


async def _campaign(
    db: AsyncSession, org: CmsOrganization, *, sov=10.0, status="approved",
    daily_hours=None, max_pph=None, creatives=(("spot", 15_000, 1),),
    target=("org", None),
):
    """Campagne + annonceur + créatifs (nom, durée, weight) + cible."""
    adv = CmsAdvertiser(id_org=org.id_org, advertiser_name=f"Acme-{uuid.uuid4().hex[:6]}")
    db.add(adv)
    await db.flush()
    camp = CmsCampaign(
        id_org=org.id_org, id_advertiser=adv.id_advertiser,
        campaign_name="Été", status=status,
        starts_on=date.today() - timedelta(days=1),
        ends_on=date.today() + timedelta(days=7),
        sov_percent=sov, daily_hours=daily_hours, max_plays_per_hour=max_pph,
    )
    db.add(camp)
    await db.flush()
    media_ids = []
    for name, dur, weight in creatives:
        m = CmsMedia(id_org=org.id_org, media_name=name, media_type="video",
                     storage_key=f"t/{uuid.uuid4().hex}.mp4", checksum_sha256="c",
                     transcode_status="done", duration_ms=dur)
        db.add(m)
        await db.flush()
        db.add(CmsCampaignCreative(
            id_org=org.id_org, id_campaign=camp.id_campaign, id_media=m.id_media,
            duration_ms=dur, weight=weight,
        ))
        media_ids.append(m.id_media)
    db.add(CmsCampaignTarget(
        id_org=org.id_org, id_campaign=camp.id_campaign,
        target_type=target[0], target_id=target[1],
    ))
    await db.commit()
    return camp, media_ids


# ── Fenêtre quotidienne (pure) ────────────────────────────────────────────────


def test_daily_window():
    at = lambda h: datetime(2026, 7, 9, h, 30)  # noqa: E731
    assert in_daily_window(None, at(3))
    assert in_daily_window({}, at(3))
    assert in_daily_window({"start": "09:00", "end": "20:00"}, at(10))
    assert not in_daily_window({"start": "09:00", "end": "20:00"}, at(21))
    assert not in_daily_window({"start": "09:00", "end": "20:00"}, at(8))
    # À cheval sur minuit : 22:00 → 06:00
    assert in_daily_window({"start": "22:00", "end": "06:00"}, at(23))
    assert in_daily_window({"start": "22:00", "end": "06:00"}, at(3))
    assert not in_daily_window({"start": "22:00", "end": "06:00"}, at(12))


# ── Splice (pur) ──────────────────────────────────────────────────────────────


def _item(name: str, ms: int) -> dict:
    return {"sort_order": 0, "duration_ms": ms, "media": {"media_name": name}}


def test_splice_positions_and_renumber():
    home = [_item("h1", 30_000), _item("h2", 30_000), _item("h3", 30_000)]
    slot = AdSlot(id_campaign=1, id_creative=1, id_media=9, duration_ms=15_000, position=0.5)
    out = splice_ad_items(home, [(slot, _item("ad", 15_000))])
    names = [i["media"]["media_name"] for i in out]
    # position 0.5 × 90 s = 45 s → après h2 (cumul 60 s ≥ 45 s)
    assert names == ["h1", "h2", "ad", "h3"]
    assert [i["sort_order"] for i in out] == [0, 1, 2, 3]


def test_splice_no_back_to_back_overflow_dropped():
    """Anti-martèlement (bug NUC 12/07) : au plus UNE pub par frontière — l'excédent
    est abandonné plutôt qu'enchaîné dos à dos (l'ancien splice mettait le reliquat
    en fin de boucle → 2 pubs consécutives)."""
    home = [_item("h1", 30_000)]
    slots = [
        (AdSlot(1, 1, 9, 10_000, position=0.2), _item("ad1", 10_000)),
        (AdSlot(1, 2, 9, 10_000, position=0.9), _item("ad2", 10_000)),
    ]
    out = splice_ad_items(home, slots)
    assert [i["media"]["media_name"] for i in out] == ["h1", "ad1"]


def test_splice_never_two_ads_adjacent_nuc_case():
    """Cas réel NUC (campagne 8) : 6 vidéos maison LONGUES + 29 slots (SOV 25 %,
    spot 10 s) → l'ancien splice produisait des paquets de 4-6 pubs consécutives
    (confirmé PoP). Désormais : 1 pub max par frontière, jamais 2 adjacentes."""
    home = [_item(f"h{i}", ms) for i, ms in enumerate(
        [142_560, 129_880, 155_320, 156_520, 118_840, 171_760])]
    slots = [
        (AdSlot(8, 7, 162, 10_041, position=(k + 0.5) / 29), _item("ad", 10_041))
        for k in range(29)
    ]
    out = splice_ad_items(home, slots)
    names = [i["media"]["media_name"] for i in out]
    assert names.count("ad") == 6                       # 1 par frontière, excédent abandonné
    for a, b in zip(names, names[1:]):
        assert not (a == "ad" and b == "ad"), "deux pubs dos à dos"
    # collision au même point : la 2e glisse à la frontière libre suivante
    home2 = [_item("h1", 60_000), _item("h2", 60_000), _item("h3", 60_000)]
    slots2 = [
        (AdSlot(1, 1, 9, 5_000, position=0.10), _item("adA", 5_000)),
        (AdSlot(2, 2, 8, 5_000, position=0.12), _item("adB", 5_000)),
    ]
    out2 = splice_ad_items(home2, slots2)
    assert [i["media"]["media_name"] for i in out2] == ["h1", "adA", "h2", "adB", "h3"]


# ── campaign_ad_slots (DB) ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_slots_live_campaign(db_session, org):
    player, *_ = await _scene(db_session, org)
    camp, media_ids = await _campaign(db_session, org, sov=10.0)
    slots = await campaign_ad_slots(db_session, org.id_org, player.id_player,
                                    datetime.now(), 60_000)
    assert slots, "campagne live ciblant l'org → au moins un slot"
    assert all(s.id_media == media_ids[0] for s in slots)
    assert all(0.0 <= s.position < 1.0 for s in slots)
    # SOV 10 %, boucle 60 s, créatif 15 s → T = 60/0.9 ≈ 66,7 s → n = round(0.44) → min 1
    assert len(slots) == 1


@pytest.mark.asyncio
async def test_slots_excluded_cases(db_session, org):
    player, *_ = await _scene(db_session, org)
    now = datetime.now()
    # paused → rien
    await _campaign(db_session, org, status="paused")
    assert await campaign_ad_slots(db_session, org.id_org, player.id_player, now, 60_000) == []
    # fenêtre quotidienne fermée → rien
    closed = {"start": "00:00", "end": "00:01"} if now.strftime("%H:%M") > "00:01" \
        else {"start": "23:58", "end": "23:59"}
    await _campaign(db_session, org, daily_hours=closed)
    assert await campaign_ad_slots(db_session, org.id_org, player.id_player, now, 60_000) == []
    # cible = un AUTRE player → rien
    other = CmsPlayer(id_org=org.id_org, player_name="Other", player_os="linux")
    db_session.add(other)
    await db_session.flush()
    await db_session.commit()
    await _campaign(db_session, org, target=("player", other.id_player))
    assert await campaign_ad_slots(db_session, org.id_org, player.id_player, now, 60_000) == []


@pytest.mark.asyncio
async def test_optout_player_gets_no_ads(db_session, org):
    """`campaigns_optout` (migr 0075) : le player marqué ne reçoit JAMAIS de créatif,
    même ciblé via l'org, et sort de la projection d'occupation (pas de l'inventaire)."""
    from app.services.campaign_inventory import check_campaign_occupancy
    from app.services.targeting import Target

    player, *_ = await _scene(db_session, org)
    await _campaign(db_session, org, sov=40.0)
    now = datetime.now()
    assert await campaign_ad_slots(db_session, org.id_org, player.id_player, now, 60_000)

    player.campaigns_optout = True
    await db_session.commit()
    assert await campaign_ad_slots(db_session, org.id_org, player.id_player, now, 60_000) == []
    occ = await check_campaign_occupancy(
        db_session, org.id_org, starts_on=now.date(), ends_on=now.date(),
        sov_percent=10.0, targets=[Target(target_type="player", target_id=player.id_player)],
    )
    assert occ["players"] == [], "un player exclu n'est pas de l'inventaire"

    player.campaigns_optout = False
    await db_session.commit()


@pytest.mark.asyncio
async def test_slots_weighted_rotation_deterministic(db_session, org):
    player, *_ = await _scene(db_session, org)
    camp, media_ids = await _campaign(
        db_session, org, sov=50.0,
        creatives=(("a", 10_000, 2), ("b", 10_000, 1)),
    )
    now = datetime.now()
    # SOV 50 %, boucle 120 s → T = 240 s, temps pub 120 s, d=10 s → n = 12
    slots1 = await campaign_ad_slots(db_session, org.id_org, player.id_player, now, 120_000)
    slots2 = await campaign_ad_slots(db_session, org.id_org, player.id_player, now, 120_000)
    assert len(slots1) == 12
    assert [s.id_creative for s in slots1] == [s.id_creative for s in slots2], "déterministe"
    counts = {mid: sum(1 for s in slots1 if s.id_media == mid) for mid in media_ids}
    assert counts[media_ids[0]] == 8 and counts[media_ids[1]] == 4, "rotation 2:1"


@pytest.mark.asyncio
async def test_slots_max_plays_per_hour_cap(db_session, org):
    player, *_ = await _scene(db_session, org)
    await _campaign(db_session, org, sov=50.0, max_pph=30,
                    creatives=(("a", 10_000, 1),))
    # Boucle 1 h : SOV 50 % → n brut = 360 ; plafond 30/h × T(2 h) = 60
    slots = await campaign_ad_slots(db_session, org.id_org, player.id_player,
                                    datetime.now(), 3_600_000)
    assert len(slots) == 60


# ── Intégration sync payload ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_payload_injects_creatives(db_session, org, monkeypatch):
    monkeypatch.setattr(ws, "get_signed_url", lambda key, ttl=86400: f"https://minio.test/{key}")
    player, m1, m2 = await _scene(db_session, org)

    # Sans campagne : boucle maison seule.
    payload = await _resolve_sync_payload(db_session, player.id_player)
    assert [i["media"]["id_media"] for i in payload["items"]] == [m1.id_media, m2.id_media]

    # Campagne SOV 40 % (créatif 15 s, boucle 60 s) → T ≈ 100 s → n brut = 3, mais
    # anti-martèlement (12/07) : 2 items maison = 2 frontières → 2 pubs max, jamais
    # dos à dos (le sous-service est mesuré S4 / alerté underserved).
    camp, media_ids = await _campaign(db_session, org, sov=40.0)
    payload = await _resolve_sync_payload(db_session, player.id_player)
    ads = [i for i in payload["items"] if i.get("campaign")]
    assert len(ads) == 2
    kinds = ["ad" if i.get("campaign") else "home" for i in payload["items"]]
    for a, b in zip(kinds, kinds[1:]):
        assert not (a == "ad" and b == "ad"), "deux pubs dos à dos"
    assert all(a["media"]["id_media"] == media_ids[0] for a in ads)
    assert all(a["campaign"]["id_campaign"] == camp.id_campaign for a in ads)
    assert all(a["media"]["url"] for a in ads), "créatif = item média normal (URL signée)"
    # La maison reste dans l'ordre, la liste finale est renumérotée.
    homes = [i["media"]["id_media"] for i in payload["items"] if not i.get("campaign")]
    assert homes == [m1.id_media, m2.id_media]
    assert [i["sort_order"] for i in payload["items"]] == list(range(len(payload["items"])))
    # Wall-clock calculé sur la liste FINALE (playlist wall_clock → position définie).
    assert payload["start_index"] is not None

    # Campagne mise en pause → la boucle redevient maison seule.
    camp.status = "paused"
    await db_session.commit()
    payload = await _resolve_sync_payload(db_session, player.id_player)
    assert [i["media"]["id_media"] for i in payload["items"]] == [m1.id_media, m2.id_media]


@pytest.mark.asyncio
async def test_event_takeover_has_no_ads(db_session, org, monkeypatch):
    """Un event actif (takeover) garde l'exclusivité : pas d'injection pub."""
    monkeypatch.setattr(ws, "get_signed_url", lambda key, ttl=86400: f"https://minio.test/{key}")
    player, m1, m2 = await _scene(db_session, org)
    await _campaign(db_session, org, sov=40.0)

    ev_pl = CmsPlaylist(id_org=org.id_org, playlist_name="EV", sync_mode="wall_clock")
    db_session.add(ev_pl)
    await db_session.flush()
    db_session.add(CmsPlaylistItem(id_playlist=ev_pl.id_playlist, id_media=m1.id_media,
                                   sort_order=0, duration_ms=30_000))
    db_session.add(CmsEvent(
        id_org=org.id_org, event_name="Takeover", event_type="manual",
        event_kind="content", status="active",
        id_playlist=ev_pl.id_playlist, target_config={"target_type": "org"}, priority=100,
    ))
    await db_session.commit()

    payload = await _resolve_sync_payload(db_session, player.id_player)
    assert payload.get("id_event"), "l'event doit prendre la main"
    assert all(not i.get("campaign") for i in payload["items"])
