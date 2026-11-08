"""Gouvernance §XVIII Phase 2 — administrateurs de nœud (immutabilité par couche)

Revision ID: 0038
Revises: 0037
Create Date: 2026-06-05 14:00:00.000000

Lien user→nœud d'administration : un utilisateur affecté à un nœud A peut
créer/modifier/supprimer les programmes (cms_schedules) rattachés à A **et à tout
son sous-arbre** (un national édite tout en dessous ; un local n'édite que le local).
CMS_ORG_ADMIN / CMS_SUPER_ADMIN contournent (édition de tout l'org).

Met en œuvre le principe spec §18.4 : « le niveau supérieur ne peut jamais être
modifié par un niveau inférieur ». Un schedule sans nœud (id_governance_node NULL)
reste éditable par quiconque a la permission schedules:edit (comportement inchangé).
"""

from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cms_governance_node_admins (
            id_node     BIGINT NOT NULL REFERENCES cms_governance_nodes(id_node) ON DELETE CASCADE,
            id_user     BIGINT NOT NULL REFERENCES cms_users(id_user) ON DELETE CASCADE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id_node, id_user)
        )
        """
    )
    op.execute("CREATE INDEX idx_cgna_user ON cms_governance_node_admins(id_user)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cms_governance_node_admins")
