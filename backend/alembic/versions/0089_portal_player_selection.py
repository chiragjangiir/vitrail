"""Portail : sélection par écran (réglage org) + durée max des créatifs

Revision ID: 0089
Revises: 0088
Create Date: 2026-07-12 18:00:00.000000

- `campaign_portal_player_selection` (défaut FALSE) : quand TRUE, le self-service
  du portail annonceur permet de déplier un site et de cocher des ÉCRANS précis
  (cibles mixtes site+player). OFF par défaut : la liste nominative des écrans
  est une information interne (arbitrage EVOLUTIONS, demande Ed 2026-07-11).
- `campaign_creative_max_duration_s` (défaut 30, NULL = pas de limite) : durée
  maximale d'un créatif de campagne — garde-fou « créatif long × boucle courte »
  (cas Nissan 90 s sur boucle 80 s = 46 % servis pour 15 % vendus ; décision Ed
  2026-07-12 : limite fixe réglable plutôt que formule dynamique). Appliquée à
  l'ajout : CMS, upload portail, import JSON.
"""

from alembic import op

revision: str = "0089"
down_revision: str | None = "0088"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cms_organizations ADD COLUMN campaign_portal_player_selection "
        "BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE cms_organizations ADD COLUMN campaign_creative_max_duration_s "
        "INTEGER DEFAULT 30"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE cms_organizations DROP COLUMN IF EXISTS campaign_portal_player_selection"
    )
    op.execute(
        "ALTER TABLE cms_organizations DROP COLUMN IF EXISTS campaign_creative_max_duration_s"
    )
