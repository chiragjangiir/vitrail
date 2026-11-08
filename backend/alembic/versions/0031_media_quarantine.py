"""Kill-switch / quarantaine média (§ retours clients Q5)

Revision ID: 0031
Revises: 0030
Create Date: 2026-06-03 16:00:00.000000

Ajoute à `cms_media` l'état de blocage (quarantaine) — enforced côté serveur :
un média `is_blocked` n'est JAMAIS inclus dans un `player:sync` (filtré dans
`_resolve_sync_payload`) et son id est poussé dans `blocked_media` (garde player
offline). Cas légal « 1000 €/passage » : retrait immédiat et tracé d'un contenu
de tous les écrans.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cms_media", sa.Column(
        "is_blocked", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("cms_media", sa.Column("block_reason", sa.Text(), nullable=True))
    op.add_column("cms_media", sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("cms_media", sa.Column("blocked_by", sa.BigInteger(), nullable=True))
    op.create_index("ix_cms_media_is_blocked", "cms_media", ["is_blocked"])


def downgrade() -> None:
    op.drop_index("ix_cms_media_is_blocked", table_name="cms_media")
    op.drop_column("cms_media", "blocked_by")
    op.drop_column("cms_media", "blocked_at")
    op.drop_column("cms_media", "block_reason")
    op.drop_column("cms_media", "is_blocked")
