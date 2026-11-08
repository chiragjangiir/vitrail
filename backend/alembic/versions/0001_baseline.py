"""baseline

Revision ID: 0001
Revises:
Create Date: 2026-05-18 00:00:00.000000

"""
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Extensions (uuid-ossp, pgcrypto, vector, pg_partman) et rôle signflow_worker
    # sont créés par docker/postgres/init.sql — pas de migration nécessaire ici.
    pass


def downgrade() -> None:
    pass
