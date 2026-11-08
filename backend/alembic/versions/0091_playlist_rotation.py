"""Playlist rotation : sous-playlists imbriquées + diffusion « N items par tour »

Revision ID: 0091
Revises: 0090
Create Date: 2026-07-16 10:00:00.000000

Retour beta testeurs (2026-07-16, validé Ed) : une « playlist rotation » posée dans
un programme ne diffuse que N item(s) par tour de boucle (séquentiel ou aléatoire
SANS répétition jusqu'à épuisement), l'item suivant au tour suivant.

- `cms_playlist_items.item_type` : 'media' (défaut) | 'sub_playlist'.
- `cms_playlist_items.id_child_playlist` : playlist imbriquée (1 seul niveau).
- `cms_playlist_items.id_media` devient NULLABLE (un item sub_playlist n'a pas de média).
- `cms_playlists.rotation_mode` : 'all' (défaut = inline complet) |
  'one_sequential' | 'one_random' (permutation seedée, sans remise).
- `cms_playlists.items_per_turn` : N items diffusés par tour (défaut 1).

Le cycle est DÉROULÉ PAR LE SERVEUR dans le payload de sync (ws.py) : les players
reçoivent une boucle plate ordinaire → zéro modification player, wall-clock/LAN
sync/PoP/injection campagnes inchangés.
"""

from alembic import op

revision: str = "0091"
down_revision: str | None = "0090"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cms_playlist_items ADD COLUMN item_type "
        "VARCHAR(20) NOT NULL DEFAULT 'media'"
    )
    op.execute(
        "ALTER TABLE cms_playlist_items ADD COLUMN id_child_playlist BIGINT "
        "REFERENCES cms_playlists(id_playlist)"
    )
    op.execute("ALTER TABLE cms_playlist_items ALTER COLUMN id_media DROP NOT NULL")
    op.execute(
        "ALTER TABLE cms_playlists ADD COLUMN rotation_mode "
        "VARCHAR(20) NOT NULL DEFAULT 'all'"
    )
    op.execute(
        "ALTER TABLE cms_playlists ADD COLUMN items_per_turn "
        "SMALLINT NOT NULL DEFAULT 1"
    )
    op.execute(
        "CREATE INDEX ix_cms_playlist_items_child ON cms_playlist_items (id_child_playlist) "
        "WHERE id_child_playlist IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_cms_playlist_items_child")
    op.execute("DELETE FROM cms_playlist_items WHERE id_media IS NULL")
    op.execute("ALTER TABLE cms_playlist_items ALTER COLUMN id_media SET NOT NULL")
    op.execute("ALTER TABLE cms_playlist_items DROP COLUMN IF EXISTS id_child_playlist")
    op.execute("ALTER TABLE cms_playlist_items DROP COLUMN IF EXISTS item_type")
    op.execute("ALTER TABLE cms_playlists DROP COLUMN IF EXISTS rotation_mode")
    op.execute("ALTER TABLE cms_playlists DROP COLUMN IF EXISTS items_per_turn")
