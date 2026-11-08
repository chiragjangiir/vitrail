"""Inventaire retail media v2 — plafonds d'occupation + tarification par écran

Revision ID: 0082
Revises: 0081
Create Date: 2026-07-11 00:00:00.000000

Demandes Ed 2026-07-11 (DOOH : chaque écran a une valeur différente) :
- **Plafond d'occupation campagnes** par player et par site
  (`campaign_max_occupancy_pct`, NULL = pas de plafond → 100). Héritage :
  player > site > 100. Le moteur S2 remplace ses seuils absolus 80/100 par
  warning ≥ 80 % DU plafond / blocage > plafond. L'opt-out (migr 0075) reste
  le « plafond 0 » simple.
- **Tarif SOV par écran** (`campaign_sov_daily_rate` = € pour 1 % de SOV par
  JOUR, NUMERIC(10,4)). Héritage : player > site > défaut org. Sert au PRIX
  INDICATIF (devis) affiché au drawer campagne + au reviewer §21 — le prix
  CONTRACTUEL reste le champ manuel de la campagne (décision Ed).
"""

from alembic import op

revision: str = "0082"
down_revision: str | None = "0081"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cms_organizations ADD COLUMN campaign_sov_daily_rate NUMERIC(10,4)"
    )
    op.execute(
        "ALTER TABLE cms_sites ADD COLUMN campaign_max_occupancy_pct INTEGER, "
        "ADD COLUMN campaign_sov_daily_rate NUMERIC(10,4)"
    )
    op.execute(
        "ALTER TABLE cms_players ADD COLUMN campaign_max_occupancy_pct INTEGER, "
        "ADD COLUMN campaign_sov_daily_rate NUMERIC(10,4)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cms_players DROP COLUMN IF EXISTS campaign_max_occupancy_pct, "
               "DROP COLUMN IF EXISTS campaign_sov_daily_rate")
    op.execute("ALTER TABLE cms_sites DROP COLUMN IF EXISTS campaign_max_occupancy_pct, "
               "DROP COLUMN IF EXISTS campaign_sov_daily_rate")
    op.execute("ALTER TABLE cms_organizations DROP COLUMN IF EXISTS campaign_sov_daily_rate")
