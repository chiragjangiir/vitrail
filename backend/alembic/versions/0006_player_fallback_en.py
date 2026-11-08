"""Players — fallback_video_message default EN

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-23 00:00:00.000000

Corrige le DEFAULT de fallback_video_message (était en français).
Met aussi à jour les lignes existantes qui avaient la valeur française.
"""

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE cms_players
            ALTER COLUMN fallback_video_message SET DEFAULT 'No content to display'
    """)
    op.execute("""
        UPDATE cms_players
        SET fallback_video_message = 'No content to display'
        WHERE fallback_video_message IN ('Aucun contenu a diffuser', 'Aucun contenu à diffuser')
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE cms_players
            ALTER COLUMN fallback_video_message SET DEFAULT 'Aucun contenu à diffuser'
    """)
