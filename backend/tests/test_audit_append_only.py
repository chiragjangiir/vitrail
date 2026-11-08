"""Le journal d'audit est en AJOUT SEUL — pour de vrai (P1.2, migration 0121).

Pourquoi ces tests ne peuvent pas être écrits « normalement » : la base de test est
bâtie par `create_all`, **sans migrations**, et le rôle de test est le propriétaire
superuser. Un test naïf (« l'API ne modifie pas le journal ») serait donc **vacant** :
il passerait avec ou sans la migration. On reprend le patron de `test_rls_force.py` —
un rôle SONDE réel, non-propriétaire, non-superuser, à qui l'on donne d'abord les
droits que la **0044** a réellement laissés en production (`ALL`), puis à qui l'on
applique le `REVOKE` **lu dans la migration**.

Ce que la suite prouve, dans l'ordre où ça compte :

  1. le ROUGE, exécuté et non affirmé : avec les droits d'aujourd'hui, la sonde
     réécrit et efface le journal ;
  2. le VERT : après le REVOKE, écrire et lire restent possibles, modifier et
     effacer ne le sont plus ;
  3. qu'on n'a rien cassé au passage : supprimer un compte référencé par une ligne
     de journal marche toujours (les déclencheurs d'intégrité tournent avec les
     droits du propriétaire de la table, pas ceux de l'appelant — affirmation
     vérifiable, donc vérifiée) ;
  4. qu'une future migration ne pourra pas rouvrir la porte en silence, comme la
     0044 l'a fait sans le voir.
"""

import importlib.util
import re
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401 — enregistre tous les modèles dans Base.metadata

VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _load_migration_0121():
    path = VERSIONS_DIR / "0121_audit_log_append_only.py"
    spec = importlib.util.spec_from_file_location("migr_0121", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_MIGR = _load_migration_0121()

PROBE_ROLE = "audit_probe"
PROBE_PASSWORD = "audit_probe_pw"
SEQUENCE = "cms_audit_log_id_audit_seq"

# Code SQLSTATE de « permission denied ». On l'assied sur le code, pas sur le
# message : celui-ci est traduit selon la locale du serveur PostgreSQL.
INSUFFICIENT_PRIVILEGE = "42501"


def _is_permission_denied(exc: DBAPIError) -> bool:
    return getattr(exc.orig, "sqlstate", None) == INSUFFICIENT_PRIVILEGE


@pytest_asyncio.fixture
async def audit_probe(engine, db_session):
    """Une organisation + un compte + une ligne de journal qui les référence, et un
    rôle sonde doté des droits que la 0044 a laissés en production (`ALL`).

    On neutralise la RLS sur `cms_audit_log` pour la durée du test : elle est
    orthogonale au sujet (privilèges), et `test_rls_force.py` la (re)pose lui-même
    dans sa propre fixture — il peut donc l'avoir laissée active et forcée si son
    module s'est exécuté avant celui-ci.
    """
    from app.models.audit_log import CmsAuditLog
    from app.models.organization import CmsOrganization
    from app.models.user import CmsUser

    tag = uuid.uuid4().hex[:8]
    org = CmsOrganization(org_name=f"Audit-{tag}", org_slug=f"audit-{tag}")
    db_session.add(org)
    await db_session.flush()
    user = CmsUser(id_org=org.id_org, email=f"audit-{tag}@t.co", password_hash="x", is_active=True)
    db_session.add(user)
    await db_session.flush()
    row = CmsAuditLog(
        id_org=org.id_org, id_user=user.id_user, action="probe", resource_type="probe"
    )
    db_session.add(row)
    await db_session.commit()

    async with engine.begin() as conn:
        await conn.exec_driver_sql(f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{PROBE_ROLE}') THEN
                    CREATE ROLE {PROBE_ROLE} LOGIN PASSWORD '{PROBE_PASSWORD}'
                        NOSUPERUSER NOBYPASSRLS;
                END IF;
            END $$
        """)
        await conn.exec_driver_sql("ALTER TABLE cms_audit_log NO FORCE ROW LEVEL SECURITY")
        await conn.exec_driver_sql("ALTER TABLE cms_audit_log DISABLE ROW LEVEL SECURITY")
        await conn.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {PROBE_ROLE}")
        # L'état RÉEL d'aujourd'hui, mesuré en prod le 05/08 : ALL sur la table.
        await conn.exec_driver_sql(f"GRANT ALL ON cms_audit_log TO {PROBE_ROLE}")
        await conn.exec_driver_sql(f"GRANT USAGE, SELECT ON SEQUENCE {SEQUENCE} TO {PROBE_ROLE}")
        # Nécessaires au seul test d'intégrité référentielle (③).
        await conn.exec_driver_sql(f"GRANT SELECT, DELETE ON cms_users TO {PROBE_ROLE}")

    probe_url = engine.url.set(
        username=PROBE_ROLE, password=PROBE_PASSWORD
    ).render_as_string(hide_password=False)
    probe = create_async_engine(probe_url, echo=False, poolclass=NullPool)
    try:
        yield {
            "engine": probe,
            # ⚠️ Un rôle ne peut pas se révoquer un droit qu'il n'a pas lui-même
            # accordé : PostgreSQL avale la commande sans rien faire ET SANS
            # ERREUR. La migration tourne sous le propriétaire — le test doit
            # donc fermer la porte par le même chemin, sous peine de mesurer un
            # REVOKE qui n'a jamais eu lieu (piège vécu en écrivant ce fichier).
            "owner": engine,
            "id_org": org.id_org,
            "id_user": user.id_user,
            "id_audit": row.id_audit,
        }
    finally:
        await probe.dispose()
        async with engine.begin() as conn:
            await conn.exec_driver_sql(f"REVOKE ALL ON cms_users FROM {PROBE_ROLE}")
            await conn.exec_driver_sql(f"GRANT ALL ON cms_audit_log TO {PROBE_ROLE}")


async def _apply_revoke(scene) -> None:
    """Ferme la porte en rejouant EXACTEMENT le SQL de la migration, par le chemin
    par lequel elle passe réellement : le propriétaire des tables."""
    async with scene["owner"].begin() as conn:
        await conn.exec_driver_sql(_MIGR.revoke_sql(PROBE_ROLE))


# ── ① Le rouge, exécuté ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_before_the_revoke_the_app_role_can_rewrite_history(audit_probe):
    """La prémisse du chantier, prouvée plutôt que citée : avec les droits que la
    0044 a laissés, le rôle qui sert toutes les requêtes de l'API réécrit et efface
    le journal. Si ce test devient rouge, c'est que le scénario n'existe plus — et
    les suivants ne prouveraient plus rien."""
    async with audit_probe["engine"].begin() as conn:
        await conn.execute(
            text("UPDATE cms_audit_log SET action = 'rewritten' WHERE id_audit = :i"),
            {"i": audit_probe["id_audit"]},
        )
        deleted = await conn.execute(
            text("DELETE FROM cms_audit_log WHERE id_audit = :i RETURNING id_audit"),
            {"i": audit_probe["id_audit"]},
        )
        assert deleted.scalar_one() == audit_probe["id_audit"]


# ── ② Le vert : ajout seul ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_after_the_revoke_writing_and_reading_still_work(audit_probe):
    """Un journal fermé qu'on ne pourrait plus alimenter serait pire que le mal :
    l'API écrit une ligne d'audit sur des dizaines de chemins de mutation."""
    await _apply_revoke(audit_probe)
    async with audit_probe["engine"].begin() as conn:
        inserted = await conn.execute(
            text(
                "INSERT INTO cms_audit_log (id_org, action, resource_type) "
                "VALUES (:o, 'probe_insert', 'probe') RETURNING id_audit"
            ),
            {"o": audit_probe["id_org"]},
        )
        new_id = inserted.scalar_one()
        seen = await conn.execute(
            text("SELECT action FROM cms_audit_log WHERE id_audit = :i"), {"i": new_id}
        )
        assert seen.scalar_one() == "probe_insert"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    [
        pytest.param("UPDATE cms_audit_log SET action = 'rewritten'", id="update"),
        pytest.param("DELETE FROM cms_audit_log", id="delete"),
        pytest.param("TRUNCATE cms_audit_log", id="truncate"),
    ],
)
async def test_after_the_revoke_history_cannot_be_altered(audit_probe, statement):
    await _apply_revoke(audit_probe)
    with pytest.raises(DBAPIError) as err:
        async with audit_probe["engine"].begin() as conn:
            await conn.execute(text(statement))
    assert _is_permission_denied(err.value), (
        f"« {statement} » a échoué pour une autre raison que le refus de droit : "
        f"{err.value.orig!r}"
    )


# ── ③ Ce qu'on n'a pas cassé ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_referential_set_null_survives_the_revoke(audit_probe, db_session):
    """`cms_audit_log.id_user` est en `ON DELETE SET NULL` : supprimer un compte
    fait donc un UPDATE sur le journal — celui-là même qu'on vient d'interdire.
    PostgreSQL exécute les déclencheurs d'intégrité avec les droits du propriétaire
    de la table, pas ceux de l'appelant, donc ça doit continuer de passer. C'est
    l'hypothèse la plus risquée de la migration : on l'exerce.

    (Le produit ne supprime aucun compte aujourd'hui — la suppression IAM est une
    désactivation logique — mais P3.3 prévoit la suppression réelle d'organisations
    et de comptes : ce test est là pour que la porte soit déjà prouvée ouverte.)"""
    await _apply_revoke(audit_probe)
    async with audit_probe["engine"].begin() as conn:
        # ⚠️ Depuis que la base de test est bâtie par les MIGRATIONS (P1.5), la RLS y est
        # réellement posée : sans contexte d'organisation, ce DELETE ne verrait aucune
        # ligne et le test passerait pour la mauvaise raison (rien supprimé, donc rien à
        # mettre à NULL). On pose le contexte comme le fait l'application.
        await conn.execute(
            text(f"SET LOCAL app.current_org_id = '{audit_probe['id_org']}'"))
        deleted = await conn.execute(
            text("DELETE FROM cms_users WHERE id_user = :u RETURNING id_user"),
            {"u": audit_probe["id_user"]},
        )
        assert deleted.scalar_one() == audit_probe["id_user"], (
            "le compte n'a pas été supprimé — le test ne prouverait rien sur l'action "
            "référentielle qu'il est censé exercer"
        )
    # Mesuré depuis la session superuser : la ligne de journal est TOUJOURS là, et
    # c'est son `id_user` qui est retombé à NULL — l'histoire survit au compte.
    kept = await db_session.execute(
        text("SELECT id_user FROM cms_audit_log WHERE id_audit = :i"),
        {"i": audit_probe["id_audit"]},
    )
    assert kept.scalar_one() is None


# ── ④ Anti-récidive : la 0044 ne doit pas se rejouer ───────────────────────────────

def test_no_later_migration_regrants_the_audit_log():
    """La 0044 a rouvert la porte de la 0009 **sans le voir**, par un
    `GRANT ALL ON ALL TABLES` dont le journal n'était qu'un dommage collatéral.
    Toute migration postérieure à la 0121 qui refait un grant en masse doit donc
    re-fermer explicitement `cms_audit_log` — sinon elle échoue ici, au lieu
    d'échouer chez un client trois mois plus tard, en silence."""
    bulk_grant = re.compile(r"GRANT\s+.*\s+ON\s+ALL\s+TABLES", re.IGNORECASE)
    coupables = []
    for path in sorted(VERSIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.py")):
        revision = path.name[:4]
        if revision <= _MIGR.revision:
            continue
        source = path.read_text(encoding="utf-8")
        if bulk_grant.search(source) and _MIGR.APPEND_ONLY_TABLE not in source:
            coupables.append(path.name)
    assert not coupables, (
        "Ces migrations accordent des droits en masse sans re-fermer le journal "
        f"d'audit (c'est exactement ce qu'a fait la 0044) : {coupables}"
    )


def test_the_migration_closes_both_application_roles():
    """Anti-dérive sur la migration elle-même : retirer un rôle ou un privilège de
    ses listes rendrait les tests ci-dessus toujours verts — ils ne sondent qu'un
    rôle — alors que la porte resterait ouverte pour l'autre."""
    assert set(_MIGR.APPLICATION_ROLES) == {"signflow_app", "signflow_worker"}
    assert set(_MIGR.REVOKED_PRIVILEGES) == {"UPDATE", "DELETE", "TRUNCATE"}
    for role in _MIGR.APPLICATION_ROLES:
        sql = _MIGR.revoke_sql(role)
        assert sql.startswith("REVOKE ") and f" FROM {role}" in sql
        assert " ON cms_audit_log " in sql
