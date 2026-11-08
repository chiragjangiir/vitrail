"""Passthrough + conformité média — encode_mode & conformance_status

Revision ID: 0028
Revises: 0027
Create Date: 2026-06-03 10:00:00.000000

Ajoute à `cms_media` :
  - `encode_mode` (auto|passthrough) : `auto` = ré-encodage pipeline §XVI.2 (défaut) ;
    `passthrough` = conserver le fichier tel quel (cas mur d'images, alignement
    frame-accurate à préserver).
  - `conformance_status` (null|ready|playable|nonconform) : verdict intrinsèque
    de diffusabilité + sync-readiness, queryable (filtrage médiathèque + propagation
    au `sync_ready` des playlists). Le rapport détaillé vit dans `metadata.conformance`.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cms_media",
        sa.Column("encode_mode", sa.String(20), server_default="auto", nullable=False),
    )
    op.add_column(
        "cms_media",
        sa.Column("conformance_status", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cms_media", "conformance_status")
    op.drop_column("cms_media", "encode_mode")
