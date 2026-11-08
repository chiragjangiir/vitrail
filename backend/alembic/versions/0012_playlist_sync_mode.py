"""Wall-clock sync playlists — Sprint 2.3

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-28 00:00:00.000000

Ajoute :
  - cms_playlists.sync_mode VARCHAR(20) DEFAULT 'wall_clock'
    'wall_clock' (défaut) = position calculée par l'heure (déterministe, synchronisé)
    'loop'                = reprise depuis le début à chaque reconnexion (opt-out)
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cms_playlists",
        sa.Column(
            "sync_mode",
            sa.String(20),
            server_default="wall_clock",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("cms_playlists", "sync_mode")
