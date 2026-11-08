"""Staging des playlists : brouillon d'édition non publié — cms_playlists.draft_items

Revision ID: 0040
Revises: 0039
Create Date: 2026-06-07 12:00:00.000000

Staging robuste (#1, archi 2). `cms_playlist_items` reste la version PUBLIÉE (servie
aux players, chemin de sync inchangé). Les éditions vont dans `draft_items` (JSONB,
NULL = pas de brouillon = propre). « Publier » applique le brouillon → items live +
push graceful ; « Annuler » efface le brouillon.

draft_items = [{uid, id_media, sort_order, duration_ms, zone_index, transition_type,
                rules: [{...}]}] (uid = id temporaire négatif côté brouillon).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cms_playlists", sa.Column("draft_items", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("cms_playlists", "draft_items")
