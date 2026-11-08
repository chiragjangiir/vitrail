"""Ce qui retient une organisation ou un compte — lu DANS LE SCHÉMA (P3.3).

Le produit sait déjà dire ce qu'une suppression emporterait, mais seulement PAR ENTITÉ
(`deletion-impact` des médias, templates, paniers, flux). Il ne savait rien dire d'une
**organisation** ni d'un **compte** — et pour l'organisation il n'existait même aucun
endpoint de suppression : un super-admin pouvait en créer, jamais en retirer.

Pendant de la ligne d'Ed « quand on efface, on efface » : on efface **franchement**, ou on
**refuse en expliquant**. Jamais un `is_deleted` qui laisse la ligne invisible et
irrécupérable, et jamais un bouton qui ne peut qu'échouer.

⚠️ LES LISTES DE TABLES SONT LUES, JAMAIS ÉCRITES À LA MAIN. Une table ajoutée le mois
prochain portera `id_org` comme les autres et se fera compter sans que personne y pense.
Une liste recopiée, elle, prend du retard **en silence** — c'est exactement ce qui venait
d'arriver à la liste blanche du mode démo (deux endpoints oubliés, 27/07 et 06/08).

🔑 TROIS NATURES DE LIEN, ET C'EST LE CŒUR DU SUJET. Le schéma ne dit pas seulement
« référencé » : il dit ce qui arriverait.

  · **bloquant** (`NO ACTION` / `RESTRICT`, ou pas de FK du tout) — PostgreSQL refuserait,
    ou la ligne resterait orpheline. C'est ce qu'il faut NOMMER dans le refus.
  · **emporté** (`CASCADE`) — la ligne disparaîtrait AVEC la cible. Sur une organisation
    c'est le vrai danger : ~20 tables partiraient sans un mot. Un rapport qui ne dirait
    que « bloqué » cacherait précisément ce qu'un opérateur doit voir avant de trancher.
  · **délié** (`SET NULL`) — la ligne survit, sa référence est vidée. Le journal d'audit
    est ici : supprimer un compte ne perd pas la trace de ses actes, elle devient anonyme.

Mesuré le 2026-08-07 : **56 tables** référencent une organisation, **31** un compte
(4 colonnes : `id_user`, `created_by`, `submitted_by`, `reviewed_by`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: Colonnes par lesquelles une ligne peut désigner un compte. `id_owner`/`requested_by`
#: n'existent pas aujourd'hui mais sont listées : si elles apparaissent, elles seront
#: comptées sans qu'on y revienne — c'est tout l'intérêt de lire le schéma.
USER_COLUMNS = ("id_user", "created_by", "submitted_by", "reviewed_by",
                "id_owner", "requested_by")
ORG_COLUMNS = ("id_org",)

#: Règles de FK qui EMPÊCHENT la suppression. Une colonne sans contrainte de clé étrangère
#: est traitée comme bloquante elle aussi : la base ne dirait rien, et on laisserait une
#: référence pendante — pire qu'un refus.
_BLOCKING_RULES = {"NO ACTION", "RESTRICT", None}

#: Colonnes qui sont la CLÉ de la ligne visée, pas une référence vers elle.
_SELF_KEYS = {("cms_organizations", "id_org"), ("cms_users", "id_user")}


@dataclass
class Reference:
    table: str
    column: str
    count: int
    kind: str          # blocking | cascade | detach

    def as_dict(self) -> dict:
        return {"table": self.table, "column": self.column,
                "count": self.count, "kind": self.kind}


@dataclass
class Impact:
    blocking: list[Reference] = field(default_factory=list)
    cascade: list[Reference] = field(default_factory=list)
    detach: list[Reference] = field(default_factory=list)

    @property
    def can_delete(self) -> bool:
        return not self.blocking

    def as_dict(self) -> dict:
        return {
            "can_delete": self.can_delete,
            "blocking": [r.as_dict() for r in self.blocking],
            "cascade": [r.as_dict() for r in self.cascade],
            "detach": [r.as_dict() for r in self.detach],
            "blocking_total": sum(r.count for r in self.blocking),
            "cascade_total": sum(r.count for r in self.cascade),
            "detach_total": sum(r.count for r in self.detach),
        }


# Le schéma est lu à CHAQUE appel, sans cache. C'est une action d'administration, jamais un
# chemin chaud — et un cache de processus mentirait juste après une migration, exactement
# quand la liste vient de changer.
_SCHEMA_Q = text("""
SELECT c.table_name, c.column_name,
       (SELECT rc.delete_rule
          FROM information_schema.key_column_usage k
          JOIN information_schema.referential_constraints rc
            ON rc.constraint_name = k.constraint_name
           AND rc.constraint_schema = k.constraint_schema
         WHERE k.table_schema = c.table_schema
           AND k.table_name = c.table_name
           AND k.column_name = c.column_name
         LIMIT 1) AS delete_rule
FROM information_schema.columns c
JOIN information_schema.tables t
  ON t.table_schema = c.table_schema AND t.table_name = c.table_name
WHERE c.table_schema = 'public'
  AND t.table_type = 'BASE TABLE'
  AND c.column_name = ANY(:cols)
ORDER BY c.table_name, c.column_name
""")


def _kind(delete_rule: str | None) -> str:
    """`NO ACTION`, `RESTRICT` et l'absence de FK tombent tous dans « bloquant » : on refuse
    plutôt que de laisser une référence pendante que personne ne verra."""
    if delete_rule == "CASCADE":
        return "cascade"
    if delete_rule == "SET NULL":
        return "detach"
    return "blocking"


async def _referencing_columns(db: AsyncSession, cols: tuple[str, ...]) -> list[tuple[str, str, str]]:
    rows = (await db.execute(_SCHEMA_Q, {"cols": list(cols)})).all()
    out: list[tuple[str, str, str]] = []
    for r in rows:
        # `cms_organizations.id_org` et `cms_users.id_user` sont les CLÉS des lignes visées,
        # pas des références vers elles. ⚠️ `cms_users.id_org`, en revanche, EST bien une
        # référence : les comptes retiennent leur organisation — c'est même, en pratique, ce
        # qui bloque en premier la suppression d'une org.
        if (r.table_name, r.column_name) in _SELF_KEYS:
            continue
        # Partitions du Proof of Play : la table parente porte déjà la colonne, compter les
        # partitions ferait un doublon par jour de rétention.
        if r.table_name.startswith("cms_proof_of_play_"):
            continue
        out.append((r.table_name, r.column_name, _kind(r.delete_rule)))
    return out


async def _count(db: AsyncSession, table: str, column: str, value: int) -> int:
    # Noms issus d'`information_schema`, jamais d'une saisie : pas d'injection possible ici,
    # et un nom de table ne peut de toute façon pas être passé en paramètre lié.
    q = text(f'SELECT count(*) FROM "{table}" WHERE "{column}" = :v')  # noqa: S608
    return int((await db.execute(q, {"v": value})).scalar() or 0)


async def _impact(db: AsyncSession, cols: tuple[str, ...], value: int) -> Impact:
    imp = Impact()
    for table, column, kind in await _referencing_columns(db, cols):
        n = await _count(db, table, column, value)
        if n == 0:
            continue          # une table vide de références n'a rien à dire
        getattr(imp, kind).append(Reference(table, column, n, kind))
    for bucket in (imp.blocking, imp.cascade, imp.detach):
        bucket.sort(key=lambda r: (-r.count, r.table))
    return imp


async def organization_impact(db: AsyncSession, id_org: int) -> Impact:
    """Ce que retient / emporterait / délierait la suppression d'une organisation."""
    return await _impact(db, ORG_COLUMNS, id_org)


async def user_impact(db: AsyncSession, id_user: int) -> Impact:
    """Ce que retient / emporterait / délierait la suppression d'un compte."""
    return await _impact(db, USER_COLUMNS, id_user)
