"""Notifications & alertes (§XXII) — canaux webhook + règles + journal

Revision ID: 0063
Revises: 0062
Create Date: 2026-07-02 00:00:00.000000

- cms_notification_channels : destination d'alerte par org (MVP = webhook, config JSONB {url}).
- cms_alert_rules : (event_type → canal) actif ; params JSONB pour de futurs seuils/filtres.
- cms_notification_log : trace des envois (event, sujet, corps, status sent/failed, détail).
TENANT-SCOPED (RLS id_org). Grants héritent de 0044. Policy = pattern 0052.
"""

from alembic import op

revision: str = "0063"
down_revision: str | None = "0062"
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
        CREATE TABLE cms_notification_channels (
            id_channel   BIGSERIAL PRIMARY KEY,
            id_org       BIGINT NOT NULL REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            name         VARCHAR(80) NOT NULL,
            channel_type VARCHAR(20) NOT NULL DEFAULT 'webhook',   -- webhook (email ultérieur)
            config       JSONB NOT NULL DEFAULT '{}'::jsonb,       -- webhook: {url}
            enabled      BOOLEAN NOT NULL DEFAULT true,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_notif_channels_org ON cms_notification_channels (id_org)")
    _rls("cms_notification_channels")

    op.execute(
        """
        CREATE TABLE cms_alert_rules (
            id_rule    BIGSERIAL PRIMARY KEY,
            id_org     BIGINT NOT NULL REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            event_type VARCHAR(40) NOT NULL,   -- player_offline | deployment_failed | feed_error…
            id_channel BIGINT NOT NULL
                       REFERENCES cms_notification_channels(id_channel) ON DELETE CASCADE,
            params     JSONB NOT NULL DEFAULT '{}'::jsonb,
            enabled    BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_alert_rules_org ON cms_alert_rules (id_org, event_type)")
    _rls("cms_alert_rules")

    op.execute(
        """
        CREATE TABLE cms_notification_log (
            id_log     BIGSERIAL PRIMARY KEY,
            id_org     BIGINT NOT NULL REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            id_rule    BIGINT REFERENCES cms_alert_rules(id_rule) ON DELETE SET NULL,
            event_type VARCHAR(40) NOT NULL,
            subject    VARCHAR(200),
            body       TEXT,
            status     VARCHAR(20) NOT NULL DEFAULT 'sent',   -- sent | failed
            detail     TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_notif_log_org ON cms_notification_log (id_org, created_at)")
    _rls("cms_notification_log")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cms_notification_log")
    op.execute("DROP TABLE IF EXISTS cms_alert_rules")
    op.execute("DROP TABLE IF EXISTS cms_notification_channels")
