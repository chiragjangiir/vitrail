"""Player alert reasons + org alert settings

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-30 00:00:00.000000

Ajoute :
  - cms_players.alert_reasons  JSONB DEFAULT '[]'
    Liste des codes d'alerte actifs : offline_critical, cpu_high, ram_high,
    disk_high, token_7d, token_3d, version_outdated
  - cms_organizations.player_alert_settings  JSONB DEFAULT '{}'
    Seuils d'alerte configurables par org :
    { offline_critical_min, cpu_warn_pct, ram_warn_pct, disk_warn_pct,
      token_warn_days, min_player_version }
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import text

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cms_players",
        sa.Column("alert_reasons", JSONB, server_default=text("'[]'"), nullable=False),
    )
    op.add_column(
        "cms_organizations",
        sa.Column("player_alert_settings", JSONB, server_default=text("'{}'"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("cms_players", "alert_reasons")
    op.drop_column("cms_organizations", "player_alert_settings")
