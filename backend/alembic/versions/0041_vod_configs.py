"""VOD à la demande (Feature B) — configs VOD + permissions RBAC

Revision ID: 0041
Revises: 0040
Create Date: 2026-06-14 12:00:00.000000

Une config VOD = set nommé de médias visuels pré-cachés sur des players du même site,
déclenchable à la demande (cloud / LAN-local). Phase 1 = modèle + affectation + pré-cache.

Nouveau module RBAC `vod` (create/read/edit/delete/trigger). Comme le seed 0002 a étendu
le wildcard `*` de CMS_ORG_ADMIN en lignes explicites, on accorde ici les nouvelles
permissions à CMS_ORG_ADMIN (+ SCHEDULER read/create/trigger, VIEWER read). SUPER_ADMIN
est bypassé en code → pas de grant nécessaire.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels = None
depends_on = None


_VOD_PERMISSIONS = [
    ("vod", "create", "Créer une config VOD"),
    ("vod", "read", "Lire une config VOD"),
    ("vod", "edit", "Modifier une config VOD"),
    ("vod", "delete", "Supprimer une config VOD"),
    ("vod", "trigger", "Déclencher une lecture VOD"),
]

# {role_key: set of "vod:operation"} — ORG_ADMIN reçoit tout (wildcard figé au seed 0002).
_VOD_ROLE_GRANTS = {
    "CMS_ORG_ADMIN": {"vod:create", "vod:read", "vod:edit", "vod:delete", "vod:trigger"},
    "CMS_SCHEDULER": {"vod:create", "vod:read", "vod:trigger"},
    "CMS_VIEWER": {"vod:read"},
}


def upgrade() -> None:
    op.create_table(
        "cms_vod_configs",
        sa.Column("id_vod", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("id_org", sa.BigInteger, nullable=False),
        sa.Column("id_site", sa.BigInteger, nullable=True),
        sa.Column("vod_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_by", sa.BigInteger, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["id_org"], ["cms_organizations.id_org"]),
        sa.ForeignKeyConstraint(["id_site"], ["cms_sites.id_site"]),
        sa.ForeignKeyConstraint(["created_by"], ["cms_users.id_user"]),
    )
    op.create_index("ix_cms_vod_configs_id_org", "cms_vod_configs", ["id_org"])

    op.create_table(
        "cms_vod_config_media",
        sa.Column("id_vod_media", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("id_vod", sa.BigInteger, nullable=False),
        sa.Column("id_media", sa.BigInteger, nullable=False),
        sa.Column("sort_order", sa.Integer, server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["id_vod"], ["cms_vod_configs.id_vod"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["id_media"], ["cms_media.id_media"]),
        sa.UniqueConstraint("id_vod", "id_media", name="uq_cms_vod_config_media"),
    )
    op.create_index("ix_cms_vod_config_media_id_vod", "cms_vod_config_media", ["id_vod"])

    op.create_table(
        "cms_vod_config_players",
        sa.Column("id_vod_player", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("id_vod", sa.BigInteger, nullable=False),
        sa.Column("id_player", sa.BigInteger, nullable=False),
        sa.ForeignKeyConstraint(["id_vod"], ["cms_vod_configs.id_vod"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["id_player"], ["cms_players.id_player"]),
        sa.UniqueConstraint("id_vod", "id_player", name="uq_cms_vod_config_players"),
    )
    op.create_index("ix_cms_vod_config_players_id_vod", "cms_vod_config_players", ["id_vod"])

    # ── Seed : permissions du module vod ──────────────────────────────────────
    conn = op.get_bind()
    for module, operation, label in _VOD_PERMISSIONS:
        conn.execute(sa.text("""
            INSERT INTO cms_permissions (module, operation, label)
            VALUES (:m, :o, :l)
            ON CONFLICT (module, operation) DO NOTHING
        """), {"m": module, "o": operation, "l": label})

    perm_ids = {
        f"{m}:{o}": conn.execute(
            sa.text("SELECT id_permission FROM cms_permissions WHERE module=:m AND operation=:o"),
            {"m": m, "o": o},
        ).scalar()
        for m, o, _ in _VOD_PERMISSIONS
    }

    for role_key, perms in _VOD_ROLE_GRANTS.items():
        role_id = conn.execute(
            sa.text("SELECT id_role FROM cms_roles WHERE role_key = :rk"), {"rk": role_key}
        ).scalar()
        if not role_id:
            continue
        for perm in perms:
            pid = perm_ids.get(perm)
            if pid is None:
                continue
            conn.execute(sa.text("""
                INSERT INTO cms_role_permissions (id_role, id_permission)
                VALUES (:r, :p) ON CONFLICT DO NOTHING
            """), {"r": role_id, "p": pid})


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("""
        DELETE FROM cms_role_permissions WHERE id_permission IN (
            SELECT id_permission FROM cms_permissions WHERE module = 'vod'
        )
    """))
    conn.execute(sa.text("DELETE FROM cms_permissions WHERE module = 'vod'"))
    op.drop_table("cms_vod_config_players")
    op.drop_table("cms_vod_config_media")
    op.drop_table("cms_vod_configs")
