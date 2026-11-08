"""Portail annonceur Phase B1 — lien user↔annonceur + rôle CMS_ADVERTISER

Revision ID: 0080
Revises: 0079
Create Date: 2026-07-10 00:00:00.000000

Décisions Ed 2026-07-10 (docs/PLAN_PORTAIL_ANNONCEUR.md §3) : 1 user = 1 annonceur
(`cms_users.id_advertiser` FK nullable — NULL = user retailer normal) ; auth commune
(même /login, le rôle décide de l'UI). Rôle SYSTÈME `CMS_ADVERTISER` = lecture seule
de SES campagnes : campaigns:read + campaigns:report. L'isolation INTRA-org est
APPLICATIVE (endpoints campagnes — la RLS org reste en place) : cross-annonceur = 404.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0080"
down_revision: str | None = "0079"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cms_users ADD COLUMN id_advertiser BIGINT "
        "REFERENCES cms_advertisers(id_advertiser) ON DELETE SET NULL"
    )
    op.execute("CREATE INDEX idx_users_advertiser ON cms_users (id_advertiser)")

    conn = op.get_bind()
    conn.execute(sa.text("""
        INSERT INTO cms_roles (role_key, label, description, is_system)
        VALUES ('CMS_ADVERTISER', 'Annonceur (portail)',
                'Compte externe annonceur — lecture seule de SES campagnes et rapports (portail)',
                true)
        ON CONFLICT (role_key) DO NOTHING
    """))
    role_id = conn.execute(
        sa.text("SELECT id_role FROM cms_roles WHERE role_key = 'CMS_ADVERTISER'")
    ).scalar()
    for module, operation in (("campaigns", "read"), ("campaigns", "report")):
        pid = conn.execute(
            sa.text("SELECT id_permission FROM cms_permissions WHERE module=:m AND operation=:o"),
            {"m": module, "o": operation},
        ).scalar()
        if pid:
            conn.execute(sa.text(
                "INSERT INTO cms_role_permissions (id_role, id_permission) "
                "VALUES (:r, :p) ON CONFLICT DO NOTHING"
            ), {"r": role_id, "p": pid})


def downgrade() -> None:
    op.execute("ALTER TABLE cms_users DROP COLUMN IF EXISTS id_advertiser")
    op.execute("DELETE FROM cms_roles WHERE role_key = 'CMS_ADVERTISER' AND is_system = true")
