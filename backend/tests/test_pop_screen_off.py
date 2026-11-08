"""Proof of Play — preuves émises ÉCRAN COUPÉ (migr 0102).

Constat prod du 2026-07-23 : la fenêtre des programmations (08:00–19:00) et les heures
d'ouverture du site (08:25–19:00 + marge 15 min) sont deux réglages INDÉPENDANTS. Quand
elles divergent, le player continue de jouer sur une sortie vidéo coupée et émettait des
preuves SIGNÉES d'une diffusion que personne n'a vue — comptée comme de l'antenne, et
facturable pour une campagne Retail Media.

Décision Ed : écran coupé = pas de diffusion. La lecture continue (wall-clock/sync LAN
intacts), seul le COMPTAGE change. La preuve reste stockée et dans la chaîne Merkle —
c'est ce qui permet à la fois d'auditer le phénomène et de garder l'attestation
recalculable — mais elle est exclue de tous les agrégats.

Couvre : marquage à l'ingestion, exclusion des agrégats, non-régression de la chaîne,
exemption AUDIO, et les deux gardes qui font répondre « non » par défaut.
"""

import uuid
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, create_player_token, hash_password
from app.models.media import CmsMedia
from app.models.organization import (
    CmsOrganization,
    CmsOrgAuthSettings,
    CmsSite,
    CmsSiteException,
    CmsSiteHours,
)
from app.models.player import CmsPlayer
from app.models.pop import CmsProofOfPlay
from app.models.role import CmsRole, CmsUserRoleAssignment
from app.models.user import CmsUser

# Dates RELATIVES au jour courant : un jour codé en dur finit par sortir des fenêtres
# des endpoints (`/verify?days=` est borné à 365) et la suite devient rouge des mois plus
# tard sans que personne ne l'ait touchée — c'est exactement ce qui était arrivé à
# `test_campaign_audio`. Le site de la fixture ouvre 7 j/7, le jour de la semaine
# n'influe donc sur rien.
DAY = date.today()


def _utc(hh: int, mm: int = 0) -> str:
    """Instant UTC (ISO) correspondant à `hh:mm` HEURE LOCALE DU SITE ce jour-là.

    Passer par la conversion réelle plutôt que par un décalage fixe : sinon le test
    bascule d'une heure entre l'été et l'hiver.
    """
    local = datetime.combine(DAY, time(hh, mm), tzinfo=ZoneInfo("Europe/Paris"))
    return local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# Site ouvert 08:00–19:00 avec marges de 15 min ⇒ écran allumé 07:45 → 19:15 locales.
OFF_MORNING = _utc(6, 0)    # 06:00 — avant l'allumage
ON_MIDDAY = _utc(12, 0)     # 12:00 — pleine ouverture
OFF_EVENING = _utc(20, 0)   # 20:00 — après l'extinction


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="ScreenOffOrg", org_slug=f"so-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def site(db_session: AsyncSession, org: CmsOrganization) -> CmsSite:
    """Site auto-power, ouvert tous les jours 08:00–19:00, fuseau Paris."""
    s = CmsSite(
        id_org=org.id_org, site_name="Boutique", timezone="Europe/Paris",
        auto_power_enabled=True, power_lead_min=15, power_lag_min=15,
        respect_holidays=False, holiday_region="FR",
    )
    db_session.add(s)
    await db_session.flush()
    for wd in range(7):
        db_session.add(CmsSiteHours(
            id_site=s.id_site, weekday=wd, is_closed=False,
            open_time=time(8, 0), close_time=time(19, 0),
        ))
    await db_session.commit()
    await db_session.refresh(s)
    return s


async def _make_player(db_session: AsyncSession, org: CmsOrganization,
                       site: CmsSite | None, display_config: dict | None) -> CmsPlayer:
    p = CmsPlayer(
        id_org=org.id_org, player_name=f"p-{uuid.uuid4().hex[:8]}", player_os="linux",
        id_site=site.id_site if site else None, display_config=display_config,
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest_asyncio.fixture
async def player(db_session: AsyncSession, org: CmsOrganization, site: CmsSite) -> CmsPlayer:
    """Player dont l'écran est réellement pilotable (repli sortie vidéo)."""
    return await _make_player(db_session, org, site, {"output_power_fallback": True})


@pytest_asyncio.fixture
async def visual(db_session: AsyncSession, org: CmsOrganization) -> CmsMedia:
    """Média VISUEL explicite.

    Ne jamais coder un `id_media` en dur ici : les identifiants sont séquentiels et
    partagés par toute la suite — un test voisin qui crée un média AUDIO peut se
    retrouver propriétaire de l'id 1 et rendre les autres tests faussement verts, le
    média étant alors exempté de marquage à bon droit.
    """
    m = CmsMedia(id_org=org.id_org, media_name="clip", media_type="video",
                 storage_key=f"k/{uuid.uuid4().hex}.mp4", checksum_sha256=uuid.uuid4().hex * 2)
    db_session.add(m)
    await db_session.commit()
    await db_session.refresh(m)
    return m


@pytest_asyncio.fixture
async def admin_token(db_session: AsyncSession, org: CmsOrganization) -> str:
    user = CmsUser(id_org=org.id_org, email=f"a-{uuid.uuid4().hex[:8]}@t.com",
                   password_hash=hash_password("Password1!"), is_active=True)
    db_session.add(user)
    await db_session.flush()
    await db_session.execute(
        pg_insert(CmsRole).values(role_key="CMS_ORG_ADMIN", label="Org Admin", is_system=True)
        .on_conflict_do_nothing(constraint="uq_cms_roles_role_key")
    )
    await db_session.flush()
    role = (await db_session.execute(
        select(CmsRole).where(CmsRole.role_key == "CMS_ORG_ADMIN"))).scalar_one()
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    return create_access_token(
        user.id_user, extra={"org": org.id_org, "roles": ["CMS_ORG_ADMIN"], "locale": "en"})


async def _post(client: AsyncClient, player: CmsPlayer, logs: list[dict]):
    token, _ = create_player_token(player.id_player)
    return await client.post(
        "/api/v1/pop/batch", json={"logs": logs},
        headers={"Authorization": f"Bearer {token}"},
    )


async def _flags(db_session: AsyncSession, player: CmsPlayer) -> list[bool]:
    return list((await db_session.execute(
        select(CmsProofOfPlay.screen_off)
        .where(CmsProofOfPlay.id_player == player.id_player)
        .order_by(CmsProofOfPlay.id_pop)
    )).scalars().all())


# ── Marquage à l'ingestion ─────────────────────────────────────────────────────

async def test_marks_plays_outside_screen_on_window(
    client: AsyncClient, db_session: AsyncSession, player: CmsPlayer, visual: CmsMedia
) -> None:
    """Avant l'allumage et après l'extinction → marqué ; en pleine ouverture → compté."""
    resp = await _post(client, player, [
        {"id_media": visual.id_media, "played_at": OFF_MORNING, "duration_ms": 5000},
        {"id_media": visual.id_media, "played_at": ON_MIDDAY, "duration_ms": 5000},
        {"id_media": visual.id_media, "played_at": OFF_EVENING, "duration_ms": 5000},
    ])
    assert resp.status_code == 200
    assert resp.json()["screen_off"] == 2
    assert await _flags(db_session, player) == [True, False, True]


async def test_lead_margin_counts_as_screen_on(
    client: AsyncClient, db_session: AsyncSession, player: CmsPlayer, visual: CmsMedia
) -> None:
    """L'écran s'allume 15 min AVANT l'ouverture : 07:50 locale (05:50Z) compte déjà.

    C'est le cas qui distingue une vraie lecture des marges du worker : à 07:30 l'écran
    est encore éteint, à 07:50 il est allumé bien que le site ne soit pas ouvert.
    """
    resp = await _post(client, player, [
        {"id_media": visual.id_media, "played_at": _utc(7, 30), "duration_ms": 1000},
        {"id_media": visual.id_media, "played_at": _utc(7, 50), "duration_ms": 1000},
    ])
    assert resp.status_code == 200
    assert await _flags(db_session, player) == [True, False]


async def test_dated_exception_shifts_the_window(
    client: AsyncClient, db_session: AsyncSession, site: CmsSite, player: CmsPlayer,
    visual: CmsMedia,
) -> None:
    """Une exception datée prime sur l'horaire hebdo — le cas exact vécu en prod.

    Ouverture décalée à 08:25 ce jour-là ⇒ écran allumé à 08:10 : une diffusion de 08:00
    (les programmations, elles, démarrent à 08:00) tombe désormais dans le noir.
    """
    db_session.add(CmsSiteException(
        id_site=site.id_site, date_from=DAY, date_to=DAY, kind="hours",
        open_time=time(8, 25), close_time=time(19, 0), label="Day off",
    ))
    await db_session.commit()

    resp = await _post(client, player, [
        {"id_media": visual.id_media, "played_at": _utc(8, 0), "duration_ms": 1000},
        {"id_media": visual.id_media, "played_at": _utc(8, 20), "duration_ms": 1000},
    ])
    assert resp.status_code == 200
    assert await _flags(db_session, player) == [True, False]


async def test_audio_media_is_never_marked(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization, player: CmsPlayer,
    visual: CmsMedia,
) -> None:
    """Écran éteint ≠ haut-parleurs éteints : l'audio reste compté (facturation §S1/S2)."""
    audio = CmsMedia(id_org=org.id_org, media_name="jingle", media_type="audio",
                     storage_key="k/a.mp3", checksum_sha256="a" * 64)
    db_session.add(audio)
    await db_session.commit()

    resp = await _post(client, player, [
        {"id_media": audio.id_media, "played_at": OFF_MORNING, "duration_ms": 1000},
        {"id_media": visual.id_media, "played_at": OFF_MORNING, "duration_ms": 1000},
    ])
    assert resp.status_code == 200
    assert resp.json()["screen_off"] == 1
    assert await _flags(db_session, player) == [False, True]


# ── Les deux gardes : dans le doute, on ne retire rien de l'antenne ─────────────

async def test_no_marking_when_site_auto_power_disabled(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization, site: CmsSite,
    visual: CmsMedia,
) -> None:
    """Sans auto-power sur le site, aucun écran n'est piloté : on ne sait pas, donc non."""
    site.auto_power_enabled = False
    await db_session.commit()
    p = await _make_player(db_session, org, site, {"output_power_fallback": True})

    resp = await _post(client, p, [{"id_media": visual.id_media, "played_at": OFF_MORNING, "duration_ms": 1000}])
    assert resp.status_code == 200
    assert await _flags(db_session, p) == [False]


async def test_no_marking_when_screen_not_piloted(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization, site: CmsSite,
    visual: CmsMedia,
) -> None:
    """Player sans écran piloté ni repli sortie vidéo (ex. PWA ChromeOS) : jamais marqué."""
    p = await _make_player(db_session, org, site, {"pop_sign": True})

    resp = await _post(client, p, [{"id_media": visual.id_media, "played_at": OFF_MORNING, "duration_ms": 1000}])
    assert resp.status_code == 200
    assert await _flags(db_session, p) == [False]


async def test_no_marking_when_power_schedule_manual(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization, site: CmsSite,
    visual: CmsMedia,
) -> None:
    """Mode `manual` = player jamais piloté automatiquement → son écran n'est pas coupé."""
    p = await _make_player(db_session, org, site, {
        "output_power_fallback": True, "power_schedule": {"mode": "manual"},
    })

    resp = await _post(client, p, [{"id_media": visual.id_media, "played_at": OFF_MORNING, "duration_ms": 1000}])
    assert resp.status_code == 200
    assert await _flags(db_session, p) == [False]


async def test_always_on_player_is_never_marked(
    client: AsyncClient, db_session: AsyncSession, org: CmsOrganization, site: CmsSite,
    visual: CmsMedia,
) -> None:
    """Écran `always_on` (vitrine 24/7) : allumé même site fermé → tout compte."""
    p = await _make_player(db_session, org, site, {
        "output_power_fallback": True, "power_schedule": {"mode": "always_on"},
    })

    resp = await _post(client, p, [{"id_media": visual.id_media, "played_at": OFF_MORNING, "duration_ms": 1000}])
    assert resp.status_code == 200
    assert await _flags(db_session, p) == [False]


# ── Effet sur les comptages et non-régression de la chaîne ──────────────────────

async def test_aggregates_exclude_screen_off_but_chain_stays_valid(
    client: AsyncClient, player: CmsPlayer, admin_token: str, visual: CmsMedia
) -> None:
    """/analytics ne compte que l'antenne réelle ; /verify voit TOUTES les preuves.

    C'est le point délicat : filtrer la chaîne ferait diverger le recalcul et conclurait
    à tort « chaîne altérée ». Le certificat expose donc les deux nombres.
    """
    resp = await _post(client, player, [
        {"id_media": visual.id_media, "played_at": OFF_MORNING, "duration_ms": 5000},
        {"id_media": visual.id_media, "played_at": ON_MIDDAY, "duration_ms": 5000},
        {"id_media": visual.id_media, "played_at": OFF_EVENING, "duration_ms": 5000},
    ])
    assert resp.status_code == 200
    assert resp.json()["screen_off"] == 2, "le marquage à l'ingestion doit avoir eu lieu"
    h = {"Authorization": f"Bearer {admin_token}"}

    day = DAY.isoformat()
    cert = await client.get(
        f"/api/v1/pop/certificate?from={day}&until={day}", headers=h)
    assert cert.status_code == 200
    body = cert.json()
    assert body["total_plays"] == 1          # seule la diffusion de 12:00 est de l'antenne
    assert body["total_screen_off"] == 2
    assert body["players"][0]["plays"] == 1
    assert body["players"][0]["screen_off"] == 2

    # La chaîne porte sur les 3 preuves et reste recalculable.
    ver = await client.get("/api/v1/pop/verify?days=2", headers=h)
    assert ver.status_code == 200
    assert ver.json()["chain_valid"] is True

    # La vue forensique montre les 3 lignes, drapeau à l'appui (les masquer rendrait le
    # phénomène indétectable pour l'exploitant).
    plays = await client.get(
        f"/api/v1/pop/plays?from={day}&until={day}", headers=h)
    assert plays.status_code == 200
    rows = plays.json()["rows"]
    assert len(rows) == 3
    assert sum(1 for r in rows if r["screen_off"]) == 2
