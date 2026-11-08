"""Polices personnalisées par organisation (Générateur Promo §12.7)

Revision ID: 0061
Revises: 0060
Create Date: 2026-07-02 00:00:00.000000

- cms_org_fonts : 1 ligne par (id_org, family, weight). Le fichier woff2/ttf/otf est stocké
  dans MinIO (bucket média, préfixe `org-fonts/`) ; la table porte les métadonnées + la clé.
  TENANT-SCOPED (RLS id_org). `license_ack` = attestation utilisateur « j'ai le droit d'utiliser
  cette police » (responsabilité de l'org, cf. §12.7 — beaucoup d'EULA interdisent l'embarquement).

Grants : héritent des ALTER DEFAULT PRIVILEGES posés en 0044 (signflow_app/worker). Policy RLS =
pattern 0052 (USING = WITH CHECK implicite).

Cf. docs/PLAN_GENERATEUR_PROMO.md §12.7.
"""

from alembic import op

revision: str = "0061"
down_revision: str | None = "0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cms_org_fonts (
            id_font         BIGSERIAL PRIMARY KEY,
            id_org          BIGINT NOT NULL REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            family          VARCHAR(80) NOT NULL,      -- nom de famille CSS (ex. « Acme Sans »)
            weight          SMALLINT NOT NULL DEFAULT 400,
            storage_key     VARCHAR(400) NOT NULL,     -- clé MinIO (bucket média, org-fonts/…)
            font_format     VARCHAR(8) NOT NULL,       -- woff2 | woff | ttf | otf
            file_size_bytes INTEGER NOT NULL,
            license_ack     BOOLEAN NOT NULL DEFAULT false,
            created_by      BIGINT REFERENCES cms_users(id_user) ON DELETE SET NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (id_org, family, weight)
        )
        """
    )
    op.execute("CREATE INDEX idx_org_fonts_org ON cms_org_fonts (id_org)")
    op.execute("ALTER TABLE cms_org_fonts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cms_org_fonts FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY cms_org_fonts_org_isolation ON cms_org_fonts
            USING (id_org = current_setting('app.current_org_id', true)::bigint)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cms_org_fonts")
