"""Compte démo — cms_users.is_demo

Revision ID: 0064
Revises: 0063
Create Date: 2026-07-03 00:00:00.000000

Mode démo (§II) : un compte marqué `is_demo` navigue comme un Org Admin (lecture de tout) mais toute
requête modifiante est bloquée côté serveur (middleware) avec un message localisé « compte démo ».
Exceptions : auth, changement de langue du profil, et l'envoi de feedback.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0064"
down_revision: str | None = "0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cms_users",
        sa.Column("is_demo", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("cms_users", "is_demo")
