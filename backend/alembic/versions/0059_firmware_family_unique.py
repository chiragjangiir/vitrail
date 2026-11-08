"""Firmware : unicité par (track, version, model_family) au lieu de (track, version).

Bug P1.1 : la contrainte uq_cms_player_update_versions_track_version interdisait deux firmwares de
MÊME version pour des familles DIFFÉRENTES — or malibu (XT4) et pagani (HD4) ont tous deux la
version 9.1.132 (binaires .bsfw distincts). On élargit l'unicité à la famille. NULLS NOT DISTINCT
(PG15+) préserve l'unicité (track, version) pour les pistes sans famille (server/player → NULL).

Revision ID: 0059
Revises: 0058
"""
from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_cms_player_update_versions_track_version",
        "cms_player_update_versions",
        type_="unique",
    )
    # create_unique_constraint ne sait pas exprimer NULLS NOT DISTINCT → SQL brut.
    op.execute(
        "ALTER TABLE cms_player_update_versions "
        "ADD CONSTRAINT uq_cms_player_update_versions_track_version_family "
        "UNIQUE NULLS NOT DISTINCT (track, version, model_family)"
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_cms_player_update_versions_track_version_family",
        "cms_player_update_versions",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_cms_player_update_versions_track_version",
        "cms_player_update_versions",
        ["track", "version"],
    )
