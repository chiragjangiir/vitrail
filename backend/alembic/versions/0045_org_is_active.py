"""Organisation active/inactive (suspension par le super-admin)

Revision ID: 0045
Revises: 0044
Create Date: 2026-06-19 00:00:00.000000

Ajoute `is_active` à cms_organizations. Une org suspendue (is_active=false) :
ses utilisateurs ne peuvent plus se connecter (sauf super-admin). Réversible —
les données / players sont conservés.
"""

from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cms_organizations ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT true"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cms_organizations DROP COLUMN is_active")
