"""Dashboard géographique (§24.2) — coordonnées lat/lng des sites

Revision ID: 0069
Revises: 0068
Create Date: 2026-07-04 00:00:00.000000

Ajoute latitude/longitude à cms_sites → carte géographique du parc (Dashboard NOC §24.2).
Renseignées manuellement par l'org-admin (pas de géocodage auto). NULL = non placé sur la carte.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0069"
down_revision: str | None = "0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cms_sites", sa.Column("latitude", sa.Numeric(9, 6), nullable=True))
    op.add_column("cms_sites", sa.Column("longitude", sa.Numeric(9, 6), nullable=True))


def downgrade() -> None:
    op.drop_column("cms_sites", "longitude")
    op.drop_column("cms_sites", "latitude")
