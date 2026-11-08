"""Exclusion concurrentielle (retour Ed #10, option B — décision 2026-07-12)

Revision ID: 0087
Revises: 0086
Create Date: 2026-07-12 00:00:00.000000

Catégories d'industrie gérées par l'org (« Automobile », « Boissons »…) :
- `cms_industry_categories` : la liste (unicité du nom par org) ;
- `cms_advertisers.id_industry_category` : la catégorie de l'annonceur (SET NULL) ;
- `cms_site_excluded_categories` : catégories exclues par SITE (héritées players).

Enforcement applicatif dans `campaign_eligible_players` (même tuyau que l'opt-out
player, migr 0075) : les players d'un site qui exclut la catégorie de l'annonceur
sortent du ciblage / inventaire / dispo portail / devis / diffusion. RLS id_org
pattern 0074 sur les deux tables.
"""

from alembic import op

revision: str = "0087"
down_revision: str | None = "0086"
branch_labels = None
depends_on = None

_CAT = "cms_industry_categories"
_EXC = "cms_site_excluded_categories"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {_CAT} (
            id_category   BIGSERIAL PRIMARY KEY,
            id_org        BIGINT NOT NULL REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            category_name VARCHAR(100) NOT NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_industry_category_name UNIQUE (id_org, category_name)
        )
        """
    )
    op.execute(f"CREATE INDEX idx_industry_categories_org ON {_CAT} (id_org)")
    op.execute(
        f"""
        CREATE TABLE {_EXC} (
            id_site     BIGINT NOT NULL REFERENCES cms_sites(id_site) ON DELETE CASCADE,
            id_category BIGINT NOT NULL REFERENCES {_CAT}(id_category) ON DELETE CASCADE,
            id_org      BIGINT NOT NULL REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id_site, id_category)
        )
        """
    )
    op.execute(f"CREATE INDEX idx_site_excluded_categories_org ON {_EXC} (id_org)")
    op.execute(
        f"CREATE INDEX idx_site_excluded_categories_category ON {_EXC} (id_category)")
    for table in (_CAT, _EXC):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_org_isolation ON {table} "
            "USING (id_org = current_setting('app.current_org_id', true)::bigint)"
        )
    op.execute(
        "ALTER TABLE cms_advertisers ADD COLUMN id_industry_category BIGINT "
        f"REFERENCES {_CAT}(id_category) ON DELETE SET NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cms_advertisers DROP COLUMN IF EXISTS id_industry_category")
    op.execute(f"DROP TABLE IF EXISTS {_EXC}")
    op.execute(f"DROP TABLE IF EXISTS {_CAT}")
