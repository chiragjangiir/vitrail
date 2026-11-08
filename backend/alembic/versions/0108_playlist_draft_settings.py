"""Rotation d'une playlist : réglages passés par le BROUILLON (décision Ed 2026-07-25 ④).

Constat d'Ed : dans l'éditeur de playlist, deux réglages voisins ne se comportaient pas
pareil. Toute modification d'ITEM (ajout, retrait, ordre, durée) va au brouillon et attend
le bouton « Publier » ; les réglages de ROTATION (`rotation_mode`, `items_per_turn`,
`no_ads_inside`), eux, étaient écrits directement dans les colonnes de la playlist et
poussés aux players sur-le-champ (`force_sync`). On pouvait donc changer la boucle des
écrans sans jamais publier — et sans possibilité de revenir en arrière.

Cette migration ajoute `draft_settings` (JSONB, NULL = aucun réglage en attente), pendant
exact de `draft_items` : l'éditeur écrit dedans, `apply_draft` le recopie dans les colonnes
à la publication, `discard` l'efface. Les colonnes publiées ne bougent plus qu'à la
publication — donc les players (qui lisent ces colonnes via ws.py) ne voient jamais un
réglage non publié, et une playlist gouvernée sous modération fait passer sa rotation par
l'approbation §XXI comme le reste de son contenu.

Nullable, sans valeur par défaut ⇒ aucune playlist existante n'est touchée.

Revision ID: 0108
Revises: 0107
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0108"
down_revision: str | None = "0107"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cms_playlists",
        sa.Column("draft_settings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cms_playlists", "draft_settings")
