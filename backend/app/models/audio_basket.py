from __future__ import annotations

from datetime import datetime, time
from typing import Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsAudioBasket(Base):
    """Panier audio thématique : collection d'assets audio avec poids de rotation (§XIX.2)."""

    __tablename__ = "cms_audio_baskets"

    id_basket: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False, index=True
    )
    # Gouvernance (lot 4 du Sprint 2.5) — pas de FK pour l'instant. NULL = portée globale org.
    id_node: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    basket_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # music | message | jingle | ambiance | emergency
    basket_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # national | regional | local | style
    basket_scope: Mapped[str] = mapped_column(String(20), server_default="local", default="local", nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False, nullable=False)
    min_ratio: Mapped[int] = mapped_column(SmallInteger, server_default="0", default=0, nullable=False)
    max_ratio: Mapped[int] = mapped_column(SmallInteger, server_default="100", default=100, nullable=False)
    # {"enabled":true,"target_pct":20,"fade_in_ms":500,"fade_out_ms":1500} (§XIX.5)
    ducking_config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"), default=dict, nullable=False)
    # Récurrence jingle : 'tracks' (tous les N morceaux) | 'minutes' (toutes les N min)
    trigger_mode: Mapped[str] = mapped_column(String(10), server_default="tracks", default="tracks", nullable=False)
    trigger_value: Mapped[int] = mapped_column(Integer, server_default="5", default=5, nullable=False)
    # Lecture en ordre aléatoire (paniers Music) — le player mélange les titres.
    shuffle: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True, nullable=False)
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class CmsAudioBasketItem(Base):
    """Média dans un panier audio avec poids de rotation et fenêtre de validité (§XIX.2)."""

    __tablename__ = "cms_audio_basket_items"

    id_item: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_basket: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_audio_baskets.id_basket", ondelete="CASCADE"), nullable=False, index=True
    )
    id_media: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_media.id_media"), nullable=False
    )
    weight: Mapped[int] = mapped_column(Integer, server_default="1", default=1, nullable=False)
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Règle de diffusion récurrente (heure locale) : jours + créneau. null = perpétuel.
    # JSON et non JSONB : la migration 0033 crée un `json`, et c'est la base qui fait foi
    # (P2.6). Sans conséquence ici — la valeur n'est jamais interrogée par un opérateur JSON,
    # seulement lue comme une liste Python (`ws.py`) — mais le modèle doit dire le vrai.
    rule_days: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    rule_time_start: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    rule_time_end: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0", default=0, nullable=False)


# ⛔ `CmsBasketPermission` (table `cms_basket_permissions`) a été SUPPRIMÉE par la migration
# 0116 (audit §XIX du 2026-07-29). Elle portait le modèle de droits §19.2 par rôle
# (`allowed_role`/`can_activate`/`can_edit_ratio`) mais n'a jamais été branchée : aucun code
# ne la lisait, 0 ligne en production. Le droit réel d'agir sur un panier depuis le panneau
# local vient de `allowed_basket_ids` du profil `local_control` ; côté CMS, du RBAC
# (`audio_baskets:read|control|configure`) et de la gouvernance (`id_node`).


class CmsPlayerBasketConfig(Base):
    """Panier actif sur un player avec son ratio de mix (§XIX.2)."""

    __tablename__ = "cms_player_basket_config"

    id_player: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_players.id_player", ondelete="CASCADE"), primary_key=True
    )
    id_basket: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_audio_baskets.id_basket", ondelete="CASCADE"), primary_key=True
    )
    mix_ratio: Mapped[int] = mapped_column(SmallInteger, server_default="50", default=50, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True, nullable=False)
    activated_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user"), nullable=True
    )
    activated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
