"""Proof of Play — rendre la création des partitions journalières possible (§XXIV, P3.5)

Revision ID: 0127
Revises: 0126
Create Date: 2026-08-07 16:00:00.000000

🔴 DÉFAUT MESURÉ EN PRODUCTION : `ensure_pop_partitions` échouait CHAQUE JOUR depuis le
10/07 avec

    InsufficientPrivilege: permission denied for schema public
    LINE 1: CREATE TABLE cms_proof_of_play_2026_08_07 PARTITION OF cms_p...

Les partitions posées par la 0060 couvraient J..J+7, soit jusqu'au 09/07. Au-delà, plus
aucune n'a pu être créée : toutes les preuves sont tombées dans la partition DEFAULT, qui
n'est ni archivée ni droppable. La rotation vendue (« archivage au-delà de 90 jours ») était
donc inopérante, en silence, sur toute installation — pendant que la tâche `archive_pop`
continuait de rendre « succès » chaque nuit.

**Il fallait DEUX droits, pas un — mesuré en exécutant, invisible à la relecture.** Accorder
`CREATE ON SCHEMA public` ne suffit pas : attacher une partition modifie la table PARENTE,
donc PostgreSQL exige d'en être PROPRIÉTAIRE (`must be owner of table cms_proof_of_play`).
Or le parent appartient à `signflow`. Mesuré aussi, et rassurant : le `DROP` d'une partition,
lui, ne demande que la propriété de la PARTITION — l'hypothèse de la 0060 tenait. La rotation
était donc asymétrique : le worker pouvait détruire, jamais créer.

**Pourquoi une fonction et pas un changement de propriétaire.** Donner `cms_proof_of_play` à
`signflow_worker` lui donnerait aussi le droit de la supprimer, de l'altérer, et de défaire
sa RLS `FORCE`. La fonction ci-dessous n'accorde qu'une seule chose : créer UNE partition
journalière de cette table-là. Le motif de nom est une GARDE, pas une seconde définition du
nommage — le nom et les bornes sont calculés en Python (`pop_archive.day_partition_name`),
qui reste la seule définition. Sans cette garde, `SECURITY DEFINER` deviendrait un
« créez-moi n'importe quelle table en tant que propriétaire ».

⛔ Aucun `GRANT CREATE ON SCHEMA public` : le worker n'en a plus besoin, la fonction
s'exécute sous le propriétaire. `signflow_app` ne reçoit rien du tout.
"""

from alembic import op

revision: str = "0127"
down_revision: str | None = "0126"
branch_labels = None
depends_on = None

FUNCTION_NAME = "cms_create_pop_partition"

# Un nom de partition journalière et rien d'autre : cms_proof_of_play_AAAA_MM_JJ.
NAME_PATTERN = r"^cms_proof_of_play_[0-9]{4}_[0-9]{2}_[0-9]{2}$"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {FUNCTION_NAME}(p_name text, p_from date, p_to date)
        RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        -- search_path FIGÉ : sans lui, un objet placé dans un schéma que l'appelant
        -- contrôle pourrait être résolu à la place du nôtre, et s'exécuterait avec les
        -- droits du propriétaire. C'est LE piège des fonctions SECURITY DEFINER.
        --
        -- ⚠️ Corollaire mesuré : avec `pg_catalog` en tête, un `CREATE TABLE <nom>` non
        -- qualifié vise `pg_catalog` et échoue (« permission denied to create
        -- pg_catalog.cms_proof_of_play_… »). Les noms sont donc TOUS qualifiés `public.`,
        -- plutôt que de relâcher le search_path pour faire porter la résolution au hasard
        -- de son ordre.
        SET search_path = pg_catalog, public
        AS $fn$
        BEGIN
            IF p_name !~ '{NAME_PATTERN}' THEN
                RAISE EXCEPTION 'nom de partition refuse : %', p_name;
            END IF;
            EXECUTE format(
                'CREATE TABLE public.%I PARTITION OF public.cms_proof_of_play '
                'FOR VALUES FROM (%L) TO (%L)',
                p_name, p_from, p_to
            );
            -- La propriété conditionne le DROP que fera `archive_pop` : une partition
            -- créée sans elle s'archiverait sans jamais rendre le disque.
            EXECUTE format('ALTER TABLE public.%I OWNER TO signflow_worker', p_name);
        END;
        $fn$
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION_NAME}(text, date, date) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {FUNCTION_NAME}(text, date, date) TO signflow_worker")


def downgrade() -> None:
    # Rend le défaut d'origine : les partitions journalières cesseront d'être créées et les
    # preuves retomberont dans la DEFAULT. `ensure_pop_partitions` le dira désormais
    # bruyamment (log ERROR + `failed` non vide) au lieu d'échouer sans témoin.
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION_NAME}(text, date, date)")
