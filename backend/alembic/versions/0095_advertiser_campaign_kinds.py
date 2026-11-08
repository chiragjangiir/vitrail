"""Retail Media AUDIO S3 — types de campagne autorisés par annonceur (portail).

Deux flags sur `cms_advertisers` qui gatent le PORTAIL self-service uniquement (le
retailer CMS reste libre de créer n'importe quel type pour n'importe quel annonceur) :
- `allow_visual_campaigns` (défaut TRUE) : l'annonceur peut créer des campagnes visuelles ;
- `allow_audio_campaigns` (défaut FALSE) : l'annonceur peut créer des campagnes audio (spots).

Revision ID: 0095
Revises: 0094
"""

from alembic import op

revision: str = "0095"
down_revision: str | None = "0094"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cms_advertisers ADD COLUMN allow_visual_campaigns BOOLEAN "
        "NOT NULL DEFAULT TRUE"
    )
    op.execute(
        "ALTER TABLE cms_advertisers ADD COLUMN allow_audio_campaigns BOOLEAN "
        "NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cms_advertisers DROP COLUMN allow_audio_campaigns")
    op.execute("ALTER TABLE cms_advertisers DROP COLUMN allow_visual_campaigns")
