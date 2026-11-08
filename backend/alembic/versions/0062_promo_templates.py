"""Modèles promo réutilisables (Générateur Promo Phase C, §12.5)

Revision ID: 0062
Revises: 0061
Create Date: 2026-07-02 00:00:00.000000

- cms_promo_templates : instantané nommé de l'état de l'éditeur promo (template built-in choisi,
  format/résolution, textes + style_overrides + calques, fond/produit). L'utilisateur le recharge
  et l'ajuste. `config` JSONB = le snapshot (re-sanitisé/validé au rendu → stockage brut sûr).
  TENANT-SCOPED (RLS id_org).

Grants héritent des ALTER DEFAULT PRIVILEGES posés en 0044. Policy RLS = pattern 0052/0061.

Cf. docs/PLAN_GENERATEUR_PROMO.md §12.5.
"""

from alembic import op

revision: str = "0062"
down_revision: str | None = "0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cms_promo_templates (
            id_promo_template BIGSERIAL PRIMARY KEY,
            id_org            BIGINT NOT NULL
                              REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            name              VARCHAR(120) NOT NULL,
            config            JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_by        BIGINT REFERENCES cms_users(id_user) ON DELETE SET NULL,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_promo_templates_org ON cms_promo_templates (id_org)")
    op.execute("ALTER TABLE cms_promo_templates ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cms_promo_templates FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY cms_promo_templates_org_isolation ON cms_promo_templates
            USING (id_org = current_setting('app.current_org_id', true)::bigint)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cms_promo_templates")
