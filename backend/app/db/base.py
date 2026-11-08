from datetime import datetime

from sqlalchemy import DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    # P2.6 (2026-08-05) — TOUTE date est un `timestamptz`, y compris quand la colonne ne
    # déclare aucun type et laisse SQLAlchemy le déduire de `Mapped[datetime]`.
    #
    # LE DÉFAUT QUE ÇA FERME. Le défaut de SQLAlchemy pour `datetime` est un `DateTime()`
    # **naïf**, alors que toute la base est en `timestamptz` : 40 colonnes de 29 tables
    # étaient dans ce cas (mesuré en comparant les modèles à une base bâtie par les
    # migrations, P1.5). Un modèle naïf fait **refuser par asyncpg** toute écriture d'un
    # datetime *aware* — c'est exactement ce qui rendait `PATCH /media/{id}/embargo`
    # inutilisable en production le 28/07, avec un 500 et aucune trace ailleurs. Ces 40-là
    # ne cassaient pas encore, parce qu'elles sont remplies par `server_default now()` et
    # jamais écrites depuis Python ; rien n'aurait annoncé le premier chemin qui le ferait.
    #
    # 🔑 Corrigé ICI plutôt qu'en 40 endroits, pour la raison qui compte : une correction
    # colonne par colonne aurait laissé le **défaut** en place, et la 41ᵉ colonne écrite
    # demain serait repartie naïve. `tests/test_model_schema_drift.py` mesure qu'aucune
    # colonne ne diverge plus de la base.
    #
    # ⚠️ Ne concerne QUE la déduction depuis l'annotation : une colonne qui déclare son
    # type explicitement garde le sien (toutes déclarent déjà `DateTime(timezone=True)`).
    type_annotation_map = {datetime: DateTime(timezone=True)}
