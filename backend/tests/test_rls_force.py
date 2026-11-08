"""
Filet RLS (chantier 2026-07-30, feu vert Ed) — le filet est enfin TESTÉ.

Aucun test de la suite ne se connectait avec un rôle soumis à la RLS : la base de test est
bâtie par `create_all` (sans migrations, donc sans politiques) et le rôle de test est
superuser — la RLS y est invisible par construction. Ces tests créent un rôle SONDE
(non-propriétaire, non-superuser), posent ENABLE + FORCE + la politique **depuis la
définition de la migration 0119** (patron « le test lit la migration », comme _PERMS en
0111 — une copie locale de la politique finirait par diverger de ce qui est déployé), puis
prouvent, table par table, que :

  · avec `app.current_org_id` = org A, la sonde ne voit QUE les lignes d'org A ;
  · avec le GUC absent, elle ne voit RIEN (politique à NULL — le mode de défaillance sûr) ;

Décision d'Ed (30/07) : un super-admin ne lit PAS le journal des autres organisations —
`cms_audit_log` reçoit la politique standard, sans exception. Les lectures cross-org
légitimes de la console passent par `get_db_worker` (BYPASSRLS explicite), jamais par la
session applicative.
"""

import importlib.util
import uuid
from datetime import date
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401 — enregistre tous les modèles dans Base.metadata
from app.db.base import Base
from app.db.session import assert_app_url_is_isolated


def _load_migration_0119():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0119_force_rls.py"
    spec = importlib.util.spec_from_file_location("migr_0119", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_MIGR = _load_migration_0119()

EXPECTED_TABLES = {
    "cms_assistant_sessions", "cms_assistant_stats", "cms_audio_baskets", "cms_audit_log",
    "cms_datafeeds", "cms_event_ai_suggestions", "cms_events", "cms_feedback",
    "cms_generation_campaigns", "cms_generation_jobs", "cms_governance_nodes",
    "cms_local_control_profiles", "cms_media_folders", "cms_playlists", "cms_pop_archives",
    "cms_schedules", "cms_tag_namespaces", "cms_templates", "cms_vod_configs",
}


def test_migration_list_is_the_measured_19():
    """Anti-dérive : la liste DE LA MIGRATION est celle mesurée le 29/07 — ni plus ni
    moins. Une table retirée là-bas serait retirée du filet sans qu'aucun test rougisse."""
    assert set(_MIGR.FORCED_TABLES) == EXPECTED_TABLES
    assert len(_MIGR.FORCED_TABLES) == 19
    # Chaque table du filet existe au métadata et porte bien la colonne de la politique.
    for t in _MIGR.FORCED_TABLES:
        tab = Base.metadata.tables.get(t)
        assert tab is not None, f"{t} absente du metadata"
        assert "id_org" in tab.columns, f"{t} sans colonne id_org"


def test_app_url_guard_refuses_superuser_fallback():
    """La garde de `session.py` : une URL applicative qui dégénère en URL SUPERUSER
    (repli `.replace` inopérant sur un mot de passe généré = le trou des installs client)
    doit refuser de démarrer, en nommant le geste qui répare."""
    with pytest.raises(RuntimeError, match="DATABASE_APP_URL"):
        assert_app_url_is_isolated(
            "postgresql+asyncpg://signflow:generated@db/signflow",
            "postgresql+asyncpg://signflow:generated@db/signflow",
        )
    # URL réellement dérivée (ou explicite) → passe.
    assert_app_url_is_isolated(
        "postgresql+asyncpg://signflow_app:x@db/signflow",
        "postgresql+asyncpg://signflow:y@db/signflow",
    )


# ── Le filet lui-même, table par table ─────────────────────────────────────────────

PROBE_ROLE = "rls_probe"
PROBE_PASSWORD = "rls_probe_pw"


def _row_values(table: str, id_org: int, ctx: dict) -> dict:
    """Ligne MINIMALE valide par table (colonnes non-nullables sans défaut, mesurées au
    metadata). Les parents requis (user, player) sont dans `ctx`, par organisation."""
    u = uuid.uuid4().hex[:10]
    base = {
        "cms_assistant_sessions": {"id_user": ctx["user"][id_org]},
        "cms_assistant_stats": {},
        "cms_audio_baskets": {"basket_name": f"b-{u}", "basket_type": "music"},
        "cms_audit_log": {"action": "probe", "resource_type": "probe"},
        "cms_datafeeds": {"feed_name": f"f-{u}", "feed_type": "rss"},
        "cms_event_ai_suggestions": {
            "trigger_summary": "t", "suggested_config": {}, "confidence": 0.5},
        "cms_events": {
            "event_name": f"e-{u}", "event_type": "manual",
            "target_config": {"target_type": "org", "target_ids": []}},
        "cms_feedback": {
            "id_user": ctx["user"][id_org], "feedback_type": "bug", "description": "t"},
        "cms_generation_campaigns": {"brief": "t", "model": "m"},
        "cms_generation_jobs": {
            "kind": "image", "provider": "fal", "model": "m", "prompt": "t"},
        "cms_governance_nodes": {"node_name": f"n-{u}"},
        "cms_local_control_profiles": {
            "id_player": ctx["player"][id_org], "token": uuid.uuid4().hex},
        "cms_media_folders": {"folder_name": f"d-{u}"},
        "cms_playlists": {"playlist_name": f"p-{u}"},
        "cms_pop_archives": {
            "period_start": date(2026, 1, 1), "period_end": date(2026, 1, 31),
            "csv_key": f"k/{u}"},
        "cms_schedules": {"schedule_name": f"s-{u}"},
        "cms_tag_namespaces": {"namespace_key": f"ns{u[:6]}"},
        "cms_templates": {"template_name": f"t-{u}"},
        "cms_vod_configs": {"vod_name": f"v-{u}"},
    }[table]
    return {"id_org": id_org, **base}


@pytest_asyncio.fixture
async def rls_scene(engine, db_session):
    """2 orgs (+ user + player chacune) · rôle sonde · ENABLE+FORCE+politique sur les 19
    tables, posés depuis la MIGRATION. Le tout via l'engine superuser du conftest — la
    RLS ne s'applique pas à lui, il peut donc semer les deux organisations."""
    from app.models.organization import CmsOrganization
    from app.models.player import CmsPlayer
    from app.models.user import CmsUser

    ctx: dict = {"user": {}, "player": {}, "org": []}
    for tag in ("a", "b"):
        org = CmsOrganization(org_name=f"RLS-{tag}", org_slug=f"rls-{tag}-{uuid.uuid4().hex[:8]}")
        db_session.add(org)
        await db_session.flush()
        user = CmsUser(id_org=org.id_org, email=f"rls-{tag}-{uuid.uuid4().hex[:8]}@t.co",
                       password_hash="x", is_active=True)
        player = CmsPlayer(id_org=org.id_org, player_name=f"rls-{tag}", player_os="linux")
        db_session.add_all([user, player])
        await db_session.flush()
        ctx["org"].append(org.id_org)
        ctx["user"][org.id_org] = user.id_user
        ctx["player"][org.id_org] = player.id_player
    await db_session.commit()

    async with engine.begin() as conn:
        # Rôle sonde : LOGIN, ni superuser ni BYPASSRLS. On le rend PROPRIÉTAIRE des 19
        # tables : c'est la sémantique que la migration ajoute (`FORCE` soumet le
        # propriétaire), et c'est le seul moyen de la prouver — un non-propriétaire est
        # déjà soumis dès ENABLE, un superuser ne l'est jamais.
        await conn.exec_driver_sql(f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{PROBE_ROLE}') THEN
                    CREATE ROLE {PROBE_ROLE} LOGIN PASSWORD '{PROBE_PASSWORD}'
                        NOSUPERUSER NOBYPASSRLS;
                END IF;
            END $$
        """)
        await conn.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {PROBE_ROLE}")
        for t in _MIGR.FORCED_TABLES:
            await conn.exec_driver_sql(f"ALTER TABLE {t} OWNER TO {PROBE_ROLE}")
            await conn.exec_driver_sql(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
            await conn.exec_driver_sql(f"DROP POLICY IF EXISTS {t}_org_isolation ON {t}")
            await conn.exec_driver_sql(_MIGR.org_isolation_policy_sql(t))
    return ctx


@pytest.mark.asyncio
@pytest.mark.parametrize("table", sorted(EXPECTED_TABLES))
async def test_rls_net_isolates_each_table(table, rls_scene, db_session, engine):
    ctx = rls_scene
    org_a, org_b = ctx["org"]

    # Semis en superuser (hors RLS) : une ligne par organisation.
    tab = Base.metadata.tables[table]
    await db_session.execute(tab.insert().values(**_row_values(table, org_a, ctx)))
    await db_session.execute(tab.insert().values(**_row_values(table, org_b, ctx)))
    await db_session.commit()

    # ⚠️ `str(url)` MASQUE le mot de passe en `***` — render_as_string obligatoire.
    probe_url = engine.url.set(
        username=PROBE_ROLE, password=PROBE_PASSWORD
    ).render_as_string(hide_password=False)
    # NullPool : chaque `connect()` = connexion VIERGE. Sur une connexion réutilisée, un
    # GUC custom posé par SET LOCAL retombe à '' (pas NULL) après la transaction — la
    # politique lève alors `""::bigint` (erreur = fermé, mais ce n'est pas le scénario
    # « jamais posé » qu'on veut prouver ici).
    probe = create_async_engine(probe_url, echo=False, poolclass=NullPool)

    async def _counts(conn) -> tuple[int, int]:
        both = (await conn.execute(text(
            f"SELECT count(*) FROM {table} WHERE id_org IN (:a, :b)"
        ), {"a": org_a, "b": org_b})).scalar_one()
        cross = (await conn.execute(text(
            f"SELECT count(*) FROM {table} WHERE id_org = :b"), {"b": org_b}
        )).scalar_one()
        return both, cross

    try:
        # ── ROUGE DÉMONTRÉ : sans FORCE, le PROPRIÉTAIRE traverse la politique ────────
        # C'est la prémisse du chantier, exécutée plutôt qu'affirmée : ENABLE + politique
        # ne protègent pas le propriétaire — il voit les DEUX organisations.
        async with engine.begin() as su:
            await su.exec_driver_sql(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        async with probe.connect() as conn:
            await conn.execute(text(f"SET LOCAL app.current_org_id = '{org_a}'"))
            both, cross = await _counts(conn)
            assert both == 2 and cross == 1, (
                f"{table} : le propriétaire sans FORCE devrait tout voir "
                "(sinon ce test ne prouve rien)"
            )

        # ── VERT : le FORCE de la migration ferme la porte, même au propriétaire ──────
        async with engine.begin() as su:
            await su.exec_driver_sql(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        async with probe.connect() as conn:
            await conn.execute(text(f"SET LOCAL app.current_org_id = '{org_a}'"))
            both, cross = await _counts(conn)
            assert both == 1, f"{table} : org A doit voir SA ligne (vu {both})"
            assert cross == 0, f"{table} : la ligne d'org B est VISIBLE cross-org"
        async with probe.connect() as conn:
            # GUC absent → politique à NULL → rien. Le mode de défaillance est FERMÉ :
            # un chemin qui oublierait de poser le contexte ne fuit pas, il voit vide.
            both, _ = await _counts(conn)
            assert both == 0, f"{table} : visible SANS contexte d'organisation"
    finally:
        await probe.dispose()
