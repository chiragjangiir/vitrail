"""Gouvernance §XVIII — `time_budget` devient un volume ABSOLU par cycle (décision D1).

Revue du 2026-07-23 (R13) : `time_budget` n'était pas un budget mais une *part d'un total
que les autres nœuds contrôlent*. La formule `sec_per_hour × cycle_total / 3600` prenait pour
référence la somme de **toutes** les couches → ajouter du contenu à un sous-nœud dé-rognait la
couche parente. Décision D1 : le budget est un **volume absolu par cycle** (`sec_per_cycle`),
indépendant des autres couches. Le moteur ne divise plus par la longueur du cycle.

Cette migration renomme le paramètre stocké `sec_per_hour → sec_per_cycle` dans les règles de
type `time_budget`. La valeur numérique est **conservée telle quelle** — sa signification change
(part → secondes absolues), mais aucune donnée de gouvernance n'existe en production au moment
de cette bascule (0 nœud, 0 règle vérifié à la revue), donc rien à ré-interpréter : les rares
règles de banc de test seront reconfigurées. Le renommage garde seulement le schéma cohérent
pour d'éventuelles règles résiduelles.

Revision ID: 0104
Revises: 0103
"""

from alembic import op


revision: str = "0104"
down_revision: str | None = "0103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # JSONB : retirer l'ancienne clé et poser la nouvelle avec la même valeur.
    op.execute(
        """
        UPDATE cms_delegation_rules
        SET params = (params - 'sec_per_hour')
                     || jsonb_build_object('sec_per_cycle', params -> 'sec_per_hour')
        WHERE rule_type = 'time_budget'
          AND params ? 'sec_per_hour'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE cms_delegation_rules
        SET params = (params - 'sec_per_cycle')
                     || jsonb_build_object('sec_per_hour', params -> 'sec_per_cycle')
        WHERE rule_type = 'time_budget'
          AND params ? 'sec_per_cycle'
        """
    )
