"""Templates, Playlists & Schedules — Sprint 1.4

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-22 00:00:00.000000

Crée :
  - cms_templates  (§XIII) — layout JSONB, RLS
  - cms_playlists  (§XIII) — FK template, RLS
  - cms_playlist_items     — FK playlist + media, sort_order
  - cms_schedules  (§XIII) — priorité, RLS
  - cms_schedule_rules     — règles horaires (always/weekly/date_range)
  - cms_schedule_targets   — cibles player/player_group
"""

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cms_templates ──────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE cms_templates (
            id_template     BIGSERIAL PRIMARY KEY,
            id_org          BIGINT NOT NULL REFERENCES cms_organizations(id_org),
            template_name   VARCHAR(255) NOT NULL,
            description     TEXT,
            layout          JSONB NOT NULL DEFAULT '{}',
            preview_url     TEXT,
            is_deleted      BOOLEAN NOT NULL DEFAULT false,
            created_by      BIGINT REFERENCES cms_users(id_user),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_cms_templates_id_org ON cms_templates(id_org)")
    op.execute("ALTER TABLE cms_templates ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY cms_templates_org_isolation ON cms_templates
            USING (id_org = current_setting('app.current_org_id', true)::bigint)
    """)

    # ── cms_playlists ──────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE cms_playlists (
            id_playlist     BIGSERIAL PRIMARY KEY,
            id_org          BIGINT NOT NULL REFERENCES cms_organizations(id_org),
            playlist_name   VARCHAR(255) NOT NULL,
            description     TEXT,
            id_template     BIGINT REFERENCES cms_templates(id_template),
            is_deleted      BOOLEAN NOT NULL DEFAULT false,
            created_by      BIGINT REFERENCES cms_users(id_user),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_cms_playlists_id_org ON cms_playlists(id_org)")
    op.execute("ALTER TABLE cms_playlists ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY cms_playlists_org_isolation ON cms_playlists
            USING (id_org = current_setting('app.current_org_id', true)::bigint)
    """)

    # ── cms_playlist_items ─────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE cms_playlist_items (
            id_item         BIGSERIAL PRIMARY KEY,
            id_playlist     BIGINT NOT NULL REFERENCES cms_playlists(id_playlist),
            id_media        BIGINT NOT NULL REFERENCES cms_media(id_media),
            sort_order      INT NOT NULL DEFAULT 0,
            duration_ms     INT,
            zone_index      INT NOT NULL DEFAULT 0,
            transition_type VARCHAR(20) NOT NULL DEFAULT 'cut',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX ix_cms_playlist_items_id_playlist ON cms_playlist_items(id_playlist)"
    )

    # ── cms_schedules ──────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE cms_schedules (
            id_schedule     BIGSERIAL PRIMARY KEY,
            id_org          BIGINT NOT NULL REFERENCES cms_organizations(id_org),
            schedule_name   VARCHAR(255) NOT NULL,
            id_playlist     BIGINT NOT NULL REFERENCES cms_playlists(id_playlist),
            priority        INT NOT NULL DEFAULT 0,
            is_active       BOOLEAN NOT NULL DEFAULT true,
            is_deleted      BOOLEAN NOT NULL DEFAULT false,
            created_by      BIGINT REFERENCES cms_users(id_user),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_cms_schedules_id_org ON cms_schedules(id_org)")
    op.execute("CREATE INDEX ix_cms_schedules_id_playlist ON cms_schedules(id_playlist)")
    op.execute("ALTER TABLE cms_schedules ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY cms_schedules_org_isolation ON cms_schedules
            USING (id_org = current_setting('app.current_org_id', true)::bigint)
    """)

    # ── cms_schedule_rules ─────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE cms_schedule_rules (
            id_rule         BIGSERIAL PRIMARY KEY,
            id_schedule     BIGINT NOT NULL REFERENCES cms_schedules(id_schedule),
            rule_type       VARCHAR(20) NOT NULL DEFAULT 'weekly',
            days_of_week    INT[],
            time_start      TIME,
            time_end        TIME,
            date_from       DATE,
            date_to         DATE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX ix_cms_schedule_rules_id_schedule ON cms_schedule_rules(id_schedule)"
    )

    # ── cms_schedule_targets ───────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE cms_schedule_targets (
            id_target       BIGSERIAL PRIMARY KEY,
            id_schedule     BIGINT NOT NULL REFERENCES cms_schedules(id_schedule),
            target_type     VARCHAR(20) NOT NULL,
            target_id       BIGINT NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX ix_cms_schedule_targets_id_schedule "
        "ON cms_schedule_targets(id_schedule)"
    )
    op.execute(
        "CREATE INDEX ix_cms_schedule_targets_target "
        "ON cms_schedule_targets(target_type, target_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cms_schedule_targets")
    op.execute("DROP TABLE IF EXISTS cms_schedule_rules")
    op.execute("DROP TABLE IF EXISTS cms_schedules")
    op.execute("DROP TABLE IF EXISTS cms_playlist_items")
    op.execute("DROP TABLE IF EXISTS cms_playlists")
    op.execute("DROP TABLE IF EXISTS cms_templates")
