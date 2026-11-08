"""Retail Media S4 — share links de rapport de campagne (annonceur)

Revision ID: 0076
Revises: 0075

Les liens de partage §24.4 (password bcrypt + IP allowlist, migr 0072) portent
désormais un type : `executive` (défaut, comportement inchangé) ou `campaign`
(+ `id_campaign`) — le lien public /share/{token} sert alors le rapport
annonceur de la campagne (PoP agrégés, SOV servi, montant) au lieu du
dashboard exécutif.
"""

from alembic import op

revision: str = "0076"
down_revision: str | None = "0075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE cms_report_share_links
            ADD COLUMN report_type VARCHAR(30) NOT NULL DEFAULT 'executive',
            ADD COLUMN id_campaign BIGINT
                REFERENCES cms_campaigns(id_campaign) ON DELETE CASCADE
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE cms_report_share_links DROP COLUMN id_campaign, DROP COLUMN report_type"
    )
