"""Player Groups — Sprint 1.7

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-25 00:00:00.000000

Creates:
  - cms_player_groups       : named groups of players, per org
  - cms_player_group_members: many-to-many players <-> groups
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cms_player_groups",
        sa.Column("id_group", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("id_org", sa.BigInteger(), nullable=False),
        sa.Column("group_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["id_org"], ["cms_organizations.id_org"]),
        sa.PrimaryKeyConstraint("id_group"),
        sa.UniqueConstraint("id_org", "group_name", name="uq_player_group_name_per_org"),
    )
    op.create_index("ix_cms_player_groups_id_org", "cms_player_groups", ["id_org"])

    op.create_table(
        "cms_player_group_members",
        sa.Column("id_group", sa.BigInteger(), nullable=False),
        sa.Column("id_player", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["id_group"], ["cms_player_groups.id_group"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["id_player"], ["cms_players.id_player"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id_group", "id_player"),
    )

    # RLS
    for table in ("cms_player_groups", "cms_player_group_members"):
        op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))

    op.execute(sa.text("""
        CREATE POLICY cms_player_groups_org_isolation ON cms_player_groups
            AS PERMISSIVE FOR ALL
            USING (id_org = current_setting('app.current_org_id', true)::BIGINT)
    """))

    # For members, join to groups to check org
    op.execute(sa.text("""
        CREATE POLICY cms_player_group_members_org_isolation ON cms_player_group_members
            AS PERMISSIVE FOR ALL
            USING (
                id_group IN (
                    SELECT id_group FROM cms_player_groups
                    WHERE id_org = current_setting('app.current_org_id', true)::BIGINT
                )
            )
    """))

    op.execute(sa.text("GRANT SELECT, INSERT, UPDATE, DELETE ON cms_player_groups TO signflow_app"))
    op.execute(sa.text("GRANT ALL ON cms_player_groups TO signflow_worker"))
    op.execute(sa.text("GRANT SELECT, INSERT, DELETE ON cms_player_group_members TO signflow_app"))
    op.execute(sa.text("GRANT ALL ON cms_player_group_members TO signflow_worker"))
    op.execute(sa.text(
        "GRANT USAGE, SELECT ON SEQUENCE cms_player_groups_id_group_seq TO signflow_app"
    ))
    op.execute(sa.text(
        "GRANT USAGE, SELECT ON SEQUENCE cms_player_groups_id_group_seq TO signflow_worker"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS cms_player_group_members CASCADE"))
    op.execute(sa.text("DROP TABLE IF EXISTS cms_player_groups CASCADE"))
