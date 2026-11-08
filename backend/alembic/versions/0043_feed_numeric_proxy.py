"""Feed Display §25.3 — connecteurs feed-proxy + valeurs numériques (data_chart / social_wall)

Revision ID: 0043
Revises: 0042
Create Date: 2026-06-17 12:00:00.000000

Deuxième vague des Feeds : feed_types socials / financiers / météo servis par le microservice
`signflow-feed-proxy` (reddit/crypto/weather publics ; instagram/twitter_x/linkedin/facebook_page/
tiktok via OAuth) + 2 nouveaux display_modes : `social_wall` (mosaïque de posts) et `data_chart`
(graphique de valeurs numériques — crypto/financier/météo).

`data_chart` a besoin de valeurs NUMÉRIQUES par item — non représentables dans les colonnes texte
existantes. On ajoute donc à `cms_feed_items` :
  - `value_num`  : la mesure (prix, température…)
  - `value_unit` : son unité (EUR, °C, %…)
  - `change_pct` : variation (ex. 24 h crypto/bourse)
  - `series`     : points de sparkline (JSONB array de nombres)
Ces colonnes restent NULL pour les feeds RSS/Atom (aucun impact).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cms_feed_items", sa.Column("value_num", sa.Float, nullable=True))
    op.add_column("cms_feed_items", sa.Column("value_unit", sa.String(16), nullable=True))
    op.add_column("cms_feed_items", sa.Column("change_pct", sa.Float, nullable=True))
    op.add_column("cms_feed_items", sa.Column("series", postgresql.JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("cms_feed_items", "series")
    op.drop_column("cms_feed_items", "change_pct")
    op.drop_column("cms_feed_items", "value_unit")
    op.drop_column("cms_feed_items", "value_num")
