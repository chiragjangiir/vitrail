from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Optional

from sqlalchemy import ARRAY, BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, SmallInteger, String, Time, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsSchedule(Base):
    """Programme de diffusion : playlist → players selon règles horaires (§XIII)."""

    __tablename__ = "cms_schedules"

    id_schedule: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False, index=True
    )
    schedule_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # content (playlist visuelle) | audio (panier audio §XIX)
    schedule_kind: Mapped[str] = mapped_column(
        String(20), server_default="content", default="content", nullable=False
    )
    # NULL pour les schedules audio (qui ciblent des paniers via cms_schedule_baskets)
    id_playlist: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_playlists.id_playlist"), nullable=True, index=True
    )
    # Nœud de gouvernance propriétaire (§XVIII). NULL = pas de contrainte (défaut).
    id_governance_node: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_governance_nodes.id_node", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    # Priorité de diffusion : la valeur la plus haute l'emporte en cas de conflit
    priority: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    # Enveloppe de validité (heure locale) appliquée PAR-DESSUS les règles de récurrence :
    # le programme n'est actif que si valid_from <= aujourd'hui <= valid_until ET qu'une
    # règle matche. NULL = borne ouverte (programme perpétuel par défaut).
    valid_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    valid_until: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    # `onupdate` au MODÈLE (audit menu ⑧, 2026-07-31) : updated_at ne bougeait JAMAIS
    # (16/16 programmes de prod figés à created_at). Même correctif que playlists et
    # templates — instrumenter chaque chemin de mutation garantirait d'en oublier.
    # ⚠️ Exige DateTime(timezone=True) : la colonne EST timestamptz (vérifié prod + dev),
    # seul le modèle ne le déclarait pas (le piège de l'embargo, latent ici aussi).
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"),
        onupdate=lambda: datetime.now(UTC), nullable=False,
    )


class CmsScheduleRule(Base):
    """Règle horaire d'un schedule (always / weekly / date_range)."""

    __tablename__ = "cms_schedule_rules"

    id_rule: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_schedule: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_schedules.id_schedule"), nullable=False, index=True
    )
    # always | weekly | date_range
    rule_type: Mapped[str] = mapped_column(
        String(20), server_default="weekly", nullable=False
    )
    # 0=Lun … 6=Dim (ISO weekday - 1)
    days_of_week: Mapped[Optional[list[int]]] = mapped_column(ARRAY(Integer), nullable=True)
    time_start: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    time_end: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    date_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    date_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class CmsScheduleTarget(Base):
    """Cible d'un schedule : player ou groupe de players."""

    __tablename__ = "cms_schedule_targets"

    id_target: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_schedule: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_schedules.id_schedule"), nullable=False, index=True
    )
    # player | player_group
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class CmsScheduleBasket(Base):
    """Panier audio d'un schedule (programme multi-paniers, §XIX). mix_ratio = part de mix."""

    __tablename__ = "cms_schedule_baskets"

    id_sb: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_schedule: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_schedules.id_schedule", ondelete="CASCADE"), nullable=False, index=True
    )
    id_basket: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_audio_baskets.id_basket", ondelete="CASCADE"), nullable=False
    )
    mix_ratio: Mapped[int] = mapped_column(SmallInteger, server_default="50", default=50, nullable=False)
