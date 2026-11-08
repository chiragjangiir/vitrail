"""IAM & Multi-tenancy — Sprint 1.1

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-18 00:00:00.000000

Crée :
  - cms_organizations, cms_sites, cms_users, cms_api_keys
  - cms_roles, cms_permissions, cms_role_permissions
  - cms_user_groups, cms_group_members, cms_group_roles, cms_user_role_assignments
  - cms_org_auth_settings, cms_ldap_configs
  - cms_players (stub — logique Sprint 1.5)
  - cms_player_update_versions, cms_update_deployments, cms_update_deployment_targets (§XXX)
  - RLS policies sur toutes les tables tenant-aware
  - Grants signflow_worker
  - Seed : 11 rôles système + catalogue de permissions (16 modules)
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB, MACADDR

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels = None
depends_on = None

# ── Catalogue des permissions atomiques (§II.1) ───────────────────────────────
_PERMISSIONS: list[tuple[str, str, str]] = [
    ("media", "create", "Créer un média"),
    ("media", "read", "Lire un média"),
    ("media", "edit", "Modifier un média"),
    ("media", "delete", "Supprimer un média"),
    ("media", "approve", "Approuver un média"),
    ("media", "export", "Exporter un média"),
    ("templates", "create", "Créer un template"),
    ("templates", "read", "Lire un template"),
    ("templates", "edit", "Modifier un template"),
    ("templates", "delete", "Supprimer un template"),
    ("templates", "publish", "Publier un template"),
    ("playlists", "create", "Créer une playlist"),
    ("playlists", "read", "Lire une playlist"),
    ("playlists", "edit", "Modifier une playlist"),
    ("playlists", "delete", "Supprimer une playlist"),
    ("playlists", "schedule", "Programmer une playlist"),
    ("schedules", "create", "Créer un schedule"),
    ("schedules", "read", "Lire un schedule"),
    ("schedules", "edit", "Modifier un schedule"),
    ("schedules", "delete", "Supprimer un schedule"),
    ("schedules", "activate", "Activer un schedule"),
    ("players", "read", "Voir un player"),
    ("players", "edit", "Modifier un player"),
    ("players", "reboot", "Redémarrer un player"),
    ("players", "update_fw", "Mettre à jour le firmware"),
    ("players", "delete", "Supprimer un player"),
    ("players", "screenshot", "Capturer l'écran"),
    ("players", "command", "Envoyer une commande"),
    ("events", "create", "Créer un événement"),
    ("events", "read", "Lire un événement"),
    ("events", "trigger", "Déclencher un événement"),
    ("events", "delete", "Supprimer un événement"),
    ("campaigns", "create", "Créer une campagne"),
    ("campaigns", "read", "Lire une campagne"),
    ("campaigns", "edit", "Modifier une campagne"),
    ("campaigns", "delete", "Supprimer une campagne"),
    ("campaigns", "publish", "Publier une campagne"),
    ("campaigns", "report", "Rapport campagne"),
    ("reports", "read", "Lire un rapport"),
    ("reports", "export", "Exporter un rapport"),
    ("reports", "share", "Partager un rapport"),
    ("users", "create", "Créer un utilisateur"),
    ("users", "read", "Voir un utilisateur"),
    ("users", "edit", "Modifier un utilisateur"),
    ("users", "delete", "Supprimer un utilisateur"),
    ("users", "assign_roles", "Assigner des rôles"),
    ("groups", "create", "Créer un groupe"),
    ("groups", "read", "Voir un groupe"),
    ("groups", "edit", "Modifier un groupe"),
    ("groups", "delete", "Supprimer un groupe"),
    ("org_settings", "read", "Voir les paramètres org"),
    ("org_settings", "edit", "Modifier les paramètres org"),
    ("api_keys", "create", "Créer une API key"),
    ("api_keys", "read", "Voir les API keys"),
    ("api_keys", "revoke", "Révoquer une API key"),
    ("audio_baskets", "read", "Voir les paniers audio"),
    ("audio_baskets", "control", "Contrôler les paniers audio"),
    ("audio_baskets", "configure", "Configurer les paniers audio"),
    ("governance", "read", "Voir la gouvernance"),
    ("governance", "edit", "Modifier la gouvernance"),
    ("governance", "delegate", "Déléguer des droits"),
    ("approvals", "submit", "Soumettre pour approbation"),
    ("approvals", "review", "Réviser une demande"),
    ("approvals", "approve", "Approuver une demande"),
    ("approvals", "reject", "Rejeter une demande"),
    ("spf", "create", "Créer un scénario SPF"),
    ("spf", "read", "Voir un scénario SPF"),
    ("spf", "edit", "Modifier un scénario SPF"),
    ("spf", "delete", "Supprimer un scénario SPF"),
    ("spf", "publish", "Publier un scénario SPF"),
    ("spf", "trigger", "Déclencher un scénario SPF"),
]

# ── Permissions par rôle système ──────────────────────────────────────────────
# Format : {role_key: set of "module:operation" — '*' signifie toutes les permissions}
_ROLE_PERMISSIONS: dict[str, set[str]] = {
    "CMS_SUPER_ADMIN": {"*"},
    "CMS_ORG_ADMIN": {"*"},
    "CMS_CAMPAIGN_MANAGER": {
        "media:read", "templates:read",
        "campaigns:create", "campaigns:read", "campaigns:edit",
        "campaigns:delete", "campaigns:publish", "campaigns:report",
        "reports:read", "reports:export",
        "users:read",
    },
    "CMS_DESIGNER": {
        "media:create", "media:read", "media:edit", "media:delete",
        "templates:create", "templates:read", "templates:edit",
        "templates:delete", "templates:publish",
        "playlists:create", "playlists:read", "playlists:edit",
    },
    "CMS_SCHEDULER": {
        "media:read", "templates:read",
        "playlists:read", "playlists:schedule",
        "schedules:create", "schedules:read", "schedules:edit",
        "schedules:delete", "schedules:activate",
        "players:read",
        "events:create", "events:read", "events:trigger",
    },
    "CMS_APPROVER": {
        "media:read", "templates:read", "playlists:read",
        "approvals:review", "approvals:approve", "approvals:reject",
    },
    "CMS_REPORT_VIEWER": {
        "reports:read", "reports:export", "reports:share",
    },
    "CMS_VIEWER": {
        "media:read", "templates:read", "playlists:read",
        "schedules:read", "players:read", "events:read",
        "campaigns:read", "reports:read",
    },
    "CMS_STORE_OPERATOR": {
        "audio_baskets:read", "audio_baskets:control",
    },
    "CMS_API_USER": set(),   # Accès contrôlé par les scopes de la clé API
    "CMS_PLAYER": set(),     # Token machine — pas de permissions RBAC
}


def upgrade() -> None:
    # ── cms_organizations ──────────────────────────────────────────────────────
    op.create_table(
        "cms_organizations",
        sa.Column("id_org", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("org_name", sa.String(255), nullable=False),
        sa.Column("org_slug", sa.String(100), nullable=False),
        sa.Column("erp_org_id", sa.Integer, nullable=True),
        sa.Column("erp_master", sa.Boolean, server_default="false", nullable=False),
        sa.Column("subscription_status", sa.String(20), server_default="unknown", nullable=False),
        sa.Column("db_schema", sa.String(50), nullable=True),
        sa.Column("org_fallback_audio_id", sa.BigInteger, nullable=True),  # FK added Sprint 1.2
        sa.Column("version_lock_enabled", sa.Boolean, server_default="false", nullable=False),
        sa.Column("player_version_lock", sa.String(20), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("org_slug", name="uq_cms_organizations_org_slug"),
    )

    # ── cms_sites ─────────────────────────────────────────────────────────────
    op.create_table(
        "cms_sites",
        sa.Column("id_site", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("id_org", sa.BigInteger, nullable=False),
        sa.Column("site_name", sa.String(255), nullable=False),
        sa.Column("erp_site_id", sa.Integer, nullable=True),
        sa.Column("address", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["id_org"], ["cms_organizations.id_org"]),
    )
    op.create_index("ix_cms_sites_id_org", "cms_sites", ["id_org"])

    # ── cms_users ─────────────────────────────────────────────────────────────
    op.create_table(
        "cms_users",
        sa.Column("id_user", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("id_org", sa.BigInteger, nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("avatar_url", sa.Text, nullable=True),
        sa.Column("totp_secret", sa.Text, nullable=True),
        sa.Column("totp_enabled", sa.Boolean, server_default="false", nullable=False),
        sa.Column("totp_backup_codes", JSONB, server_default=sa.text("'[]'"), nullable=False),
        sa.Column("erp_user_id", sa.Integer, nullable=True),
        sa.Column("locale", sa.String(5), server_default="en", nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("last_login_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["id_org"], ["cms_organizations.id_org"]),
        sa.UniqueConstraint("email", name="uq_cms_users_email"),
    )
    op.create_index("ix_cms_users_id_org", "cms_users", ["id_org"])
    op.create_index("ix_cms_users_email", "cms_users", ["email"])

    # ── cms_api_keys ──────────────────────────────────────────────────────────
    op.create_table(
        "cms_api_keys",
        sa.Column("id_key", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("id_org", sa.BigInteger, nullable=False),
        sa.Column("id_user", sa.BigInteger, nullable=True),
        sa.Column("key_hash", sa.Text, nullable=False),
        sa.Column("key_prefix", sa.String(12), nullable=False),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("scopes", ARRAY(sa.Text), server_default="{}", nullable=False),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("max_uses", sa.Integer, nullable=True),
        sa.Column("use_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["id_org"], ["cms_organizations.id_org"]),
        sa.ForeignKeyConstraint(["id_user"], ["cms_users.id_user"]),
        sa.UniqueConstraint("key_hash", name="uq_cms_api_keys_key_hash"),
    )
    op.create_index("ix_cms_api_keys_id_org", "cms_api_keys", ["id_org"])

    # ── cms_roles ─────────────────────────────────────────────────────────────
    op.create_table(
        "cms_roles",
        sa.Column("id_role", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("id_org", sa.BigInteger, nullable=True),
        sa.Column("role_key", sa.String(50), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_system", sa.Boolean, server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["id_org"], ["cms_organizations.id_org"]),
        sa.UniqueConstraint("role_key", name="uq_cms_roles_role_key"),
    )
    op.create_index("ix_cms_roles_id_org", "cms_roles", ["id_org"])

    # ── cms_permissions ───────────────────────────────────────────────────────
    op.create_table(
        "cms_permissions",
        sa.Column("id_permission", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("module", sa.String(50), nullable=False),
        sa.Column("operation", sa.String(50), nullable=False),
        sa.Column("label", sa.String(150), nullable=True),
        sa.UniqueConstraint("module", "operation", name="uq_cms_permissions_module_operation"),
    )

    # ── cms_role_permissions ──────────────────────────────────────────────────
    op.create_table(
        "cms_role_permissions",
        sa.Column("id_role", sa.BigInteger, nullable=False),
        sa.Column("id_permission", sa.BigInteger, nullable=False),
        sa.ForeignKeyConstraint(["id_role"], ["cms_roles.id_role"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["id_permission"], ["cms_permissions.id_permission"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id_role", "id_permission"),
    )

    # ── cms_user_groups ───────────────────────────────────────────────────────
    op.create_table(
        "cms_user_groups",
        sa.Column("id_group", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("id_org", sa.BigInteger, nullable=False),
        sa.Column("group_name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("scope_type", sa.String(20), server_default="org", nullable=False),
        sa.Column("scope_id", sa.BigInteger, nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["id_org"], ["cms_organizations.id_org"], ondelete="CASCADE"),
        sa.UniqueConstraint("id_org", "group_name", name="uq_cms_user_groups_org_name"),
    )
    op.create_index("ix_cug_org", "cms_user_groups", ["id_org"])

    # ── cms_group_members ─────────────────────────────────────────────────────
    op.create_table(
        "cms_group_members",
        sa.Column("id_group", sa.BigInteger, nullable=False),
        sa.Column("id_user", sa.BigInteger, nullable=False),
        sa.Column("added_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("added_by", sa.BigInteger, nullable=True),
        sa.ForeignKeyConstraint(["id_group"], ["cms_user_groups.id_group"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["id_user"], ["cms_users.id_user"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["added_by"], ["cms_users.id_user"]),
        sa.PrimaryKeyConstraint("id_group", "id_user"),
    )

    # ── cms_group_roles ───────────────────────────────────────────────────────
    op.create_table(
        "cms_group_roles",
        sa.Column("id_group", sa.BigInteger, nullable=False),
        sa.Column("id_role", sa.BigInteger, nullable=False),
        sa.ForeignKeyConstraint(["id_group"], ["cms_user_groups.id_group"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["id_role"], ["cms_roles.id_role"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id_group", "id_role"),
    )

    # ── cms_user_role_assignments ─────────────────────────────────────────────
    op.create_table(
        "cms_user_role_assignments",
        sa.Column("id_user", sa.BigInteger, nullable=False),
        sa.Column("id_role", sa.BigInteger, nullable=False),
        sa.Column("is_deny", sa.Boolean, server_default="false", nullable=False),
        sa.Column("assigned_by", sa.BigInteger, nullable=True),
        sa.Column("assigned_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["id_user"], ["cms_users.id_user"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["id_role"], ["cms_roles.id_role"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_by"], ["cms_users.id_user"]),
        sa.PrimaryKeyConstraint("id_user", "id_role"),
    )

    # ── cms_org_auth_settings ─────────────────────────────────────────────────
    op.create_table(
        "cms_org_auth_settings",
        sa.Column("id_org", sa.BigInteger, primary_key=True),
        sa.Column("auth_2fa_policy", sa.String(20), server_default="optional", nullable=False),
        sa.Column("session_lifetime", sa.Integer, server_default="480", nullable=False),
        sa.Column("max_sessions", sa.Integer, server_default="5", nullable=False),
        sa.Column("password_min_len", sa.Integer, server_default="10", nullable=False),
        sa.Column(
            "password_policy",
            JSONB,
            server_default=sa.text(
                """'{"uppercase": true, "digit": true, "special": false}'::jsonb"""
            ),
            nullable=False,
        ),
        sa.Column("ip_allowlist", ARRAY(INET), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["id_org"], ["cms_organizations.id_org"], ondelete="CASCADE"
        ),
    )

    # ── cms_ldap_configs ──────────────────────────────────────────────────────
    op.create_table(
        "cms_ldap_configs",
        sa.Column("id_ldap_config", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("id_org", sa.BigInteger, nullable=False),
        sa.Column("enabled", sa.Boolean, server_default="false", nullable=False),
        sa.Column("server_url", sa.String(255), nullable=False, server_default=""),
        sa.Column("auth_type", sa.String(10), server_default="simple", nullable=False),
        sa.Column("bind_dn_pattern", sa.String(255), nullable=True),
        sa.Column("search_base", sa.String(255), nullable=False, server_default=""),
        sa.Column("group_attr", sa.String(50), server_default="memberOf", nullable=False),
        sa.Column("group_mappings", JSONB, server_default=sa.text("'[]'"), nullable=False),
        sa.Column("auto_provision", sa.Boolean, server_default="true", nullable=False),
        sa.Column("fallback_enabled", sa.Boolean, server_default="true", nullable=False),
        sa.Column("tls_verify", sa.Boolean, server_default="true", nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["id_org"], ["cms_organizations.id_org"], ondelete="CASCADE"),
        sa.UniqueConstraint("id_org", name="uq_cms_ldap_configs_id_org"),
    )

    # ── cms_players (stub — logique Sprint 1.5) ───────────────────────────────
    op.create_table(
        "cms_players",
        sa.Column("id_player", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("id_org", sa.BigInteger, nullable=False),
        sa.Column("id_site", sa.BigInteger, nullable=True),
        sa.Column("erp_equipment_id", sa.BigInteger, nullable=True),
        sa.Column("player_name", sa.String(255), nullable=False),
        sa.Column("player_token", sa.Text, nullable=True),
        sa.Column("player_os", sa.String(50), nullable=True),
        sa.Column("player_version", sa.String(20), nullable=True),
        sa.Column("ip_address", INET, nullable=True),
        sa.Column("mac_address", MACADDR, nullable=True),
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), server_default="offline", nullable=False),
        sa.Column("display_config", JSONB, nullable=True),
        sa.Column("security_config", JSONB, nullable=True),
        sa.Column("chromeos_policy_config", JSONB, nullable=True),
        sa.Column("fallback_audio_id", sa.BigInteger, nullable=True),  # FK added Sprint 1.2
        sa.Column(
            "fallback_video_message",
            sa.String(255),
            server_default="'No content to display'",
            nullable=False,
        ),
        sa.Column("fallback_video_config", JSONB, server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["id_org"], ["cms_organizations.id_org"]),
        sa.ForeignKeyConstraint(["id_site"], ["cms_sites.id_site"]),
    )
    op.create_index("ix_cms_players_org", "cms_players", ["id_org"])
    op.create_index("ix_cms_players_site", "cms_players", ["id_site"])
    op.create_index(
        "ix_cms_players_erp", "cms_players", ["erp_equipment_id"],
        postgresql_where=sa.text("erp_equipment_id IS NOT NULL"),
    )

    # ── cms_player_update_versions (§XXX) ─────────────────────────────────────
    op.create_table(
        "cms_player_update_versions",
        sa.Column("id_version", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("track", sa.String(20), nullable=False),
        sa.Column("version", sa.String(20), nullable=False),
        sa.Column("channel", sa.String(20), server_default="stable", nullable=False),
        sa.Column("release_notes", sa.Text, nullable=True),
        sa.Column("release_notes_fr", sa.Text, nullable=True),
        sa.Column("download_url", sa.String(500), nullable=True),
        sa.Column("sha256_checksum", sa.String(64), nullable=True),
        sa.Column("gpg_signature", sa.Text, nullable=True),
        sa.Column("min_server_ver", sa.String(20), nullable=True),
        sa.Column("eol_date", sa.Date, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("track", "version", name="uq_cms_player_update_versions_track_version"),
    )

    # ── cms_update_deployments (§XXX) ─────────────────────────────────────────
    op.create_table(
        "cms_update_deployments",
        sa.Column("id_deployment", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("id_org", sa.BigInteger, nullable=False),
        sa.Column("id_version", sa.BigInteger, nullable=False),
        sa.Column("approved_by", sa.BigInteger, nullable=False),
        sa.Column("approved_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("strategy", sa.String(20), server_default="immediate", nullable=False),
        sa.Column("strategy_params", JSONB, server_default=sa.text("'{}'"), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("total_targets", sa.Integer, server_default="0", nullable=False),
        sa.Column("success_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["id_org"], ["cms_organizations.id_org"]),
        sa.ForeignKeyConstraint(["id_version"], ["cms_player_update_versions.id_version"]),
        sa.ForeignKeyConstraint(["approved_by"], ["cms_users.id_user"]),
    )

    # ── cms_update_deployment_targets (§XXX) ──────────────────────────────────
    op.create_table(
        "cms_update_deployment_targets",
        sa.Column("id_target", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("id_deployment", sa.BigInteger, nullable=False),
        sa.Column("id_player", sa.BigInteger, nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("previous_version", sa.String(20), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["id_deployment"], ["cms_update_deployments.id_deployment"]),
        sa.ForeignKeyConstraint(["id_player"], ["cms_players.id_player"]),
    )

    # ── Grants signflow_worker ────────────────────────────────────────────────
    op.execute(sa.text("GRANT USAGE ON SCHEMA public TO signflow_worker"))
    op.execute(sa.text("GRANT ALL ON ALL TABLES IN SCHEMA public TO signflow_worker"))
    op.execute(sa.text("GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO signflow_worker"))
    op.execute(sa.text(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO signflow_worker"
    ))
    op.execute(sa.text(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO signflow_worker"
    ))

    # ── RLS sur les tables tenant-aware ───────────────────────────────────────
    _rls_tables = [
        "cms_sites",
        "cms_users",
        "cms_api_keys",
        "cms_user_groups",
        "cms_ldap_configs",
        "cms_org_auth_settings",
        "cms_players",
        "cms_update_deployments",
    ]
    for table in _rls_tables:
        op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"""
            CREATE POLICY {table}_org_isolation ON {table}
                AS PERMISSIVE FOR ALL
                USING (id_org = current_setting('app.current_org_id', true)::BIGINT)
        """))

    # Tables sans id_org direct — RLS via sous-requête
    for table, subq in [
        (
            "cms_group_members",
            "id_group IN (SELECT id_group FROM cms_user_groups "
            "WHERE id_org = current_setting('app.current_org_id', true)::BIGINT)",
        ),
        (
            "cms_group_roles",
            "id_group IN (SELECT id_group FROM cms_user_groups "
            "WHERE id_org = current_setting('app.current_org_id', true)::BIGINT)",
        ),
        (
            "cms_user_role_assignments",
            "id_user IN (SELECT id_user FROM cms_users "
            "WHERE id_org = current_setting('app.current_org_id', true)::BIGINT)",
        ),
    ]:
        op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"""
            CREATE POLICY {table}_org_isolation ON {table}
                AS PERMISSIVE FOR ALL
                USING ({subq})
        """))

    # cms_roles : rôles système visibles de tous + custom roles de l'org
    op.execute(sa.text("ALTER TABLE cms_roles ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE cms_roles FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("""
        CREATE POLICY cms_roles_org_isolation ON cms_roles
            AS PERMISSIVE FOR ALL
            USING (
                id_org IS NULL
                OR id_org = current_setting('app.current_org_id', true)::BIGINT
            )
    """))

    # ── Seed : 11 rôles système ───────────────────────────────────────────────
    conn = op.get_bind()
    system_roles = [
        ("CMS_SUPER_ADMIN", "Super Administrateur", "Accès total plateforme, bypass RLS, gestion multi-tenants"),
        ("CMS_ORG_ADMIN", "Administrateur Organisation", "Admin complet org : users, groupes, rôles, settings"),
        ("CMS_CAMPAIGN_MANAGER", "Responsable Campagnes", "Campagnes retail media, créatifs, ciblage, rapports"),
        ("CMS_DESIGNER", "Designer / Créatif", "Médias, templates, playlists — pas de scheduling ni gestion players"),
        ("CMS_SCHEDULER", "Planificateur", "Schedules, programmes, events — pas de création médias"),
        ("CMS_APPROVER", "Approbateur", "Validation contenus (Approval Workflow) — lecture + approve/reject"),
        ("CMS_REPORT_VIEWER", "Lecteur Rapports", "Dashboards exécutifs et rapports uniquement — aucun accès contenu"),
        ("CMS_VIEWER", "Lecteur", "Vue contenu, playlists, schedules, players — aucune écriture"),
        ("CMS_STORE_OPERATOR", "Opérateur Magasin", "Store Control Panel LAN + paniers audio — pas d'accès CMS back-office"),
        ("CMS_API_USER", "Utilisateur API", "Accès API uniquement via API key avec scopes configurables"),
        ("CMS_PLAYER", "Token Player", "Authentification player — non humain"),
    ]
    for role_key, label, desc in system_roles:
        conn.execute(sa.text("""
            INSERT INTO cms_roles (role_key, label, description, is_system)
            VALUES (:rk, :lb, :dc, true)
        """), {"rk": role_key, "lb": label, "dc": desc})

    # ── Seed : catalogue de permissions ───────────────────────────────────────
    for module, operation, label in _PERMISSIONS:
        conn.execute(sa.text("""
            INSERT INTO cms_permissions (module, operation, label)
            VALUES (:m, :o, :l)
        """), {"m": module, "o": operation, "l": label})

    # ── Seed : permissions par rôle système ───────────────────────────────────
    all_perm_ids = {
        f"{m}:{o}": conn.execute(
            sa.text("SELECT id_permission FROM cms_permissions WHERE module=:m AND operation=:o"),
            {"m": m, "o": o},
        ).scalar()
        for m, o, _ in _PERMISSIONS
    }

    for role_key, perms in _ROLE_PERMISSIONS.items():
        role_id = conn.execute(
            sa.text("SELECT id_role FROM cms_roles WHERE role_key = :rk"),
            {"rk": role_key},
        ).scalar()
        if not role_id:
            continue

        if "*" in perms:
            perm_ids = list(all_perm_ids.values())
        else:
            perm_ids = [all_perm_ids[p] for p in perms if p in all_perm_ids]

        for pid in perm_ids:
            conn.execute(
                sa.text("""
                    INSERT INTO cms_role_permissions (id_role, id_permission)
                    VALUES (:r, :p) ON CONFLICT DO NOTHING
                """),
                {"r": role_id, "p": pid},
            )


def downgrade() -> None:
    # Suppression dans l'ordre inverse des dépendances
    op.drop_table("cms_update_deployment_targets")
    op.drop_table("cms_update_deployments")
    op.drop_table("cms_player_update_versions")
    op.drop_table("cms_players")
    op.drop_table("cms_ldap_configs")
    op.drop_table("cms_org_auth_settings")
    op.drop_table("cms_user_role_assignments")
    op.drop_table("cms_group_roles")
    op.drop_table("cms_group_members")
    op.drop_table("cms_user_groups")
    op.drop_table("cms_role_permissions")
    op.drop_table("cms_permissions")
    op.drop_table("cms_roles")
    op.drop_table("cms_api_keys")
    op.drop_table("cms_users")
    op.drop_table("cms_sites")
    op.drop_table("cms_organizations")
