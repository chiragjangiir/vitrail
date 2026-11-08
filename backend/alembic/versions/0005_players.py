"""Players Sprint 1.5 — métriques heartbeat + expiry token

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-23 00:00:00.000000

Ajoute à cms_players :
  - cpu_usage, ram_usage, disk_usage  — métriques heartbeat (FLOAT)
  - current_playlist_id               — playlist en cours (FK cms_playlists, SET NULL)
  - token_expires_at                  — expiry du player_token
"""

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE cms_players
            ADD COLUMN cpu_usage            FLOAT,
            ADD COLUMN ram_usage            FLOAT,
            ADD COLUMN disk_usage           FLOAT,
            ADD COLUMN current_playlist_id  BIGINT
                REFERENCES cms_playlists(id_playlist) ON DELETE SET NULL,
            ADD COLUMN token_expires_at     TIMESTAMPTZ
    """)
    op.execute(
        "CREATE INDEX ix_cms_players_current_playlist_id ON cms_players(current_playlist_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_cms_players_current_playlist_id")
    op.execute("""
        ALTER TABLE cms_players
            DROP COLUMN IF EXISTS cpu_usage,
            DROP COLUMN IF EXISTS ram_usage,
            DROP COLUMN IF EXISTS disk_usage,
            DROP COLUMN IF EXISTS current_playlist_id,
            DROP COLUMN IF EXISTS token_expires_at
    """)
