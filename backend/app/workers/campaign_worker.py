"""Notifications retail media (§2.8 S5) — worker beat.

`check_campaign_notifications` (beat 5 min) : détecte les transitions de cycle de vie
des campagnes — démarrée (statut approved + date du jour dans [starts_on, ends_on]) et
terminée (ends_on dépassé ou complete manuel) — et, une fois par jour, la sous-diffusion
(SOV servi < seuil × SOV vendu, mesuré sur les jours PLEINS écoulés pour éviter la
dilution du jour en cours). Edge-triggered : dédup par colonnes de cms_campaigns
(started_notified_at / ended_notified_at / underserved_checked_on, migr 0077) — jamais
de re-notification, y compris au premier passage sur des campagnes déjà finies.

Émission via notifications.dispatch_sync (webhooks §XXII, psycopg2) après le commit du
sweep — best-effort, un webhook injoignable ne casse pas la tâche. Le contexte coûteux
(rapport de fin, SOV servi) n'est calculé que si l'org a une règle active pour
l'événement. Engine async frais + NullPool par exécution (même raison que
report_worker : asyncio.run = nouvelle boucle à chaque beat).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.campaign import CmsAdvertiser, CmsCampaign
from app.models.notification import CmsAlertRule
from app.services import notifications
from app.services.campaign_report import build_campaign_report
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

CAMPAIGN_EVENTS = ("campaign_started", "campaign_ended", "campaign_underserved")

# Sous-diffusion : notifie si SOV servi < (ratio/100) × SOV vendu. Le ratio par défaut
# est surchargeable par règle via params {"min_served_ratio_pct": 80} ; si plusieurs
# règles d'une même org en portent, on retient le plus élevé (le plus sensible).
DEFAULT_MIN_SERVED_RATIO_PCT = 80.0


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(settings.SIGNFLOW_TZ)
    except (ZoneInfoNotFoundError, KeyError):
        return ZoneInfo("UTC")


def _db_conn():
    url = settings.db_worker_url.replace("postgresql+asyncpg://", "postgresql://")
    return psycopg2.connect(url)


def _base_ctx(c: CmsCampaign, advertiser_name: str | None) -> dict:
    return {
        "id_campaign": c.id_campaign,
        "campaign_name": c.campaign_name,
        "advertiser_name": advertiser_name or "?",
        "starts_on": c.starts_on.isoformat(),
        "ends_on": c.ends_on.isoformat(),
        "sov_percent": float(c.sov_percent or 0),
    }


async def _collect(db: AsyncSession, tz: ZoneInfo) -> list[tuple[int, str, dict]]:
    """Balaye les campagnes, marque les dédups (sans commit) et renvoie les notifications
    à émettre : liste de (id_org, event_type, ctx)."""
    today = datetime.now(tz).date()
    now = datetime.now(UTC)
    pending: list[tuple[int, str, dict]] = []

    rules = (await db.execute(
        select(CmsAlertRule.id_org, CmsAlertRule.event_type, CmsAlertRule.params)
        .where(CmsAlertRule.enabled.is_(True), CmsAlertRule.event_type.in_(CAMPAIGN_EVENTS))
    )).all()
    has_rule = {(r.id_org, r.event_type) for r in rules}
    ratio_by_org: dict[int, float] = {}
    for r in rules:
        if r.event_type != "campaign_underserved":
            continue
        try:
            ratio = float((r.params or {}).get("min_served_ratio_pct",
                                               DEFAULT_MIN_SERVED_RATIO_PCT))
        except (TypeError, ValueError):
            ratio = DEFAULT_MIN_SERVED_RATIO_PCT
        ratio_by_org[r.id_org] = max(ratio_by_org.get(r.id_org, 0.0), ratio)

    camps = (await db.execute(
        select(CmsCampaign).where(
            CmsCampaign.is_deleted == False,  # noqa: E712
            CmsCampaign.status.in_(("approved", "completed")),
        )
    )).scalars().all()
    if not camps:
        return []
    adv_names = dict((await db.execute(
        select(CmsAdvertiser.id_advertiser, CmsAdvertiser.advertiser_name)
        .where(CmsAdvertiser.id_advertiser.in_({c.id_advertiser for c in camps}))
    )).all())

    for c in camps:
        ctx = _base_ctx(c, adv_names.get(c.id_advertiser))

        # ── Démarrée : la campagne devient effectivement live (une seule fois).
        if (c.status == "approved" and c.starts_on <= today <= c.ends_on
                and c.started_notified_at is None):
            c.started_notified_at = now
            if (c.id_org, "campaign_started") in has_rule:
                pending.append((c.id_org, "campaign_started", dict(ctx)))

        # ── Terminée : fin de période ou complete manuel. Le garde started_notified_at
        # évite de notifier en rafale les campagnes déjà finies au premier passage.
        if (c.ended_notified_at is None and c.started_notified_at is not None
                and (c.status == "completed"
                     or (c.status == "approved" and today > c.ends_on))):
            c.ended_notified_at = now
            if (c.id_org, "campaign_ended") in has_rule:
                ended_ctx = dict(ctx)
                try:
                    rep = await build_campaign_report(db, c, tz)
                    ended_ctx.update(
                        plays=rep["totals"]["plays"],
                        signed_plays=rep["totals"]["signed_plays"],
                        sov_served_pct=rep["sov"]["served_pct"],
                    )
                except Exception:  # noqa: BLE001 — le bilan est un bonus, pas un bloqueur
                    logger.exception("bilan campagne %s indisponible", c.id_campaign)
                pending.append((c.id_org, "campaign_ended", ended_ctx))

        # ── Sous-servie : campagne live avec du vendu, au moins un jour plein écoulé,
        # une évaluation par jour (jours pleins → pas de dilution du jour en cours).
        # AUDIO (S2, migr 0094) : le vendu est en spots/h → ratio = spots servis /
        # spots attendus (section `spots` du rapport, rapportée aux heures d'ouverture).
        is_audio = getattr(c, "campaign_kind", "visual") == "audio"
        has_sold = (int(c.spots_per_hour or 0) > 0 if is_audio
                    else float(c.sov_percent or 0) > 0)
        if (c.status == "approved" and c.starts_on <= today <= c.ends_on
                and today > c.starts_on and has_sold
                and c.underserved_checked_on != today
                and (c.id_org, "campaign_underserved") in has_rule):
            c.underserved_checked_on = today
            threshold = ratio_by_org.get(c.id_org, DEFAULT_MIN_SERVED_RATIO_PCT)
            try:
                until = today - timedelta(days=1)
                rep = await build_campaign_report(db, c, tz, until_d=until)
                if is_audio:
                    sp = rep.get("spots") or {}
                    ratio = sp.get("served_ratio_pct")
                    if ratio is not None and ratio < threshold:
                        under_ctx = dict(ctx)
                        under_ctx.update(
                            spots_served=sp.get("served"),
                            spots_expected=sp.get("expected"),
                            served_ratio_pct=ratio,
                            threshold_pct=threshold,
                            period_from=rep["period"]["from"],
                            period_until=rep["period"]["until"],
                        )
                        pending.append((c.id_org, "campaign_underserved", under_ctx))
                else:
                    served = rep["sov"]["served_pct"]
                    sold = float(c.sov_percent)
                    if served is not None and served < sold * threshold / 100.0:
                        under_ctx = dict(ctx)
                        under_ctx.update(
                            sov_served_pct=served,
                            threshold_pct=threshold,
                            period_from=rep["period"]["from"],
                            period_until=rep["period"]["until"],
                        )
                        pending.append((c.id_org, "campaign_underserved", under_ctx))
            except Exception:  # noqa: BLE001
                logger.exception("évaluation sous-diffusion campagne %s échouée",
                                 c.id_campaign)

    return pending


async def _sweep() -> list[tuple[int, str, dict]]:
    tz = _tz()
    # Engine FRAIS + NullPool : asyncio.run() = nouvelle boucle à chaque beat (cf.
    # report_worker) — un engine module-level casserait sur asyncpg.
    engine = create_async_engine(settings.db_worker_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as db:
            pending = await _collect(db, tz)
            await db.commit()
            return pending
    finally:
        await engine.dispose()


@celery_app.task(name="app.workers.campaign_worker.check_campaign_notifications")
def check_campaign_notifications() -> dict:
    pending = asyncio.run(_sweep())
    sent = 0
    if pending:
        # Dispatch APRÈS le commit des dédups (comme check_player_health) : un webhook
        # injoignable est tracé failed dans cms_notification_log, jamais re-tenté.
        conn = _db_conn()
        try:
            for id_org, event_type, ctx in pending:
                try:
                    sent += notifications.dispatch_sync(conn, id_org, event_type, ctx)
                except Exception:  # noqa: BLE001
                    logger.exception("dispatch %s échoué (org %s)", event_type, id_org)
        finally:
            conn.close()
    return {"pending": len(pending), "sent": sent}
