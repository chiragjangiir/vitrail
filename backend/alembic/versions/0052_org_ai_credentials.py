"""Coffre-fort de clés API IA par organisation (BYOK §XXVII)

Revision ID: 0052
Revises: 0051
Create Date: 2026-06-22 00:00:00.000000

- cms_org_ai_credentials : 1 ligne par (id_org, provider). Le secret est chiffré au
  repos côté applicatif (Fernet, app.core.crypto) → stocké en TEXT. TENANT-SCOPED
  (RLS id_org, FORCE pour soumettre même le propriétaire de table). La clé en clair ne
  ressort jamais de l'API (seul key_last4 est exposé).
- cms_organizations.ai_byok_mode : strict (défaut) | platform. Pilote si l'org peut
  utiliser la clé Anthropic plateforme (opt-in super-admin explicite, aucun repli auto).

Grants : héritent des ALTER DEFAULT PRIVILEGES posés en 0044 (signflow_app/worker) →
rien à granter ici. Policy RLS = pattern 0044/0046 (USING = WITH CHECK implicite).

Cf. docs/PLAN_BYOK_AI_KEYS.md.
"""

from alembic import op

revision: str = "0052"
down_revision: str | None = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cms_org_ai_credentials (
            id_credential    BIGSERIAL PRIMARY KEY,
            id_org           BIGINT NOT NULL REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            provider         VARCHAR(20) NOT NULL,       -- anthropic | fal | elevenlabs
            secret_encrypted TEXT NOT NULL,              -- clé chiffrée (Fernet) — jamais en clair
            key_last4        VARCHAR(8),                 -- affichage masqué (sk-…a3f9)
            extra_config     JSONB NOT NULL DEFAULT '{}'::jsonb,
            status           VARCHAR(16) NOT NULL DEFAULT 'unverified',  -- unverified | valid | invalid
            validated_at     TIMESTAMPTZ,
            created_by       BIGINT REFERENCES cms_users(id_user) ON DELETE SET NULL,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (id_org, provider)
        )
        """
    )
    op.execute("CREATE INDEX idx_org_ai_cred_org ON cms_org_ai_credentials (id_org)")
    op.execute("ALTER TABLE cms_org_ai_credentials ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cms_org_ai_credentials FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY cms_org_ai_credentials_org_isolation ON cms_org_ai_credentials
            USING (id_org = current_setting('app.current_org_id', true)::bigint)
        """
    )

    op.execute(
        "ALTER TABLE cms_organizations "
        "ADD COLUMN ai_byok_mode VARCHAR(10) NOT NULL DEFAULT 'strict'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cms_organizations DROP COLUMN IF EXISTS ai_byok_mode")
    op.execute("DROP TABLE IF EXISTS cms_org_ai_credentials")
