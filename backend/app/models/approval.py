from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsApprovalRequest(Base):
    """Demande d'approbation §XXI (générique, migr 0081). TENANT-SCOPED (RLS).

    Machine à états : pending_review → approved | rejected | changes_requested
    (→ resubmit → pending_review) ; approved → published (marqué par le module
    ressource au moment de SA publication — ex. publish campagne). rejected /
    published = terminaux. Une seule demande ACTIVE par ressource (index unique
    partiel `uq_car_active_per_resource`).
    """

    __tablename__ = "cms_approval_requests"

    id_request: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org", ondelete="CASCADE"),
        nullable=False, index=True
    )
    resource_type: Mapped[str] = mapped_column(String(30), nullable=False)
    resource_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    submitted_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user"), nullable=False
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(30), server_default="pending_review", default="pending_review", nullable=False
    )
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Cloche portail (retour Ed #8, migr 0086) : décision vue par le soumetteur.
    submitter_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class CmsApprovalComment(Base):
    """Commentaire / trace d'action sur une demande §XXI. TENANT-SCOPED (RLS).

    `action` : submitted | approved | rejected | changes_requested | resubmitted |
    published | NULL (commentaire libre).
    """

    __tablename__ = "cms_approval_comments"

    id_comment: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_request: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_approval_requests.id_request", ondelete="CASCADE"),
        nullable=False, index=True
    )
    # Dénormalisé pour la policy RLS standard (pattern 0074/0079).
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org", ondelete="CASCADE"), nullable=False
    )
    id_user: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user"), nullable=False
    )
    comment_text: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
