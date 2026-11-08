"""Crée `events:edit` — la permission qui manquait au catalogue (audit Events, 2026-07-29).

**Le défaut.** `PUT /events/{id}` — qui réécrit le nom, le CONTENU diffusé, la priorité, les
CIBLES, l'embargo et le nœud de gouvernance — était gardé par **`events:trigger`**, une
permission de *déclenchement*. Tout porteur du droit de déclencher détenait donc l'écriture
complète.

**Pourquoi personne ne l'avait vu.** La migration 0099 croyait accorder `events:edit` au rôle
CMS_SCHEDULER : son `INSERT … SELECT … WHERE (module, operation) IN (…)` ne correspondait à
rien, puisque le seed 0002 ne déclare que `events:create|read|trigger|delete`. C'était donc
un **no-op silencieux**. Et le test censé couvrir la matrice des rôles **crée lui-même** la
permission dans sa base — le trou du catalogue lui était invisible. Mesuré sur la production
avant correctif : `events:edit` = **0 ligne**, quand `events:read`, `events:trigger` et
`vod:edit` en ont bien une.

**ADDITIF, et pas une bascule sèche** — même discipline que la 0114 (sous-modules médias) :
on ne retire RIEN. Tout rôle détenant déjà `events:trigger` reçoit `events:edit`, y compris
les rôles PERSONNALISÉS d'un client qu'on ne connaît pas. Sans cela, la bascule de `PUT`
enfermerait des utilisateurs qui éditent des événements aujourd'hui — et le produit tourne
déjà chez un client.

⚠️ Contrepartie assumée : `events:trigger` reste, pour qui le détenait déjà, un passe-partout
vers l'édition. Ce que la migration change, c'est qu'à partir de maintenant on peut créer un
rôle qui **déclenche sans pouvoir modifier** — ce qui était impossible.

Revision ID: 0117
Revises: 0116
"""

from alembic import op

revision: str = "0117"
down_revision: str | None = "0116"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO cms_permissions (module, operation, label)
        VALUES ('events', 'edit', 'Modifier — Événements')
        ON CONFLICT ON CONSTRAINT uq_cms_permissions_module_operation DO NOTHING
    """)
    # Additif : qui pouvait éditer via `trigger` continue de pouvoir éditer.
    op.execute("""
        INSERT INTO cms_role_permissions (id_role, id_permission)
        SELECT rp.id_role, new_p.id_permission
          FROM cms_role_permissions rp
          JOIN cms_permissions old_p ON old_p.id_permission = rp.id_permission
         CROSS JOIN cms_permissions new_p
         WHERE old_p.module = 'events' AND old_p.operation = 'trigger'
           AND new_p.module = 'events' AND new_p.operation = 'edit'
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM cms_role_permissions rp
         USING cms_permissions p
         WHERE rp.id_permission = p.id_permission
           AND p.module = 'events' AND p.operation = 'edit'
    """)
    op.execute("DELETE FROM cms_permissions WHERE module = 'events' AND operation = 'edit'")
