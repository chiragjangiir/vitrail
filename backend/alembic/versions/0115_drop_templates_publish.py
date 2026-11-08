"""Retire `templates:publish` — permission MORTE (décision d'Ed, 2026-07-28).

Seedée par 0002, elle n'a jamais été vérifiée nulle part : aucun endpoint ne la lit, il
n'existe aucune notion de « publication » pour un template. Ed, au constat : « soit on la
retire soit on implémente, la première me semble plus adéquate ».

Pourquoi ça compte au-delà du ménage : une permission qu'on peut cocher dans l'éditeur de
rôles et qui n'accorde RIEN est une promesse fausse faite à l'administrateur. C'est
exactement ce que l'audit des rôles du 2026-07-20 avait relevé (27 permissions décoratives)
et ce que `gen_role_matrix.py` existe pour rendre visible.

`downgrade` la recrée à l'identique, mais SANS la réattribuer : rien ne la lisait, donc
aucun comportement ne dépendait de qui la détenait.

Revision ID: 0115
Revises: 0114
"""

from alembic import op

revision: str = "0115"
down_revision: str | None = "0114"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DELETE FROM cms_role_permissions WHERE id_permission IN (
            SELECT id_permission FROM cms_permissions
             WHERE module = 'templates' AND operation = 'publish')
    """)
    op.execute("DELETE FROM cms_permissions WHERE module = 'templates' AND operation = 'publish'")


def downgrade() -> None:
    op.execute("""
        INSERT INTO cms_permissions (module, operation, label)
        VALUES ('templates', 'publish', 'Publier — Templates')
        ON CONFLICT ON CONSTRAINT uq_cms_permissions_module_operation DO NOTHING
    """)
