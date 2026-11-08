"""Approval Workflow §XXI générique — demandes + commentaires (S7 Phase C1)

Revision ID: 0081
Revises: 0080
Create Date: 2026-07-10 00:00:00.000000

Le module §XXI n'avait JAMAIS été implémenté (découverte S5 — seul son RBAC
`approvals:*` + le rôle CMS_APPROVER sont seedés en 0002). C1 le construit en
générique : `cms_approval_requests` (machine à états pending_review →
approved/rejected/changes_requested → published) + `cms_approval_comments`
(timeline). 1er consommateur = les campagnes retail media (soumission par le
portail annonceur en C2 ; dès C1 un retailer peut soumettre une campagne draft).

Déviation spec assumée : PAS de table `cms_approval_reviewers` (assignation par
nœud de gouvernance) en v1 — les reviewers = RBAC `approvals:approve/reject`
(rôle CMS_APPROVER, org-admin) et les notifications §XXII sont des webhooks
org-level, donc une assignation nominale n'aurait aucun consommateur. À
construire si un client demande le routage par nœud.

Index UNIQUE partiel : une seule demande ACTIVE (pending_review /
changes_requested / approved non publiée) par ressource. rejected/published/
cancelled = terminaux, une nouvelle soumission redevient possible.

Seed : `approvals:submit` ajouté au rôle CMS_CAMPAIGN_MANAGER (il soumet ses
campagnes à validation) — CMS_ORG_ADMIN a déjà tout ('*').

TENANT-SCOPED (RLS id_org sur les 2 tables, pattern 0079). Grants hérités 0044.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0081"
down_revision: str | None = "0080"
branch_labels = None
depends_on = None

_TABLES = (
    "cms_approval_comments",
    "cms_approval_requests",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cms_approval_requests (
            id_request    BIGSERIAL PRIMARY KEY,
            id_org        BIGINT NOT NULL REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            resource_type VARCHAR(30) NOT NULL,
            resource_id   BIGINT NOT NULL,
            submitted_by  BIGINT NOT NULL REFERENCES cms_users(id_user),
            submitted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            status        VARCHAR(30) NOT NULL DEFAULT 'pending_review',
            due_date      TIMESTAMPTZ,
            notes         TEXT,
            reviewed_by   BIGINT REFERENCES cms_users(id_user),
            reviewed_at   TIMESTAMPTZ,
            published_at  TIMESTAMPTZ,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE cms_approval_comments (
            id_comment   BIGSERIAL PRIMARY KEY,
            id_request   BIGINT NOT NULL
                         REFERENCES cms_approval_requests(id_request) ON DELETE CASCADE,
            id_org       BIGINT NOT NULL REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            id_user      BIGINT NOT NULL REFERENCES cms_users(id_user),
            comment_text TEXT NOT NULL,
            action       VARCHAR(30),
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_car_org_status ON cms_approval_requests (id_org, status)")
    op.execute("CREATE INDEX idx_car_resource ON cms_approval_requests (resource_type, resource_id)")
    # Une seule demande ACTIVE par ressource (règle §21.4) — enforced en base, pas
    # seulement dans le service.
    op.execute(
        "CREATE UNIQUE INDEX uq_car_active_per_resource "
        "ON cms_approval_requests (id_org, resource_type, resource_id) "
        "WHERE status IN ('pending_review', 'changes_requested', 'approved')"
    )
    op.execute("CREATE INDEX idx_cac_request ON cms_approval_comments (id_request, created_at)")
    for t in _TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {t}_org_isolation ON {t} "
            "USING (id_org = current_setting('app.current_org_id', true)::bigint)"
        )

    # Seed : le campaign manager peut soumettre pour approbation.
    conn = op.get_bind()
    role_id = conn.execute(
        sa.text("SELECT id_role FROM cms_roles WHERE role_key = 'CMS_CAMPAIGN_MANAGER'")
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
    for t in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {t}")
