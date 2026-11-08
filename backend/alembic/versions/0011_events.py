"""Event Engine — Sprint 2.1

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-26 00:00:00.000000

Crée :
  - cms_events               (§XVI.4 / §XX) — Event Override, machine à états
  - cms_event_ai_suggestions (§XX.8)        — Suggestions IA en attente de validation
"""

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cms_events ─────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE cms_events (
            id_event       BIGSERIAL PRIMARY KEY,
            id_org         BIGINT NOT NULL REFERENCES cms_organizations(id_org),
            event_name     VARCHAR(255) NOT NULL,
            event_type     VARCHAR(30) NOT NULL,
            id_playlist    BIGINT NOT NULL REFERENCES cms_playlists(id_playlist),
            priority       SMALLINT NOT NULL DEFAULT 70,
            duration_ms    BIGINT,
            revert_on_end  BOOLEAN NOT NULL DEFAULT true,
            status         VARCHAR(20) NOT NULL DEFAULT 'inactive',
            trigger_config JSONB,
            target_config  JSONB NOT NULL,
            activated_at   TIMESTAMPTZ,
            expires_at     TIMESTAMPTZ,
            created_by     BIGINT REFERENCES cms_users(id_user),
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_cms_events_org    ON cms_events(id_org)")
    op.execute("CREATE INDEX idx_cms_events_status ON cms_events(status)")
    op.execute("ALTER TABLE cms_events ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY cms_events_org_isolation ON cms_events
            USING (id_org = current_setting('app.current_org_id', true)::bigint)
    """)

    # ── cms_event_ai_suggestions ───────────────────────────────────────────────
    op.execute("""
        CREATE TABLE cms_event_ai_suggestions (
            id_suggestion    BIGSERIAL PRIMARY KEY,
            id_org           BIGINT NOT NULL REFERENCES cms_organizations(id_org),
            trigger_summary  TEXT NOT NULL,
            suggested_config JSONB NOT NULL,
            id_playlist      BIGINT REFERENCES cms_playlists(id_playlist),
            confidence       NUMERIC(4,3) NOT NULL,
            based_on         TEXT,
            status           VARCHAR(20) NOT NULL DEFAULT 'pending',
            reviewed_by      BIGINT REFERENCES cms_users(id_user),
            reviewed_at      TIMESTAMPTZ,
            id_event_created BIGINT REFERENCES cms_events(id_event),
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX idx_ceas_org_status ON cms_event_ai_suggestions(id_org, status)"
    )
    op.execute("ALTER TABLE cms_event_ai_suggestions ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY cms_event_ai_suggestions_org_isolation ON cms_event_ai_suggestions
            USING (id_org = current_setting('app.current_org_id', true)::bigint)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cms_event_ai_suggestions")
    op.execute("DROP TABLE IF EXISTS cms_events")
