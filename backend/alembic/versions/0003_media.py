"""Media Library — Sprint 1.2

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-18 00:00:00.000000

Crée :
  - cms_media (§XVI.2) — avec RLS policy, index partiel ISRC, chiffrement SSE-S3
  - FK org_fallback_audio_id → cms_media(id_media) sur cms_organizations
  - FK fallback_audio_id → cms_media(id_media) sur cms_players
"""

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Table cms_media ────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE cms_media (
            id_media         BIGSERIAL PRIMARY KEY,
            id_org           BIGINT NOT NULL REFERENCES cms_organizations(id_org),
            media_name       VARCHAR(255) NOT NULL,
            media_type       VARCHAR(30) NOT NULL,
            mime_type        VARCHAR(100),
            storage_key      TEXT NOT NULL,
            cdn_url          TEXT,
            file_size_bytes  BIGINT,
            duration_ms      INT,
            width            INT,
            height           INT,
            checksum_sha256  TEXT NOT NULL,
            thumbnail_url    TEXT,
            source           VARCHAR(20) NOT NULL DEFAULT 'upload',
            attribution_text TEXT,
            isrc             VARCHAR(12),
            rights_metadata  JSONB NOT NULL DEFAULT '{}',
            metadata         JSONB NOT NULL DEFAULT '{}',
            transcode_status VARCHAR(20) NOT NULL DEFAULT 'pending',
            is_encrypted     BOOLEAN NOT NULL DEFAULT true,
            is_deleted       BOOLEAN NOT NULL DEFAULT false,
            created_by       BIGINT REFERENCES cms_users(id_user),
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("CREATE INDEX idx_cms_media_org  ON cms_media(id_org)")
    op.execute("CREATE INDEX idx_cms_media_type ON cms_media(media_type)")
    op.execute("CREATE INDEX idx_cms_media_isrc ON cms_media(isrc) WHERE isrc IS NOT NULL")

    # ── RLS ────────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE cms_media ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cms_media FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY cms_media_org_isolation ON cms_media
            USING (id_org = current_setting('app.current_org_id', true)::BIGINT)
    """)
    op.execute("GRANT ALL ON cms_media TO signflow_app")
    op.execute("GRANT ALL ON cms_media TO signflow_worker")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE cms_media_id_media_seq TO signflow_app")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE cms_media_id_media_seq TO signflow_worker")

    # ── FK sur cms_organizations ───────────────────────────────────────────────
    op.execute("""
        ALTER TABLE cms_organizations
            ADD CONSTRAINT fk_org_fallback_audio
            FOREIGN KEY (org_fallback_audio_id) REFERENCES cms_media(id_media)
            ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED
    """)

    # ── FK sur cms_players ─────────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE cms_players
            ADD CONSTRAINT fk_player_fallback_audio
            FOREIGN KEY (fallback_audio_id) REFERENCES cms_media(id_media)
            ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE cms_players DROP CONSTRAINT IF EXISTS fk_player_fallback_audio")
    op.execute("ALTER TABLE cms_organizations DROP CONSTRAINT IF EXISTS fk_org_fallback_audio")
    op.execute("DROP TABLE IF EXISTS cms_media")
