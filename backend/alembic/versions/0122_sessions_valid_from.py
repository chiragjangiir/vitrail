"""Révocation des sessions — borne `cms_users.sessions_valid_from` (P1.1, 2026-08-05).

Revision ID: 0122
Revises: 0121

Réinitialiser le mot de passe d'un compte ne fermait **aucune** session ouverte : les
jetons utilisateurs ne portaient pas de date d'émission (seuls les jetons *player* en
avaient une), donc rien ne permettait de dire « ce jeton est antérieur à la coupure ».
Un mot de passe changé en urgence — compte compromis, personne qui part — laissait la
session en cours vivre jusqu'à son expiration, et son jeton de rafraîchissement la
prolonger pendant des jours.

Colonne NULLABLE, sans valeur par défaut, et c'est le point : `NULL` signifie « aucune
révocation n'a jamais eu lieu ». Au déploiement, **tous** les comptes sont à NULL et
aucune session n'est coupée — un correctif de sécurité qui déconnecterait tout le monde
au moment de son installation serait un incident, pas un correctif.

⚠️ La borne se pose par `services/session_revocation.revocation_bound()`, jamais à la
main : elle est tronquée à la seconde. Cf. le module pour le pourquoi.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0122"
down_revision: str | None = "0121"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cms_users",
        sa.Column("sessions_valid_from", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cms_users", "sessions_valid_from")
