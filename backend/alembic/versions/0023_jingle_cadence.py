"""Cadence configurable des jingles (§XIX)

Revision ID: 0023
Revises: 0022
Create Date: 2026-05-31 22:00:00.000000

Un panier jingle peut être joué automatiquement soit tous les X morceaux, soit
toutes les X minutes (au lieu d'une cadence déduite du mix_ratio).

cms_audio_baskets :
  + trigger_mode  ('tracks' | 'minutes') — mode de récurrence (jingle)
  + trigger_value INT                    — X morceaux ou X minutes
"""

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cms_audio_baskets ADD COLUMN trigger_mode VARCHAR(10) NOT NULL DEFAULT 'tracks'"
    )
    op.execute(
        "ALTER TABLE cms_audio_baskets ADD COLUMN trigger_value INT NOT NULL DEFAULT 5"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cms_audio_baskets DROP COLUMN IF EXISTS trigger_value")
    op.execute("ALTER TABLE cms_audio_baskets DROP COLUMN IF EXISTS trigger_mode")
