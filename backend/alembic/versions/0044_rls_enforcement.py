"""RLS enforcement — active réellement l'isolation multi-tenant

Revision ID: 0044
Revises: 0043
Create Date: 2026-06-19 00:00:00.000000

Jusqu'ici la RLS était INERTE au runtime : l'app se connectait en `signflow`
(superuser → bypasse toute RLS). Les policies (migrations 0002→0020) étaient
décoratives, et l'isolation tenant reposait uniquement sur le filtrage `id_org`
applicatif des endpoints (incomplet — ex. `list_users` n'en avait pas).

Cette migration prépare la bascule de l'app sur le rôle `signflow_app`
(non-superuser, SOUMIS à la RLS — cf. `app/db/session.py` + `config.db_app_url`) :

  1. GRANT rétroactif à signflow_app / signflow_worker sur TOUTES les tables &
     séquences existantes — les tables créées après 0020 (feeds, vod, folders,
     gouvernance, tags) n'avaient AUCUN grant pour signflow_app.
  2. ALTER DEFAULT PRIVILEGES (rôle courant = `signflow`, propriétaire des tables
     créées par les migrations) → les FUTURES tables/séquences sont auto-grantées,
     on ne reproduit plus jamais ce trou.
  3. ENABLE ROW LEVEL SECURITY + policy `*_org_isolation` sur les 8 tables tenant
     (porteuses de `id_org`) ajoutées après 0020 et restées sans policy.

Les tables ENFANT (sans `id_org` : feed_items, vod_config_*, media_renditions,
tag_values, governance_assignments, …) suivent le précédent du repo (ex.
`cms_playlist_items` en 0004) : PAS de RLS — l'isolation passe par la FK vers le
parent org-scoped + les requêtes endpoints toujours filtrées par le parent.

Pattern policy identique à 0004/0019 : `USING (id_org = current_setting(...))`.
Note PostgreSQL : une policy USING sans WITH CHECK utilise l'expression USING
comme WITH CHECK pour INSERT/UPDATE → les insertions cross-org sont aussi bloquées.
"""

from alembic import op

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels = None
depends_on = None


# Tables tenant (porteuses de id_org) créées après 0020 et restées sans policy RLS.
# Les autres tables de ces migrations sont des tables ENFANT/jonction (clé = id_node /
# id_tag / id_item / id_vod / id_datafeed / id_parent…) sans id_org → pas de RLS,
# isolation via la FK au parent org-scoped (précédent cms_playlist_items, 0004).
TENANT_TABLES = [
    "cms_governance_nodes",  # 0025
    "cms_tag_namespaces",    # 0026
    "cms_media_folders",     # 0030
    "cms_vod_configs",       # 0041
    "cms_datafeeds",         # 0042
]


def upgrade() -> None:
    # ── 1+2. Grants rétroactifs + default privileges (futures tables) ───────────
    for role in ("signflow_app", "signflow_worker"):
        op.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
        op.execute(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {role}")
        op.execute(f"GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO {role}")
        # Le rôle courant (signflow) est propriétaire des tables créées par les
        # migrations → ses futures créations seront auto-grantées à ce rôle.
        op.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {role}"
        )
        op.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO {role}"
        )

    # ── 3. RLS + policy d'isolation sur les tables tenant post-0020 ─────────────
    for t in TENANT_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {t}_org_isolation ON {t}
                USING (id_org = current_setting('app.current_org_id', true)::bigint)
            """
        )


def downgrade() -> None:
    for t in reversed(TENANT_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {t}_org_isolation ON {t}")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")
    # Les GRANT et ALTER DEFAULT PRIVILEGES ne sont volontairement PAS révoqués :
    # les révoquer couperait l'accès de l'app si elle tourne déjà en signflow_app.
