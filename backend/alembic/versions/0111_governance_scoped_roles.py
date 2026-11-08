"""Rôles DÉDIÉS à la gouvernance §XVIII — phase 3 de l'audit du 2026-07-27 (décision G4).

Constat de l'audit : les deux rôles seedés le 21/07 (migr 0101) portent des verbes, pas un
périmètre. Un « programmeur de site » pouvait donc éditer une playlist d'org, créer un
programme visant n'importe quel écran et modifier un template partagé (défaut N3) : sa
restriction ne venait que de son assignation comme admin de nœud, qui ne dit rien du
contenu NON gouverné.

**G4 (Ed, 2026-07-27) : LE RÔLE PORTE LA SÉMANTIQUE DE PÉRIMÈTRE.** Un porteur d'un rôle de
gouvernance n'agit que dans son sous-arbre, **et ce qui n'est pas gouverné lui est
invisible**. Sans cela un « scheduler gouvernance » éditerait encore le non-gouverné —
N3 renommé, pas corrigé. ⛔ Écarté par Ed : déduire la restriction du seul fait d'être admin
de nœud, ce qui changerait le comportement d'utilisateurs existants sans décision.

La liste des rôles concernés vit dans `app/services/governance_access.GOVERNANCE_SCOPED_ROLES`
(pas de colonne : le marquage doit être lisible avec le code qui l'applique).

Cette migration :
  1. **recadre** les deux rôles existants (libellés + description) plutôt que d'empiler ;
  2. donne `approvals:submit` au Programmeur — **défaut N4** : il soumettait à l'approbation
     (200) puis recevait 403 sur `/approvals`, donc ne voyait JAMAIS un « modifications
     demandées » ; et `playlists:create/edit`, sans quoi il ne peut pas faire son travail ;
  3. ajoute **Éditeur** (contenu du nœud, sans `media:delete`) et **Valideur** (décide, ne
     produit pas).

Idempotent (ON CONFLICT DO NOTHING). Aucune donnée utilisateur touchée : les affectations
existantes de rôles restent telles quelles.

Revision ID: 0111
Revises: 0110
"""

from alembic import op

revision: str = "0111"
down_revision: str | None = "0110"
branch_labels = None
depends_on = None


# (role_key, label, description)
_ROLES = [
    ("CMS_GOVERNANCE_MANAGER", "Gouvernance — Directeur",
     "Bâtit et délègue la hiérarchie de gouvernance (§XVIII) : nœuds, périmètres, "
     "administrateurs, règles. N'agit que dans son sous-arbre ; le contenu non gouverné "
     "ne lui est pas visible."),
    ("CMS_SITE_PROGRAMMER", "Gouvernance — Programmeur",
     "Programme la diffusion des nœuds qu'il administre (programmes + playlists) et soumet "
     "à l'approbation. N'agit que dans son sous-arbre ; le contenu non gouverné ne lui est "
     "pas visible."),
    ("CMS_GOVERNANCE_EDITOR", "Gouvernance — Éditeur",
     "Produit le contenu des nœuds qu'il administre (playlists, médias) et le soumet à "
     "l'approbation. Ne supprime aucun média, ne programme pas la diffusion."),
    ("CMS_GOVERNANCE_APPROVER", "Gouvernance — Valideur",
     "Décide des demandes d'approbation portant sur son sous-arbre. Ne décide jamais sur sa "
     "propre soumission."),
]

_PERMS = {
    # Le Directeur construit la structure ; il ne produit pas le contenu (lecture seule).
    "CMS_GOVERNANCE_MANAGER": (
        "('governance','read'),('governance','edit'),('governance','delegate'),"
        "('players','read'),('schedules','read'),('playlists','read'),('media','read')"
    ),
    # Le Programmeur diffuse : programmes + playlists de SON nœud, et soumet (N4).
    "CMS_SITE_PROGRAMMER": (
        "('schedules','create'),('schedules','read'),('schedules','edit'),"
        "('schedules','delete'),"
        "('playlists','create'),('playlists','read'),('playlists','edit'),"
        "('media','read'),('players','read'),('governance','read'),"
        "('approvals','submit')"
    ),
    # L'Éditeur produit : playlists + médias, sans jamais SUPPRIMER un média (un local ne
    # doit pas pouvoir effacer un média national — c'est ce que l'audit a mesuré en N3).
    "CMS_GOVERNANCE_EDITOR": (
        "('playlists','create'),('playlists','read'),('playlists','edit'),"
        "('media','read'),('media','edit'),('governance','read'),"
        "('approvals','submit')"
    ),
    # Le Valideur décide et lit ce qu'il valide ; il ne produit rien.
    "CMS_GOVERNANCE_APPROVER": (
        "('approvals','review'),('approvals','approve'),('approvals','reject'),"
        "('playlists','read'),('media','read'),('schedules','read'),('governance','read')"
    ),
}


def upgrade() -> None:
    for role_key, label, desc in _ROLES:
        label_sql = label.replace("'", "''")
        desc_sql = desc.replace("'", "''")
        # Recadrage : si le rôle existe déjà (0101), on met à jour libellé + description.
        op.execute(f"""
            INSERT INTO cms_roles (role_key, label, description, is_system)
            VALUES ('{role_key}', '{label_sql}', '{desc_sql}', true)
            ON CONFLICT (role_key) DO UPDATE
              SET label = EXCLUDED.label, description = EXCLUDED.description
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
    # Les 2 rôles de la 0101 sont conservés (ils préexistaient) ; seuls les 2 nouveaux
    # partent, avec leurs permissions.
    for role_key in ("CMS_GOVERNANCE_EDITOR", "CMS_GOVERNANCE_APPROVER"):
        op.execute(f"""
            DELETE FROM cms_role_permissions rp
            USING cms_roles r
            WHERE rp.id_role = r.id_role AND r.role_key = '{role_key}'
        """)
        op.execute(f"DELETE FROM cms_roles WHERE role_key = '{role_key}' AND is_system = true")
