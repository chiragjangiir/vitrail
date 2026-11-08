"""Audit du menu Paniers Audio §XIX (décisions d'Ed, 2026-07-29) — A3, A5, A4-bis.

**A3 — `cms_basket_permissions` est une table MORTE, on la supprime.** Créée par 0019 pour
porter le modèle de droits §19.2 (`allowed_role` / `can_activate` / `can_deactivate` /
`can_edit_ratio`), elle n'a JAMAIS été branchée : aucune ligne de code ne la lit ni ne
l'écrit, et la production en compte **0 ligne**. Le contrôle réel du panneau local passe par
`allowed_basket_ids` du profil `local_control`. Décision d'Ed : « si pas utilisé alors on
supprime ». Même geste que `templates:publish` (0115) — une structure qui promet un droit
qu'elle n'accorde pas est un mensonge fait à l'administrateur.

**A5 — `cms_events.id_basket` gagne `ON DELETE SET NULL`.** La FK posée par 0021 n'avait
aucune action : supprimer un panier référencé par un événement audio produisait une **erreur
500** (violation de clé étrangère). Le filet de sécurité complète la garde applicative (409
qui NOMME les programmes et événements concernés, `?force=true` pour détacher) : la garde
protège le geste, la contrainte protège la base. Un événement dont le panier est NULL est
ignoré par la résolution (`ws.py` : `if ev.id_basket is None: continue`), donc inerte et
jamais silencieusement redirigé vers un autre panier.

**A4-bis — `cms_audio_baskets.id_node` gagne enfin sa clé étrangère (`ON DELETE SET NULL`).**
La colonne, ajoutée sans FK (« pas de FK pour l'instant »), laissait un panier pointer vers
un nœud de gouvernance SUPPRIMÉ — alors que `governance.py` affirme en commentaire
« baskets id_node → NULL » à la suppression d'un nœud. Ce n'était pas vrai. Un identifiant
pendant devient critique maintenant que les gardes d'écriture sont calculées à partir de
lui : le panier serait devenu inéditable pour tout le monde sauf l'org-admin.

Déploiement NEUTRE, mesuré avant sur la production : 0 ligne dans `cms_basket_permissions`,
0 événement portant un panier, 0 panier rattaché à un nœud.

Revision ID: 0116
Revises: 0115
"""

from alembic import op

revision: str = "0116"
down_revision: str | None = "0115"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A3 — table morte
    op.execute("DROP TABLE IF EXISTS cms_basket_permissions")

    # A5 — un panier supprimé rend l'événement inerte au lieu de faire échouer la suppression
    op.execute("""
        DO $$
        DECLARE cname text;
        BEGIN
            SELECT conname INTO cname FROM pg_constraint
             WHERE conrelid = 'cms_events'::regclass AND contype = 'f'
               AND conkey = ARRAY[(SELECT attnum FROM pg_attribute
                                    WHERE attrelid = 'cms_events'::regclass
                                      AND attname = 'id_basket')];
            IF cname IS NOT NULL THEN
                EXECUTE format('ALTER TABLE cms_events DROP CONSTRAINT %I', cname);
            END IF;
        END $$;
    """)
    op.execute("""
        ALTER TABLE cms_events
          ADD CONSTRAINT fk_cms_events_basket
          FOREIGN KEY (id_basket) REFERENCES cms_audio_baskets(id_basket) ON DELETE SET NULL
    """)

    # A4-bis — le rattachement de gouvernance n'était garanti par rien
    op.execute("""
        ALTER TABLE cms_audio_baskets
          ADD CONSTRAINT fk_cms_audio_baskets_node
          FOREIGN KEY (id_node) REFERENCES cms_governance_nodes(id_node) ON DELETE SET NULL
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE cms_audio_baskets DROP CONSTRAINT IF EXISTS fk_cms_audio_baskets_node")
    op.execute("ALTER TABLE cms_events DROP CONSTRAINT IF EXISTS fk_cms_events_basket")
    op.execute("""
        ALTER TABLE cms_events
          ADD CONSTRAINT cms_events_id_basket_fkey
          FOREIGN KEY (id_basket) REFERENCES cms_audio_baskets(id_basket)
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS cms_basket_permissions (
            id_perm        BIGSERIAL PRIMARY KEY,
            id_basket      BIGINT NOT NULL REFERENCES cms_audio_baskets(id_basket) ON DELETE CASCADE,
            id_node        BIGINT,
            allowed_role   VARCHAR(50) NOT NULL,
            can_activate   BOOLEAN NOT NULL DEFAULT true,
            can_deactivate BOOLEAN NOT NULL DEFAULT true,
            can_edit_ratio BOOLEAN NOT NULL DEFAULT false,
            UNIQUE (id_basket, id_node, allowed_role)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_cbp_basket ON cms_basket_permissions(id_basket)")
