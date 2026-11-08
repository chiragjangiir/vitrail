"""Où s'affiche un spot de campagne sur un écran MULTI-ZONES (P3.6, décision Ed 2026-08-06).

Jusqu'ici, l'injection des créatifs était purement et simplement **coupée** dès qu'un
template portait 2 zones ou plus (`ws.py`, garde `not is_multizone`). Or **aucun service ne
connaît cette notion** — mesuré : `campaign_eligible_players`, l'occupancy-check, le SOV et
le devis comptent ces écrans comme **vendables**. Un annonceur pouvait donc être facturé
pour des écrans qui ne diffuseraient jamais son spot : angle mort de **facturation**, pas
simple fonctionnalité manquante.

Décision d'Ed : le comportement est **choisi par template**, parce que les deux usages
existent réellement —

- `fullscreen` (défaut) : le spot **recouvre tout l'écran** le temps de sa diffusion, les
  zones reprennent ensuite. C'est le seul mode cohérent avec la tarification au **SOV**, qui
  suppose une exposition plein écran ;
- `zone` : le spot s'insère comme un item normal dans la **zone principale**, les autres
  zones continuent. Non intrusif — le cas du menu board ou du panneau à bandeau
  d'actualités, où tout effacer pendant 10 s n'est pas acceptable.

**Défaut `fullscreen`** : c'est la valeur qui préserve le modèle de vente. ⚠️ Conséquence
assumée : après déploiement, un écran multi-zones qui ne recevait AUCUN spot commencera à
en recevoir. C'est précisément l'objet du chantier — et c'est neutre sur le parc actuel,
où **aucune playlist en service n'utilise de template multi-zones** (mesuré le 06/08).

Revision ID: 0124
Revises: 0123
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0124"
down_revision: str | None = "0123"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cms_templates",
        sa.Column(
            "campaign_placement",
            sa.String(length=20),
            server_default="fullscreen",
            nullable=False,
        ),
    )
    # Le jeu de valeurs est verrouillé en base : un mode inconnu ferait silencieusement
    # retomber le player sur un comportement par défaut, donc diffuser autre chose que ce
    # qui a été vendu. Mieux vaut refuser l'écriture.
    # ⚠️ Nom NU : la convention de nommage du projet préfixe déjà `ck_<table>_`. Lui passer
    # un nom qui contient ce préfixe le DOUBLE (`ck_cms_templates_ck_cms_templates_…`) —
    # constaté sur la production le 2026-08-06. La contrainte fonctionnait, mais le
    # `downgrade` ci-dessous visait un nom inexistant : il aurait échoué le jour du rollback.
    op.create_check_constraint(
        "campaign_placement",
        "cms_templates",
        "campaign_placement IN ('fullscreen', 'zone')",
    )


def downgrade() -> None:
    # ⚠️ Nom NU : la convention `ck_%(table_name)s_%(constraint_name)s` s'applique AUSSI à
    # `drop_constraint`. Le correctif du 2026-08-06 n'avait mis au nom nu que le `create` :
    # le downgrade doublait donc encore le préfixe et échouait — vu en EXÉCUTANT le
    # downgrade le 2026-08-07, jamais en le relisant.
    op.drop_constraint("campaign_placement", "cms_templates", type_="check")
    op.drop_column("cms_templates", "campaign_placement")
