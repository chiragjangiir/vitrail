"""Events — valid_from, valid_until, is_recurring

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-30 00:00:00.000000

Modifications :
  - cms_events.valid_from   TIMESTAMPTZ  -- date/heure de début de validité (NULL = immédiat)
  - cms_events.valid_until  TIMESTAMPTZ  -- date/heure de fin de validité (NULL = pas de limite)
  - cms_events.is_recurring BOOL DEFAULT FALSE
    Si TRUE, l'event repasse en 'inactive' apres chaque expiration au lieu de 'completed'.
    Permet une répétition automatique dans la fenêtre valid_from→valid_until.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cms_events",
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "cms_events",
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "cms_events",
        sa.Column(
            "is_recurring",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("cms_events", "is_recurring")
    op.drop_column("cms_events", "valid_until")
    op.drop_column("cms_events", "valid_from")
