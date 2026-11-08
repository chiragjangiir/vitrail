"""Retire `schedules:activate` — permission MORTE (décision d'Ed, 2026-07-31).

Seedée par 0002, vérifiée NULLE PART : activer/désactiver un programme passe par
`PUT /schedules/{id}` (champ `is_active`), gardé par `schedules:edit`. Mesuré en prod
avant retrait : **3 rôles la portaient** — trois promesses fausses dans l'éditeur de
rôles (même constat que `templates:publish`, retirée par la 0115 sur le même patron).

`downgrade` la recrée à l'identique, mais SANS la réattribuer : rien ne la lisait,
donc aucun comportement ne dépendait de qui la détenait.

Revision ID: 0120
Revises: 0119
"""

from alembic import op

revision: str = "0120"
down_revision: str | None = "0119"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DELETE FROM cms_role_permissions WHERE id_permission IN (
            SELECT id_permission FROM cms_permissions
             WHERE module = 'schedules' AND operation = 'activate')
    """)
    op.execute("DELETE FROM cms_permissions WHERE module = 'schedules' AND operation = 'activate'")


def downgrade() -> None:
    op.execute("""
        INSERT INTO cms_permissions (module, operation, label)
        VALUES ('schedules', 'activate', 'Activer un schedule')
        ON CONFLICT ON CONSTRAINT uq_cms_permissions_module_operation DO NOTHING
    """)
