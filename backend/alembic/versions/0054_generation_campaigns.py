"""Campagnes de génération IA (§ génération — Phase 4, campagne one-shot)

Revision ID: 0054
Revises: 0053
Create Date: 2026-06-23 00:00:00.000000

cms_generation_campaigns : un brief NL → un bundle de visuels (plusieurs concepts ×
plusieurs ratios). Chaque asset = une ligne cms_generation_jobs portant id_campaign.
TENANT-SCOPED (RLS id_org). Grants auto-hérités de 0044 (ALTER DEFAULT PRIVILEGES).
Cf. docs/PLAN_GENERATION_CONTENU.md §4 / §6.
"""

from alembic import op

revision: str = "0054"
down_revision: str | None = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cms_generation_campaigns (
            id_campaign     BIGSERIAL PRIMARY KEY,
            id_org          BIGINT NOT NULL REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            brief           TEXT NOT NULL,
            model           VARCHAR(80) NOT NULL,
            ratios          JSONB NOT NULL DEFAULT '[]'::jsonb,
            status          VARCHAR(12) NOT NULL DEFAULT 'pending',  -- pending|processing|ready|failed
            total_cost_usd  NUMERIC(10,4),
            created_by      BIGINT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_generation_campaigns_org ON cms_generation_campaigns (id_org)")
    op.execute("ALTER TABLE cms_generation_campaigns ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY cms_generation_campaigns_org_isolation ON cms_generation_campaigns
            USING (id_org = current_setting('app.current_org_id', true)::bigint)
        """
    )
    op.execute("ALTER TABLE cms_generation_jobs ADD COLUMN id_campaign BIGINT")
    op.execute(
        "CREATE INDEX idx_generation_jobs_campaign ON cms_generation_jobs (id_campaign)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cms_generation_jobs DROP COLUMN IF EXISTS id_campaign")
    op.execute("DROP TABLE IF EXISTS cms_generation_campaigns")
