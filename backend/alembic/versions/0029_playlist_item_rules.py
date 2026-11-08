"""Règles de diffusion par item de playlist (§ retours clients item 4)

Revision ID: 0029
Revises: 0028
Create Date: 2026-06-03 14:00:00.000000

Crée `cms_playlist_item_rules` : une règle temporelle (heure LOCALE wall-clock)
attachée à un item de playlist. Un item sans règle = perpétuel ; un item avec règle(s)
ne joue que dans la/les fenêtre(s) (récurrence weekly + validité date_range).

Miroir de `cms_schedule_rules` (mêmes 6 champs) + une portée `scope` :
  - `default` (P1) : s'applique à tous les players ;
  - `player` / `player_group` (P2) : override par cible (`target_id`).

Sémantique = heure LOCALE SIGNFLOW_TZ (≠ embargo `not_before_utc` qui est un instant
ABSOLU UTC). Évalué côté serveur via le noyau scheduling (services/scheduling.py),
dans `ws.py` après le filtre tags et avant le wall-clock.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cms_playlist_item_rules",
        sa.Column("id_item_rule", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("id_item", sa.BigInteger(), nullable=False),
        sa.Column("scope", sa.String(20), server_default="default", nullable=False),
        sa.Column("target_id", sa.BigInteger(), nullable=True),
        sa.Column("rule_type", sa.String(20), server_default="weekly", nullable=False),
        sa.Column("days_of_week", sa.ARRAY(sa.Integer()), nullable=True),
        sa.Column("time_start", sa.Time(), nullable=True),
        sa.Column("time_end", sa.Time(), nullable=True),
        sa.Column("date_from", sa.Date(), nullable=True),
        sa.Column("date_to", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["id_item"], ["cms_playlist_items.id_item"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id_item_rule"),
    )
    op.create_index(
        "ix_cms_playlist_item_rules_id_item", "cms_playlist_item_rules", ["id_item"]
    )


def downgrade() -> None:
    op.drop_index("ix_cms_playlist_item_rules_id_item", table_name="cms_playlist_item_rules")
    op.drop_table("cms_playlist_item_rules")
