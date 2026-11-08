"""Audit Log — Sprint 1.10

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-25 00:00:00.000000

Creates:
  - cms_audit_log : immutable event log, RLS by id_org
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'cms_audit_log',
        sa.Column('id_audit', sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column('id_org', sa.BigInteger, sa.ForeignKey('cms_organizations.id_org', ondelete='SET NULL'), nullable=True),
        sa.Column('id_user', sa.BigInteger, sa.ForeignKey('cms_users.id_user', ondelete='SET NULL'), nullable=True),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('resource_type', sa.String(100), nullable=False),
        sa.Column('resource_id', sa.String(255), nullable=True),
        sa.Column('detail', JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index('ix_cms_audit_log_id_org', 'cms_audit_log', ['id_org'])
    op.create_index('ix_cms_audit_log_created_at', 'cms_audit_log', ['created_at'])

    op.execute("ALTER TABLE cms_audit_log ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cms_audit_log_org ON cms_audit_log "
        "USING (id_org = current_setting('app.current_org_id', true)::bigint)"
    )
    op.execute("GRANT SELECT, INSERT ON cms_audit_log TO signflow_app")
    op.execute("GRANT ALL ON cms_audit_log TO signflow_worker")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE cms_audit_log_id_audit_seq TO signflow_app")


def downgrade() -> None:
    op.drop_table('cms_audit_log')
