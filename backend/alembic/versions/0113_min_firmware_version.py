"""Firmware minimum requis par une version de renderer BrightSign — décision 2 du chantier
« un seul canal de MAJ pour tous les players » (Ed, 2026-07-27).

Le firmware BS n'est PAS distribué par image OCI (chaque modèle a le sien, la matrice complète
serait énorme) : si une version de renderer exige un BOS minimum, le serveur le SIGNALE à
l'admin porteur — il télécharge le `.bsfw` chez BrightSign et l'importe par le menu — puis la
mise à jour orchestre firmware PUIS renderer sur les players concernés.

Colonne nullable, aucune ligne existante ne change : déploiement neutre.

Revision ID: 0113
Revises: 0112
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0113"
down_revision: str | None = "0112"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cms_player_update_versions",
        sa.Column("min_firmware_version", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cms_player_update_versions", "min_firmware_version")
