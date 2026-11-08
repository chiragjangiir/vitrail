"""Documents multipages (PDF / PPT / PPTX) — rendu page par page (§3.2)

Revision ID: 0092
Revises: 0091
Create Date: 2026-07-16 18:00:00.000000

Décisions Ed 2026-07-16 : durée par page programmable (défaut 10 s = duration_ms
de l'item, sémantique « par page » pour les documents), sélection de pages dès la
v1, PPT/PPTX converti serveur-side (LibreOffice headless → PDF → pdftoppm).

- `cms_media.page_count` : nb de pages converties en images (NULL = pas un
  document converti). Les clés/checksums des pages vivent dans metadata["document"].
- `cms_playlist_items.doc_pages` : sélection "2-5,8" (NULL = toutes les pages).
- `cms_playlist_items.doc_page_count` : nb de pages résolues quand doc_pages est
  posé — dénormalisé pour les agrégats SQL (durée totale, simulation, feasibility).

La diffusion est déroulée par le serveur (ws.py) : N items image par document dans
le payload — zéro modification player.
"""

from alembic import op

revision: str = "0092"
down_revision: str | None = "0091"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE cms_media ADD COLUMN page_count INTEGER")
    op.execute("ALTER TABLE cms_playlist_items ADD COLUMN doc_pages VARCHAR(200)")
    op.execute("ALTER TABLE cms_playlist_items ADD COLUMN doc_page_count INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE cms_playlist_items DROP COLUMN IF EXISTS doc_page_count")
    op.execute("ALTER TABLE cms_playlist_items DROP COLUMN IF EXISTS doc_pages")
    op.execute("ALTER TABLE cms_media DROP COLUMN IF EXISTS page_count")
