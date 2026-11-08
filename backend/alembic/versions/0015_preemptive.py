"""add is_preemptive to cms_events

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cms_events",
        sa.Column(
            "is_preemptive",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("cms_events", "is_preemptive")
