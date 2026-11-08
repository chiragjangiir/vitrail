"""Gouvernance §XVIII — une seule règle de délégation par TYPE et par nœud (décision D5).

Revue du 2026-07-23 (R7, défaut 1) : deux règles du même type sur un nœud donnaient un
résultat NON DÉTERMINISTE. `parse_constraints` écrasait au fil de la lecture (la dernière
gagnait) et `_node_constraints` lisait sans `ORDER BY`. Vicieux : la liste affichée à
l'écran EST triée (`list_rules` a `ORDER BY id_rule`) → ce qu'on voyait n'était pas
forcément ce qui gagnait.

Décision Ed (D5) : contrainte d'unicité (id_node, rule_type). Le plus simple à comprendre
et à expliquer. On dédoublonne d'abord (aucune donnée en production — 0 règle à la revue —
mais les bancs de dev peuvent en avoir), en gardant la règle la PLUS RÉCENTE (max id_rule),
puis on pose la contrainte.

Revision ID: 0106
Revises: 0105
"""

from alembic import op


revision: str = "0106"
down_revision: str | None = "0105"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Dédoublonnage : ne garder que la règle la plus récente par (id_node, rule_type).
    op.execute(
        """
        DELETE FROM cms_delegation_rules a
        USING cms_delegation_rules b
        WHERE a.id_node = b.id_node
          AND a.rule_type = b.rule_type
          AND a.id_rule < b.id_rule
        """
    )
    op.create_unique_constraint(
        "uq_delegation_rule_node_type", "cms_delegation_rules", ["id_node", "rule_type"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_delegation_rule_node_type", "cms_delegation_rules", type_="unique")
