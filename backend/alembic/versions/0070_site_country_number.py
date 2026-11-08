"""Sites — pays + numéro de site (carte géo §24.2)

Revision ID: 0070
Revises: 0069
Create Date: 2026-07-04 00:00:00.000000

Ajoute `country` (pays, libre) et `site_number` (numéro/code de site, libre) à cms_sites.
Optionnels — utilisés par la recherche/filtres de la carte du parc.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0070"
down_revision: str | None = "0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cms_sites", sa.Column("country", sa.String(80), nullable=True))
    op.add_column("cms_sites", sa.Column("site_number", sa.String(40), nullable=True))


def downgrade() -> None:
    op.drop_column("cms_sites", "site_number")
    op.drop_column("cms_sites", "country")
