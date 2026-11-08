"""Executive Dashboard §24.3 — rapports PDF planifiés par email + historique

Revision ID: 0068
Revises: 0067
Create Date: 2026-07-04 00:00:00.000000

- cms_report_schedules : planification d'un rapport exécutif récurrent (hebdo/mensuel) →
  génération PDF + envoi email aux destinataires. next_run_at piloté par le worker beat.
- cms_report_history : trace des rapports générés/envoyés (status sent|failed).
TENANT-SCOPED (RLS id_org). Grants héritent de 0044. Policy = pattern 0063/0065/0066.
"""

from alembic import op

revision: str = "0068"
down_revision: str | None = "0067"
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
        CREATE TABLE cms_report_schedules (
            id_schedule   BIGSERIAL PRIMARY KEY,
            id_org        BIGINT NOT NULL REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            label         VARCHAR(120),
            report_type   VARCHAR(30) NOT NULL DEFAULT 'executive',
            frequency     VARCHAR(10) NOT NULL DEFAULT 'monthly',   -- weekly | monthly
            send_hour     SMALLINT NOT NULL DEFAULT 7,              -- heure locale d'envoi
            send_dow      SMALLINT NOT NULL DEFAULT 1,              -- weekly : 0=lun … 6=dim
            send_dom      SMALLINT NOT NULL DEFAULT 1,              -- monthly : jour du mois (1-28)
            period_days   INTEGER NOT NULL DEFAULT 30,
            language      VARCHAR(5) NOT NULL DEFAULT 'fr',
            recipients    JSONB NOT NULL DEFAULT '[]'::jsonb,       -- liste d'emails
            include_roi   BOOLEAN NOT NULL DEFAULT true,
            enabled       BOOLEAN NOT NULL DEFAULT true,
            last_run_at   TIMESTAMPTZ,
            next_run_at   TIMESTAMPTZ,
            created_by    BIGINT REFERENCES cms_users(id_user) ON DELETE SET NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_report_sched_due ON cms_report_schedules (enabled, next_run_at)")
    op.execute("CREATE INDEX idx_report_sched_org ON cms_report_schedules (id_org)")
    _rls("cms_report_schedules")

    op.execute(
        """
        CREATE TABLE cms_report_history (
            id_history   BIGSERIAL PRIMARY KEY,
            id_org       BIGINT NOT NULL REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            id_schedule  BIGINT REFERENCES cms_report_schedules(id_schedule) ON DELETE SET NULL,
            report_type  VARCHAR(30) NOT NULL DEFAULT 'executive',
            period_from  DATE,
            period_until DATE,
            recipients   JSONB NOT NULL DEFAULT '[]'::jsonb,
            status       VARCHAR(10) NOT NULL DEFAULT 'sent',       -- sent | failed
            detail       TEXT,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_report_hist_org ON cms_report_history (id_org, created_at)")
    _rls("cms_report_history")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cms_report_history")
    op.execute("DROP TABLE IF EXISTS cms_report_schedules")
