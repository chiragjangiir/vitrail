"""Donne `players:read` au Campaign Manager (décision Ed 2026-07-21).

Le rôle CMS_CAMPAIGN_MANAGER gère des campagnes CIBLÉES sur des sites / players /
groupes, mais ne détenait pas `players:read` — or les sélecteurs de cible du drawer
campagne (et la carte) listent sites/players/groupes via des endpoints gatés
`players:read`. Résultat : toutes les listes de cibles étaient VIDES et la carte
vide, rendant impossible la création d'une campagne ciblée.

On ajoute donc `players:read` au rôle système. Effet voulu : le CM voit désormais
les menus Players et Sites EN LECTURE (contexte légitime pour cibler). Idempotent
(ON CONFLICT DO NOTHING) ; la permission existe déjà au catalogue (seed 0002).

NB complémentaire (hors migration, dans le CODE) : les listes `/player-groups/` et
`/site-groups/` étaient gatées `require_org_admin` — relâchées à
`require_admin_or_permission("players","read")` dans le même lot, sinon le CM (et
le Planificateur, latent) auraient toujours des groupes vides.

Revision ID: 0100
Revises: 0099
"""

from alembic import op

revision: str = "0100"
down_revision: str | None = "0099"
branch_labels = None
depends_on = None


_PAIRS = "('players','read')"

_GRANT = f"""
INSERT INTO cms_role_permissions (id_role, id_permission)
SELECT r.id_role, p.id_permission
FROM cms_roles r, cms_permissions p
WHERE r.role_key = 'CMS_CAMPAIGN_MANAGER' AND r.is_system = true
  AND (p.module, p.operation) IN ({_PAIRS})
ON CONFLICT DO NOTHING
"""

_REVOKE = f"""
DELETE FROM cms_role_permissions rp
USING cms_roles r, cms_permissions p
WHERE rp.id_role = r.id_role
  AND rp.id_permission = p.id_permission
  AND r.role_key = 'CMS_CAMPAIGN_MANAGER' AND r.is_system = true
  AND (p.module, p.operation) IN ({_PAIRS})
"""


def upgrade() -> None:
    op.execute(_GRANT)


def downgrade() -> None:
    op.execute(_REVOKE)
