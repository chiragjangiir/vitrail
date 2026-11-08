"""Annonceur multi-catégories d'industrie (retour Ed 2026-07-12 #8)

Revision ID: 0088
Revises: 0087
Create Date: 2026-07-12 12:00:00.000000

Une agence de pub porte PLUSIEURS industries : la colonne 1-1
`cms_advertisers.id_industry_category` (0087, déployée le matin même) devient la
table de jonction `cms_advertiser_industry_categories`. Les valeurs existantes
sont migrées puis la colonne est supprimée. RLS id_org pattern 0074.
"""

from alembic import op

revision: str = "0088"
down_revision: str | None = "0087"
branch_labels = None
depends_on = None

_T = "cms_advertiser_industry_categories"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {_T} (
            id_advertiser BIGINT NOT NULL
                REFERENCES cms_advertisers(id_advertiser) ON DELETE CASCADE,
            id_category   BIGINT NOT NULL
                REFERENCES cms_industry_categories(id_category) ON DELETE CASCADE,
            id_org        BIGINT NOT NULL
                REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id_advertiser, id_category)
        )
        """
    )
    op.execute(f"CREATE INDEX idx_adv_industry_categories_org ON {_T} (id_org)")
    op.execute(f"CREATE INDEX idx_adv_industry_categories_category ON {_T} (id_category)")
    op.execute(f"ALTER TABLE {_T} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_T} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {_T}_org_isolation ON {_T} "
        "USING (id_org = current_setting('app.current_org_id', true)::bigint)"
    )
    op.execute(
        f"""
        INSERT INTO {_T} (id_advertiser, id_category, id_org)
        SELECT id_advertiser, id_industry_category, id_org
        FROM cms_advertisers
        WHERE id_industry_category IS NOT NULL
        """
    )
    op.execute("ALTER TABLE cms_advertisers DROP COLUMN id_industry_category")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE cms_advertisers ADD COLUMN id_industry_category BIGINT "
        "REFERENCES cms_industry_categories(id_category) ON DELETE SET NULL"
    )
    op.execute(
        f"""
        UPDATE cms_advertisers a SET id_industry_category = j.id_category
        FROM (SELECT DISTINCT ON (id_advertiser) id_advertiser, id_category
              FROM {_T} ORDER BY id_advertiser, id_category) j
        WHERE j.id_advertiser = a.id_advertiser
        """
    )
    op.execute(f"DROP TABLE IF EXISTS {_T}")
