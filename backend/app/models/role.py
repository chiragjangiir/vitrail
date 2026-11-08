from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsRole(Base):
    """Rôles système (is_system=True) et custom par org (§II.1)."""

    __tablename__ = "cms_roles"

    id_role: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # NULL = rôle système global visible par toutes les orgs
    id_org: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=True, index=True
    )
    role_key: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class CmsPermission(Base):
    """Catalogue des permissions atomiques module:opération (§II.1)."""

    __tablename__ = "cms_permissions"

    id_permission: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    module: Mapped[str] = mapped_column(String(50), nullable=False)
    operation: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)

    __table_args__ = (
        UniqueConstraint("module", "operation", name="uq_cms_permissions_module_operation"),
    )


class CmsRolePermission(Base):
    """Association rôle → permission."""

    __tablename__ = "cms_role_permissions"

    id_role: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("cms_roles.id_role", ondelete="CASCADE"),
        primary_key=True,
    )
    id_permission: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("cms_permissions.id_permission", ondelete="CASCADE"),
        primary_key=True,
    )


class CmsUserGroup(Base):
    """Groupes d'utilisateurs par organisation (§II.1)."""

    __tablename__ = "cms_user_groups"

    id_group: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("cms_organizations.id_org", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    group_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # org | site | player_group
    scope_type: Mapped[str] = mapped_column(
        String(20), server_default="org", nullable=False
    )
    scope_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)

    __table_args__ = (
        UniqueConstraint("id_org", "group_name", name="uq_cms_user_groups_org_name"),
    )


class CmsGroupMember(Base):
    """Appartenance des users aux groupes."""

    __tablename__ = "cms_group_members"

    id_group: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("cms_user_groups.id_group", ondelete="CASCADE"),
        primary_key=True,
    )
    id_user: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("cms_users.id_user", ondelete="CASCADE"),
        primary_key=True,
    )
    added_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
    added_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user"), nullable=True
    )


class CmsGroupRole(Base):
    """Rôles assignés aux groupes."""

    __tablename__ = "cms_group_roles"

    id_group: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("cms_user_groups.id_group", ondelete="CASCADE"),
        primary_key=True,
    )
    id_role: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("cms_roles.id_role", ondelete="CASCADE"),
        primary_key=True,
    )


class CmsUserRoleAssignment(Base):
    """Rôles directs sur un user — deny explicite prime sur tout héritage (§II.1)."""

    __tablename__ = "cms_user_role_assignments"

    id_user: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("cms_users.id_user", ondelete="CASCADE"),
        primary_key=True,
    )
    id_role: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("cms_roles.id_role", ondelete="CASCADE"),
        primary_key=True,
    )
    # true = deny explicite, prime sur tous les héritages
    is_deny: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    assigned_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user"), nullable=True
    )
    assigned_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
