"""Horodatage de la dernière capture d'écran player (§ retours clients — cartes players)

Revision ID: 0032
Revises: 0031
Create Date: 2026-06-04 10:00:00.000000

Ajoute `cms_players.last_screenshot_at` : mis à jour à chaque upload de capture
(`POST /players/{id}/screenshot`). Sert de drapeau « une capture existe » côté API
(génération de l'URL signée MinIO uniquement si non-null) et affiche la fraîcheur
de la vignette dans la carte/le drawer player. La capture périodique est pilotée
par `display_config.screenshot_interval` (JSONB libre, pas de migration).
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cms_players", sa.Column(
        "last_screenshot_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("cms_players", "last_screenshot_at")
