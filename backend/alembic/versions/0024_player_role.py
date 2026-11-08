"""Rôle audio/contenu par player (§XIX)

Revision ID: 0024
Revises: 0023
Create Date: 2026-05-31 23:30:00.000000

Un player a un rôle explicite qui détermine sa sortie audio et son éligibilité
aux groupes :
  - content : contenu visuel uniquement (défaut) — sortie HDMI/jack/USB
  - audio   : player audio dédié (paniers §XIX) — sortie jack/USB
  - mixed   : contenu + paniers sur la même machine — sortie jack/USB,
              son des contenus standards forcé muté (sortie réservée aux paniers)

cms_players :
  + player_role ('content' | 'audio' | 'mixed') NOT NULL DEFAULT 'content'
"""

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cms_players ADD COLUMN player_role VARCHAR(10) NOT NULL DEFAULT 'content'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cms_players DROP COLUMN IF EXISTS player_role")
