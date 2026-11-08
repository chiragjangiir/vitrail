"""Gouvernance hiérarchique §XVIII — fondation (tables + FK)

Revision ID: 0025
Revises: 0024
Create Date: 2026-06-01 10:00:00.000000

Arbre de gouvernance indépendant de l'arbre d'organisations. Fondation seule
(CRUD nœuds + assignations + règles de délégation). Le moteur d'application
(compiled-schedule multi-couches, budgets, préemption §18.4) = Phase 2.

Crée :
  - cms_governance_nodes        (arbre, path matérialisé "1.5.23")
  - cms_governance_assignments  (player|group|site rattachés à un nœud)
  - cms_delegation_rules        (contraintes budget/fréquence par nœud)

Ajoute :
  - cms_schedules.id_governance_node       (FK, NULL = pas de contrainte)
  - FK cms_audio_baskets.id_node           (colonne existante, sans FK avant)
  - FK cms_basket_permissions.id_node      (colonne existante, sans FK avant)
"""

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cms_governance_nodes (
            id_node     BIGSERIAL PRIMARY KEY,
            id_org      BIGINT NOT NULL REFERENCES cms_organizations(id_org),
            parent_id   BIGINT REFERENCES cms_governance_nodes(id_node) ON DELETE CASCADE,
            node_name   VARCHAR(255) NOT NULL,
            node_level  INT NOT NULL DEFAULT 0,
            node_type   VARCHAR(50),
            path        TEXT NOT NULL DEFAULT '',
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_cgn_org    ON cms_governance_nodes(id_org)")
    op.execute("CREATE INDEX idx_cgn_parent ON cms_governance_nodes(parent_id)")
    op.execute("CREATE INDEX idx_cgn_path   ON cms_governance_nodes(path text_pattern_ops)")

    op.execute(
        """
        CREATE TABLE cms_governance_assignments (
            id_node     BIGINT NOT NULL REFERENCES cms_governance_nodes(id_node) ON DELETE CASCADE,
            target_type VARCHAR(20) NOT NULL,
            target_id   BIGINT NOT NULL,
            PRIMARY KEY (id_node, target_type, target_id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE cms_delegation_rules (
            id_rule     BIGSERIAL PRIMARY KEY,
            id_node     BIGINT NOT NULL REFERENCES cms_governance_nodes(id_node) ON DELETE CASCADE,
            rule_type   VARCHAR(30) NOT NULL,
            params      JSONB NOT NULL DEFAULT '{}',
            soft_cut    BOOLEAN NOT NULL DEFAULT true,
            is_active   BOOLEAN NOT NULL DEFAULT true,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_cdr_node ON cms_delegation_rules(id_node)")

    # cms_schedules : nœud de gouvernance propriétaire (NULL = comportement actuel)
    op.execute(
        "ALTER TABLE cms_schedules ADD COLUMN id_governance_node BIGINT "
        "REFERENCES cms_governance_nodes(id_node) ON DELETE SET NULL"
    )

    # FK sur colonnes id_node existantes (créées en 0019 sans contrainte)
    op.execute(
        "ALTER TABLE cms_audio_baskets ADD CONSTRAINT fk_cms_audio_baskets_id_node "
        "FOREIGN KEY (id_node) REFERENCES cms_governance_nodes(id_node) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE cms_basket_permissions ADD CONSTRAINT fk_cms_basket_permissions_id_node "
        "FOREIGN KEY (id_node) REFERENCES cms_governance_nodes(id_node) ON DELETE CASCADE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cms_basket_permissions DROP CONSTRAINT IF EXISTS fk_cms_basket_permissions_id_node")
    op.execute("ALTER TABLE cms_audio_baskets DROP CONSTRAINT IF EXISTS fk_cms_audio_baskets_id_node")
    op.execute("ALTER TABLE cms_schedules DROP COLUMN IF EXISTS id_governance_node")
    op.execute("DROP TABLE IF EXISTS cms_delegation_rules")
    op.execute("DROP TABLE IF EXISTS cms_governance_assignments")
    op.execute("DROP TABLE IF EXISTS cms_governance_nodes")
