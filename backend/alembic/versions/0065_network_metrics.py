"""Executive Dashboard (§XXIV) — rollup quotidien des métriques réseau

Revision ID: 0065
Revises: 0064
Create Date: 2026-07-04 00:00:00.000000

- cms_network_metrics_daily : 1 ligne / org / jour, écrite par la tâche beat
  `rollup_network_metrics`. Alimente les séries temporelles de l'Executive Dashboard
  (uptime, alertes, health score). L'historique se remplit à partir du déploiement —
  aucune donnée n'était collectée avant (les players ne sont qu'un snapshot).
TENANT-SCOPED (RLS id_org). Grants héritent de 0044. Policy = pattern 0063.
"""

from alembic import op

revision: str = "0065"
down_revision: str | None = "0064"
branch_labels = None
depends_on = None


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_org_isolation ON {table} "
        f"USING (id_org = current_setting('app.current_org_id', true)::bigint)"
    )


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cms_network_metrics_daily (
            id_metric           BIGSERIAL PRIMARY KEY,
            id_org              BIGINT NOT NULL
                                REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            metric_date         DATE NOT NULL,
            players_total       INTEGER NOT NULL DEFAULT 0,
            players_online      INTEGER NOT NULL DEFAULT 0,
            players_warning     INTEGER NOT NULL DEFAULT 0,
            players_offline     INTEGER NOT NULL DEFAULT 0,
            players_maintenance INTEGER NOT NULL DEFAULT 0,
            conformity_pct      NUMERIC(5,2),
            alerts_active       INTEGER NOT NULL DEFAULT 0,
            plays_count         BIGINT NOT NULL DEFAULT 0,
            play_seconds        BIGINT NOT NULL DEFAULT 0,
            health_score        SMALLINT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_network_metrics_org_day UNIQUE (id_org, metric_date)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_network_metrics_org_date "
        "ON cms_network_metrics_daily (id_org, metric_date)"
    )
    _rls("cms_network_metrics_daily")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cms_network_metrics_daily")
