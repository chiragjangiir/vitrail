"""Proof of Play — self-heal de rotation de clé device (P0.1 BrightSign).

Un wipe storage (MAJ firmware, échange/reformatage SD) régénère le seed Ed25519 du player →
le backend, en TOFU strict, rejetait SILENCIEUSEMENT tout le PoP (400, file qui monte) jusqu'au
reset manuel de `pop_public_key`. On accepte désormais une rotation de clé authentifiée (le lot
prouve la possession de la nouvelle clé privée) ; cette colonne horodate la dernière rotation
auto pour la visibilité CMS (auditeur : « clé tournée le T »).

Revision ID: 0057
Revises: 0056
"""
from alembic import op
import sqlalchemy as sa

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cms_players",
        sa.Column("pop_key_rotated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cms_players", "pop_key_rotated_at")
