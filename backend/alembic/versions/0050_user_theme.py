"""Préférence de thème jour/nuit par utilisateur (§ Thème)

Revision ID: 0050
Revises: 0049
Create Date: 2026-06-21 12:00:00.000000

Colonne `theme` sur `cms_users` (light|dark, défaut light) — persiste le choix de thème de
l'UTILISATEUR côté serveur (partagé cross-device), comme `locale`. localStorage reste la source
de vérité pour l'anti-flash pré-paint ; le serveur est réconcilié au chargement (cross-device).
"""

from alembic import op

revision: str = "0050"
down_revision: str | None = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE cms_users
            ADD COLUMN theme VARCHAR(5) NOT NULL DEFAULT 'light'
                CHECK (theme IN ('light','dark'))
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cms_users DROP COLUMN theme")
