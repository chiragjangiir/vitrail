"""Share links §24.4 — options avancées : mot de passe + IP allowlist

Revision ID: 0072
Revises: 0071
Create Date: 2026-07-08 00:00:00.000000

- password_hash : bcrypt (passlib, même contexte que cms_users) — NULL = pas de mot de passe.
- ip_allowlist  : JSONB liste de CIDR ("81.2.3.4/32", "192.168.1.0/24") — NULL = pas de
  restriction. Vérifiée sur la 1re valeur de X-Forwarded-For derrière Caddy (comme le
  rate-limit login). Colonnes additives, aucune donnée existante impactée.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0072"
down_revision: str | None = "0071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cms_report_share_links", sa.Column("password_hash", sa.Text(), nullable=True))
    op.add_column("cms_report_share_links", sa.Column("ip_allowlist", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("cms_report_share_links", "ip_allowlist")
    op.drop_column("cms_report_share_links", "password_hash")
