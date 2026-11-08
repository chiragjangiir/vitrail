"""Journal d'audit réellement en AJOUT SEUL — P1.2 (2026-08-05).

Revision ID: 0121
Revises: 0120

CE QUE CETTE MIGRATION RÉPARE. La 0009 avait posé l'intention dès l'origine :
`GRANT SELECT, INSERT ON cms_audit_log TO signflow_app` — un journal qu'on écrit
et qu'on lit, jamais qu'on réécrit. La **0044 l'a défaite sans le voir** : pour
préparer la bascule sur `signflow_app`, elle a fait `GRANT ALL ON ALL TABLES`
aux deux rôles applicatifs, `cms_audit_log` comprise. Depuis, « le journal est en
ajout seul » n'est plus qu'une **convention de code** : le rôle qui sert toutes
les requêtes de l'API peut le réécrire ou l'effacer.

MESURÉ AVANT D'AGIR (2026-08-05, production ET banc de dev) :

    grantee         | privilèges
    signflow_app    | DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE
    signflow_worker | DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE

`relkind = 'r'` : table ordinaire, **pas partitionnée** (le `*` du tableau de
`CLAUDE.md` est prospectif) — le REVOKE n'a donc pas de partitions à parcourir.

CE QUE ÇA NE CASSE PAS, vérifié plutôt que supposé :

  · **rien dans le code ne mute ce journal** — aucun `UPDATE` ni `DELETE` sur
    `cms_audit_log` dans `app/` ni dans `scripts/` (grep vide, 04/08 et 05/08).
    Il n'y a donc aucune purge existante à préserver ;
  · le **propriétaire** (`signflow`) garde tous ses droits : les migrations
    tournent sous lui, et la rétention à venir (P3.5) tournera sous lui aussi ;
  · les **actions référentielles** continuent de passer. `cms_audit_log` porte
    deux clés étrangères `ON DELETE SET NULL` (vers `cms_organizations` et
    `cms_users`) : supprimer une organisation ou un compte fait bien un UPDATE
    sur le journal, mais PostgreSQL exécute les déclencheurs d'intégrité avec
    les droits du **propriétaire de la table**, pas ceux de l'appelant. C'est
    exactement le genre d'affirmation qui mérite une preuve plutôt qu'une
    citation : `tests/test_audit_append_only.py` l'exerce en réel.

CE QUE ÇA NE GARANTIT PAS. Une future migration qui referait un
`GRANT ALL ON ALL TABLES` rouvrirait la porte **en silence**, exactement comme
la 0044. Le garde-fou est dans le test (`test_no_later_migration_regrants_audit_log`),
qui refuse toute migration postérieure faisant un grant en masse sans re-fermer
le journal. `ALTER DEFAULT PRIVILEGES`, lui, ne concerne que les tables à venir :
il n'atteint pas celle-ci.

Prolongement direct de la 0119 (RLS `FORCE`) : on transforme une convention en
garantie, au niveau où elle tient — les privilèges.
"""

from alembic import op

revision: str = "0121"
down_revision: str | None = "0120"
branch_labels = None
depends_on = None


APPEND_ONLY_TABLE = "cms_audit_log"

# TRUNCATE est révoqué avec le reste : effacer le journal d'un coup est la forme
# la plus expéditive de le réécrire, et aucun code ne le fait.
REVOKED_PRIVILEGES = ("UPDATE", "DELETE", "TRUNCATE")

# Les deux rôles applicatifs. `signflow_worker` y passe aussi : il est BYPASSRLS
# et sert les lectures cross-org de la console — raison de plus pour qu'il ne
# puisse pas modifier l'histoire qu'il a le droit de lire en entier.
APPLICATION_ROLES = ("signflow_app", "signflow_worker")


def revoke_sql(role: str) -> str:
    """SQL de fermeture pour un rôle. Lu par le test (patron « le test lit la
    migration », comme `_PERMS` en 0111 et `FORCED_TABLES` en 0119) : la base de
    test est bâtie par `create_all`, sans migrations — sans ce partage, le test
    prouverait une copie locale au lieu de ce qui est réellement déployé."""
    return (
        f"REVOKE {', '.join(REVOKED_PRIVILEGES)} ON {APPEND_ONLY_TABLE} FROM {role}"
    )


def _for_each_existing_role(sql_for_role) -> None:
    """Un rôle absent ferait échouer la migration entière. Les deux existent
    depuis `postgres-init.sh` (et la 0044 les référence déjà sans garde), mais
    une installation ancienne ou rattrapée à la main ne doit pas se retrouver
    bloquée par une fermeture de porte."""
    for role in APPLICATION_ROLES:
        statement = sql_for_role(role).replace("'", "''")
        op.execute(
            f"""
            DO $$ BEGIN
                IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
                    EXECUTE '{statement}';
                END IF;
            END $$
            """
        )


def upgrade() -> None:
    _for_each_existing_role(revoke_sql)


def downgrade() -> None:
    # Retour à l'état laissé par la 0044 (et non à celui de la 0009) : c'est
    # l'état réel d'où l'on vient, et un downgrade doit rendre la base telle
    # qu'elle était juste avant, pas telle qu'on aurait aimé qu'elle soit.
    _for_each_existing_role(
        lambda role: (
            f"GRANT {', '.join(REVOKED_PRIVILEGES)} ON {APPEND_ONLY_TABLE} TO {role}"
        )
    )
