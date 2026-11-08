"""Quota assistant en EUR + seuil d'alerte (§XXVII)

Revision ID: 0048
Revises: 0047
Create Date: 2026-06-21 00:00:00.000000

Étend le crédit de tokens de l'assistant :
  - ai_quota_unit VARCHAR(8) NOT NULL DEFAULT 'tokens'  → 'tokens' | 'eur' (unité du crédit).
  - ai_quota_eur NUMERIC(10,2) NULL  → plafond en EUR quand l'unité = 'eur' (NULL/≤0 = illimité).
  - ai_alert_threshold_pct SMALLINT NOT NULL DEFAULT 80  → % d'alerte (0 = aucune alerte).

Le crédit existant `ai_quota_tokens` reste utilisé quand l'unité = 'tokens'. Réversible.
"""

from alembic import op

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cms_organizations "
        "ADD COLUMN ai_quota_unit VARCHAR(8) NOT NULL DEFAULT 'tokens'"
    )
    op.execute("ALTER TABLE cms_organizations ADD COLUMN ai_quota_eur NUMERIC(10,2)")
    op.execute(
        "ALTER TABLE cms_organizations "
        "ADD COLUMN ai_alert_threshold_pct SMALLINT NOT NULL DEFAULT 80"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cms_organizations DROP COLUMN ai_alert_threshold_pct")
    op.execute("ALTER TABLE cms_organizations DROP COLUMN ai_quota_eur")
    op.execute("ALTER TABLE cms_organizations DROP COLUMN ai_quota_unit")
