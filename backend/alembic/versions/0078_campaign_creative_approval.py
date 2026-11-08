"""Retail Media S5 — approbation des créatifs de campagne (optionnelle par org)

Revision ID: 0078
Revises: 0077

Décision Ed 2026-07-09 (+ archi 2026-07-10) : approbation INLINE légère sur
`cms_campaign_creatives` (pattern moderation_status des feeds §25) — le module
Approval Workflow §21 générique viendra avec le portail annonceur (S7).

- `cms_organizations.campaign_creative_approval` (défaut FALSE = comportement
  actuel inchangé) : quand TRUE, tout nouveau créatif naît `pending` et seuls
  les créatifs `approved` sont diffusés (gate campaign_delivery) / comptent
  pour la publication.
- `cms_campaign_creatives.approval_status` ('pending'|'approved'|'rejected',
  défaut 'approved' → les créatifs existants restent diffusables) +
  `reviewed_by`/`reviewed_at`.

Endpoints de revue gatés par le RBAC §21 déjà seedé (approvals:approve/reject,
rôle CMS_APPROVER) — premier consommateur réel de ces permissions.
"""

from alembic import op

revision: str = "0078"
down_revision: str | None = "0077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cms_organizations "
        "ADD COLUMN campaign_creative_approval BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        """
        ALTER TABLE cms_campaign_creatives
            ADD COLUMN approval_status VARCHAR(20) NOT NULL DEFAULT 'approved',
            ADD COLUMN reviewed_by BIGINT REFERENCES cms_users(id_user) ON DELETE SET NULL,
            ADD COLUMN reviewed_at TIMESTAMPTZ
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE cms_campaign_creatives DROP COLUMN reviewed_at, "
        "DROP COLUMN reviewed_by, DROP COLUMN approval_status"
    )
    op.execute("ALTER TABLE cms_organizations DROP COLUMN campaign_creative_approval")
