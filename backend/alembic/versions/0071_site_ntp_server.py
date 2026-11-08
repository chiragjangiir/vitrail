"""Sites — serveur NTP (hérité par les players du site)

Revision ID: 0071
Revises: 0070
Create Date: 2026-07-07 00:00:00.000000

Ajoute `ntp_server` (IP ou nom d'hôte) à cms_sites : les players du site SANS config NTP
propre (ntp_role/ntp_server du display_config, ex. relais LAN sync) le reçoivent au sync
en rôle 'client'. Précision d'horloge = critique depuis l'autonomie offline auto-power
(les fenêtres locales suivent l'horloge OS du player).
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0071"
down_revision: str | None = "0070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cms_sites", sa.Column("ntp_server", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("cms_sites", "ntp_server")
