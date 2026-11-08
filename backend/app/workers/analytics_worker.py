"""Analytics (§XXIV) — rollup quotidien des métriques réseau.

`rollup_network_metrics` : tâche beat (1×/jour) qui enregistre, pour chaque org, un instantané
des métriques réseau du jour dans `cms_network_metrics_daily`. Alimente les séries temporelles
de l'Executive Dashboard (uptime, alertes, health score) — l'historique se construit à partir
du déploiement (les players ne sont qu'un snapshot, aucun historique n'existait avant).

BYPASSRLS via le rôle worker (psycopg2 sync, comme pop_worker). UPSERT idempotent par
(id_org, metric_date) → plusieurs exécutions le même jour rafraîchissent la ligne.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg2

from app.core.config import settings
from app.services.analytics import FRESH_THRESHOLD, compute_health_score
from app.services.pop_counting import COUNTED_SQL
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _db_conn():
    url = settings.db_worker_url.replace("postgresql+asyncpg://", "postgresql://")
    return psycopg2.connect(url)


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(settings.SIGNFLOW_TZ)
    except (ZoneInfoNotFoundError, KeyError):
        return ZoneInfo("UTC")


@celery_app.task(name="app.workers.analytics_worker.rollup_network_metrics")
def rollup_network_metrics() -> dict:
    """Écrit/rafraîchit le rollup du jour pour chaque org ayant des players."""
    now = datetime.now(UTC)
    fresh_after = now - FRESH_THRESHOLD
    since_24h = now - timedelta(hours=24)
    metric_date = datetime.now(_tz()).date()

    conn = _db_conn()
    written = 0
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT id_org FROM cms_players")
            org_ids = [r[0] for r in cur.fetchall()]

            for org in org_ids:
                cur.execute(
                    """
                    SELECT
                        count(*) AS total,
                        count(*) FILTER (WHERE status = 'online') AS online,
                        count(*) FILTER (WHERE status = 'warning') AS warning,
                        count(*) FILTER (WHERE status IN ('offline','critical')) AS offline,
                        count(*) FILTER (WHERE status = 'maintenance') AS maintenance,
                        count(*) FILTER (WHERE last_seen_at >= %s) AS fresh
                    FROM cms_players WHERE id_org = %s
                    """,
                    (fresh_after, org),
                )
                f = cur.fetchone()
                total, online, warning, offline, maintenance, fresh = (x or 0 for x in f)
                if total == 0:
                    continue

                # Conformité : players ayant réellement diffusé dans les 24 dernières heures.
                # Une preuve émise alors que la sortie vidéo était coupée (migr 0102) ou que
                # la zone était recouverte par un overlay plein écran (migr 0125) n'atteste
                # aucune diffusion — un player qui n'aurait joué que dans le noir ne doit pas
                # être compté « conforme », ni gonfler l'antenne. Condition partagée avec
                # tout le reste du produit : services/pop_counting.
                cur.execute(
                    "SELECT count(DISTINCT id_player) FROM cms_proof_of_play "
                    "WHERE id_org = %s AND played_at >= %s AND " + COUNTED_SQL,
                    (org, since_24h),
                )
                conforming = cur.fetchone()[0] or 0

                # Contenu diffusé sur les 24 dernières heures (marqueur quotidien).
                cur.execute(
                    "SELECT count(*), COALESCE(sum(duration_ms), 0) FROM cms_proof_of_play "
                    "WHERE id_org = %s AND played_at >= %s AND " + COUNTED_SQL,
                    (org, since_24h),
                )
                plays_count, total_ms = cur.fetchone()
                plays_count = plays_count or 0
                play_seconds = round((total_ms or 0) / 1000)

                cur.execute(
                    "SELECT count(*) FROM cms_notification_log "
                    "WHERE id_org = %s AND created_at >= %s",
                    (org, since_24h),
                )
                alerts_active = cur.fetchone()[0] or 0

                conformity_pct = round(100.0 * conforming / total, 2)
                health = compute_health_score(
                    total=total, online=online, fresh=fresh,
                    conforming=conforming, open_alerts=alerts_active,
                )

                cur.execute(
                    """
                    INSERT INTO cms_network_metrics_daily (
                        id_org, metric_date, players_total, players_online, players_warning,
                        players_offline, players_maintenance, conformity_pct, alerts_active,
                        plays_count, play_seconds, health_score
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (id_org, metric_date) DO UPDATE SET
                        players_total = EXCLUDED.players_total,
                        players_online = EXCLUDED.players_online,
                        players_warning = EXCLUDED.players_warning,
                        players_offline = EXCLUDED.players_offline,
                        players_maintenance = EXCLUDED.players_maintenance,
                        conformity_pct = EXCLUDED.conformity_pct,
                        alerts_active = EXCLUDED.alerts_active,
                        plays_count = EXCLUDED.plays_count,
                        play_seconds = EXCLUDED.play_seconds,
                        health_score = EXCLUDED.health_score
                    """,
                    (org, metric_date, total, online, warning, offline, maintenance,
                     conformity_pct, alerts_active, plays_count, play_seconds, health),
                )
                written += 1
    finally:
        conn.close()

    logger.info("Analytics rollup : %s org(s) le %s", written, metric_date)
    return {"date": metric_date.isoformat(), "orgs": written}
