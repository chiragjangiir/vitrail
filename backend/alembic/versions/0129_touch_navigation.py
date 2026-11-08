"""Navigation tactile des documents multipages — item de playlist

Revision ID: 0129
Revises: 0128
Create Date: 2026-08-14 00:00:00.000000

Un document (PDF/PPTX) est déjà déroulé par le serveur en N items IMAGE portant `doc_page` /
`doc_page_count` et un `id_item` COMMUN (§3.2). Il ne manquait qu'une chose pour qu'un visiteur
puisse le feuilleter au doigt sur une dalle tactile : l'autorisation.

DEUX PROPRIÉTÉS DISTINCTES, ET C'EST CE QUI DÉCIDE DE L'EMPLACEMENT (décision d'Ed 2026-08-14) :
la dalle tactile appartient au PLAYER, l'autorisation de naviguer appartient au CONTENU. On les
croise donc — le drapeau vit sur l'item de playlist, et le renderer le rend inerte sur un écran
qui ne remonte aucun point de contact. Un réglage par player seul n'aurait pas permis de rendre
un document navigable et un autre non sur le même écran.

- `touch_navigation` : false par défaut ⇒ **déploiement strictement neutre**, aucun écran du parc
  ne change de comportement tant qu'un opérateur ne coche pas la case.
- `touch_resume_after_s` : NULL = valeur par défaut du renderer. Délai SANS interaction au bout
  duquel l'écran quitte le document et reprend la diffusion normale. Il est nécessaire parce que
  la décision « en fin de document, rester tant qu'il interagit » n'a de sens que si l'on sait
  dire quand l'interaction s'est arrêtée — sinon un objet posé sur la dalle immobiliserait
  l'écran. SMALLINT : la base fait foi (P2.6), et une valeur de ce champ est de l'ordre de la
  minute.

⚠️ Le drapeau ne vaut QUE pour un item document. Sur tout autre type il est écrit mais jamais
lu : le renderer ne l'active que sur un run de pages (`doc_page` présent). On ne pose pas de
contrainte SQL là-dessus — `item_type` ne distingue pas un document d'une image, c'est
`cms_media.page_count` qui le dit, et une contrainte inter-tables ici coûterait plus qu'elle ne
protège.

Grants : héritent des ALTER DEFAULT PRIVILEGES posés en 0044 (colonnes sur une table existante).
"""

from alembic import op
import sqlalchemy as sa

revision: str = "0129"
down_revision: str = "0128"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cms_playlist_items",
        sa.Column(
            "touch_navigation",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="Document multipage : autoriser le visiteur à feuilleter au doigt "
                    "(inerte sur un écran non tactile).",
        ),
    )
    op.add_column(
        "cms_playlist_items",
        sa.Column(
            "touch_resume_after_s",
            sa.SmallInteger(),
            nullable=True,
            comment="Délai sans interaction avant de quitter le document et reprendre la "
                    "diffusion normale. NULL = valeur par défaut du renderer.",
        ),
    )


def downgrade() -> None:
    op.drop_column("cms_playlist_items", "touch_resume_after_s")
    op.drop_column("cms_playlist_items", "touch_navigation")
