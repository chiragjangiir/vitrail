"""Open source : retrait de l'intégration ERP et du système de licences

Revision ID: 0130
Revises: 0129
Create Date: 2026-11-08 00:00:00.000000

Le projet est publié sous AGPL-3.0. Deux héritages disparaissent :

- l'intégration ERP, qui n'avait jamais dépassé le stade des colonnes : aucune ligne de code
  ne lisait ni n'écrivait `erp_*` / `subscription_status` ;
- la licence produit (fichier signé Ed25519) : sa table d'état `cms_licence_state` n'a plus
  de lecteur une fois le contrôle retiré.

Le downgrade recrée les colonnes et la table à l'identique (vides), sans leurs données.
"""

import sqlalchemy as sa
from alembic import op

revision = "0130"
down_revision = "0129"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_cms_players_erp")
    op.execute("DROP INDEX IF EXISTS ix_cms_players_erp_equipment_id")
    op.execute("ALTER TABLE cms_players DROP COLUMN IF EXISTS erp_equipment_id")
    op.execute("ALTER TABLE cms_users DROP COLUMN IF EXISTS erp_user_id")
    op.execute("ALTER TABLE cms_sites DROP COLUMN IF EXISTS erp_site_id")
    op.execute("ALTER TABLE cms_organizations DROP COLUMN IF EXISTS erp_org_id")
    op.execute("ALTER TABLE cms_organizations DROP COLUMN IF EXISTS erp_master")
    op.execute("ALTER TABLE cms_organizations DROP COLUMN IF EXISTS subscription_status")
    op.execute("DROP TABLE IF EXISTS cms_licence_state")


def downgrade() -> None:
    op.add_column("cms_organizations", sa.Column("erp_org_id", sa.Integer, nullable=True))
    op.add_column(
        "cms_organizations",
        sa.Column("erp_master", sa.Boolean, server_default="false", nullable=False),
    )
    op.add_column(
        "cms_organizations",
        sa.Column("subscription_status", sa.String(20), server_default="unknown", nullable=False),
    )
    op.add_column("cms_sites", sa.Column("erp_site_id", sa.Integer, nullable=True))
    op.add_column("cms_users", sa.Column("erp_user_id", sa.Integer, nullable=True))
    op.add_column("cms_players", sa.Column("erp_equipment_id", sa.BigInteger, nullable=True))
    op.create_index(
        "ix_cms_players_erp", "cms_players", ["erp_equipment_id"],
        postgresql_where=sa.text("erp_equipment_id IS NOT NULL"),
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cms_licence_state (
            id               SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
            licence_id       VARCHAR(64)  NOT NULL,
            customer         VARCHAR(255) NOT NULL,
            expires_at       DATE,
            first_seen_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
            last_seen_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
            warned_threshold SMALLINT
        )
        """
    )
