from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, MACADDR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsPlayer(Base):
    """
    Table créée en Sprint 1.1 pour satisfaire la FK de cms_update_deployment_targets.
    Logique player complète implémentée en Sprint 1.5.
    FKs vers cms_media (fallback_audio_id, org_fallback_audio_id) ajoutées en Sprint 1.2.
    """

    __tablename__ = "cms_players"

    id_player: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False, index=True
    )
    id_site: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_sites.id_site"), nullable=True, index=True
    )
    player_name: Mapped[str] = mapped_column(String(255), nullable=False)
    player_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # linux | windows | android | chromeos | chrome_extension | tizen | webos | brightsign
    player_os: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    player_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(INET, nullable=True)
    wan_ip: Mapped[Optional[str]] = mapped_column(INET, nullable=True)
    mac_address: Mapped[Optional[str]] = mapped_column(MACADDR, nullable=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # online | offline | warning | maintenance | critical
    status: Mapped[str] = mapped_column(
        String(20), server_default="offline", nullable=False
    )
    # Rôle audio/contenu du player (§XIX) : content (défaut) | audio | mixed.
    # Détermine les choix de sortie audio (HDMI/jack/USB vs jack/USB) et l'éligibilité
    # aux groupes typés. default= Python-side pour exposer la vraie valeur avec
    # expire_on_commit=False (cf. règle CLAUDE.md).
    player_role: Mapped[str] = mapped_column(
        String(10), server_default="content", default="content", nullable=False
    )
    # Retail Media §2.8 : player exclu des campagnes (écran caisse, back-office…) —
    # retiré de toute résolution de cible campagne (diffusion + inventaire), même si
    # son site/groupe/org est ciblé (demande Ed 2026-07-09, migr 0075).
    campaigns_optout: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    # Inventaire v2 (migr 0082) : plafond d'occupation campagnes (%) — NULL = hérite du
    # site, sinon 100. Tarif SOV = € pour 1 % de SOV par JOUR (devis) — NULL = hérite
    # site puis org.
    campaign_max_occupancy_pct: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    campaign_sov_daily_rate: Mapped[Optional[float]] = mapped_column(Numeric(10, 4), nullable=True)
    # Retail Media AUDIO S2 (migr 0094) : plafond spots/h (NULL = hérite site puis org)
    # + tarif audio €/spot/h/jour (NULL = hérite site puis org).
    campaign_audio_spots_cap: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    campaign_audio_spot_daily_rate: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 4), nullable=True
    )
    display_config: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # Capacités matérielles auto-détectées (décodage vidéo HW) — remontées par le
    # player dans player:status à partir de capabilities.json écrit à l'install.
    # Clés : gpu_vendor, gpu_model, hw_decode (vaapi|v4l2|d3d11|mediacodec|none),
    # hw_decode_active, codecs[], gl_backend, sf_hw_decode, chromium_flags[],
    # detection_source, detected_at. Cf. services/player_capabilities.py.
    capabilities: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    security_config: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    chromeos_policy_config: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # Clé publique Ed25519 du player pour le Proof of Play signé (P2, §XXIV). Enregistrée en
    # TOFU à la 1re remontée d'un lot signé ; sert à vérifier la signature de chaque preuve.
    pop_public_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Horodatage de la dernière rotation auto de la clé PoP (P0.1 self-heal). NULL = jamais
    # tournée (TOFU initial seulement). Posé quand un wipe storage device (MAJ firmware / SD)
    # a régénéré le seed et que le lot prouve la possession de la nouvelle clé privée.
    pop_key_rotated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # FK vers cms_media ajoutée en Sprint 1.2
    fallback_audio_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    fallback_video_message: Mapped[str] = mapped_column(
        String(255),
        # server_default via text() → DDL `DEFAULT 'No content to display'` (valeur sans
        # guillemets). default= Python-side évite la valeur SQL brute exposée avec
        # expire_on_commit=False (cf. piège CLAUDE.md). La prod est déjà corrigée par 0006.
        server_default=text("'No content to display'"),
        default="No content to display",
        nullable=False,
    )
    fallback_video_config: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'"), nullable=False
    )
    # Métriques heartbeat — mis à jour à chaque player:status reçu (Sprint 1.5)
    cpu_usage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ram_usage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    disk_usage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_playlist_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("cms_playlists.id_playlist", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Token précédent, conservé après une rotation pour une fenêtre de grâce (couvre un push
    # token:refresh raté ou un player offline au moment de la rotation). cf. services/player_token.
    player_token_prev: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    player_token_prev_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Horodatage de la dernière capture d'écran uploadée (POST /screenshot). Sert de
    # drapeau « capture disponible » + fraîcheur de la vignette dans la carte player.
    last_screenshot_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Auto-power écrans (§ heures d'ouverture) — dernier état d'alimentation appliqué par
    # la tâche beat apply_site_power. Sert à n'envoyer power_on/power_off qu'aux transitions
    # (edge-triggered) et à survivre au restart du worker. NULL = jamais piloté.
    last_power_state: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    last_power_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Alertes actives calculées par check_player_health (Celery Beat 5 min)
    # Codes : offline_critical | cpu_high | ram_high | disk_high | token_7d | token_3d | token_expired | version_outdated
    alert_reasons: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'"), nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
