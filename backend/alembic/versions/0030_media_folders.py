"""Dossiers médias (§ retours clients ≈) — cms_media_folders + cms_media.id_folder

Revision ID: 0030
Revises: 0029
Create Date: 2026-06-03 15:00:00.000000

Arborescence de classement des médias (explorateur de fichiers). Path matérialisé
(réutilise le pattern Gouvernance §XVIII). `cms_media.id_folder` (NULL = racine /
non classé). FK SET NULL : supprimer un dossier ne supprime pas les médias (ils
remontent à la racine). Complémentaire aux Tags §XVII (dossiers = rangement ;
tags = ciblage diffusion).
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cms_media_folders",
        sa.Column("id_folder", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("id_org", sa.BigInteger(), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("folder_name", sa.String(255), nullable=False),
        sa.Column("depth", sa.Integer(), server_default="0", nullable=False),
        sa.Column("path", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["id_org"], ["cms_organizations.id_org"]),
        sa.ForeignKeyConstraint(["parent_id"], ["cms_media_folders.id_folder"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id_folder"),
    )
    op.create_index("ix_cms_media_folders_id_org", "cms_media_folders", ["id_org"])
    op.create_index("ix_cms_media_folders_parent_id", "cms_media_folders", ["parent_id"])

    op.add_column(
        "cms_media",
        sa.Column("id_folder", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_cms_media_id_folder", "cms_media", "cms_media_folders",
        ["id_folder"], ["id_folder"], ondelete="SET NULL",
    )
    op.create_index("ix_cms_media_id_folder", "cms_media", ["id_folder"])


def downgrade() -> None:
    op.drop_index("ix_cms_media_id_folder", table_name="cms_media")
    op.drop_constraint("fk_cms_media_id_folder", "cms_media", type_="foreignkey")
    op.drop_column("cms_media", "id_folder")
    op.drop_index("ix_cms_media_folders_parent_id", table_name="cms_media_folders")
    op.drop_index("ix_cms_media_folders_id_org", table_name="cms_media_folders")
    op.drop_table("cms_media_folders")
