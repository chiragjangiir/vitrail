"""Store Control Panel LAN — Sprint 2.5 lot 3 (§19.3)

Revision ID: 0020
Revises: 0019
Create Date: 2026-05-31 12:00:00.000000

Ajoute le support du Store Control Panel LAN (§19.3) :
  - cms_local_control_profiles — profils d'accès local par player (token QR,
    rôle, paniers autorisés, permissions, expiration). Le serveur HTTP embarqué
    du player (port 8765) valide le token et applique les actions de l'opérateur.
  - cms_audit_log.source — origine d'une action ('cms' par défaut, 'local_control'
    pour les actions issues du Store Control Panel) (§19.3 audit trail).

Le token est stocké en clair : faible sensibilité (scopé à 1 player, expirable,
révocable) et nécessaire au CMS pour ré-afficher le QR + au player pour valider.
L'activation du serveur est pilotée par display_config.local_control_enabled
(JSONB existant, zéro colonne) — opt-in par player, OFF par défaut.
"""

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cms_local_control_profiles ─────────────────────────────────────────────
    op.execute("""
        CREATE TABLE cms_local_control_profiles (
            id_profile        BIGSERIAL PRIMARY KEY,
            id_org            BIGINT NOT NULL REFERENCES cms_organizations(id_org),
            id_player         BIGINT NOT NULL REFERENCES cms_players(id_player) ON DELETE CASCADE,
            token             VARCHAR(64) NOT NULL,
            role              VARCHAR(50) NOT NULL DEFAULT 'CMS_STORE_OPERATOR',
            allowed_basket_ids JSONB,                      -- NULL = tous les paniers actifs du player
            can_edit_ratio    BOOLEAN NOT NULL DEFAULT false,
            can_set_volume    BOOLEAN NOT NULL DEFAULT true,
            can_trigger_event BOOLEAN NOT NULL DEFAULT false,
            expires_at        TIMESTAMPTZ,
            revoked           BOOLEAN NOT NULL DEFAULT false,
            created_by        BIGINT REFERENCES cms_users(id_user),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_clcp_player ON cms_local_control_profiles(id_player)")
    op.execute("CREATE INDEX idx_clcp_org    ON cms_local_control_profiles(id_org)")
    # Un seul profil non-révoqué par player (révocation = soft, on garde l'historique)
    op.execute("""
        CREATE UNIQUE INDEX uq_clcp_active_player ON cms_local_control_profiles(id_player)
            WHERE revoked = false
    """)
    op.execute("ALTER TABLE cms_local_control_profiles ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY cms_local_control_profiles_org_isolation ON cms_local_control_profiles
            USING (id_org = current_setting('app.current_org_id', true)::bigint)
    """)

    # ── cms_audit_log.source ───────────────────────────────────────────────────
    op.execute(
        "ALTER TABLE cms_audit_log ADD COLUMN source VARCHAR(30) NOT NULL DEFAULT 'cms'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cms_audit_log DROP COLUMN IF EXISTS source")
    op.execute("DROP TABLE IF EXISTS cms_local_control_profiles")
