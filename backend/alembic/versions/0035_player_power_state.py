"""État d'alimentation appliqué par player (dédup auto-power) — cms_players

Revision ID: 0035
Revises: 0034
Create Date: 2026-06-04 22:00:00.000000

La tâche beat d'auto-power n'envoie une commande power_on/power_off qu'aux
*transitions* (edge-triggered). On mémorise le dernier état appliqué par player
pour dédupliquer et survivre au restart du worker.
  - last_power_state : True=allumé / False=éteint / NULL=jamais piloté
  - last_power_at    : horodatage de la dernière commande envoyée
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cms_players", sa.Column("last_power_state", sa.Boolean(), nullable=True))
    op.add_column(
        "cms_players",
        sa.Column("last_power_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cms_players", "last_power_at")
    op.drop_column("cms_players", "last_power_state")
