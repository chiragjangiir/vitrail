"""Sous-playlists : « pas de publicité entre les contenus » (retour Ed 2026-07-16)

Revision ID: 0093
Revises: 0092
Create Date: 2026-07-16 21:30:00.000000

Même mécanisme que l'anti-coupure des documents multipages (no_ad_before) :
quand une playlist marquée `no_ads_inside` est imbriquée comme sous-playlist,
son bloc d'items passe d'une traite — l'injection Retail Media place le spot
avant ou après le bloc, jamais dedans. Ne s'applique PAS quand la playlist est
le programme principal (l'opt-out pub par player existe déjà, et un opt-out
contenu total recréerait l'angle mort d'inventaire du multi-zones).
Le « SOV réalisable » compte un bloc protégé comme UNE frontière utilisable.
"""

from alembic import op

revision: str = "0093"
down_revision: str | None = "0092"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cms_playlists ADD COLUMN no_ads_inside "
        "BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cms_playlists DROP COLUMN IF EXISTS no_ads_inside")
