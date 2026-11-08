"""VOD à la demande (« lance cette vidéo sur cet écran ») — Feature B.

Une **config VOD** = un set nommé de médias visuels (vidéo/image/document) + des players
**du même site** sur lesquels ces médias sont **pré-cachés** (offline-first content store)
→ lecture instantanée locale, déclenchable à la demande (cloud `play_now` §Phase 2 / panneau
LAN-local §Phase 3).

Contrainte autoritaire = `id_site` : tous les players affectés partagent le même site
(cf. EVOLUTIONS.md § « PRIORISÉ AVANT SPRINT 2.8 / B »). Le sanity-check réseau (subnet /24 +
wan_ip) reste un simple avertissement côté frontend.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsVodConfig(Base):
    """Config VOD nommée réutilisable (médias + players même site)."""

    __tablename__ = "cms_vod_configs"

    id_vod: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False, index=True
    )
    # Site commun des players affectés (contrainte « même site »). NULL = players sans site
    # (l'orgs qui n'utilise pas les sites) — la cohérence reste vérifiée à l'affectation.
    id_site: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_sites.id_site"), nullable=True
    )
    # Mode de ciblage (migr 0096) :
    #  - 'players' (défaut, historique) : cible = liste FIGÉE de cms_vod_config_players ;
    #  - 'site'                         : cible = TOUS les players de `id_site`, résolus à
    #                                     la lecture (un player ajouté au site plus tard
    #                                     hérite du pré-cache). La table players est vide.
    # Ne JAMAIS lire ce champ à la main : passer par services/vod_targeting.py (source unique).
    target_mode: Mapped[str] = mapped_column(
        String(16), server_default=text("'players'"), default="players", nullable=False
    )
    vod_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Gouvernance §XVIII (phase 4 de l'audit 2026-07-27, migr 0112). NULL = config
    # d'organisation (comportement historique). Non NULL = édition gardée par le nœud —
    # une VOD prend l'écran en plein cadre, elle n'échappe pas à la hiérarchie.
    id_governance_node: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_governance_nodes.id_node", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    # `onupdate` et non une écriture manuelle : `update_vod_config` n'écrivait JAMAIS
    # `updated_at`, si bien que la date ne bougeait plus après la création — mesuré en
    # production le 2026-07-29, **0 config sur 4**, alors que le champ est exposé dans
    # `VodConfigRead`. Même défaut, même correctif que les playlists (0/20) et les
    # templates (0/8) : au MODÈLE, pour que tout chemin de mutation l'entretienne.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"),
        onupdate=lambda: datetime.now(UTC), nullable=False,
    )


class CmsVodConfigMedia(Base):
    """Média affecté à une config VOD (pré-caché sur ses players)."""

    __tablename__ = "cms_vod_config_media"

    id_vod_media: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_vod: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_vod_configs.id_vod", ondelete="CASCADE"), nullable=False, index=True
    )
    id_media: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_media.id_media"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0", default=0, nullable=False)


class CmsVodConfigPlayer(Base):
    """Player affecté à une config VOD (cible du pré-cache + des triggers)."""

    __tablename__ = "cms_vod_config_players"

    id_vod_player: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_vod: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_vod_configs.id_vod", ondelete="CASCADE"), nullable=False, index=True
    )
    id_player: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_players.id_player"), nullable=False
    )
