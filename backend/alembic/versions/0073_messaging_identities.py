"""« Jeanine » §EVOLUTIONS — identités messagerie (POC Telegram)

Revision ID: 0073
Revises: 0072
Create Date: 2026-07-08 00:00:00.000000

Agent conversationnel par messagerie : lie un compte de canal externe (Telegram d'abord,
WhatsApp ensuite) à un CmsUser via un code de liaison opt-in (Redis, TTL 10 min). La ligne
porte aussi l'état de conversation « proposition en attente » (lot d'actions signé, le
« OUI » du fil retrouve son jeton).
TENANT-SCOPED (RLS id_org) — le webhook (sans contexte user) résout l'identité via la
session worker BYPASSRLS, comme l'auth. Policy = pattern 0063/0065/0068.
"""

from alembic import op

revision: str = "0073"
down_revision: str | None = "0072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cms_messaging_identities (
            id_identity        BIGSERIAL PRIMARY KEY,
            id_org             BIGINT NOT NULL REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            id_user            BIGINT NOT NULL REFERENCES cms_users(id_user) ON DELETE CASCADE,
            channel            VARCHAR(20) NOT NULL DEFAULT 'telegram',
            external_user_id   VARCHAR(64) NOT NULL,   -- id utilisateur côté canal (from.id Telegram)
            chat_id            VARCHAR(64) NOT NULL,   -- id de conversation (envoi sortant)
            display_name       VARCHAR(120),
            is_active          BOOLEAN NOT NULL DEFAULT true,
            pending_token      TEXT,                    -- lot d'actions signé en attente de OUI
            pending_summary    JSONB,                   -- descriptions des étapes (ré-affichage)
            pending_expires_at TIMESTAMPTZ,
            last_seen_at       TIMESTAMPTZ,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (channel, external_user_id)
        )
        """
    )
    op.execute("CREATE INDEX idx_msg_ident_org ON cms_messaging_identities (id_org)")
    op.execute("ALTER TABLE cms_messaging_identities ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cms_messaging_identities FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cms_messaging_identities_org_isolation ON cms_messaging_identities "
        "USING (id_org = current_setting('app.current_org_id', true)::bigint)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cms_messaging_identities")
