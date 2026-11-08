"""Heures d'ouverture des sites + auto-power écrans — cms_site_hours / cms_site_exceptions

Revision ID: 0034
Revises: 0033
Create Date: 2026-06-04 20:00:00.000000

Allumage/extinction automatique des écrans calé sur les heures d'ouverture du magasin
(site), avec exceptions datées (soirée, férié ouvert/fermé) et marges avant/après.
Le mode d'alimentation par player (follow_site / always_on / custom pour les vitrines)
vit dans `cms_players.display_config` (JSONB, pas de colonne dédiée).
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Réglages d'alimentation au niveau site
    op.add_column("cms_sites", sa.Column("timezone", sa.String(64), nullable=True))
    op.add_column("cms_sites", sa.Column("auto_power_enabled", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("cms_sites", sa.Column("power_lead_min", sa.Integer(), server_default="15", nullable=False))
    op.add_column("cms_sites", sa.Column("power_lag_min", sa.Integer(), server_default="15", nullable=False))
    op.add_column("cms_sites", sa.Column("respect_holidays", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("cms_sites", sa.Column("holiday_region", sa.String(8), server_default="FR", nullable=False))

    # Horaires hebdomadaires réguliers (1 ligne par jour défini)
    op.create_table(
        "cms_site_hours",
        sa.Column("id_site_hours", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("id_site", sa.BigInteger(), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),  # 0=Lun … 6=Dim
        sa.Column("is_closed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("open_time", sa.Time(), nullable=True),
        sa.Column("close_time", sa.Time(), nullable=True),  # close < open ⇒ overnight
        sa.ForeignKeyConstraint(["id_site"], ["cms_sites.id_site"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id_site_hours"),
        sa.UniqueConstraint("id_site", "weekday", name="uq_site_hours_site_weekday"),
    )
    op.create_index("ix_cms_site_hours_id_site", "cms_site_hours", ["id_site"])

    # Exceptions datées (override des horaires hebdo pour une date ou une plage)
    op.create_table(
        "cms_site_exceptions",
        sa.Column("id_exception", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("id_site", sa.BigInteger(), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),  # closed | hours | open_24h
        sa.Column("open_time", sa.Time(), nullable=True),
        sa.Column("close_time", sa.Time(), nullable=True),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["id_site"], ["cms_sites.id_site"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id_exception"),
    )
    op.create_index("ix_cms_site_exceptions_id_site", "cms_site_exceptions", ["id_site"])


def downgrade() -> None:
    op.drop_index("ix_cms_site_exceptions_id_site", table_name="cms_site_exceptions")
    op.drop_table("cms_site_exceptions")
    op.drop_index("ix_cms_site_hours_id_site", table_name="cms_site_hours")
    op.drop_table("cms_site_hours")
    op.drop_column("cms_sites", "holiday_region")
    op.drop_column("cms_sites", "respect_holidays")
    op.drop_column("cms_sites", "power_lag_min")
    op.drop_column("cms_sites", "power_lead_min")
    op.drop_column("cms_sites", "auto_power_enabled")
    op.drop_column("cms_sites", "timezone")
