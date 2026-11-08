"""Capacités matérielles player — décodage vidéo HW auto-détecté (pré-Sprint 2.7)

Revision ID: 0027
Revises: 0026
Create Date: 2026-06-02 19:00:00.000000

Ajoute `cms_players.capabilities` (JSONB nullable). Renseigné par le player à
chaque heartbeat (`player:status`) à partir de la détection faite à l'install
(`install.sh`/`install.ps1` → `capabilities.json`). Sert de base à la matrice
`player_os` et aux alertes de conformité de décodage (un média 4K décodé en
logiciel sur un CPU faible → risque de saccade/désync).

Schéma logique du JSONB (libre, non contraint) :
  { gpu_vendor, gpu_model, hw_decode (vaapi|v4l2|d3d11|mediacodec|none),
    hw_decode_active (bool), codecs[], gl_backend, sf_hw_decode (auto|on|off),
    chromium_flags[], detection_source (install|runtime), detected_at }
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cms_players",
        sa.Column("capabilities", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cms_players", "capabilities")
