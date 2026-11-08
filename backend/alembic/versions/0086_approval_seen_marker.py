"""Marqueur « décision vue » par le soumetteur (cloche portail — retour Ed #8)

Revision ID: 0086
Revises: 0085
Create Date: 2026-07-11 00:00:00.000000

`submitter_seen_at` sur cms_approval_requests : la cloche du portail annonceur
compte les décisions (approved / rejected / changes_requested / published) non
encore vues par le soumetteur — serveur-side, donc cohérent entre navigateurs.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0086"
down_revision: str | None = "0085"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cms_approval_requests",
        sa.Column("submitter_seen_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cms_approval_requests", "submitter_seen_at")
