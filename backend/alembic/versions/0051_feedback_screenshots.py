"""Captures d'écran jointes aux retours utilisateurs (§ retours UI)

Revision ID: 0051
Revises: 0050
Create Date: 2026-06-22 09:00:00.000000

Colonne `screenshot_keys` JSONB sur `cms_feedback` : liste de clés MinIO (bucket média,
préfixe `feedback/{id_org}/`) des captures jointes manuellement par l'utilisateur dans le
widget de retour. Affichées au super-admin dans /settings/feedback via URLs pré-signées.
"""

from alembic import op

revision: str = "0051"
down_revision: str | None = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE cms_feedback
            ADD COLUMN screenshot_keys JSONB NOT NULL DEFAULT '[]'::jsonb
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cms_feedback DROP COLUMN screenshot_keys")
