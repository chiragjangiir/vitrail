"""Gouvernance §XVIII — restrictions PAR FAMILLE + plafonds portés par le NŒUD (décisions Ed 2026-07-26).

Deux changements de modèle, tous deux issus de la revue de l'écran avec Ed :

**① Une restriction par FAMILLE, plus un booléen unique.**
`rules_delegated` (0109) ouvrait ou fermait les quatre familles d'un coup. Ed veut pouvoir
déléguer le nombre de contenus par tour sans déléguer la préemption — « pour la préemption,
la case gouverne le droit d'UTILISER la fonction, pas de régler un paramètre ».
⇒ `rules_locked` (JSONB) = une entrée par type de règle : `item_count`, `time_budget`,
`time_window`, `preemptive`.

**Polarité inversée, volontairement.** Le produit portait deux polarités opposées côte à côte
(`requires_approval` = restriction cochée par défaut, `rules_delegated` = permission décochée
par défaut) : à l'écran, deux cases voisines dont l'une coche pour interdire et l'autre pour
autoriser. Décision Ed : **tout devient une restriction cochée par défaut**, qui se propage
vers le bas et ne se lève que depuis un niveau supérieur.
⇒ valeur EFFECTIVE = **OU logique** sur le nœud et ses ancêtres (avant : ET sur la permission
— strictement la même monotonie, lue à l'endroit).
⚠️ **Clé absente = restreinte.** Un nœud créé sans rien est verrouillé ; on n'ouvre que par
un `false` explicite. C'est pour ça que la migration écrit les quatre clés au lieu de `{}`.

**② Les plafonds quittent la règle `item_count` pour le nœud.**
`max_for_children` et `max_item_sec` étaient rangés dans les `params` d'une règle `item_count`
alors qu'ils ne décrivent pas la diffusion du nœud mais **le droit de ses descendants**. Effet
de bord vécu : pour poser un plafond sur le national, il fallait lui créer une règle de
diffusion `item_count` dont il n'avait aucun besoin. Ils deviennent donc deux colonnes du nœud.

Revision ID: 0110
Revises: 0109
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0110"
down_revision: str | None = "0109"
branch_labels = None
depends_on = None

_FAMILIES = ("item_count", "time_budget", "time_window", "preemptive")

# Défaut du modèle : tout est restreint, seul un niveau supérieur ouvre.
_ALL_LOCKED = '{"item_count": true, "time_budget": true, "time_window": true, "preemptive": true}'
_NONE_LOCKED = '{"item_count": false, "time_budget": false, "time_window": false, "preemptive": false}'


def upgrade() -> None:
    # ── ① restrictions par famille ───────────────────────────────────────────
    op.add_column(
        "cms_governance_nodes",
        sa.Column(
            "rules_locked",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text(f"'{_ALL_LOCKED}'::jsonb"),
        ),
    )
    # Report de la valeur 0109 : délégué → les 4 familles ouvertes ; sinon → les 4 fermées.
    # On écrit les clés explicitement (une clé absente vaut « restreinte », cf. en-tête).
    op.execute(
        f"UPDATE cms_governance_nodes SET rules_locked = '{_NONE_LOCKED}'::jsonb "
        "WHERE rules_delegated = true"
    )
    op.drop_column("cms_governance_nodes", "rules_delegated")

    # ── ② plafonds portés par le nœud ────────────────────────────────────────
    op.add_column("cms_governance_nodes", sa.Column("max_for_children", sa.Integer(), nullable=True))
    op.add_column("cms_governance_nodes", sa.Column("max_item_sec", sa.Integer(), nullable=True))
    # Récupération des plafonds déjà posés dans les params d'une règle item_count.
    # `is_active` n'est pas filtré : un plafond désactivé par mégarde reste une intention
    # de configuration, et le perdre silencieusement rouvrirait une porte fermée.
    for col in ("max_for_children", "max_item_sec"):
        op.execute(
            f"""
            UPDATE cms_governance_nodes n
               SET {col} = (r.params ->> '{col}')::int
              FROM cms_delegation_rules r
             WHERE r.id_node = n.id_node
               AND r.rule_type = 'item_count'
               AND r.params ? '{col}'
               AND (r.params ->> '{col}') ~ '^[0-9]+$'
            """
        )
    op.execute(
        "UPDATE cms_delegation_rules "
        "   SET params = params - 'max_for_children' - 'max_item_sec' "
        " WHERE rule_type = 'item_count' "
        "   AND (params ? 'max_for_children' OR params ? 'max_item_sec')"
    )


def downgrade() -> None:
    # ② plafonds : retour dans les params de la règle item_count du nœud (si elle existe).
    for col in ("max_for_children", "max_item_sec"):
        op.execute(
            f"""
            UPDATE cms_delegation_rules r
               SET params = r.params || jsonb_build_object('{col}', n.{col})
              FROM cms_governance_nodes n
             WHERE n.id_node = r.id_node
               AND r.rule_type = 'item_count'
               AND n.{col} IS NOT NULL
            """
        )
    op.drop_column("cms_governance_nodes", "max_item_sec")
    op.drop_column("cms_governance_nodes", "max_for_children")

    # ① retour au booléen : délégué seulement si AUCUNE famille n'est restreinte.
    op.add_column(
        "cms_governance_nodes",
        sa.Column("rules_delegated", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    conds = " AND ".join(
        f"COALESCE((rules_locked ->> '{f}')::bool, true) = false" for f in _FAMILIES
    )
    op.execute(f"UPDATE cms_governance_nodes SET rules_delegated = true WHERE {conds}")
    op.drop_column("cms_governance_nodes", "rules_locked")
