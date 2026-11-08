"""Audio baskets — Sprint 2.5 (§XIX)

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-31 00:00:00.000000

Crée les 4 tables des paniers audio in-store (§19.2) :
  - cms_audio_baskets        — définition des paniers (type, scope, ducking_config)
  - cms_audio_basket_items   — médias dans un panier (poids de rotation, validité)
  - cms_basket_permissions   — droits d'activation par rôle/nœud
  - cms_player_basket_config — paniers actifs sur un player + ratios de mix

Note gouvernance : id_node est nullable SANS FK pour l'instant (cms_governance_nodes
n'existe pas encore — branchée au lot 4 du Sprint 2.5). Scope org via RLS.

Les permissions audio_baskets:read/control/configure et le rôle CMS_STORE_OPERATOR
sont déjà seedés dans 0002_iam.py — rien à ajouter ici.
"""

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cms_audio_baskets ──────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE cms_audio_baskets (
            id_basket      BIGSERIAL PRIMARY KEY,
            id_org         BIGINT NOT NULL REFERENCES cms_organizations(id_org),
            id_node        BIGINT,                       -- gouvernance (lot 4) — pas de FK pour l'instant
            basket_name    VARCHAR(255) NOT NULL,
            basket_type    VARCHAR(30) NOT NULL,         -- music | message | jingle | ambiance | emergency
            basket_scope   VARCHAR(20) NOT NULL DEFAULT 'local',  -- national | regional | local | style
            description    TEXT,
            is_mandatory   BOOLEAN NOT NULL DEFAULT false,
            min_ratio      SMALLINT NOT NULL DEFAULT 0,
            max_ratio      SMALLINT NOT NULL DEFAULT 100,
            ducking_config JSONB NOT NULL DEFAULT '{}',
            is_active      BOOLEAN NOT NULL DEFAULT true,
            created_by     BIGINT REFERENCES cms_users(id_user),
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_cab_org  ON cms_audio_baskets(id_org)")
    op.execute("CREATE INDEX idx_cab_node ON cms_audio_baskets(id_node)")
    op.execute("ALTER TABLE cms_audio_baskets ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY cms_audio_baskets_org_isolation ON cms_audio_baskets
            USING (id_org = current_setting('app.current_org_id', true)::bigint)
    """)

    # ── cms_audio_basket_items ─────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE cms_audio_basket_items (
            id_item     BIGSERIAL PRIMARY KEY,
            id_basket   BIGINT NOT NULL REFERENCES cms_audio_baskets(id_basket) ON DELETE CASCADE,
            id_media    BIGINT NOT NULL REFERENCES cms_media(id_media),
            weight      INT NOT NULL DEFAULT 1,
            valid_from  TIMESTAMPTZ,
            valid_until TIMESTAMPTZ,
            is_active   BOOLEAN NOT NULL DEFAULT true,
            sort_order  INT NOT NULL DEFAULT 0
        )
    """)
    op.execute("CREATE INDEX idx_cabi_basket ON cms_audio_basket_items(id_basket)")

    # ── cms_basket_permissions ─────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE cms_basket_permissions (
            id_perm        BIGSERIAL PRIMARY KEY,
            id_basket      BIGINT NOT NULL REFERENCES cms_audio_baskets(id_basket) ON DELETE CASCADE,
            id_node        BIGINT,                       -- gouvernance (lot 4) — pas de FK pour l'instant
            allowed_role   VARCHAR(50) NOT NULL,
            can_activate   BOOLEAN NOT NULL DEFAULT true,
            can_deactivate BOOLEAN NOT NULL DEFAULT true,
            can_edit_ratio BOOLEAN NOT NULL DEFAULT false,
            UNIQUE (id_basket, id_node, allowed_role)
        )
    """)
    op.execute("CREATE INDEX idx_cbp_basket ON cms_basket_permissions(id_basket)")

    # ── cms_player_basket_config ───────────────────────────────────────────────
    op.execute("""
        CREATE TABLE cms_player_basket_config (
            id_player    BIGINT NOT NULL REFERENCES cms_players(id_player) ON DELETE CASCADE,
            id_basket    BIGINT NOT NULL REFERENCES cms_audio_baskets(id_basket) ON DELETE CASCADE,
            mix_ratio    SMALLINT NOT NULL DEFAULT 50,
            is_active    BOOLEAN NOT NULL DEFAULT true,
            activated_by BIGINT REFERENCES cms_users(id_user),
            activated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id_player, id_basket)
        )
    """)
    op.execute("CREATE INDEX idx_cpbc_player ON cms_player_basket_config(id_player)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cms_player_basket_config")
    op.execute("DROP TABLE IF EXISTS cms_basket_permissions")
    op.execute("DROP TABLE IF EXISTS cms_audio_basket_items")
    op.execute("DROP TABLE IF EXISTS cms_audio_baskets")
