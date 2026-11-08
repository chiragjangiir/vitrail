"""FORCE ROW LEVEL SECURITY sur les 19 tables tenant qui ne l'avaient pas (2026-07-30).

Chantier « filet RLS » (feu vert d'Ed le 29/07, décision audit_log le 30/07 : un
super-admin ne lit PAS le journal des autres organisations — les lectures cross-org
légitimes de la console passent déjà par `get_db_worker`, BYPASSRLS explicite).

CE QUE CETTE MIGRATION CHANGE — ET NE CHANGE PAS. La mesure du 30/07 a corrigé la
prémisse du 29/07 : l'API se connecte en `signflow_app` (ni propriétaire ni superuser),
donc la RLS s'applique à elle dès `ENABLE` — le filet était DÉJÀ tendu en production sur
ces 19 tables. `FORCE` est une défense en profondeur : il soumet aussi le PROPRIÉTAIRE
des tables aux politiques. Aujourd'hui ce propriétaire (`signflow`) est superuser — que
FORCE n'atteint pas — mais le jour où une installation tourne sur un Postgres managé
(RDS…) où le propriétaire N'EST PAS superuser, ces 19 tables seraient les seules sans
filet. Et l'uniformité a sa valeur propre : « toute table tenant est forcée » se vérifie
d'une requête, « sauf 19 » ne se vérifie qu'avec la liste sous les yeux.

Le VRAI trou trouvé par ce chantier est ailleurs et corrigé à part : le compose CLIENT ne
définissait pas `DATABASE_APP_URL`, le repli en code ne matchait pas un mot de passe
généré, et le backend d'une install client tournait en SUPERUSER — toute la RLS inerte,
les 40 tables déjà forcées comprises. Cf. `app/db/session.py::assert_app_url_is_isolated`.

`FORCED_TABLES` est lu par `tests/test_rls_force.py` (patron « le test lit la migration »,
comme _PERMS en 0111) : la liste ne peut pas dériver de ce que les tests prouvent.

Revision ID: 0119
Revises: 0118
"""

from alembic import op

revision: str = "0119"
down_revision: str | None = "0118"
branch_labels = None
depends_on = None

# Les 19 tables tenant (porteuses de `id_org`, politique *_org* déjà en place) qui
# étaient restées en ENABLE sans FORCE. Mesuré le 29/07 sur la production :
# SELECT relname FROM pg_class WHERE relrowsecurity AND NOT relforcerowsecurity.
FORCED_TABLES = [
    "cms_assistant_sessions",
    "cms_assistant_stats",
    "cms_audio_baskets",
    "cms_audit_log",
    "cms_datafeeds",
    "cms_event_ai_suggestions",
    "cms_events",
    "cms_feedback",
    "cms_generation_campaigns",
    "cms_generation_jobs",
    "cms_governance_nodes",
    "cms_local_control_profiles",
    "cms_media_folders",
    "cms_playlists",
    "cms_pop_archives",
    "cms_schedules",
    "cms_tag_namespaces",
    "cms_templates",
    "cms_vod_configs",
]

# La politique standard du produit (mêmes qual/portée que 0004/0019/0044). Les vraies
# bases l'ont déjà — mais la base de TEST est bâtie par create_all, sans migrations :
# le test RLS pose ENABLE + FORCE + cette politique depuis CETTE définition, pour
# prouver la sémantique réellement déployée et non une copie qui divergerait.
def org_isolation_policy_sql(table: str) -> str:
    return (
        f"CREATE POLICY {table}_org_isolation ON {table} "
        "USING (id_org = current_setting('app.current_org_id', true)::bigint)"
    )


def upgrade() -> None:
    for t in FORCED_TABLES:
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    for t in FORCED_TABLES:
        op.execute(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY")
