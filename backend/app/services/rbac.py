"""
Résolution des permissions effectives d'un utilisateur.

Algorithme :
  permissions_effectives =
    UNION(permissions directes non-deny + permissions via groupes)
    MINUS(permissions des rôles deny explicites)

SUPER_ADMIN bypass : toujours vrai.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_SUPER_ADMIN_KEY = "CMS_SUPER_ADMIN"
_ORG_ADMIN_KEY = "CMS_ORG_ADMIN"

_GET_USER_ROLES_SQL = text("""
    WITH direct_roles AS (
        SELECT ura.id_role, r.role_key
        FROM cms_user_role_assignments ura
        JOIN cms_roles r ON r.id_role = ura.id_role
        WHERE ura.id_user = :id_user AND ura.is_deny = false
    ),
    group_roles AS (
        SELECT gr.id_role, r.role_key
        FROM cms_group_roles gr
        JOIN cms_roles r ON r.id_role = gr.id_role
        JOIN cms_group_members gm ON gm.id_group = gr.id_group
        WHERE gm.id_user = :id_user
    ),
    denied_role_ids AS (
        SELECT ura.id_role
        FROM cms_user_role_assignments ura
        WHERE ura.id_user = :id_user AND ura.is_deny = true
    )
    SELECT DISTINCT role_key
    FROM (SELECT * FROM direct_roles UNION SELECT * FROM group_roles) all_roles
    WHERE id_role NOT IN (SELECT id_role FROM denied_role_ids)
""")

_GET_PERMISSIONS_SQL = text("""
    WITH user_role_ids AS (
        SELECT ura.id_role
        FROM cms_user_role_assignments ura
        WHERE ura.id_user = :id_user AND ura.is_deny = false
        UNION
        SELECT gr.id_role
        FROM cms_group_roles gr
        JOIN cms_group_members gm ON gm.id_group = gr.id_group
        WHERE gm.id_user = :id_user
    ),
    denied_role_ids AS (
        SELECT ura.id_role
        FROM cms_user_role_assignments ura
        WHERE ura.id_user = :id_user AND ura.is_deny = true
    )
    SELECT DISTINCT p.module || ':' || p.operation AS perm
    FROM cms_permissions p
    JOIN cms_role_permissions rp ON rp.id_permission = p.id_permission
    WHERE rp.id_role IN (SELECT id_role FROM user_role_ids)
    AND rp.id_role NOT IN (SELECT id_role FROM denied_role_ids)
""")


async def get_user_role_keys(db: AsyncSession, id_user: int) -> list[str]:
    result = await db.execute(_GET_USER_ROLES_SQL, {"id_user": id_user})
    return [row[0] for row in result.fetchall()]


#: Comptes ACTIFS d'une organisation qui détiennent le rôle d'administration.
#
# ⚠️ La résolution DOIT être identique à `_GET_USER_ROLES_SQL` — direct ∪ groupe, moins les
# refus explicites. Une garde qui ne compterait que les assignations DIRECTES verrait 0
# administrateur là où un groupe en porte un : elle refuserait des gestes légitimes, et
# surtout elle ne dirait plus la même chose que ce qui accorde réellement l'accès.
_ORG_ADMIN_IDS_SQL = text("""
    WITH direct_roles AS (
        SELECT ura.id_user, ura.id_role
        FROM cms_user_role_assignments ura
        WHERE ura.is_deny = false
    ),
    group_roles AS (
        SELECT gm.id_user, gr.id_role
        FROM cms_group_roles gr
        JOIN cms_group_members gm ON gm.id_group = gr.id_group
    ),
    all_roles AS (
        SELECT * FROM direct_roles UNION SELECT * FROM group_roles
    ),
    denied AS (
        SELECT ura.id_user, ura.id_role
        FROM cms_user_role_assignments ura
        WHERE ura.is_deny = true
    )
    SELECT DISTINCT u.id_user
    FROM cms_users u
    JOIN all_roles ar ON ar.id_user = u.id_user
    JOIN cms_roles r ON r.id_role = ar.id_role
    WHERE u.id_org = :id_org
      AND u.is_active = true
      AND r.role_key = :role_key
      AND NOT EXISTS (SELECT 1 FROM denied d
                       WHERE d.id_user = ar.id_user AND d.id_role = ar.id_role)
""")


async def org_admin_user_ids(db: AsyncSession, id_org: int) -> set[int]:
    """Comptes ACTIFS de l'organisation qui sont administrateurs (P3.3).

    Sert la garde « on ne retire pas le dernier administrateur » : sans elle, un porteur de
    `users:delete` qui n'est PAS org-admin peut désactiver tous les administrateurs et
    laisser l'organisation sans personne pour la rouvrir.
    """
    rows = await db.execute(_ORG_ADMIN_IDS_SQL, {"id_org": id_org, "role_key": _ORG_ADMIN_KEY})
    return {r[0] for r in rows.fetchall()}


async def get_user_permissions(db: AsyncSession, id_user: int) -> set[str]:
    result = await db.execute(_GET_PERMISSIONS_SQL, {"id_user": id_user})
    return {row[0] for row in result.fetchall()}


async def check_permission(
    db: AsyncSession, id_user: int, module: str, operation: str
) -> bool:
    """Vérifie si l'utilisateur a la permission module:operation."""
    role_keys = await get_user_role_keys(db, id_user)
    if _SUPER_ADMIN_KEY in role_keys:
        return True
    permissions = await get_user_permissions(db, id_user)
    return f"{module}:{operation}" in permissions


async def user_is_server_operator(db: AsyncSession, user) -> bool:
    """L'utilisateur EXPLOITE-t-il ce serveur ?

    Deux cas :
      · **super-admin** → oui ;
      · **org-admin d'un serveur SANS super-admin actif** → oui : installation autonome,
        il est l'exploitant et personne d'autre ne peut agir.
    Un org-admin d'une organisation hébergée sur un serveur qui a un super-admin → non.

    Définition UNIQUE, partagée par les gestes d'exploitant (firmware, signalétique serveur).
    """
    from sqlalchemy import select

    from app.models.role import CmsRole, CmsUserRoleAssignment
    from app.models.user import CmsUser

    roles = await get_user_role_keys(db, user.id_user)
    if "CMS_SUPER_ADMIN" in roles:
        return True
    if "CMS_ORG_ADMIN" not in roles:
        return False
    exists_super = (await db.execute(
        select(CmsUser.id_user)
        .join(CmsUserRoleAssignment, CmsUserRoleAssignment.id_user == CmsUser.id_user)
        .join(CmsRole, CmsRole.id_role == CmsUserRoleAssignment.id_role)
        .where(CmsRole.role_key == "CMS_SUPER_ADMIN", CmsUser.is_active.is_(True))
        .limit(1)
    )).scalar_one_or_none()
    return exists_super is None
