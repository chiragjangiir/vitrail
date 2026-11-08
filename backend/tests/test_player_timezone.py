"""Alignement auto du fuseau OS des players sur celui du site (services/player_timezone).

Tables de correspondance par OS + déclenchement à l'attachement / au changement de
fuseau du site. La publication Redis est capturée par un faux client (pas de Redis).
"""

import json
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import CmsOrganization
from app.models.player import CmsPlayer
from app.services import player_timezone as ptz
from tests.test_sites_power import _make_org, _make_user


# ── Faux Redis : capture les publish ─────────────────────────────────────────
class _FakeRedis:
    published: list[tuple[str, dict]] = []

    async def publish(self, channel: str, payload: str) -> None:
        _FakeRedis.published.append((channel, json.loads(payload)))

    async def aclose(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _fake_redis(monkeypatch):
    _FakeRedis.published = []
    monkeypatch.setattr(ptz.aioredis, "from_url", lambda url: _FakeRedis())
    return _FakeRedis


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    return await _make_org(db_session)


@pytest_asyncio.fixture
async def auth(db_session, org):
    return await _make_user(db_session, org)


# ── Tables de correspondance (pur) ───────────────────────────────────────────
def test_target_for_by_os():
    # linux/rpi/android : IANA tel quel
    assert ptz.target_for("linux-x64", "Europe/Monaco") == "Europe/Monaco"
    assert ptz.target_for("android-armeabi-v7a", "Asia/Tokyo") == "Asia/Tokyo"
    # windows : canonique du groupe Windows ; zone inconnue → None
    assert ptz.target_for("windows", "Europe/Monaco") == "Europe/Berlin"
    assert ptz.target_for("windows", "Europe/Brussels") == "Europe/Paris"
    assert ptz.target_for("windows", "Europe/Paris") == "Europe/Paris"
    assert ptz.target_for("windows", "Pacific/Chatham") is None
    # brightsign : libellé natif BOS ; zone hors table → None
    assert ptz.target_for("brightsign", "Europe/Paris") == "CET"
    assert ptz.target_for("brightsign", "Europe/London") == "GMTBST"
    assert ptz.target_for("brightsign", "Pacific/Chatham") is None
    # non pilotables
    assert ptz.target_for("chromeos", "Europe/Paris") is None
    assert ptz.target_for("chrome_extension", "Europe/Paris") is None
    assert ptz.target_for(None, "Europe/Paris") is None


def test_is_aligned_equivalences():
    # Exact
    assert ptz.is_aligned("linux-x64", "Europe/Paris", "Europe/Paris")
    # BrightSign : CET ≡ Europe/Paris
    assert ptz.is_aligned("brightsign", "CET", "Europe/Paris")
    assert not ptz.is_aligned("brightsign", "GMT", "Europe/Paris")
    # Windows : le canonique du groupe vaut alignement (site Monaco, remonté Berlin)
    assert ptz.is_aligned("windows", "Europe/Berlin", "Europe/Monaco")
    assert not ptz.is_aligned("windows", "Europe/London", "Europe/Paris")
    # Pas de fuseau site = rien à faire ; pas de fuseau remonté = à aligner
    assert ptz.is_aligned("linux-x64", None, None)
    assert not ptz.is_aligned("linux-x64", None, "Europe/Paris")


# ── Déclenchements endpoints ─────────────────────────────────────────────────
async def _mk_site(client: AsyncClient, headers: dict, tz: str | None) -> int:
    body = {"site_name": f"S-{uuid.uuid4().hex[:6]}"}
    if tz:
        body["timezone"] = tz
    return (await client.post("/api/v1/sites", json=body, headers=headers)).json()["id_site"]


async def test_attach_pushes_set_timezone(client: AsyncClient, auth, org, db_session) -> None:
    _, token = auth
    headers = {"Authorization": f"Bearer {token}"}
    sid = await _mk_site(client, headers, "Europe/Paris")
    p = CmsPlayer(id_org=org.id_org, player_name="TZ-linux", player_os="linux-x64",
                  capabilities={"timezone": "Asia/Shanghai"})
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)

    resp = await client.post(f"/api/v1/sites/{sid}/players/{p.id_player}", headers=headers)
    assert resp.status_code == 204
    assert len(_FakeRedis.published) == 1
    ch, msg = _FakeRedis.published[0]
    assert ch == f"signflow:player:{p.id_player}:cmds"
    assert msg["command"] == "set_timezone"
    assert msg["params"]["timezone"] == "Europe/Paris"


async def test_attach_aligned_or_unmapped_no_push(client: AsyncClient, auth, org, db_session) -> None:
    _, token = auth
    headers = {"Authorization": f"Bearer {token}"}
    sid = await _mk_site(client, headers, "Europe/Paris")
    aligned = CmsPlayer(id_org=org.id_org, player_name="TZ-ok", player_os="linux-x64",
                        capabilities={"timezone": "Europe/Paris"})
    bs_equiv = CmsPlayer(id_org=org.id_org, player_name="TZ-bs", player_os="brightsign",
                         capabilities={"timezone": "CET"})
    pwa = CmsPlayer(id_org=org.id_org, player_name="TZ-pwa", player_os="chromeos",
                    capabilities={"timezone": "Asia/Tokyo"})
    db_session.add_all([aligned, bs_equiv, pwa])
    await db_session.commit()
    for p in (aligned, bs_equiv, pwa):
        await db_session.refresh(p)
        assert (await client.post(
            f"/api/v1/sites/{sid}/players/{p.id_player}", headers=headers
        )).status_code == 204
    assert _FakeRedis.published == []  # déjà alignés / non pilotable → aucun envoi


async def test_site_timezone_change_realigns_players(client: AsyncClient, auth, org, db_session) -> None:
    _, token = auth
    headers = {"Authorization": f"Bearer {token}"}
    sid = await _mk_site(client, headers, "Europe/Paris")
    lin = CmsPlayer(id_org=org.id_org, id_site=sid, player_name="TZ-l", player_os="linux-x64",
                    capabilities={"timezone": "Europe/Paris"})
    bs = CmsPlayer(id_org=org.id_org, id_site=sid, player_name="TZ-b", player_os="brightsign",
                   capabilities={"timezone": "CET"})
    db_session.add_all([lin, bs])
    await db_session.commit()

    resp = await client.put(f"/api/v1/sites/{sid}", json={"timezone": "Europe/London"}, headers=headers)
    assert resp.status_code == 200
    sent = {msg["params"]["timezone"] for _, msg in _FakeRedis.published}
    assert sent == {"Europe/London", "GMTBST"}  # IANA au linux, libellé natif au BS

    # Update SANS toucher au fuseau → aucun ré-envoi
    _FakeRedis.published = []
    assert (await client.put(f"/api/v1/sites/{sid}", json={"site_name": "renamed"},
                             headers=headers)).status_code == 200
    assert _FakeRedis.published == []
