"""Media embargo — not_before_utc + embargo_event_id (§XX / §XVI)

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-30 00:00:00.000000

Ajoute sur cms_media :
  - not_before_utc    TIMESTAMPTZ  — embargo manuel direct
  - embargo_event_id  BIGINT FK    — OU lié à un event sous embargo (SET NULL si event supprimé)

Règle de résolution dans ws.py :
  embargo effectif = event.not_before_utc  (si embargo_event_id)
                     OU not_before_utc     (si embargo direct)
                     OU null              (pas d'embargo)
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cms_media",
        sa.Column("not_before_utc", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "cms_media",
        sa.Column(
            "embargo_event_id",
            sa.BigInteger(),
            sa.ForeignKey("cms_events.id_event", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_cms_media_embargo_event_id",
        "cms_media",
        ["embargo_event_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_cms_media_embargo_event_id", "cms_media")
    op.drop_column("cms_media", "embargo_event_id")
    op.drop_column("cms_media", "not_before_utc")
