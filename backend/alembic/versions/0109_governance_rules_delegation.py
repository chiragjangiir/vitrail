"""Gouvernance §XVIII — délégation EXPLICITE du droit de modifier les règles (décision Ed 2026-07-26).

Modèle d'Ed : « l'arborescence des nœuds et donc leurs règles sont créées au niveau national ;
un admin inférieur hiérarchiquement ne modifie pas les paramètres, il modifie les contenus. »
La délégation devient donc un choix explicite, et surtout un choix qui **ne peut que se fermer**
en descendant : « si la case est décochée à un niveau, tous les nœuds inférieurs ne peuvent plus
la rouvrir et ne peuvent plus toucher aux règles ». Sans cette monotonie, la délégation n'aurait
aucun sens — le nœud contraint lèverait sa propre contrainte.

`rules_delegated` = ce nœud AUTORISE-T-IL son propre administrateur à modifier ses règles ?
DEFAULT **false** : par défaut personne en dessous ne touche aux paramètres (posture d'Ed).
La valeur EFFECTIVE est le ET logique sur le nœud ET tous ses ancêtres — d'où la monotonie.
La case elle-même n'est modifiable que par un ancêtre STRICT (ou l'org-admin), jamais par le
nœud concerné : même garde que `requires_approval` (D7), pour la même raison.

⚠️ Un admin d'ancêtre strict garde en toutes circonstances le droit d'écrire les règles de ses
descendants — c'est le cas « le national configure tout », qui est la norme dans ce modèle.

Revision ID: 0109
Revises: 0108
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0109"
down_revision: str | None = "0108"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cms_governance_nodes",
        sa.Column("rules_delegated", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("cms_governance_nodes", "rules_delegated")
