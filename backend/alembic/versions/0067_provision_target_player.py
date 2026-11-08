"""Installeur terrain (§XXIX) — bind provisioning token → player cible (ré-attache au choix)

Revision ID: 0067
Revises: 0066
Create Date: 2026-07-04 00:00:00.000000

Un provisioning token (CmsApiKey scope player:register) peut viser un player EXISTANT
(`provision_target_player`). À l'enregistrement, le device se ré-attache à ce player (réutilise
son identité/token) au lieu d'en créer un nouveau → anti-doublon lors d'un reprovisioning
(décision Ed : « ré-attacher OU créer, au choix »). NULL = création d'un nouveau player.
"""

from alembic import op

revision: str = "0067"
down_revision: str | None = "0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cms_api_keys ADD COLUMN provision_target_player BIGINT "
        "REFERENCES cms_players(id_player) ON DELETE SET NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cms_api_keys DROP COLUMN IF EXISTS provision_target_player")
