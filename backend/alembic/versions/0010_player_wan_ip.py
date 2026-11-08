"""Players Sprint 1.11 — WAN IP

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-25 00:00:00.000000

Ajoute à cms_players :
  - wan_ip  — IP WAN signalée par le player (ipify.org)
"""

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE cms_players ADD COLUMN wan_ip INET")


def downgrade() -> None:
    op.execute("ALTER TABLE cms_players DROP COLUMN IF EXISTS wan_ip")
