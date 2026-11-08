"""Events — ajout id_media + id_playlist nullable (Sprint 2.4)

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-30 00:00:00.000000

Modifications :
  - cms_events.id_media  BIGINT FK -> cms_media.id_media  (nullable, SET NULL)
    Permet d'associer un contenu unique (pas de playlist) a un event.
  - cms_events.id_playlist passe de NOT NULL a NULL
    Un event doit avoir soit id_playlist, soit id_media (validation applicative).
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Ajouter la colonne id_media (nullable)
    op.add_column(
        "cms_events",
        sa.Column("id_media", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_cms_events_id_media",
        "cms_events",
        "cms_media",
        ["id_media"],
        ["id_media"],
        ondelete="SET NULL",
    )

    # 2. Rendre id_playlist nullable (un event peut desormais pointer vers un media direct)
    op.alter_column(
        "cms_events",
        "id_playlist",
        existing_type=sa.BigInteger(),
        nullable=True,
    )


def downgrade() -> None:
    # Attention : downgrade echouera si des events ont id_playlist=NULL
    op.alter_column(
        "cms_events",
        "id_playlist",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    op.drop_constraint("fk_cms_events_id_media", "cms_events", type_="foreignkey")
    op.drop_column("cms_events", "id_media")
