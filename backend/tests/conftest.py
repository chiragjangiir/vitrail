"""
Configuration des fixtures de test.

Utilise une base de données PostgreSQL de test séparée, bâtie par la CHAÎNE DE
MIGRATIONS et non par les modèles (P1.5, 2026-08-05 — cf. `_build_schema_with_alembic`).
Le schéma de test est donc celui de la production, types compris.

⚠️ La RLS est bien posée par les migrations, mais elle ne s'applique pas : le rôle de test
(`signflow`) est superuser. Les tests qui veulent la mesurer se connectent par un rôle
dédié — cf. `test_rls_force.py`.
Les dépendances get_db_worker et get_db sont toutes deux overridées par db_session.
"""

import asyncio
import os
from pathlib import Path

# Désactive le rate-limit global AVANT d'importer l'app (le middleware est ajouté à l'import
# selon ce réglage). Sans ça, la suite partage IP+fenêtre-minute → faux 429 sous Redis réel.
os.environ.setdefault("CMS_RATE_LIMIT_ENABLED", "false")

import pytest_asyncio
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401 — enregistre tous les modèles dans Base.metadata
from app.core.deps import get_db, get_db_for_actor
from app.db.session import get_db_worker
from app.main import app

# Dans Docker : postgres:5432 (service name). Sur l'hôte : localhost:5432 (ou port remappé).
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://signflow:signflow@postgres:5432/signflow_test",
)


def _build_schema_with_alembic() -> None:
    """Bâtit la base de test en JOUANT LA CHAÎNE DE MIGRATIONS (P1.5, 2026-08-05).

    POURQUOI, ET CE QUE ÇA A DÉJÀ TROUVÉ. La base de test était bâtie par
    `Base.metadata.create_all`, c'est-à-dire d'après les MODÈLES. Deux conséquences,
    toutes deux vérifiées en mesurant :

      · une chaîne de migrations qui ne sait plus bâtir une base vierge n'échouait
        JAMAIS en test — c'est la famille exacte du défaut du 2026-08-02, où une version
        parfaitement installable-à-jour était **impossible à installer à neuf** depuis la
        1.0.9, sans que personne le sache. `sfctl validate-install` l'attrape désormais,
        mais *après* le build ; ici on l'attrape avant ;

      · le schéma de test **différait de la production** : 43 colonnes de dates y étaient
        créées NAÏVES (`timestamp`) là où les migrations posent des `timestamptz`, plus
        `rule_days` (json/jsonb) et `items_per_turn` (smallint/integer). C'est la classe
        du défaut de l'embargo (28/07) : `cms_media` déclarait un `DateTime` naïf, asyncpg
        refusait tout datetime *aware*, et `PATCH /embargo` répondait **500 en
        production** — invisible en test, où la colonne était naïve elle aussi.

    La chaîne complète prend ~3,5 s sur une base vierge (mesuré) : le coût est nul à
    l'échelle d'une suite de 6 minutes.

    On repart d'un schéma VIDE plutôt que de `downgrade base` : plus rapide, et surtout
    robuste si une exécution précédente s'est arrêtée en plein vol (ou a laissé des
    tables appartenant au rôle sonde de `test_rls_force.py`).
    """
    from alembic import command
    from alembic.config import Config

    from app.core.config import settings

    root = Path(__file__).resolve().parents[1]
    sync_url = TEST_DATABASE_URL.replace("+asyncpg", "+psycopg2")

    admin = sa.create_engine(sync_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA public")
        # pgvector est posé par init.sql en réel ; la base de test ne le joue pas, et il
        # doit exister AVANT la migration qui crée cms_doc_chunks (§XXVII).
        conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
    admin.dispose()

    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    # `alembic/env.py` lit `settings.DATABASE_URL` : on la pointe sur la base de TEST le
    # temps de la construction, sinon la chaîne se jouerait sur la base de développement.
    previous = settings.DATABASE_URL
    settings.DATABASE_URL = TEST_DATABASE_URL
    try:
        command.upgrade(cfg, "head")
    finally:
        settings.DATABASE_URL = previous


@pytest_asyncio.fixture(scope="session")
async def engine():
    """Crée l'engine dans le bon event loop pytest-asyncio (session-scoped)."""
    await asyncio.to_thread(_build_schema_with_alembic)
    _engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    yield _engine
    await _engine.dispose()


@pytest_asyncio.fixture
async def db_session(engine):
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session):
    async def _override():
        yield db_session

    app.dependency_overrides[get_db_worker] = _override
    app.dependency_overrides[get_db] = _override
    app.dependency_overrides[get_db_for_actor] = _override

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()
