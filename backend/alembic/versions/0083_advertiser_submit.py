"""Portail annonceur C2 — approvals:submit pour CMS_ADVERTISER

Revision ID: 0083
Revises: 0082
Create Date: 2026-07-11 00:00:00.000000

Self-service (S7 C2) : l'annonceur soumet SES brouillons au retailer via le
Workflow §21. `approvals:submit` lui donne aussi la visibilité de SES demandes
(file /approvals scope soumetteur) + le resubmit après « modifications
demandées ». L'isolation intra-org est applicative (services/approvals.submit :
cross-annonceur = 404). Data-only, idempotent.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0083"
down_revision: str | None = "0082"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    role_id = conn.execute(
        sa.text("SELECT id_role FROM cms_roles WHERE role_key = 'CMS_ADVERTISER'")
    ).scalar()
    pid = conn.execute(
        sa.text("SELECT id_permission FROM cms_permissions "
                "WHERE module = 'approvals' AND operation = 'submit'")
    ).scalar()
    if role_id and pid:
        conn.execute(sa.text(
            "INSERT INTO cms_role_permissions (id_role, id_permission) "
            "VALUES (:r, :p) ON CONFLICT DO NOTHING"
        ), {"r": role_id, "p": pid})


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(
        "DELETE FROM cms_role_permissions rp USING cms_roles r, cms_permissions p "
        "WHERE rp.id_role = r.id_role AND rp.id_permission = p.id_permission "
        "AND r.role_key = 'CMS_ADVERTISER' AND p.module = 'approvals' "
        "AND p.operation = 'submit'"
    ))
