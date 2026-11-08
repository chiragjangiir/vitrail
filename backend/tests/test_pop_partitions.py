"""Rotation Proof of Play — le SQL, là où vivaient réellement les défauts (§XXIV, P3.5).

Le filet existant (`test_pop_archive.py`) ne couvrait que des helpers PURS. Tout ce qui a
cassé en production était dans le worker : le droit de créer une partition, l'interaction
avec la partition DEFAULT, la résilience de la boucle, le compte rendu. D'où ces tests, qui
se connectent à la base de TEST et exécutent les vraies requêtes.

⚠️ Le worker ouvre sa PROPRE connexion psycopg2 sur `settings.db_worker_url`, c'est-à-dire
la base APPLICATIVE. Sans la couture ci-dessous, ces tests mesureraient la base de
développement depuis la base de test — et accuseraient (ou blanchiraient) du code au hasard.
"""

import os
from datetime import date, datetime, timedelta, timezone

import psycopg2
import pytest

from app.services import pop_archive
from app.workers import pop_worker

TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://signflow:signflow@postgres:5432/signflow_test",
).replace("+asyncpg", "")

# Volontairement loin devant : aucune partition ne couvre ces jours, et aucun autre test de
# la suite n'y écrit. C'est ce qui rend le cas « la ligne tombe dans la DEFAULT » reproductible.
HORIZON = date.today() + timedelta(days=300)
DEFAULT_TBL = f"{pop_archive.PARTITION_PREFIX}default"
ORG = 990_001


def _connect():
    return psycopg2.connect(TEST_DSN)


def _insert_proof(conn, day: date, *, covered: bool = False) -> None:
    at = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=10)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO cms_proof_of_play (id_org, id_player, id_media, played_at, "
            "duration_ms, merkle_hash, covered) VALUES (%s, 1, 1, %s, 1000, %s, %s)",
            (ORG, at, "d" * 64, covered),
        )
    conn.commit()


def _partition_exists(conn, day: date) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (pop_archive.day_partition_name(day),))
        return cur.fetchone()[0] is not None


def _cleanup(conn, days: list[date], extra_tables: list[str] = ()) -> None:
    # Un test qui vient d'exercer un échec laisse la transaction avortée : sans ce rollback,
    # le nettoyage échouerait à son tour et masquerait le verdict du test lui-même.
    conn.rollback()
    with conn.cursor() as cur:
        for name in extra_tables:
            cur.execute(f"DROP TABLE IF EXISTS {name}")
        for d in days:
            cur.execute(f"DROP TABLE IF EXISTS {pop_archive.day_partition_name(d)}")
        cur.execute("DELETE FROM cms_proof_of_play WHERE id_org = %s", (ORG,))
    conn.commit()


@pytest.fixture
def wconn(engine, monkeypatch):
    """Connexion psycopg2 sur la base de TEST, substituée à celle du worker.

    `engine` est demandée pour que la chaîne de migrations ait bâti le schéma : sans elle,
    `cms_proof_of_play` peut ne pas exister quand ce fichier est lancé seul.
    """
    monkeypatch.setattr(pop_worker, "_db_conn", _connect)
    conn = _connect()
    _cleanup(conn, [HORIZON + timedelta(days=i) for i in range(4)], ["_pop_intruder"])
    yield conn
    _cleanup(conn, [HORIZON + timedelta(days=i) for i in range(4)], ["_pop_intruder"])
    conn.close()


async def test_proof_without_partition_lands_in_default(wconn):
    """Le point de départ du défaut : sans partition, la preuve N'EST PAS perdue — elle
    tombe dans la DEFAULT, qui n'est ni archivée ni droppable. Rien ne casse, et c'est
    précisément pourquoi la panne a tenu 28 jours sans se voir."""
    assert not _partition_exists(wconn, HORIZON)
    _insert_proof(wconn, HORIZON)
    with wconn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {DEFAULT_TBL} WHERE id_org = %s", (ORG,))
        assert cur.fetchone()[0] == 1
    wconn.rollback()


async def test_partition_creation_recovers_rows_trapped_in_default(wconn):
    """PostgreSQL REFUSE de créer une partition dont la DEFAULT porte déjà des lignes.

    Sans rapatriement, un jour ayant manqué sa partition ne pourrait plus JAMAIS en obtenir
    une : l'échec se rend lui-même permanent. La preuve doit finir dans la partition du jour,
    et la DEFAULT être vidée d'autant.
    """
    _insert_proof(wconn, HORIZON, covered=True)

    pop_worker._create_day_partition(wconn, HORIZON)

    assert _partition_exists(wconn, HORIZON)
    with wconn.cursor() as cur:
        cur.execute(
            f"SELECT count(*) FROM {pop_archive.day_partition_name(HORIZON)} WHERE id_org=%s",
            (ORG,),
        )
        assert cur.fetchone()[0] == 1, "la preuve n'a pas rejoint la partition du jour"
        cur.execute(f"SELECT count(*) FROM {DEFAULT_TBL} WHERE id_org = %s", (ORG,))
        assert cur.fetchone()[0] == 0, "la preuve est restée dans la DEFAULT"
        # Le drapeau a survécu au déplacement : c'est lui qui dit que la preuve ne compte pas.
        cur.execute(
            "SELECT covered FROM cms_proof_of_play WHERE id_org = %s", (ORG,)
        )
        assert cur.fetchone()[0] is True
    wconn.rollback()


async def test_partition_is_owned_by_the_worker_that_must_drop_it(wconn):
    """La rotation rend le disque par DROP, et le DROP exige la propriété. Une partition
    créée sans le bon propriétaire s'archiverait sans jamais libérer la place."""
    pop_worker._create_day_partition(wconn, HORIZON)
    with wconn.cursor() as cur:
        cur.execute(
            "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname = %s",
            (pop_archive.day_partition_name(HORIZON),),
        )
        assert cur.fetchone()[0] == "signflow_worker"
    wconn.rollback()


async def test_partition_function_refuses_any_name_but_a_daily_partition(wconn):
    """La fonction de création tourne avec les droits du PROPRIÉTAIRE de la table.

    Sans sa garde de nom, elle serait un « créez-moi n'importe quelle table sous le compte
    propriétaire » offert au rôle worker — c'est le risque propre à `SECURITY DEFINER`, et
    la raison pour laquelle on ne lui a pas simplement donné la propriété du parent.
    """
    end = HORIZON + timedelta(days=1)
    for forbidden in ("evil_table", "cms_proof_of_play_default", "cms_users"):
        with pytest.raises(psycopg2.Error, match="refuse"):
            with wconn.cursor() as cur:
                cur.execute(
                    "SELECT cms_create_pop_partition(%s, %s, %s)", (forbidden, HORIZON, end)
                )
        wconn.rollback()


async def test_one_impossible_day_does_not_block_the_others(wconn, monkeypatch):
    """Chaque jour est indépendant.

    La boucle d'origine était tout-ou-rien : le premier jour en échec emportait la création
    de tous les suivants, pourtant créables. C'est ce qui a transformé un incident de droits
    ponctuel en panne permanente.
    """
    blocked = HORIZON + timedelta(days=1)
    # Une partition « intruse » couvre le jour visé sous un autre nom : le CREATE de ce
    # jour-là échouera (chevauchement de bornes), les autres n'ont aucune raison d'échouer.
    with wconn.cursor() as cur:
        cur.execute(
            "CREATE TABLE _pop_intruder PARTITION OF cms_proof_of_play "
            f"FOR VALUES FROM ('{blocked.isoformat()}') "
            f"TO ('{(blocked + timedelta(days=1)).isoformat()}')"
        )
    wconn.commit()

    class _Today(date):
        @classmethod
        def today(cls):
            return HORIZON

    monkeypatch.setattr(pop_worker, "date", _Today)
    result = pop_worker.ensure_pop_partitions(days_ahead=2)

    assert pop_archive.day_partition_name(HORIZON) in result["created"]
    assert pop_archive.day_partition_name(HORIZON + timedelta(days=2)) in result["created"], (
        "un jour créable a été sacrifié à cause d'un autre jour en échec"
    )
    assert blocked.isoformat() in result["failed"]


async def test_archive_reports_proofs_stranded_in_default(wconn, monkeypatch):
    """Le compte rendu doit distinguer « rien à archiver » de « je ne peux rien archiver ».

    En production, `archive_pop` rendait `{'archived': [], 'errors': []}` chaque nuit —
    un succès — alors que toutes les preuves s'entassaient hors de portée de la rotation.
    """
    old_day = date.today() - timedelta(days=400)  # bien au-delà de la rétention chaude
    _insert_proof(wconn, old_day)
    # On neutralise l'archivage réel : ce test porte sur le COMPTE RENDU, pas sur MinIO.
    monkeypatch.setattr(pop_worker, "_archive_day", lambda *a, **k: {"dropped": False})

    result = pop_worker.archive_pop()

    assert result["stranded_in_default"] >= 1, (
        "des preuves anciennes coincées dans la DEFAULT doivent être signalées"
    )
    with wconn.cursor() as cur:
        cur.execute("DELETE FROM cms_proof_of_play WHERE id_org = %s", (ORG,))
    wconn.commit()
