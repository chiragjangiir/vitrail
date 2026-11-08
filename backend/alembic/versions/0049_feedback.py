"""Retours utilisateurs (feedback) + triage IA (§ retours UI)

Revision ID: 0049
Revises: 0048
Create Date: 2026-06-21 00:00:00.000000

Table `cms_feedback` (tenant-scoped, RLS) : un utilisateur signale un bug / une suggestion /
une amélioration / un point UX / une question depuis l'UI. Auto-contexte (page, route, user
agent, version, erreurs JS captées). Triage IA best-effort (catégorie/sévérité/résumé) rempli
par un worker LiteLLM. Tri par le super-admin (statut + note).

La table héritant des ALTER DEFAULT PRIVILEGES de 0044 (créée par le rôle signflow), elle est
auto-grantée à signflow_app/worker → seul ENABLE RLS + policy org_isolation sont nécessaires.
"""

from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cms_feedback (
            id_feedback     BIGSERIAL PRIMARY KEY,
            id_org          BIGINT NOT NULL REFERENCES cms_organizations(id_org),
            id_user         BIGINT NOT NULL REFERENCES cms_users(id_user),
            feedback_type   VARCHAR(20) NOT NULL
                CHECK (feedback_type IN ('bug','suggestion','amelioration','ux','question')),
            description     TEXT NOT NULL,
            page_url        TEXT,
            route           TEXT,
            user_agent      TEXT,
            app_version     VARCHAR(40),
            console_errors  JSONB NOT NULL DEFAULT '[]'::jsonb,
            severity        SMALLINT CHECK (severity IS NULL OR severity IN (1,2,3)),
            status          VARCHAR(20) NOT NULL DEFAULT 'new'
                CHECK (status IN ('new','triaged','planned','in_progress','done','rejected')),
            admin_note      TEXT,
            ai_category     VARCHAR(40),
            ai_severity     SMALLINT CHECK (ai_severity IS NULL OR ai_severity IN (1,2,3)),
            ai_summary      TEXT,
            ai_processed_at TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_feedback_org ON cms_feedback (id_org)")
    op.execute("CREATE INDEX idx_feedback_status ON cms_feedback (status)")
    op.execute("CREATE INDEX idx_feedback_created ON cms_feedback (created_at DESC)")
    op.execute("ALTER TABLE cms_feedback ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY cms_feedback_org_isolation ON cms_feedback
            USING (id_org = current_setting('app.current_org_id', true)::bigint)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE cms_feedback")
