"""Crédits / quotas de tokens de l'AI Assistant (§XXVII).

Vérifie : calcul de période (weekly/monthly), crédit effectif (NULL/0 = illimité),
estimation du coût EUR, agrégat d'usage org-scopé, l'endpoint de suivi super-admin,
et l'ENFORCEMENT à l'entrée de /assistant/chat (org au-delà du quota → bloquée sans
appel au modèle ; super-admin exempté).
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.security import create_access_token
from app.models.assistant import CmsAssistantStat
from app.models.organization import CmsOrganization
from app.models.role import CmsRole, CmsUserRoleAssignment
from app.models.user import CmsUser
from app.services.assistant_quota import (
    effective_quota,
    period_start,
    quota_status,
    tokens_to_eur,
    usage_history,
    usage_in_period,
)

_SEQ = [0]


def _uid() -> int:
    _SEQ[0] += 1
    return _SEQ[0]


async def _org(db, **kw) -> CmsOrganization:
    o = CmsOrganization(org_name=f"QOrg{_uid()}", org_slug=f"q-{_uid()}", **kw)
    db.add(o)
    await db.flush()
    return o


async def _grant_super_admin(db, user) -> None:
    await db.execute(
        pg_insert(CmsRole)
        .values(role_key="CMS_SUPER_ADMIN", label="Super Admin", is_system=True)
        .on_conflict_do_nothing(constraint="uq_cms_roles_role_key")
    )
    await db.flush()
    role = (
        await db.execute(select(CmsRole).where(CmsRole.role_key == "CMS_SUPER_ADMIN"))
    ).scalar_one()
    db.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db.flush()


async def _stat(db, id_org, d: date, tokens: int, messages: int = 1) -> None:
    db.add(CmsAssistantStat(
        id_org=id_org, stat_date=d, token_count=tokens, message_count=messages
    ))
    await db.flush()


# ── Fonctions pures ────────────────────────────────────────────────────────────

def test_period_start_weekly_is_monday():
    # mercredi 2026-06-24 → lundi 2026-06-22
    assert period_start("weekly", date(2026, 6, 24)) == date(2026, 6, 22)
    # un lundi reste lui-même
    assert period_start("weekly", date(2026, 6, 22)) == date(2026, 6, 22)


def test_period_start_monthly_is_first():
    assert period_start("monthly", date(2026, 6, 24)) == date(2026, 6, 1)
    assert period_start("unknown", date(2026, 6, 24)) == date(2026, 6, 1)  # défaut monthly


def test_effective_quota():
    assert effective_quota(None) is None
    assert effective_quota(0) is None        # 0 = illimité
    assert effective_quota(-5) is None
    assert effective_quota(1000) == 1000


def test_tokens_to_eur_uses_blended_rate():
    # défaut 9.0 EUR/Mtok → 1M tokens = 9 EUR
    assert tokens_to_eur(1_000_000) == pytest.approx(9.0)
    assert tokens_to_eur(0) == 0.0


# ── Agrégat d'usage (DB) ─────────────────────────────────────────────────────────

async def test_usage_in_period_sums_only_current_period(db_session):
    org = await _org(db_session)
    today = date.today()
    start = period_start("monthly", today)
    await _stat(db_session, org.id_org, today, 100, 1)
    await _stat(db_session, org.id_org, start, 50, 1)
    # hors période (veille du début de période) → exclu
    await _stat(db_session, org.id_org, start - timedelta(days=1), 9999, 9)

    u = await usage_in_period(db_session, org.id_org, "monthly", today)
    assert u["tokens"] == 150 and u["messages"] == 2


# ── Endpoint de suivi super-admin ────────────────────────────────────────────────

async def test_usage_endpoint_super_admin(client, db_session):
    org = await _org(db_session, ai_quota_tokens=1000, ai_quota_period="monthly")
    await _stat(db_session, org.id_org, date.today(), 250, 3)
    await db_session.commit()

    su = CmsUser(id_org=org.id_org, email=f"su-{_uid()}@t.com", password_hash="x")
    db_session.add(su)
    await db_session.flush()
    await _grant_super_admin(db_session, su)
    await db_session.commit()
    token = create_access_token(su.id_user, extra={"org": org.id_org, "roles": ["CMS_SUPER_ADMIN"]})

    resp = await client.get(
        "/api/v1/admin/assistant/usage", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    rows = {r["id_org"]: r for r in resp.json()}
    row = rows[org.id_org]
    assert row["unit"] == "tokens" and row["limit"] == 1000 and row["used_tokens"] == 250
    assert row["pct"] == 25.0 and row["blocked"] is False
    assert row["cost_eur"] == pytest.approx(tokens_to_eur(250))


def test_quota_status_tokens_and_threshold():
    class FakeOrg:
        ai_quota_unit = "tokens"
        ai_quota_tokens = 1000
        ai_quota_eur = None
        ai_alert_threshold_pct = 80
    st = quota_status(FakeOrg(), 850)
    assert st["unit"] == "tokens" and st["limit"] == 1000 and st["pct"] == 85.0
    assert st["blocked"] is False and st["over_threshold"] is True
    # au-delà du crédit → bloqué (et plus "over_threshold", c'est un dépassement franc)
    st2 = quota_status(FakeOrg(), 1200)
    assert st2["blocked"] is True and st2["over_threshold"] is False


def test_quota_status_eur():
    class FakeOrg:
        ai_quota_unit = "eur"
        ai_quota_tokens = None
        ai_quota_eur = 9.0           # = 1M tokens au tarif par défaut (9 €/Mtok)
        ai_alert_threshold_pct = 0   # alerte désactivée
    st = quota_status(FakeOrg(), 500_000)  # 0,5M tokens = 4,5 €
    assert st["unit"] == "eur" and st["limit"] == 9.0
    assert st["used"] == pytest.approx(4.5) and st["pct"] == 50.0
    assert st["blocked"] is False and st["over_threshold"] is False
    st2 = quota_status(FakeOrg(), 1_000_000)  # 9 € → atteint le crédit
    assert st2["blocked"] is True


async def test_usage_history_fills_gaps(db_session):
    org = await _org(db_session)
    today = date.today()
    await _stat(db_session, org.id_org, today, 120, 2)
    hist = await usage_history(db_session, org.id_org, 7, today)
    assert len(hist) == 7                       # série continue, sans trou
    assert hist[-1]["date"] == today.isoformat()
    assert hist[-1]["tokens"] == 120 and hist[-1]["cost_eur"] == pytest.approx(tokens_to_eur(120))
    assert hist[0]["tokens"] == 0               # jours sans usage = 0


# ── Enforcement /assistant/chat ──────────────────────────────────────────────────

async def test_chat_blocked_when_over_quota(client, db_session, monkeypatch):
    """Org au-delà du quota → frame `quota_exceeded`, AUCUN appel au modèle (court-circuit).
    Le quota ne s'applique qu'en mode `platform` (clé plateforme) — BYOK §XXVII."""
    from app.core.config import settings as _settings
    monkeypatch.setattr(_settings, "ANTHROPIC_API_KEY", "sk-platform")
    org = await _org(
        db_session, ai_quota_tokens=100, ai_quota_period="monthly", ai_byok_mode="platform"
    )
    await _stat(db_session, org.id_org, date.today(), 150, 2)  # 150 > 100
    user = CmsUser(id_org=org.id_org, email=f"u-{_uid()}@t.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()
    token = create_access_token(user.id_user, extra={"org": org.id_org, "roles": ["CMS_VIEWER"]})

    resp = await client.post(
        "/api/v1/assistant/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"messages": [{"role": "user", "content": "bonjour"}]},
    )
    assert resp.status_code == 200
    assert '"quota_exceeded": true' in resp.text


async def test_chat_not_blocked_under_quota(client, db_session, monkeypatch):
    """Sous le quota → pas de drapeau quota_exceeded (l'agent prend le relais).
    On mocke l'agent pour ne pas dépendre de LiteLLM."""
    import app.api.v1.endpoints.assistant as ep

    async def fake_run_agent(db, **kw):  # noqa: ARG001
        if kw.get("usage_out") is not None:
            kw["usage_out"]["total"] = 5
        yield "ok"

    monkeypatch.setattr(ep, "run_agent", fake_run_agent)
    from app.core.config import settings as _settings
    monkeypatch.setattr(_settings, "ANTHROPIC_API_KEY", "sk-platform")

    org = await _org(
        db_session, ai_quota_tokens=10000, ai_quota_period="monthly", ai_byok_mode="platform"
    )
    await _stat(db_session, org.id_org, date.today(), 100, 1)
    user = CmsUser(id_org=org.id_org, email=f"u-{_uid()}@t.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()
    token = create_access_token(user.id_user, extra={"org": org.id_org, "roles": ["CMS_VIEWER"]})

    resp = await client.post(
        "/api/v1/assistant/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"messages": [{"role": "user", "content": "bonjour"}]},
    )
    assert resp.status_code == 200
    assert "quota_exceeded" not in resp.text
    assert '"delta": "ok"' in resp.text
