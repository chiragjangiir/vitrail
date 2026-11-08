"""Gouvernance §XVIII — retrait des 3 règles de délégation sans effet (décision D3).

Revue du 2026-07-23 (R7) : sur 7 leviers, trois ne servaient à rien.
  - `priority_band` : totalement inerte (posait un témoin dans le rapport, ne filtrait ni
    ne réordonnait aucune couche ; pas même de min/max sur `priority`).
  - `frequency_cap` : effet étroit + mémoire de diffusion partagée entre couches (le national
    faisait sauter la copie du local) — valeur métier jugée insuffisante.
  - `position_lock` : ordonnait les couches (first/last), effet nul hors arbre multi-niveaux.

Décision Ed (D3) : les retirer. Un levier inerte fait douter de tous les autres.
Le moteur ne les parse plus et l'API refuse désormais ces `rule_type`. Cette migration
supprime les lignes résiduelles (aucune en production — 0 règle à la revue — mais nettoie
les bancs de dev pour que l'UI n'affiche pas de règle sans libellé).

Revision ID: 0105
Revises: 0104
"""

from alembic import op


revision: str = "0105"
down_revision: str | None = "0104"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM cms_delegation_rules
        WHERE rule_type IN ('priority_band', 'frequency_cap', 'position_lock')
        """
    )


def downgrade() -> None:
    # Suppression de données : les lignes retirées ne sont pas restaurables. La migration
    # de retour est un no-op assumé (les types ne sont plus acceptés par le code).
    pass
