"""Jobs de génération de contenu IA asynchrone (§ génération — vidéo/audio)

Revision ID: 0053
Revises: 0052
Create Date: 2026-06-22 00:00:00.000000

cms_generation_jobs : un job par génération lente (vidéo/audio). L'image reste
synchrone (endpoint). TENANT-SCOPED (RLS id_org). Grants auto-hérités de 0044.
Cf. docs/PLAN_GENERATION_CONTENU.md.
"""

from alembic import op

revision: str = "0053"
down_revision: str | None = "0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cms_generation_jobs (
            id_job        BIGSERIAL PRIMARY KEY,
            id_org        BIGINT NOT NULL REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            kind          VARCHAR(12) NOT NULL,          -- video | music | voice
            provider      VARCHAR(20) NOT NULL,          -- fal | elevenlabs
            model         VARCHAR(80) NOT NULL,
            prompt        TEXT NOT NULL,
            aspect_ratio  VARCHAR(12),
            params        JSONB NOT NULL DEFAULT '{}'::jsonb,
            status        VARCHAR(12) NOT NULL DEFAULT 'pending',  -- pending|processing|ready|failed
            id_media      BIGINT,
            cost_usd      NUMERIC(10,4),
            error_detail  TEXT,
            created_by    BIGINT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_generation_jobs_org ON cms_generation_jobs (id_org)")
    op.execute("CREATE INDEX idx_generation_jobs_status ON cms_generation_jobs (id_org, status)")
    op.execute("ALTER TABLE cms_generation_jobs ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY cms_generation_jobs_org_isolation ON cms_generation_jobs
            USING (id_org = current_setting('app.current_org_id', true)::bigint)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cms_generation_jobs")
