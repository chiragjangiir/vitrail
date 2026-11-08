"""Les modèles décrivent-ils la base réellement déployée ? — P2.6 (2026-08-05).

CE QUE CE FICHIER EMPÊCHE. Un modèle SQLAlchemy peut parfaitement décrire un schéma que la
base n'a pas : rien ne les confronte au démarrage, et les requêtes marchent tant qu'on ne
touche pas au détail qui diffère. C'est ce qui a rendu `PATCH /media/{id}/embargo`
inutilisable **en production** le 28/07 — `cms_media` déclarait un `DateTime` naïf là où la
colonne est un `timestamptz`, asyncpg refusait tout datetime *aware*, et la route répondait
500 sans que rien d'autre ne bouge.

Ce test n'a pu être écrit qu'après P1.5 : tant que la base de test était bâtie **depuis les
modèles** (`create_all`), elle leur donnait forcément raison. Elle est désormais bâtie par
la **chaîne de migrations**, donc la comparaison a un sens — et elle a immédiatement trouvé
**40 colonnes de dates naïves sur 29 tables**, plus deux types divergents.

⚠️ Ce test compare ce qui compte pour le comportement (fuseau des dates, famille de type),
pas la lettre du DDL : `Float` produit un `DOUBLE PRECISION`, `String(50)` un
`VARCHAR(50)` — des écritures différentes de la même chose. Un test qui exigerait l'égalité
littérale serait rouge en permanence et finirait désactivé, ce qui est pire que pas de test.
"""

import sqlalchemy as sa
import pytest
from sqlalchemy import inspect

import app.models  # noqa: F401 — enregistre tous les modèles dans Base.metadata
from app.db.base import Base


@pytest.fixture(scope="module")
def reflected(engine):
    """Colonnes RÉELLES de la base de test (bâtie par les migrations, cf. conftest)."""
    # ⚠️ `str(url)` MASQUE le mot de passe en `***` — `render_as_string` obligatoire
    # (même piège que dans `test_rls_force.py`).
    sync_url = engine.url.render_as_string(hide_password=False).replace("+asyncpg", "+psycopg2")
    sync = sa.create_engine(sync_url)
    try:
        insp = inspect(sync)
        yield {t: {c["name"]: c for c in insp.get_columns(t)} for t in insp.get_table_names()}
    finally:
        sync.dispose()


def test_every_model_table_exists_in_the_migrated_database(reflected):
    """Un modèle dont la table n'est créée par aucune migration produirait un
    `UndefinedTable` au premier appel — chez un client, jamais chez nous."""
    manquantes = sorted(set(Base.metadata.tables) - set(reflected))
    assert not manquantes, (
        "ces tables existent dans les modèles mais AUCUNE migration ne les crée : "
        f"{manquantes}"
    )


def test_no_model_column_is_missing_from_the_database(reflected):
    manquantes = []
    for tname, tab in Base.metadata.tables.items():
        reels = reflected.get(tname)
        if reels is None:
            continue  # déjà signalé par le test précédent
        manquantes += [f"{tname}.{c.name}" for c in tab.columns if c.name not in reels]
    assert not manquantes, (
        "ces colonnes sont déclarées au modèle mais absentes de la base migrée : "
        f"{sorted(manquantes)}"
    )


def test_no_date_column_is_declared_naive(reflected):
    """LE test de ce fichier — celui qui aurait attrapé le défaut de l'embargo.

    Une colonne `timestamptz` décrite comme naïve au modèle fait **refuser par asyncpg**
    toute écriture d'un datetime *aware*. Les 40 colonnes trouvées le 05/08 ne cassaient pas
    encore, parce qu'elles sont remplies par `server_default now()` ; le jour où un chemin
    de code en écrit une, c'est un 500 que rien n'annonce.

    La correction vit dans `app/db/base.py` (`type_annotation_map`) et vaut donc pour toute
    colonne future : ce test mesure que le défaut ne revient pas.
    """
    naives = []
    for tname, tab in Base.metadata.tables.items():
        reels = reflected.get(tname)
        if reels is None:
            continue
        for col in tab.columns:
            reel = reels.get(col.name)
            if reel is None or not isinstance(col.type, sa.DateTime):
                continue
            if getattr(reel["type"], "timezone", False) and not col.type.timezone:
                naives.append(f"{tname}.{col.name}")
    assert not naives, (
        "ces colonnes sont des `timestamptz` en base mais des dates NAÏVES au modèle — "
        "asyncpg refusera d'y écrire un datetime aware (défaut de l'embargo, 28/07) : "
        f"{sorted(naives)}"
    )


# Familles de types dont les écritures diffèrent sans que le comportement change.
# `Float` → DOUBLE PRECISION, `Boolean` → BOOLEAN, etc. On compare la famille, pas la lettre.
_EQUIVALENTS = {
    "FLOAT": "DOUBLE PRECISION",
    "DATETIME": "TIMESTAMP",
}


def _famille(type_: object) -> str:
    nom = str(type_).upper().split("(")[0].strip()
    return _EQUIVALENTS.get(nom, nom)


def test_no_column_type_family_diverges(reflected):
    """Attrape les divergences de FAMILLE : `json` contre `jsonb`, `smallint` contre
    `integer` — les deux trouvées le 05/08. Elles n'ont pas cassé, mais un modèle qui décrit
    autre chose que le schéma déployé finit par mentir sur un détail qui compte."""
    ecarts = []
    for tname, tab in Base.metadata.tables.items():
        reels = reflected.get(tname)
        if reels is None:
            continue
        for col in tab.columns:
            reel = reels.get(col.name)
            if reel is None or isinstance(col.type, sa.DateTime):
                continue  # les dates sont traitées par le test dédié ci-dessus
            fm, fr = _famille(col.type), _famille(reel["type"])
            if fm != fr:
                ecarts.append(f"{tname}.{col.name} : modèle={fm} base={fr}")
    assert not ecarts, "divergences de type entre modèles et base migrée : " + str(sorted(ecarts))
