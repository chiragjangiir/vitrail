"""MAJ firmware BrightSign depuis l'UI (P1.1) — colonnes firmware sur cms_player_update_versions.

§XXX : les tables de gestion de versions existaient (structure Phase 1, logique Phase 2). On les
active pour le firmware BrightSign (`.bsfw`) : un super-admin enregistre une version firmware (track
'firmware'), l'épingle (is_pinned = la SEULE version que l'UI pousse, garde-fou anti-brick), et le
`.bsfw` est stocké dans MinIO (storage_key). Le firmware est spécifique à une famille de player
(model_family, ex. 'malibu'/XT4) → on ne propose que la version épinglée correspondant à la famille.

Revision ID: 0058
Revises: 0057
"""
from alembic import op
import sqlalchemy as sa

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cms_player_update_versions",
        sa.Column("is_pinned", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "cms_player_update_versions",
        sa.Column("storage_key", sa.Text(), nullable=True),
    )
    op.add_column(
        "cms_player_update_versions",
        sa.Column("model_family", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "cms_player_update_versions",
        sa.Column("file_size", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "cms_player_update_versions",
        sa.Column("original_filename", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cms_player_update_versions", "original_filename")
    op.drop_column("cms_player_update_versions", "file_size")
    op.drop_column("cms_player_update_versions", "model_family")
    op.drop_column("cms_player_update_versions", "storage_key")
    op.drop_column("cms_player_update_versions", "is_pinned")
