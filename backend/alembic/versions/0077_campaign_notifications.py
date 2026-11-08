"""Retail Media S5 — notifications de cycle de vie des campagnes (dédup)

Revision ID: 0077
Revises: 0076

Colonnes de dédup sur cms_campaigns pour les événements §XXII émis par le
worker campaign_worker : `started_notified_at` / `ended_notified_at`
(edge-triggered — une notification par transition de cycle de vie) et
`underserved_checked_on` (une évaluation de sous-diffusion SOV par jour).
Événements ajoutés au catalogue : campaign_started / campaign_ended /
campaign_underserved.
"""

from alembic import op

revision: str = "0077"
down_revision: str | None = "0076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE cms_campaigns
            ADD COLUMN started_notified_at TIMESTAMPTZ,
            ADD COLUMN ended_notified_at TIMESTAMPTZ,
            ADD COLUMN underserved_checked_on DATE
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE cms_campaigns DROP COLUMN underserved_checked_on, "
        "DROP COLUMN ended_notified_at, DROP COLUMN started_notified_at"
    )
