"""Groupes de SITES — cible « région » pour campagnes ET programmation (S6 Retail Media)

Revision ID: 0079
Revises: 0078
Create Date: 2026-07-10 00:00:00.000000

Miroir des groupes de players au niveau SITE (cadrage EVOLUTIONS 2026-07-09) :
`cms_site_groups` + `cms_site_group_members` (n-n — un site peut appartenir à plusieurs
groupes : région + enseigne + typologie). Nouveau `target_type='site_group'` dans le
contrat canonique (services/targeting.py) → campagnes, schedules, events, hdmi-check
en profitent d'un coup. Avantage vs groupes de players : un nouveau player posé dans un
site du groupe est adressé automatiquement.
TENANT-SCOPED (RLS id_org sur les 2 tables, pattern 0074). Grants auto-hérités de 0044.
"""

from alembic import op

revision: str = "0079"
down_revision: str | None = "0078"
branch_labels = None
depends_on = None

_TABLES = (
    "cms_site_group_members",
    "cms_site_groups",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cms_site_groups (
            id_site_group BIGSERIAL PRIMARY KEY,
            id_org        BIGINT NOT NULL REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            group_name    VARCHAR(255) NOT NULL,
            description   TEXT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_site_group_name_per_org UNIQUE (id_org, group_name)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE cms_site_group_members (
            id_site_group BIGINT NOT NULL REFERENCES cms_site_groups(id_site_group) ON DELETE CASCADE,
            id_site       BIGINT NOT NULL REFERENCES cms_sites(id_site) ON DELETE CASCADE,
            id_org        BIGINT NOT NULL REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id_site_group, id_site)
        )
        """
    )
    op.execute("CREATE INDEX idx_site_groups_org ON cms_site_groups (id_org)")
    op.execute("CREATE INDEX idx_site_group_members_site ON cms_site_group_members (id_site)")
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
