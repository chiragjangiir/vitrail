"""Chartes de marque (brand kits) — P3.4

Revision ID: 0128
Revises: 0127
Create Date: 2026-08-08 00:00:00.000000

- cms_brand_kits : couleurs, police, nom de marque, logo, mentions légales et ton d'une marque,
  déclarés UNE fois puis pré-remplis partout (générateur promo §12, assistant de prompt).

  **Deux rattachements possibles, jamais les deux** : `id_advertiser IS NULL` = la charte de
  l'ORGANISATION (le retailer) ; `id_advertiser` renseigné = la charte d'un ANNONCEUR. Un visuel
  fait pour un annonceur prend la sienne, sinon celle de l'org — Brightwell n'a pas les couleurs du
  magasin. Au plus UNE charte de chaque côté : deux index UNIQUE partiels le garantissent
  (l'unicité vit dans la base, pas dans une garde applicative qu'un second chemin d'écriture
  contournerait).

  Les couleurs sont contraintes au format hexadécimal **par la base** : elles finissent en CSS
  inline dans la page rendue par Chromium, une valeur arbitraire pourrait sortir de son contexte.
  Le service les re-valide au rendu — la contrainte SQL est la ceinture, pas la seule garde.

  `id_logo_media` en ON DELETE SET NULL : supprimer le média du logo ne doit pas retenir la
  suppression ni faire disparaître la charte — elle survit sans logo.

Déploiement NEUTRE : aucune charte n'existe au départ ⇒ le rendu promo est strictement inchangé
tant qu'une organisation n'en crée pas une.

Grants : héritent des ALTER DEFAULT PRIVILEGES posés en 0044. Policy RLS = pattern 0052/0061,
avec FORCE (une politique ne s'applique pas au propriétaire sans lui — cf. migr 0119).

Cf. docs/PLAN_DEV_2026-08.md §P3.4.
"""

from alembic import op

revision: str = "0128"
down_revision: str | None = "0127"
branch_labels = None
depends_on = None

# Couleurs : #rgb, #rrggbb ou #rrggbbaa. NULL = « la charte ne dit rien » ⇒ le thème du template
# garde sa valeur (une charte ne remplace QUE ce qu'elle déclare).
_HEX = "~ '^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$'"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE cms_brand_kits (
            id_brand_kit    BIGSERIAL PRIMARY KEY,
            id_org          BIGINT NOT NULL REFERENCES cms_organizations(id_org) ON DELETE CASCADE,
            -- NULL = charte de l'organisation ; renseigné = charte de cet annonceur.
            id_advertiser   BIGINT REFERENCES cms_advertisers(id_advertiser) ON DELETE CASCADE,
            kit_name        VARCHAR(120) NOT NULL,
            -- Couleurs (toutes facultatives) : reprises telles quelles par le thème du template.
            accent          VARCHAR(9) CONSTRAINT ck_cms_brand_kits_accent    CHECK (accent    IS NULL OR accent    {_HEX}),
            ink             VARCHAR(9) CONSTRAINT ck_cms_brand_kits_ink       CHECK (ink       IS NULL OR ink       {_HEX}),
            paper           VARCHAR(9) CONSTRAINT ck_cms_brand_kits_paper     CHECK (paper     IS NULL OR paper     {_HEX}),
            badge_bg        VARCHAR(9) CONSTRAINT ck_cms_brand_kits_badge_bg  CHECK (badge_bg  IS NULL OR badge_bg  {_HEX}),
            badge_ink       VARCHAR(9) CONSTRAINT ck_cms_brand_kits_badge_ink CHECK (badge_ink IS NULL OR badge_ink {_HEX}),
            -- Nom de FAMILLE de police (built-in ou custom org) — re-vérifié au catalogue à l'écriture.
            font_family     VARCHAR(80),
            -- Identité posée par le COMPOSITING, jamais par le modèle génératif.
            brand_name      VARCHAR(160),
            id_logo_media   BIGINT REFERENCES cms_media(id_media) ON DELETE SET NULL,
            legal_mentions  TEXT,
            -- Ton de marque : entre dans le prompt comme ATMOSPHÈRE à viser.
            tone            VARCHAR(400),
            created_by      BIGINT REFERENCES cms_users(id_user) ON DELETE SET NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    # Au plus UNE charte d'organisation, et au plus UNE par annonceur.
    op.execute(
        "CREATE UNIQUE INDEX uq_brand_kits_org ON cms_brand_kits (id_org) "
        "WHERE id_advertiser IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_brand_kits_advertiser ON cms_brand_kits (id_advertiser) "
        "WHERE id_advertiser IS NOT NULL"
    )
    op.execute("CREATE INDEX idx_brand_kits_org ON cms_brand_kits (id_org)")
    op.execute("ALTER TABLE cms_brand_kits ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cms_brand_kits FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY cms_brand_kits_org_isolation ON cms_brand_kits
            USING (id_org = current_setting('app.current_org_id', true)::bigint)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cms_brand_kits")
