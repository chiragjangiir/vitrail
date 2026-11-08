"""Listes de sites enregistrables par annonceur (portail — retour Ed #11)

Revision ID: 0085
Revises: 0084
Create Date: 2026-07-11 00:00:00.000000

L'annonceur du portail self-service enregistre SA sélection de sites sous un nom
(« Mes concessions Île-de-France ») et la rappelle à la prochaine campagne.
`site_ids` = JSONB (tableau d'ids — pas de table membre : liste privée, jamais
résolue par le targeting, purement UI). Unicité du nom PAR annonceur. RLS id_org
pattern 0074 ; le scope PAR annonceur est applicatif (endpoints /portal, comme
les campagnes B1).
"""

from alembic import op

revision: str = "0085"
down_revision: str | None = "0084"
branch_labels = None
depends_on = None

_T = "cms_advertiser_site_lists"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {_T} (
            id_list       BIGSERIAL PRIMARY KEY,
            id_org        BIGINT NOT NULL REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            id_advertiser BIGINT NOT NULL REFERENCES cms_advertisers(id_advertiser) ON DELETE CASCADE,
            list_name     VARCHAR(255) NOT NULL,
            site_ids      JSONB NOT NULL DEFAULT '[]',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_adv_site_list_name UNIQUE (id_advertiser, list_name)
        )
        """
    )
    op.execute(f"CREATE INDEX idx_adv_site_lists_advertiser ON {_T} (id_advertiser)")
    op.execute(f"ALTER TABLE {_T} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_T} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {_T}_org_isolation ON {_T} "
        "USING (id_org = current_setting('app.current_org_id', true)::bigint)"
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {_T}")
