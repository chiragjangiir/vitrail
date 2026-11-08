"""Compteur + verrou du PIN pour le CMS (commandes players EN MASSE).

Le PIN (`cms_users.assistant_pin_hash`, migr 0090) existait pour la MESSAGERIE : son
compteur d'essais et son verrou vivent sur `cms_messaging_identities` (état PAR identité
Telegram). Les commandes en masse déclenchées depuis le CMS n'ont aucune identité de
messagerie — il leur faut donc leur propre état, porté par l'utilisateur.

Note : ici le PIN ne joue PAS le même rôle que chez Jeanine. Par messagerie il est un 2e
facteur (un compte Telegram n'est pas une auth forte) ; dans le CMS la session est déjà
authentifiée, le PIN confirme l'INTENTION sur une action à fort rayon d'action (redémarrer
un parc entier). Le verrou reste utile : il transforme une rafale d'essais en incident
visible plutôt qu'en tâtonnement silencieux.

Revision ID: 0097
Revises: 0096
"""

from alembic import op

revision: str = "0097"
down_revision: str | None = "0096"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cms_users ADD COLUMN assistant_pin_attempts INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE cms_users ADD COLUMN assistant_pin_locked_until TIMESTAMPTZ NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cms_users DROP COLUMN assistant_pin_locked_until")
    op.execute("ALTER TABLE cms_users DROP COLUMN assistant_pin_attempts")
