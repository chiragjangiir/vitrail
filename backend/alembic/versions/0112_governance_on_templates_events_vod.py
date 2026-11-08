"""Gouvernance §XVIII sur les objets qui l'ignoraient — phase 4 de l'audit du 2026-07-27.

Constat N3, mesuré en réel : un administrateur de MAGASIN a modifié le **template partagé 5**
(200) et **créé un programme visant le BrightSign** d'un autre périmètre. Cause de fond :
`cms_templates`, `cms_events` et `cms_vod_configs` **n'ont aucune colonne de gouvernance**.
La phase 3 (rôles scopés G4) a fermé la porte pour les porteurs de rôles de gouvernance — ils
ne détiennent aucune permission `templates:*`/`events:*` — mais la remarque d'Ed reste vraie :
ajouter un `CMS_SCHEDULER` par-dessus rouvrait events + VOD sur tout le parc.

Cette migration donne à ces trois objets la même colonne que playlists et médias :
`id_governance_node` NULL = objet d'organisation (comportement d'AVANT, donc aucun changement
au déploiement : toutes les lignes existantes restent NULL), non NULL = objet gouverné, dont
l'écriture est gardée par `governance_access.user_can_edit_node` et la lecture filtrée par
`content_visibility` (D6 + G4).

`ON DELETE SET NULL` comme pour playlists/médias : supprimer un nœud ne doit jamais supprimer
du contenu — il le rend simplement non gouverné, ce que l'écran montre.

Revision ID: 0112
Revises: 0111
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0112"
down_revision: str | None = "0111"
branch_labels = None
depends_on = None

_TABLES = ("cms_templates", "cms_events", "cms_vod_configs")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column("id_governance_node", sa.BigInteger(), nullable=True),
        )
        op.create_foreign_key(
            f"fk_{table}_governance_node", table, "cms_governance_nodes",
            ["id_governance_node"], ["id_node"], ondelete="SET NULL",
        )
        # Index partiel : la très grande majorité des lignes reste NULL (contenu d'org),
        # les indexer n'apporterait rien et coûterait à chaque écriture.
        op.execute(
            f"CREATE INDEX ix_{table}_governance_node ON {table} (id_governance_node) "
            "WHERE id_governance_node IS NOT NULL"
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_governance_node")
        op.drop_constraint(f"fk_{table}_governance_node", table, type_="foreignkey")
        op.drop_column(table, "id_governance_node")
