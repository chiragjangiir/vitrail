"""Système de tags & filtrage de contenu §XVII (Sprint 2.6)

Revision ID: 0026
Revises: 0025
Create Date: 2026-06-01 14:00:00.000000

6 tables : namespaces (par org) + valeurs + jonctions (média, item playlist,
override de namespace, filtre player). Seed des 5 namespaces standards
(resolution/region/language/audience/channel) + valeurs par défaut pour chaque
org existante. cms_media n'a PAS de colonne `tags` (def canonique §XVI.2) → pas
de migration de données legacy.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels = None
depends_on = None

# Taxonomie standard (gelée dans la migration — l'app a sa propre copie dans services/tags.py)
# (namespace_key, label, match_mode, applies_to[], [(value, label, color), ...])
_STD = [
    ("resolution", "Résolution", "any", ["video", "image"],
     [("SD", "SD", "#9CA3AF"), ("FHD", "FHD", "#4875B4"), ("UHD", "UHD", "#7C3AED")]),
    ("region", "Région", "any", [],
     [("EU", "EU", "#4875B4"), ("FR", "FR", "#3B82F6"), ("DE", "DE", "#F59E0B"),
      ("UK", "UK", "#10B981"), ("US", "US", "#EF4444")]),
    ("language", "Langue", "any", [],
     [("fr", "Français", "#3B82F6"), ("en", "English", "#10B981"),
      ("de", "Deutsch", "#F59E0B"), ("es", "Español", "#EF4444")]),
    ("audience", "Audience", "any", [],
     [("adults", "Adultes", "#6366F1"), ("children", "Enfants", "#F472B6"), ("all", "Tous", "#9CA3AF")]),
    ("channel", "Canal", "any", [],
     [("promo", "Promo", "#EF4444"), ("brand", "Marque", "#4875B4"),
      ("safety", "Sécurité", "#F59E0B"), ("info", "Info", "#10B981")]),
]


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cms_tag_namespaces (
            id_namespace  BIGSERIAL PRIMARY KEY,
            id_org        BIGINT NOT NULL REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            namespace_key VARCHAR(50) NOT NULL,
            label         VARCHAR(100),
            match_mode    VARCHAR(10) NOT NULL DEFAULT 'any',
            applies_to    TEXT[] NOT NULL DEFAULT '{}',
            is_system     BOOLEAN NOT NULL DEFAULT false,
            is_active     BOOLEAN NOT NULL DEFAULT true,
            sort_order    INT NOT NULL DEFAULT 0,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (id_org, namespace_key)
        )
        """
    )
    op.execute("CREATE INDEX idx_ctn_org ON cms_tag_namespaces(id_org)")

    op.execute(
        """
        CREATE TABLE cms_tag_values (
            id_tag       BIGSERIAL PRIMARY KEY,
            id_namespace BIGINT NOT NULL REFERENCES cms_tag_namespaces(id_namespace) ON DELETE CASCADE,
            tag_value    VARCHAR(100) NOT NULL,
            label        VARCHAR(100),
            color        VARCHAR(7),
            sort_order   INT NOT NULL DEFAULT 0,
            UNIQUE (id_namespace, tag_value)
        )
        """
    )
    op.execute("CREATE INDEX idx_ctv_ns ON cms_tag_values(id_namespace)")

    op.execute(
        """
        CREATE TABLE cms_media_tag_values (
            id_media BIGINT NOT NULL REFERENCES cms_media(id_media) ON DELETE CASCADE,
            id_tag   BIGINT NOT NULL REFERENCES cms_tag_values(id_tag) ON DELETE CASCADE,
            PRIMARY KEY (id_media, id_tag)
        )
        """
    )
    op.execute("CREATE INDEX idx_cmtv_tag ON cms_media_tag_values(id_tag)")

    op.execute(
        """
        CREATE TABLE cms_playlist_item_tags (
            id_item BIGINT NOT NULL REFERENCES cms_playlist_items(id_item) ON DELETE CASCADE,
            id_tag  BIGINT NOT NULL REFERENCES cms_tag_values(id_tag) ON DELETE CASCADE,
            PRIMARY KEY (id_item, id_tag)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE cms_playlist_item_ns_overrides (
            id_item      BIGINT NOT NULL REFERENCES cms_playlist_items(id_item) ON DELETE CASCADE,
            id_namespace BIGINT NOT NULL REFERENCES cms_tag_namespaces(id_namespace) ON DELETE CASCADE,
            PRIMARY KEY (id_item, id_namespace)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE cms_player_tag_filters (
            id_player    BIGINT NOT NULL REFERENCES cms_players(id_player) ON DELETE CASCADE,
            id_namespace BIGINT NOT NULL REFERENCES cms_tag_namespaces(id_namespace) ON DELETE CASCADE,
            id_tag       BIGINT NOT NULL REFERENCES cms_tag_values(id_tag) ON DELETE CASCADE,
            PRIMARY KEY (id_player, id_tag)
        )
        """
    )
    op.execute("CREATE INDEX idx_cptf_player ON cms_player_tag_filters(id_player)")

    # ── Seed des namespaces standards pour chaque org existante ────────────────
    conn = op.get_bind()
    org_ids = [r[0] for r in conn.execute(sa.text("SELECT id_org FROM cms_organizations")).fetchall()]
    for id_org in org_ids:
        for sort_ns, (key, label, mode, applies, values) in enumerate(_STD):
            ns_id = conn.execute(
                sa.text(
                    "INSERT INTO cms_tag_namespaces "
                    "(id_org, namespace_key, label, match_mode, applies_to, is_system, sort_order) "
                    "VALUES (:o, :k, :l, :m, :a, true, :s) RETURNING id_namespace"
                ),
                {"o": id_org, "k": key, "l": label, "m": mode, "a": applies, "s": sort_ns},
            ).scalar()
            for sort_v, (val, vlabel, color) in enumerate(values):
                conn.execute(
                    sa.text(
                        "INSERT INTO cms_tag_values (id_namespace, tag_value, label, color, sort_order) "
                        "VALUES (:n, :v, :l, :c, :s)"
                    ),
                    {"n": ns_id, "v": val, "l": vlabel, "c": color, "s": sort_v},
                )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cms_player_tag_filters")
    op.execute("DROP TABLE IF EXISTS cms_playlist_item_ns_overrides")
    op.execute("DROP TABLE IF EXISTS cms_playlist_item_tags")
    op.execute("DROP TABLE IF EXISTS cms_media_tag_values")
    op.execute("DROP TABLE IF EXISTS cms_tag_values")
    op.execute("DROP TABLE IF EXISTS cms_tag_namespaces")
