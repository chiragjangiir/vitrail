"""Crédits / quotas de tokens de l'AI Assistant (§XXVII).

Le super-admin pose un crédit de tokens par org (`cms_organizations.ai_quota_tokens`)
sur une période (`ai_quota_period` = weekly|monthly). L'usage réel est agrégé depuis
`cms_assistant_stats` (compteurs quotidiens messages + tokens). Le coût en EUR est une
ESTIMATION (tokens × tarif blended configurable) — purement indicatif pour le suivi.

Fonctions pures (calcul de période, conversion EUR) + agrégat d'usage org-scopé.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.assistant import CmsAssistantStat


def period_start(period: str, today: date) -> date:
    """Début de la période courante : lundi (weekly) ou 1er du mois (monthly)."""
    if period == "weekly":
        return today - timedelta(days=today.weekday())
    return today.replace(day=1)


def effective_quota(ai_quota_tokens: int | None) -> int | None:
    """Crédit réellement appliqué : NULL ou <= 0 → None (illimité)."""
    if ai_quota_tokens and ai_quota_tokens > 0:
        return ai_quota_tokens
    return None


def tokens_to_eur(tokens: int) -> float:
    """Estimation du coût en EUR pour un nombre de tokens (tarif blended config)."""
    return round(tokens * settings.CMS_ASSISTANT_PRICE_EUR_PER_MTOK / 1_000_000, 4)


async def usage_in_period(
    db: AsyncSession, id_org: int, period: str, today: date
) -> dict[str, int]:
    """Tokens + messages consommés par l'org depuis le début de la période courante."""
    start = period_start(period, today)
    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(CmsAssistantStat.token_count), 0),
                func.coalesce(func.sum(CmsAssistantStat.message_count), 0),
            ).where(
                CmsAssistantStat.id_org == id_org,
                CmsAssistantStat.stat_date >= start,
            )
        )
    ).first()
    return {"tokens": int(row[0]), "messages": int(row[1])}


def quota_status(org: Any, used_tokens: int) -> dict[str, Any]:
    """État du crédit pour l'org, selon son unité (tokens ou EUR).

    Renvoie : unit, limit (dans l'unité, None=illimité), used (dans l'unité), used_tokens,
    cost_eur (estimé), pct (None si illimité), blocked (≥ crédit), over_threshold (≥ seuil
    d'alerte, < blocage), threshold_pct. `org` = ligne cms_organizations (attrs ai_quota_*).
    """
    unit = getattr(org, "ai_quota_unit", None) or "tokens"
    cost_eur = tokens_to_eur(used_tokens)
    threshold = int(getattr(org, "ai_alert_threshold_pct", 0) or 0)

    if unit == "eur":
        raw = getattr(org, "ai_quota_eur", None)
        limit = float(raw) if raw and float(raw) > 0 else None
        used: float = cost_eur
    else:
        limit = effective_quota(getattr(org, "ai_quota_tokens", None))
        used = used_tokens

    pct = round(used / limit * 100, 1) if limit else None
    blocked = limit is not None and used >= limit
    over_threshold = pct is not None and 0 < threshold and pct >= threshold and not blocked
    return {
        "unit": unit,
        "limit": limit,
        "used": used,
        "used_tokens": used_tokens,
        "cost_eur": cost_eur,
        "pct": pct,
        "blocked": blocked,
        "over_threshold": over_threshold,
        "threshold_pct": threshold,
    }


async def usage_history(
    db: AsyncSession, id_org: int, days: int, today: date
) -> list[dict[str, Any]]:
    """Série quotidienne (date, tokens, messages, coût EUR estimé) sur `days` jours, sans
    trous (les jours sans usage = 0) → alimente le mini-graphe d'historique."""
    start = today - timedelta(days=days - 1)
    rows = (
        await db.execute(
            select(
                CmsAssistantStat.stat_date,
                CmsAssistantStat.token_count,
                CmsAssistantStat.message_count,
            ).where(
                CmsAssistantStat.id_org == id_org,
                CmsAssistantStat.stat_date >= start,
            )
        )
    ).all()
    by_date = {r[0]: (int(r[1]), int(r[2])) for r in rows}
    out: list[dict[str, Any]] = []
    for i in range(days):
        d = start + timedelta(days=i)
        tok, msg = by_date.get(d, (0, 0))
        out.append({
            "date": d.isoformat(),
            "tokens": tok,
            "messages": msg,
            "cost_eur": tokens_to_eur(tok),
        })
    return out
