"""Gouvernance §XVIII — CONTENU gouverné (R14/R15, décisions D6/D7/D8/D9 Ed 2026-07-25).

La délégation §XVIII gouvernait le « quand et où » (programmes, budgets, fenêtres) mais
PAS le « quoi » : une playlist/un média n'appartenait à aucun nœud, `playlists.py`/`media.py`
ne connaissaient pas la gouvernance. Résultat : soit un responsable local ne touchait à rien,
soit il pouvait réécrire le contenu national.

Cette migration pose la FONDATION (nullable = zéro régression : NULL = contenu d'organisation,
comportement inchangé) :
  · `cms_playlists.id_governance_node`  — la playlist appartient à un nœud (R14/R15 A).
  · `cms_media.id_governance_node`      — idem pour les médias (décision D9/b : dans le lot).
  · `cms_governance_nodes.requires_approval` — le contenu du nœud passe-t-il par un modérateur
    (R15/D) ? DEFAULT true ; à la création d'un nœud on sème la valeur du parent (D7 : héritée,
    surchargeable ; seul un ancêtre peut la décocher — géré côté API).

FK ON DELETE SET NULL : supprimer un nœud rend son contenu « d'organisation » plutôt que de le
détruire — même choix que pour les programmes (le contenu diffusé ne doit jamais disparaître
d'un coup).

Revision ID: 0107
Revises: 0106
"""

import sqlalchemy as sa
from alembic import op


revision: str = "0107"
down_revision: str | None = "0106"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cms_playlists",
        sa.Column("id_governance_node", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_cms_playlists_governance_node",
        "cms_playlists", "cms_governance_nodes",
        ["id_governance_node"], ["id_node"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_cms_playlists_governance_node", "cms_playlists", ["id_governance_node"]
    )

    op.add_column(
        "cms_media",
        sa.Column("id_governance_node", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_cms_media_governance_node",
        "cms_media", "cms_governance_nodes",
        ["id_governance_node"], ["id_node"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_cms_media_governance_node", "cms_media", ["id_governance_node"]
    )

    op.add_column(
        "cms_governance_nodes",
        sa.Column(
            "requires_approval",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("cms_governance_nodes", "requires_approval")
    op.drop_index("ix_cms_media_governance_node", table_name="cms_media")
    op.drop_constraint("fk_cms_media_governance_node", "cms_media", type_="foreignkey")
    op.drop_column("cms_media", "id_governance_node")
    op.drop_index("ix_cms_playlists_governance_node", table_name="cms_playlists")
    op.drop_constraint(
        "fk_cms_playlists_governance_node", "cms_playlists", type_="foreignkey"
    )
    op.drop_column("cms_playlists", "id_governance_node")
