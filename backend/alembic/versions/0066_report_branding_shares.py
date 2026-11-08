"""Executive Dashboard §XXIV — branding rapport white-label + share links

Revision ID: 0066
Revises: 0065
Create Date: 2026-07-04 00:00:00.000000

- cms_report_branding : personnalisation white-label du rapport PDF + hypothèses ROI, 1/org.
- cms_report_share_links : liens de partage sans login (§24.4) — token opaque révocable, TTL.
TENANT-SCOPED (RLS id_org). Grants héritent de 0044. Policy = pattern 0063/0065.
"""

from alembic import op

revision: str = "0066"
down_revision: str | None = "0065"
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
        CREATE TABLE cms_report_branding (
            id_org             BIGINT PRIMARY KEY
                               REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            logo_key           TEXT,                       -- objet MinIO (préfixe report-logos/)
            primary_color      VARCHAR(7) NOT NULL DEFAULT '#4875B4',
            report_title       VARCHAR(120),
            report_subtitle    VARCHAR(200),
            roi_hours_per_day  NUMERIC(4,1) NOT NULL DEFAULT 12,
            roi_contacts_hour  INTEGER NOT NULL DEFAULT 50, -- contacts estimés / h / écran
            roi_cpm_eur        NUMERIC(8,2) NOT NULL DEFAULT 5,
            -- roi_paper_eur : coût affiche papier évité / mois / écran
            roi_paper_eur      NUMERIC(8,2) NOT NULL DEFAULT 50,
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    _rls("cms_report_branding")

    op.execute(
        """
        CREATE TABLE cms_report_share_links (
            id_share         BIGSERIAL PRIMARY KEY,
            id_org           BIGINT NOT NULL REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            token            VARCHAR(64) NOT NULL UNIQUE,
            label            VARCHAR(120),
            period_days      INTEGER NOT NULL DEFAULT 30,   -- fenêtre affichée par le lien
            expires_at       TIMESTAMPTZ,                   -- NULL = permanent
            revoked          BOOLEAN NOT NULL DEFAULT false,
            created_by       BIGINT REFERENCES cms_users(id_user) ON DELETE SET NULL,
            access_count     INTEGER NOT NULL DEFAULT 0,
            last_accessed_at TIMESTAMPTZ,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_report_shares_org ON cms_report_share_links (id_org)")
    _rls("cms_report_share_links")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cms_report_share_links")
    op.execute("DROP TABLE IF EXISTS cms_report_branding")
