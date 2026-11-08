"""Event embargo — not_before_utc (§XX)

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-30 00:00:00.000000

Ajoute :
  - cms_events.not_before_utc TIMESTAMPTZ (nullable)
    Plancher absolu UTC : l'event ne peut s'activer (auto ou manuel)
    avant cette date/heure, quelle que soit la SIGNFLOW_TZ du serveur.
    Null = pas d'embargo (comportement historique inchangé).
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cms_events",
        sa.Column("not_before_utc", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cms_events", "not_before_utc")
