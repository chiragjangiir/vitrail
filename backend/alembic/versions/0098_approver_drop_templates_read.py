"""Retire `templates:read` du rôle CMS_APPROVER (retour Ed 2026-07-21).

L'Approbateur voyait le menu « Templates » (gaté `templates:read` côté sidebar)
sans utilité : l'approbation §21 ne porte aujourd'hui que sur des CRÉATIFS de
campagne (= des médias). `media:read` suffit au contexte de revue ; la lecture
des templates n'apporte rien à ce rôle et brouille son périmètre.

On retire donc la seule permission `templates:read` du rôle système CMS_APPROVER.
Sur une installation neuve, 0002 la seede puis cette migration la retire — net :
absente. `playlists:read` est conservée (garde du sens si l'approbation s'étend
un jour aux playlists).

Idempotent : le DELETE ne fait rien si la ligne n'existe pas.

Revision ID: 0098
Revises: 0097
"""

from alembic import op

revision: str = "0098"
down_revision: str | None = "0097"
branch_labels = None
depends_on = None


_DELETE = """
DELETE FROM cms_role_permissions rp
USING cms_roles r, cms_permissions p
WHERE rp.id_role = r.id_role
  AND rp.id_permission = p.id_permission
  AND r.role_key = 'CMS_APPROVER' AND r.is_system = true
  AND p.module = 'templates' AND p.operation = 'read'
"""

_RESTORE = """
INSERT INTO cms_role_permissions (id_role, id_permission)
SELECT r.id_role, p.id_permission
FROM cms_roles r, cms_permissions p
WHERE r.role_key = 'CMS_APPROVER' AND r.is_system = true
  AND p.module = 'templates' AND p.operation = 'read'
ON CONFLICT DO NOTHING
"""


def upgrade() -> None:
    op.execute(_DELETE)


def downgrade() -> None:
    op.execute(_RESTORE)
