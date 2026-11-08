"""Quotas d'upload créatifs configurables par org (retour Ed portail #6)

Revision ID: 0084
Revises: 0083
Create Date: 2026-07-11 00:00:00.000000

Les quotas d'upload du portail annonceur (§3.4 : 20 créatifs/campagne,
512 MiB/fichier) étaient des constantes. Ils deviennent des réglages org
(GET/PUT /campaigns/settings) : `campaign_max_creatives` (défaut 20) +
`campaign_creative_max_mb` (défaut 1024 — relevé de 512 pour couvrir les
spots 4K, tout est re-transcodé derrière de toute façon).
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0084"
down_revision: str | None = "0083"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cms_organizations",
        sa.Column("campaign_max_creatives", sa.Integer(),
                  server_default="20", nullable=False),
    )
    op.add_column(
        "cms_organizations",
        sa.Column("campaign_creative_max_mb", sa.Integer(),
                  server_default="1024", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("cms_organizations", "campaign_creative_max_mb")
    op.drop_column("cms_organizations", "campaign_max_creatives")
