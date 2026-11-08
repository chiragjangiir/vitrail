"""Tests — règle de compatibilité LAN Sync (player_compat) + enforcement endpoint.

Règle d'HOMOGÉNÉITÉ (2026-06-11) : un groupe LAN Sync homogène (mêmes OS/renderer/matériel)
est OK, y compris en mpv/exo ; un groupe hétérogène contenant un renderer HW natif (mpv/exo)
est BLOCK (flip-flop) ; un groupe hétérogène sans HW natif est WARN. Niveaux : ok|warn|block.
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.role import CmsRole, CmsUserRoleAssignment
from app.models.user import CmsUser
from app.services.player_compat import (
    clear_lan_sync,
    homogeneity_signature,
    lan_sync_blocked,
    lan_sync_eligibility,
)


def _peer(os_: str, renderer: str = "auto", gpu: str | None = None) -> dict:
    return {
        "display_config": {"video_renderer": renderer},
        "player_os": os_,
        "capabilities": {"gpu_model": gpu} if gpu else {},
    }


# ── Tests unitaires — moteur de règles pur ───────────────────────────────────

def test_signature_normalizes_os_and_renderer() -> None:
    assert homogeneity_signature({"video_renderer": "auto"}, "linux-x64", None) == (
        "linux", "chromium", None)
    assert homogeneity_signature({}, "linux", None) == ("linux", "chromium", None)
    assert homogeneity_signature({"video_renderer": "mpv"}, "linux", {"gpu_model": "X"}) == (
        "linux", "mpv", "X")


def test_solo_player_always_ok() -> None:
    # Aucun pair → homogène avec lui-même → ok, même en mpv.
    assert lan_sync_eligibility({"video_renderer": "mpv"}, "linux")["level"] == "ok"
    assert lan_sync_eligibility(None, None)["level"] == "ok"


def test_homogeneous_mpv_group_is_ok() -> None:
    peers = [_peer("linux", "mpv", "GeminiLake"), _peer("linux-x64", "mpv", "GeminiLake")]
    e = lan_sync_eligibility(
        {"video_renderer": "mpv"}, "linux", {"gpu_model": "GeminiLake"}, peers)
    assert e["level"] == "ok"
    assert e["reason"] is None


def test_heterogeneous_group_with_mpv_is_blocked() -> None:
    # self mpv linux + pair Chromium windows → hétérogène + HW natif → block.
    peers = [_peer("windows", "auto")]
    e = lan_sync_eligibility({"video_renderer": "mpv"}, "linux", None, peers)
    assert e["level"] == "block"
    assert e["reason"] == "lan_sync_heterogeneous_hw"
    assert lan_sync_blocked({"video_renderer": "mpv"}, "linux", None, peers) is True


def test_chromium_joining_a_group_with_mpv_peer_is_blocked() -> None:
    # self Chromium + pair mpv (signature ≠) → le groupe contient du HW natif + hétérogène → block
    # (protège le pair mpv : on ne casse pas sa synchro en mélangeant).
    peers = [_peer("linux", "mpv")]
    e = lan_sync_eligibility({"video_renderer": "auto"}, "windows", None, peers)
    assert e["level"] == "block"
    assert e["reason"] == "lan_sync_heterogeneous_hw"


def test_heterogeneous_group_without_hw_native_is_warn() -> None:
    peers = [_peer("windows", "auto")]
    e = lan_sync_eligibility({"video_renderer": "auto"}, "linux", None, peers)
    assert e["level"] == "warn"
    assert e["reason"] == "heterogeneous_group"
    assert lan_sync_blocked({"video_renderer": "auto"}, "linux", None, peers) is False


def _bs_caps(model: str, family: str = "") -> dict:
    return {"bs_model": model, "bs_family": family, "platform": "brightsign"}


def _bs_peer(model: str, family: str = "") -> dict:
    """Pair BrightSign : pas de gpu_model, identité matérielle = bs_model (réf exacte)."""
    return {"display_config": {"video_renderer": "auto"},
            "player_os": "brightsign", "capabilities": _bs_caps(model, family)}


def test_brightsign_same_model_is_homogeneous() -> None:
    # Deux XT1144 (même réf) → homogène → ok. Idem pour tout modèle série 4/5/6 identique.
    for model in ("XT1144", "HD1024", "XD1035", "XT2145", "HD1025"):
        e = lan_sync_eligibility({}, "brightsign", _bs_caps(model), [_bs_peer(model)])
        assert e["level"] == "ok", model


def test_brightsign_mixed_models_is_heterogeneous_warn() -> None:
    # XT1144 (XT4) + HD1024 (HD4) → réfs différentes → hétérogène → warn (latences d'affichage
    # distinctes, drift confirmé sur HW). Pas block (chromium/roHtmlWidget, pas de HW natif).
    caps = _bs_caps("XT1144", "malibu")
    e = lan_sync_eligibility({}, "brightsign", caps, [_bs_peer("HD1024", "pagani")])
    assert e["level"] == "warn"
    assert e["reason"] == "heterogeneous_group"
    assert lan_sync_blocked({}, "brightsign", caps, [_bs_peer("HD1024", "pagani")]) is False


def test_brightsign_different_models_same_family_still_warn() -> None:
    # Même famille SoC mais modèles différents (ex. XT1144 ↔ XT2145) → warn (on ne garantit pas la
    # même latence d'affichage → conservateur : réf exacte). Générique série 4/5/6.
    e = lan_sync_eligibility({}, "brightsign", _bs_caps("XT1144", "malibu"),
                             [_bs_peer("XT2145", "malibu")])
    assert e["level"] == "warn"


def test_brightsign_signature_prefers_model_then_family() -> None:
    assert homogeneity_signature({}, "brightsign", {"bs_model": "XT1144"}) == (
        "brightsign", "chromium", "XT1144")
    # Repli sur family si model absent (autorun ancien).
    assert homogeneity_signature({}, "brightsign", {"bs_family": "malibu"}) == (
        "brightsign", "chromium", "malibu")
    # Réfs différentes → signatures différentes.
    assert (homogeneity_signature({}, "brightsign", {"bs_model": "HD1024"})
            != homogeneity_signature({}, "brightsign", {"bs_model": "XT1144"}))


def test_same_hardware_renderer_mismatch_is_warn_not_blocked() -> None:
    # Anti-deadlock : matériel IDENTIQUE (même OS + GPU), seul le renderer diffère (bascule de
    # groupe en cours, ex. 1er d'une paire J4025 passé en mpv alors que le pair est encore auto).
    # → warn, PAS block : on doit pouvoir basculer le 1er membre. (Avant : block = deadlock.)
    peers = [_peer("linux", "auto", "GeminiLake")]
    e = lan_sync_eligibility({"video_renderer": "mpv"}, "linux-x64", {"gpu_model": "GeminiLake"}, peers)
    assert e["level"] == "warn"
    assert e["reason"] == "renderer_mismatch"
    assert lan_sync_blocked(
        {"video_renderer": "mpv"}, "linux-x64", {"gpu_model": "GeminiLake"}, peers) is False


def test_homogeneous_chromium_group_is_ok() -> None:
    peers = [_peer("linux", "auto", "UHD600")]
    e = lan_sync_eligibility(
        {"video_renderer": "auto"}, "linux-x64", {"gpu_model": "UHD600"}, peers)
    assert e["level"] == "ok"


def test_clear_lan_sync_disables_and_keeps_renderer() -> None:
    cfg = clear_lan_sync({"video_renderer": "mpv", "lan_sync_enabled": True,
                          "lan_sync_group": "wall", "lan_sync_master": True})
    assert cfg["lan_sync_enabled"] is False
    assert cfg["lan_sync_master"] is False
    assert cfg["lan_sync_group"] is None
    assert cfg["video_renderer"] == "mpv"   # renderer conservé


# ── Fixtures (org admin + player) ────────────────────────────────────────────

@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="CompatOrg", org_slug=f"compat-org-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def admin_token(db_session: AsyncSession, org: CmsOrganization) -> str:
    user = CmsUser(
        id_org=org.id_org, email=f"admin-{uuid.uuid4().hex[:8]}@compat.com",
        password_hash=hash_password("Password1!"), is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.execute(
        pg_insert(CmsRole)
        .values(role_key="CMS_ORG_ADMIN", label="Org Admin", is_system=True)
        .on_conflict_do_nothing(constraint="uq_cms_roles_role_key")
    )
    await db_session.flush()
    role = (await db_session.execute(
        select(CmsRole).where(CmsRole.role_key == "CMS_ORG_ADMIN"))).scalar_one()
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    return create_access_token(
        user.id_user, extra={"org": org.id_org, "roles": ["CMS_ORG_ADMIN"], "locale": "en"})


def _mock_redis():
    mock = AsyncMock()
    mock.publish = AsyncMock(return_value=1)
    mock.aclose = AsyncMock()
    return patch("app.api.v1.endpoints.players.aioredis.from_url", return_value=mock)


async def _make_player(client: AsyncClient, token: str, os_: str = "linux") -> int:
    resp = await client.post(
        "/api/v1/players/",
        json={"player_name": f"p-{uuid.uuid4().hex[:8]}", "player_os": os_},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    return resp.json()["id_player"]


def _put_cfg(client, token, pid, cfg, **extra):
    return client.put(
        f"/api/v1/players/{pid}",
        json={"display_config": cfg, **extra},
        headers={"Authorization": f"Bearer {token}"},
    )


_WALL = {"lan_sync_enabled": True, "lan_sync_group": "wall"}


# ── Tests d'enforcement endpoint ─────────────────────────────────────────────

async def test_read_exposes_eligibility_solo_ok(client: AsyncClient, admin_token: str) -> None:
    # Player solo (hors groupe) → ok, même Android.
    pid = await _make_player(client, admin_token, "android-arm64")
    resp = await client.get(f"/api/v1/players/{pid}",
                            headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    assert resp.json()["lan_sync_eligibility"]["level"] == "ok"


async def test_homogeneous_mpv_group_allowed(client: AsyncClient, admin_token: str) -> None:
    """Deux players identiques (linux/mpv) dans le même groupe → autorisés (NOUVEAU)."""
    a = await _make_player(client, admin_token, "linux")
    b = await _make_player(client, admin_token, "linux")
    with _mock_redis():
        ra = await _put_cfg(client, admin_token, a, {"video_renderer": "mpv", **_WALL})
        rb = await _put_cfg(client, admin_token, b, {"video_renderer": "mpv", **_WALL})
    assert ra.status_code == 200
    assert rb.status_code == 200
    assert rb.json()["display_config"]["video_renderer"] == "mpv"
    assert rb.json()["display_config"]["lan_sync_enabled"] is True
    assert rb.json()["lan_sync_eligibility"]["level"] == "ok"


async def test_heterogeneous_mpv_group_blocked(client: AsyncClient, admin_token: str) -> None:
    """Un player d'un autre OS rejoignant en mpv un groupe mpv → 409 LAN_SYNC_HETEROGENEOUS."""
    a = await _make_player(client, admin_token, "linux")
    b = await _make_player(client, admin_token, "windows")
    with _mock_redis():
        await _put_cfg(client, admin_token, a, {"video_renderer": "mpv", **_WALL})
        rb = await _put_cfg(client, admin_token, b, {"video_renderer": "mpv", **_WALL})
    assert rb.status_code == 409
    assert rb.json()["detail"]["code"] == "LAN_SYNC_HETEROGENEOUS"


async def test_force_chromium_integrates_when_peers_compatible(
    client: AsyncClient, admin_token: str
) -> None:
    """force_chromium dégrade un joiner HW natif en Chromium pour lever le BLOCK d'un groupe
    MATÉRIELLEMENT hétérogène (le seul cas qui bloque encore). A=linux Chromium, B=windows mpv
    → matériel ≠ + HW natif → block ; force_chromium dégrade B en auto → plus de HW natif → warn → 200."""
    a = await _make_player(client, admin_token, "linux")
    b = await _make_player(client, admin_token, "windows")
    with _mock_redis():
        await _put_cfg(client, admin_token, a, {"video_renderer": "auto", **_WALL})
        rb_block = await _put_cfg(client, admin_token, b, {"video_renderer": "mpv", **_WALL})
        assert rb_block.status_code == 409
        rb = await _put_cfg(
            client, admin_token, b, {"video_renderer": "mpv", **_WALL}, force_chromium=True)
    assert rb.status_code == 200
    assert rb.json()["display_config"]["video_renderer"] == "auto"
    assert rb.json()["display_config"]["lan_sync_enabled"] is True
    assert rb.json()["lan_sync_eligibility"]["level"] == "warn"


async def test_same_hardware_switch_to_mpv_not_blocked(
    client: AsyncClient, admin_token: str
) -> None:
    """Anti-deadlock endpoint : deux players de MÊME matériel (linux), A en auto, B passe en mpv
    → autorisé (warn, plus de 409). On peut ensuite aligner A → groupe homogène ok."""
    a = await _make_player(client, admin_token, "linux")
    b = await _make_player(client, admin_token, "linux")
    with _mock_redis():
        await _put_cfg(client, admin_token, a, {"video_renderer": "auto", **_WALL})
        rb = await _put_cfg(client, admin_token, b, {"video_renderer": "mpv", **_WALL})
        assert rb.status_code == 200
        assert rb.json()["display_config"]["video_renderer"] == "mpv"
        assert rb.json()["lan_sync_eligibility"]["level"] == "warn"
        # Aligner A en mpv → groupe homogène → ok
        ra = await _put_cfg(client, admin_token, a, {"video_renderer": "mpv", **_WALL})
    assert ra.status_code == 200
    assert ra.json()["lan_sync_eligibility"]["level"] == "ok"


async def test_heterogeneous_chromium_group_warn_allowed(
    client: AsyncClient, admin_token: str
) -> None:
    """Groupe Chromium hétérogène (OS ≠) sans HW natif → autorisé avec avertissement (warn)."""
    a = await _make_player(client, admin_token, "linux")
    b = await _make_player(client, admin_token, "windows")
    with _mock_redis():
        await _put_cfg(client, admin_token, a, {"video_renderer": "auto", **_WALL})
        rb = await _put_cfg(client, admin_token, b, {"video_renderer": "auto", **_WALL})
    assert rb.status_code == 200
    assert rb.json()["lan_sync_eligibility"]["level"] == "warn"
