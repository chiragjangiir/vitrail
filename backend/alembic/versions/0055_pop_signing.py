"""Proof of Play — signature côté player (P2) + colonne signature.

§XXIV : le hash Merkle est calculé côté serveur (chaîne anti-altération en base) ; pour une
preuve INFALSIFIABLE émanant du player, chaque preuve est désormais SIGNÉE (Ed25519) par une
clé device dont seul le player détient la privée. On stocke :
  - cms_players.pop_public_key  : clé publique Ed25519 du player (PEM, TOFU à la 1re remontée)
  - cms_proof_of_play.signature : signature base64 de la preuve (NULL = player legacy non signant)

Rétro-compatible : colonnes nullables, les players non encore mis à jour restent acceptés.

Revision ID: 0055
Revises: 0054
"""
from alembic import op
import sqlalchemy as sa

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cms_players", sa.Column("pop_public_key", sa.Text(), nullable=True))
    # cms_proof_of_play est partitionnée : ADD COLUMN cascade automatiquement aux partitions.
    op.add_column("cms_proof_of_play", sa.Column("signature", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("cms_proof_of_play", "signature")
    op.drop_column("cms_players", "pop_public_key")
