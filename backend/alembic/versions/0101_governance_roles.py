"""Deux rôles système pour la Gouvernance §XVIII (décision Ed 2026-07-21).

Constat : AUCUN rôle métier prédéfini ne portait de permission `governance:*` — seul
l'org-admin pouvait donc utiliser la gouvernance. Or le besoin est double :
  1. quelqu'un qui BÂTIT et DÉLÈGUE la hiérarchie (national/enseigne) ;
  2. des utilisateurs de SITE qui PROGRAMMENT du contenu DANS les règles.

On seed deux rôles système prêts à l'emploi :

- **CMS_GOVERNANCE_MANAGER** — gère la gouvernance de bout en bout :
  governance:read/edit/delegate (arbre + affectations + nomination des admins de nœud)
  + players/schedules/playlists/media:read (voir/organiser les contenus gouvernés).

- **CMS_SITE_PROGRAMMER** — programme du contenu, encadré par les règles :
  schedules:create/read/edit/delete + playlists/media/players:read (programmer + cibler)
  + governance:read (voir/choisir son nœud). ⚠️ La PERMISSION ne suffit pas : le scoping
  vient de l'assignation comme **admin de nœud** (services/governance_access.user_can_edit_node
  vérifie CmsGovernanceNodeAdmin), posée par un gestionnaire via governance:delegate.
  L'immutabilité des couches parentes (§18.4) s'applique alors automatiquement.

Idempotent : ON CONFLICT (role_key) DO NOTHING pour les rôles, ON CONFLICT DO NOTHING
pour les liens. Les permissions existent déjà au catalogue (seed 0002).

Revision ID: 0101
Revises: 0100
"""

from alembic import op

revision: str = "0101"
down_revision: str | None = "0100"
branch_labels = None
depends_on = None


_ROLES = [
    ("CMS_GOVERNANCE_MANAGER", "Gestionnaire de gouvernance",
     "Bâtit et délègue la hiérarchie de gouvernance (§XVIII) — nœuds, affectations, "
     "administrateurs de nœud. Voit les contenus et programmes gouvernés."),
    ("CMS_SITE_PROGRAMMER", "Programmeur de site",
     "Programme du contenu encadré par les règles de gouvernance (§XVIII). Portée limitée "
     "à sa branche via son assignation comme administrateur de nœud."),
]

_PERMS = {
    "CMS_GOVERNANCE_MANAGER": (
        "('governance','read'),('governance','edit'),('governance','delegate'),"
        "('players','read'),('schedules','read'),('playlists','read'),('media','read')"
    ),
    "CMS_SITE_PROGRAMMER": (
        "('schedules','create'),('schedules','read'),('schedules','edit'),"
        "('schedules','delete'),('playlists','read'),('media','read'),"
        "('players','read'),('governance','read')"
    ),
}


def upgrade() -> None:
    for role_key, label, desc in _ROLES:
        op.execute(f"""
            INSERT INTO cms_roles (role_key, label, description, is_system)
            VALUES ('{role_key}', '{label}', '{desc}', true)
            ON CONFLICT (role_key) DO NOTHING
        """)
    for role_key, pairs in _PERMS.items():
        op.execute(f"""
            INSERT INTO cms_role_permissions (id_role, id_permission)
            SELECT r.id_role, p.id_permission
            FROM cms_roles r, cms_permissions p
            WHERE r.role_key = '{role_key}' AND r.is_system = true
              AND (p.module, p.operation) IN ({pairs})
            ON CONFLICT DO NOTHING
        """)


def downgrade() -> None:
    for role_key in _PERMS:
        op.execute(f"""
            DELETE FROM cms_role_permissions rp
            USING cms_roles r
            WHERE rp.id_role = r.id_role AND r.role_key = '{role_key}'
        """)
    for role_key, _label, _desc in _ROLES:
        op.execute(f"DELETE FROM cms_roles WHERE role_key = '{role_key}' AND is_system = true")
