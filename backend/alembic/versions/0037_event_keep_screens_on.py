"""Auto-power lot 2 — option « garder les écrans allumés pendant l'event »

Revision ID: 0037
Revises: 0036
Create Date: 2026-06-05 10:00:00.000000

Un event peut désormais ÉTENDRE l'alimentation des écrans de ses players ciblés :
quand un event `keep_screens_on=true` est ACTIF, la tâche auto-power (apply_site_power)
force l'écran ALLUMÉ même si les heures d'ouverture du site le voudraient éteint.
Un event n'éteint JAMAIS un écran (extension d'alimentation uniquement) — quand il
se termine, le tick suivant recalcule l'alimentation depuis les heures du site.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cms_events",
        sa.Column(
            "keep_screens_on",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("cms_events", "keep_screens_on")
