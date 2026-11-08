"""Crédit/quota de tokens de l'AI Assistant par organisation (§XXVII)

Revision ID: 0047
Revises: 0046
Create Date: 2026-06-21 00:00:00.000000

Ajoute à cms_organizations un crédit de tokens d'assistant par période :
  - ai_quota_tokens BIGINT NULL  → plafond de tokens consommés sur la période
    courante. NULL ou <= 0 = ILLIMITÉ (aucun blocage).
  - ai_quota_period VARCHAR(10) NOT NULL DEFAULT 'monthly'  → 'weekly' | 'monthly'.

Le super-admin pose ces valeurs ; l'entrée de /assistant/chat bloque si le crédit
est dépassé (super-admin exempté). Le suivi (tokens + coût estimé) s'appuie sur
cms_assistant_stats (déjà en place). Réversible.
"""

from alembic import op

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE cms_organizations ADD COLUMN ai_quota_tokens BIGINT")
    op.execute(
        "ALTER TABLE cms_organizations "
        "ADD COLUMN ai_quota_period VARCHAR(10) NOT NULL DEFAULT 'monthly'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cms_organizations DROP COLUMN ai_quota_period")
    op.execute("ALTER TABLE cms_organizations DROP COLUMN ai_quota_tokens")
