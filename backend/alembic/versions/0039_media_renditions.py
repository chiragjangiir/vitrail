"""Renditions adaptatives par capacité player (« artefacts » vidéo)

Revision ID: 0039
Revises: 0038
Create Date: 2026-06-07 10:00:00.000000

Une vidéo uploadée (« originale ») peut désormais porter des **renditions** (artefacts) :
des ré-encodages de résolution/codec inférieurs, générés par le serveur, parmi lesquels
chaque player reçoit AUTOMATIQUEMENT au sync la version adaptée à sa capacité de décodage.

  - `cms_media_renditions` : un artefact par profil (fhd/hd720/uhd…) lié au parent.
  - `cms_media.has_renditions` : drapeau de présence (badge médiathèque, drawer).
  - `cms_organizations.rendition_policy` : politique de génération auto (off | auto_fhd).

Règles transverses (cf. EVOLUTIONS.md « Renditions adaptatives ») :
  - Les playlists/templates référencent TOUJOURS le parent (l'originale).
  - L'embargo / la quarantaine (is_blocked) / le blocage CASCADENT du parent : jamais
    gérés sur la rendition (FK ondelete=CASCADE → suppression du parent purge les artefacts).
  - En groupe LAN sync : la rendition du membre le plus faible s'applique à TOUS (cohérence
    frame), résolu au sync dans ws.py (aucune contrainte stockée ici).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cms_media_renditions",
        sa.Column("id_rendition", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "id_parent",
            sa.BigInteger(),
            sa.ForeignKey("cms_media.id_media", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # Profil de rendition : uhd | fhd | hd720 (extensible). UNIQUE par parent.
        sa.Column("profile", sa.String(20), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("codec", sa.String(20), nullable=True),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("file_meta", JSONB(), server_default=sa.text("'{}'"), nullable=False),
        # Verdict conformité/sync-readiness de l'artefact (média_conformance).
        sa.Column("conformance_status", sa.String(20), nullable=True),
        # pending | processing | ready | failed
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("id_parent", "profile", name="uq_rendition_parent_profile"),
    )

    op.add_column(
        "cms_media",
        sa.Column(
            "has_renditions",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )

    op.add_column(
        "cms_organizations",
        sa.Column(
            "rendition_policy",
            sa.String(20),
            server_default="off",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("cms_organizations", "rendition_policy")
    op.drop_column("cms_media", "has_renditions")
    op.drop_table("cms_media_renditions")
