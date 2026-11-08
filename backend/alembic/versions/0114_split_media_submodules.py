"""Permissions propres pour flux / pages web / tags / génération IA (séparation ADDITIVE).

Constat d'Ed (audit du menu Média, 2026-07-28) : « tu ne peux pas confier la gestion des
flux à quelqu'un sans lui ouvrir toute la médiathèque en écriture — suppression de vidéos
comprise ». Les 33 routes de ces quatre modules étaient toutes gatées `media:*`, et aucun
de ces modules n'existait dans le catalogue de permissions (seuls `media` et
`audio_baskets` y figuraient).

⚠️ ADDITIVE, pas une bascule sèche. Le produit tourne déjà chez un client et **16 comptes**
portent `media:edit` via 4 rôles — dont des rôles PERSONNALISÉS qu'un client a pu créer et
que nous ne connaissons pas. Cette migration ne RETIRE donc rien : elle crée les nouvelles
permissions et les donne à tous les rôles qui détiennent déjà l'équivalent `media`. Le code
accepte l'ancienne OU la nouvelle (`require_any_permission`). Résultat : personne ne perd
d'accès, et un rôle « gestionnaire de flux » devient enfin possible.

Revision ID: 0114
Revises: 0113
"""

from alembic import op

revision: str = "0114"
down_revision: str | None = "0113"
branch_labels = None
depends_on = None

# Nouveau module → opérations, et l'opération `media` dont il HÉRITE les détenteurs.
_MODULES: dict[str, dict[str, str]] = {
    # Flux de données (§XXV) — RSS/Atom, réseaux sociaux, météo…
    "feeds": {"read": "read", "create": "create", "edit": "edit", "delete": "delete"},
    # Pages web affichées (§XXV) — URL Display.
    "url_display": {"read": "read", "create": "create", "edit": "edit", "delete": "delete"},
    # Espaces de noms et valeurs de tags (§XVII).
    "tags": {"read": "read", "edit": "edit"},
    # Génération de contenu par IA (§ BYOK) — coûte de l'argent au client : la déléguer
    # séparément de la médiathèque a une vraie valeur.
    "generation": {"read": "read", "create": "create"},
}

_LABELS = {
    "feeds": "Flux de données",
    "url_display": "Pages web",
    "tags": "Tags",
    "generation": "Génération IA",
}
_OPS = {"read": "Lire", "create": "Créer", "edit": "Modifier", "delete": "Supprimer"}


def upgrade() -> None:
    for module, ops in _MODULES.items():
        for operation, inherits_from in ops.items():
            label = f"{_OPS[operation]} — {_LABELS[module]}"
            op.execute(f"""
                INSERT INTO cms_permissions (module, operation, label)
                VALUES ('{module}', '{operation}', '{label}')
                ON CONFLICT ON CONSTRAINT uq_cms_permissions_module_operation DO NOTHING
            """)
            # Tout rôle qui détient déjà l'équivalent `media` reçoit la nouvelle : c'est
            # ce qui rend la migration NEUTRE pour les 16 comptes existants, rôles
            # personnalisés des clients compris.
            op.execute(f"""
                INSERT INTO cms_role_permissions (id_role, id_permission)
                SELECT rp.id_role, np.id_permission
                FROM cms_role_permissions rp
                JOIN cms_permissions mp
                  ON mp.id_permission = rp.id_permission
                 AND mp.module = 'media' AND mp.operation = '{inherits_from}'
                CROSS JOIN cms_permissions np
                WHERE np.module = '{module}' AND np.operation = '{operation}'
                ON CONFLICT DO NOTHING
            """)


def downgrade() -> None:
    for module in _MODULES:
        op.execute(f"""
            DELETE FROM cms_role_permissions WHERE id_permission IN (
                SELECT id_permission FROM cms_permissions WHERE module = '{module}')
        """)
        op.execute(f"DELETE FROM cms_permissions WHERE module = '{module}'")
