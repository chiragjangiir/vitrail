"""Règles de diffusion sur items de paniers audio + shuffle (§ retours clients)

Revision ID: 0033
Revises: 0032
Create Date: 2026-06-04 11:00:00.000000

- `cms_audio_basket_items` : règle de diffusion récurrente (heure locale) par item —
  `rule_days` (jours 0=Lun..6=Dim, null=tous), `rule_time_start`/`rule_time_end`
  (créneau, null=toute la journée). Une règle existe si days OU times sont posés ;
  sinon l'item est perpétuel. Complète `valid_from`/`valid_until` (enveloppe absolue).
  Cible les paniers Music/Ambiance/Jingle (Alert/Message = déclenchés, pas de règle).
- `cms_audio_baskets.shuffle` : lecture en ordre aléatoire (paniers Music).
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cms_audio_baskets", sa.Column(
        "shuffle", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("cms_audio_basket_items", sa.Column("rule_days", sa.JSON(), nullable=True))
    op.add_column("cms_audio_basket_items", sa.Column("rule_time_start", sa.Time(), nullable=True))
    op.add_column("cms_audio_basket_items", sa.Column("rule_time_end", sa.Time(), nullable=True))


def downgrade() -> None:
    op.drop_column("cms_audio_basket_items", "rule_time_end")
    op.drop_column("cms_audio_basket_items", "rule_time_start")
    op.drop_column("cms_audio_basket_items", "rule_days")
    op.drop_column("cms_audio_baskets", "shuffle")
