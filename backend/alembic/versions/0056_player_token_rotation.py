"""Rotation des tokens machine des players (« Option B », 2026-06-26).

Le token player passe d'une durée « 100 ans » (INTERIM permanent) à une durée finie
(CMS_PLAYER_TOKEN_EXPIRE_DAYS, défaut 60j) qui déclenche une rotation au lieu de couper l'écran.
On ajoute une fenêtre de grâce sur l'ANCIEN token pour couvrir un push token:refresh raté ou un
player offline au moment de la rotation :
  - cms_players.player_token_prev        : token précédent encore accepté
  - cms_players.player_token_prev_until  : échéance de la fenêtre de grâce

Rétro-compatible : colonnes nullables, les tokens legacy « 100 ans » restent valides et seront
migrés vers un token à durée finie à la prochaine reconnexion WS (rotation legacy).

Revision ID: 0056
Revises: 0055
"""
from alembic import op
import sqlalchemy as sa

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cms_players", sa.Column("player_token_prev", sa.Text(), nullable=True))
    op.add_column(
        "cms_players",
        sa.Column("player_token_prev_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cms_players", "player_token_prev_until")
    op.drop_column("cms_players", "player_token_prev")
