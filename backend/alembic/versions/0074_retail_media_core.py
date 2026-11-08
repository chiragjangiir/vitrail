"""Retail Media §2.8 (vague 3.1) — socle : annonceurs, campagnes, créatifs, cibles

Revision ID: 0074
Revises: 0073
Create Date: 2026-07-09 00:00:00.000000

Inventaire pDOOH monétisable (cadrage docs/PLAN_RETAIL_MEDIA.md, décisions Ed 2026-07-09) :
vente v1 = SOV % + forfait (CPM indicatif) ; surbooking = blocage + override org-admin ;
approval créatifs = optionnel par org. Les cibles reprennent le modèle canonique des
schedules/events (player/group/site/tags) → resolution via services/targeting.py.
TENANT-SCOPED (RLS id_org), policy pattern 0073.
"""

from alembic import op

revision: str = "0074"
down_revision: str | None = "0073"
branch_labels = None
depends_on = None

_TABLES = (
    "cms_campaign_targets",
    "cms_campaign_creatives",
    "cms_campaigns",
    "cms_advertisers",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cms_advertisers (
            id_advertiser   BIGSERIAL PRIMARY KEY,
            id_org          BIGINT NOT NULL REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            advertiser_name VARCHAR(255) NOT NULL,
            contact_name    VARCHAR(255),
            contact_email   VARCHAR(255),
            billing_info    JSONB NOT NULL DEFAULT '{}'::jsonb,
            notes           TEXT,
            is_active       BOOLEAN NOT NULL DEFAULT true,
            is_deleted      BOOLEAN NOT NULL DEFAULT false,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE cms_campaigns (
            id_campaign        BIGSERIAL PRIMARY KEY,
            id_org             BIGINT NOT NULL REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            id_advertiser      BIGINT NOT NULL REFERENCES cms_advertisers(id_advertiser),
            campaign_name      VARCHAR(255) NOT NULL,
            -- draft -> (pending_approval ->) approved -> live <-> paused -> completed | cancelled
            status             VARCHAR(20) NOT NULL DEFAULT 'draft',
            starts_on          DATE NOT NULL,
            ends_on            DATE NOT NULL,
            daily_hours        JSONB,                      -- {"start":"09:00","end":"20:00"} optionnel
            sov_percent        NUMERIC(5,2) NOT NULL DEFAULT 10.0,   -- part de voix vendue
            max_plays_per_hour INT,                        -- plafond optionnel de passages
            pricing_model      VARCHAR(10) NOT NULL DEFAULT 'sov',   -- sov | flat (cpm = indicatif)
            price_amount       NUMERIC(12,2),
            price_currency     VARCHAR(3) NOT NULL DEFAULT 'EUR',
            cpm_rate           NUMERIC(8,2),               -- indicatif v1 (1 passage = 1 impression)
            priority           INT NOT NULL DEFAULT 50,
            overbook_override  BOOLEAN NOT NULL DEFAULT false,   -- org-admin : forcer malgré > 100 %
            created_by         BIGINT REFERENCES cms_users(id_user),
            is_deleted         BOOLEAN NOT NULL DEFAULT false,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_campaign_dates CHECK (ends_on >= starts_on),
            CONSTRAINT ck_campaign_sov CHECK (sov_percent > 0 AND sov_percent <= 100)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE cms_campaign_creatives (
            id_creative  BIGSERIAL PRIMARY KEY,
            id_org       BIGINT NOT NULL REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            id_campaign  BIGINT NOT NULL REFERENCES cms_campaigns(id_campaign) ON DELETE CASCADE,
            id_media     BIGINT NOT NULL REFERENCES cms_media(id_media),
            duration_ms  INT,                     -- NULL = durée native du média
            weight       INT NOT NULL DEFAULT 1,  -- rotation pondérée entre créatifs
            sort_order   INT NOT NULL DEFAULT 0,
            status       VARCHAR(20) NOT NULL DEFAULT 'active',   -- active | archived
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE cms_campaign_targets (
            id_target   BIGSERIAL PRIMARY KEY,
            id_org      BIGINT NOT NULL REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            id_campaign BIGINT NOT NULL REFERENCES cms_campaigns(id_campaign) ON DELETE CASCADE,
            target_type VARCHAR(20) NOT NULL,     -- org | site | group | player | tags
            target_id   BIGINT,
            tag_expr    JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_advertisers_org ON cms_advertisers (id_org)")
    op.execute("CREATE INDEX idx_campaigns_org ON cms_campaigns (id_org)")
    op.execute("CREATE INDEX idx_campaigns_advertiser ON cms_campaigns (id_advertiser)")
    op.execute("CREATE INDEX idx_campaigns_window ON cms_campaigns (starts_on, ends_on)")
    op.execute("CREATE INDEX idx_campaign_creatives_campaign ON cms_campaign_creatives (id_campaign)")
    op.execute("CREATE INDEX idx_campaign_targets_campaign ON cms_campaign_targets (id_campaign)")
    for t in _TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {t}_org_isolation ON {t} "
            "USING (id_org = current_setting('app.current_org_id', true)::bigint)"
        )


def downgrade() -> None:
    for t in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {t}")
