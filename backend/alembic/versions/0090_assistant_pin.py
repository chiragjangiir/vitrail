"""Jeanine : PIN pour les actions sensibles par messagerie (2e facteur du « OUI »)

Revision ID: 0090
Revises: 0089
Create Date: 2026-07-13 20:00:00.000000

Un compte Telegram n'est pas une auth forte : les actions SENSIBLES (reboot,
coupure d'écran, suppression…) demandées par messagerie exigent désormais un
code PIN à 6 chiffres, défini par l'utilisateur depuis son profil CMS (session
forte). Décisions Ed 2026-07-13 : 6 chiffres · valable pour UNE action ·
expiration ~2 min · 3 essais puis verrou 15 min.

- `cms_users.assistant_pin_hash` : bcrypt du PIN (NULL = pas de PIN → les
  actions sensibles par messagerie sont refusées avec invitation à en créer un).
- `cms_messaging_identities.pending_stage` : 'confirm' (attend OUI/NON) ou
  'pin' (OUI reçu, attend le code — pending_expires_at resserré à 2 min).
- `cms_messaging_identities.pin_attempts` / `pin_locked_until` : compteur
  d'essais et verrou anti force brute.
"""

from alembic import op

revision: str = "0090"
down_revision: str | None = "0089"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cms_users ADD COLUMN assistant_pin_hash VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE cms_messaging_identities ADD COLUMN pending_stage "
        "VARCHAR(10) NOT NULL DEFAULT 'confirm'"
    )
    op.execute(
        "ALTER TABLE cms_messaging_identities ADD COLUMN pin_attempts "
        "SMALLINT NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE cms_messaging_identities ADD COLUMN pin_locked_until "
        "TIMESTAMPTZ"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cms_users DROP COLUMN IF EXISTS assistant_pin_hash")
    op.execute("ALTER TABLE cms_messaging_identities DROP COLUMN IF EXISTS pending_stage")
    op.execute("ALTER TABLE cms_messaging_identities DROP COLUMN IF EXISTS pin_attempts")
    op.execute("ALTER TABLE cms_messaging_identities DROP COLUMN IF EXISTS pin_locked_until")
