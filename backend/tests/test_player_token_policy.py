"""Tests de la politique de rotation des tokens machine players (« Option B », 2026-06-26).

Couvre les helpers PURS de app.services.player_token + la durée de vie finie du token. La logique
d'intégration (rotation WS / auto-refresh worker) repose sur ces helpers ; le WS et le worker
réalisent leurs écritures dans leurs sessions (testées séparément côté /pop pour le HTTP)."""

from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.core.security import create_player_token, decode_token
from app.services.player_token import (
    IDENTITY_CURRENT,
    IDENTITY_PREV,
    IDENTITY_UNKNOWN,
    grace_until,
    needs_rotation,
    token_identity,
)

NOW = datetime(2026, 6, 26, 12, 0, tzinfo=UTC)


# ── Durée de vie finie du token ──────────────────────────────────────────────────

def test_player_token_has_finite_expiry() -> None:
    """Fin de l'INTERIM « 100 ans » : le token expire à CMS_PLAYER_TOKEN_EXPIRE_DAYS."""
    token, expires_at = create_player_token(42)
    days = (expires_at - datetime.now(UTC)).total_seconds() / 86400
    assert abs(days - settings.CMS_PLAYER_TOKEN_EXPIRE_DAYS) < 1
    payload = decode_token(token, verify_exp=False)
    assert payload["type"] == "player"
    assert payload["sub"] == "42"
    assert "iat" in payload


# ── token_identity ───────────────────────────────────────────────────────────────

def test_identity_current() -> None:
    assert token_identity("tok", "tok", None, None, NOW) == IDENTITY_CURRENT


def test_identity_prev_within_grace() -> None:
    until = NOW + timedelta(days=2)
    assert token_identity("old", "new", "old", until, NOW) == IDENTITY_PREV


def test_identity_prev_after_grace_is_unknown() -> None:
    until = NOW - timedelta(seconds=1)
    assert token_identity("old", "new", "old", until, NOW) == IDENTITY_UNKNOWN


def test_identity_unknown_token() -> None:
    until = NOW + timedelta(days=1)
    assert token_identity("leaked", "current", "prev", until, NOW) == IDENTITY_UNKNOWN


def test_identity_null_stored_token_is_current() -> None:
    """Player jamais provisionné (player_token NULL) → comportement historique : on laisse passer."""  # noqa: E501
    assert token_identity("anything", None, None, None, NOW) == IDENTITY_CURRENT


# ── needs_rotation ───────────────────────────────────────────────────────────────

def test_rotation_when_null_expiry() -> None:
    assert needs_rotation(None, NOW) is True


def test_rotation_when_fresh_token_is_false() -> None:
    fresh = NOW + timedelta(days=settings.CMS_PLAYER_TOKEN_EXPIRE_DAYS)
    assert needs_rotation(fresh, NOW) is False


def test_rotation_when_near_expiry() -> None:
    near = NOW + timedelta(days=settings.CMS_PLAYER_TOKEN_REFRESH_DAYS - 1)
    assert needs_rotation(near, NOW) is True


def test_rotation_when_expired() -> None:
    assert needs_rotation(NOW - timedelta(days=1), NOW) is True


def test_rotation_when_legacy_100y_token() -> None:
    """Ancien token permanent (expiration ≫ politique) → migré à la prochaine occasion."""
    legacy = NOW + timedelta(days=36500)
    assert needs_rotation(legacy, NOW) is True


def test_rotation_handles_naive_datetime() -> None:
    naive_fresh = (NOW + timedelta(days=settings.CMS_PLAYER_TOKEN_EXPIRE_DAYS)).replace(tzinfo=None)
    assert needs_rotation(naive_fresh, NOW) is False


# ── grace_until ──────────────────────────────────────────────────────────────────

def test_grace_until() -> None:
    until = grace_until(NOW)
    days = (until - NOW).total_seconds() / 86400
    assert abs(days - settings.CMS_PLAYER_TOKEN_GRACE_DAYS) < 0.01
