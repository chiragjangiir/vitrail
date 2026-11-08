"""Donne au Planificateur le contrôle TOTAL des événements et de la VOD (décision Ed 2026-07-21).

Le rôle CMS_SCHEDULER pouvait CRÉER et DÉCLENCHER des événements/VOD mais ni les
éditer ni les supprimer — même les siens. Un planificateur qui se trompe restait
donc coincé avec un objet erroné. Décision : il gère événements et VOD de bout en
bout, comme il gère déjà les Programmes (schedules = create/edit/delete/read).

On ajoute donc `events:edit`, `events:delete`, `vod:edit`, `vod:delete` au rôle
système. Idempotent (ON CONFLICT DO NOTHING) ; les permissions existent déjà au
catalogue (seed 0002).

Revision ID: 0099
Revises: 0098
"""

from alembic import op

revision: str = "0099"
down_revision: str | None = "0098"
branch_labels = None
depends_on = None


_PAIRS = "('events','edit'),('events','delete'),('vod','edit'),('vod','delete')"

_GRANT = f"""
INSERT INTO cms_role_permissions (id_role, id_permission)
SELECT r.id_role, p.id_permission
FROM cms_roles r, cms_permissions p
WHERE r.role_key = 'CMS_SCHEDULER' AND r.is_system = true
  AND (p.module, p.operation) IN ({_PAIRS})
ON CONFLICT DO NOTHING
"""

_REVOKE = f"""
DELETE FROM cms_role_permissions rp
USING cms_roles r, cms_permissions p
WHERE rp.id_role = r.id_role
  AND rp.id_permission = p.id_permission
  AND r.role_key = 'CMS_SCHEDULER' AND r.is_system = true
  AND (p.module, p.operation) IN ({_PAIRS})
"""


def upgrade() -> None:
    op.execute(_GRANT)


def downgrade() -> None:
    op.execute(_REVOKE)
