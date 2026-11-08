"""`cms_event_ai_suggestions.id_event_created` gagne `ON DELETE SET NULL` (audit 2026-07-29).

La clé étrangère n'avait aucune action : supprimer un événement **né d'une suggestion IA
approuvée** violait la contrainte et sortait en **500 non traité**. Le cas est rare (il faut
avoir approuvé une suggestion) mais il est certain : la route de suppression ne l'anticipe
pas et l'utilisateur ne reçoit aucune explication.

`SET NULL` plutôt que `CASCADE` : la SUGGESTION doit survivre à l'événement qu'elle a produit
— c'est une trace de décision (« l'IA a proposé, un humain a approuvé le … »), et la perdre
parce qu'on nettoie un événement reviendrait à effacer l'historique de la décision. Après
suppression, la suggestion reste `approved` avec `id_event_created` à NULL : l'événement a
existé, il n'existe plus.

Déploiement neutre, mesuré avant sur la production : **0 suggestion** en base.

Revision ID: 0118
Revises: 0117
"""

from alembic import op

revision: str = "0118"
down_revision: str | None = "0117"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$
        DECLARE cname text;
        BEGIN
            SELECT conname INTO cname FROM pg_constraint
             WHERE conrelid = 'cms_event_ai_suggestions'::regclass AND contype = 'f'
               AND conkey = ARRAY[(SELECT attnum FROM pg_attribute
                                    WHERE attrelid = 'cms_event_ai_suggestions'::regclass
                                      AND attname = 'id_event_created')];
            IF cname IS NOT NULL THEN
                EXECUTE format('ALTER TABLE cms_event_ai_suggestions DROP CONSTRAINT %I', cname);
            END IF;
        END $$;
    """)
    op.execute("""
        ALTER TABLE cms_event_ai_suggestions
          ADD CONSTRAINT fk_cms_event_suggestion_event
          FOREIGN KEY (id_event_created) REFERENCES cms_events(id_event) ON DELETE SET NULL
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE cms_event_ai_suggestions "
               "DROP CONSTRAINT IF EXISTS fk_cms_event_suggestion_event")
    op.execute("""
        ALTER TABLE cms_event_ai_suggestions
          ADD CONSTRAINT cms_event_ai_suggestions_id_event_created_fkey
          FOREIGN KEY (id_event_created) REFERENCES cms_events(id_event)
    """)
