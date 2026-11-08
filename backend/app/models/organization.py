from __future__ import annotations

from datetime import datetime
from typing import Optional

from datetime import date as date_cls, time as time_cls

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, SmallInteger,
    String, Text, Time, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsOrganization(Base):
    __tablename__ = "cms_organizations"

    id_org: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    org_name: Mapped[str] = mapped_column(String(255), nullable=False)
    org_slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    # NULL = RLS partagé ; valeur = schéma PostgreSQL dédié (§II.1)
    db_schema: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # FK vers cms_media ajoutée en Sprint 1.2
    org_fallback_audio_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    version_lock_enabled: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False
    )
    player_version_lock: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # Seuils d'alerte player configurables par org
    # { offline_critical_min, cpu_warn_pct, ram_warn_pct, disk_warn_pct, token_warn_days, min_player_version }
    player_alert_settings: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"), nullable=False, default=dict)
    # Politique de génération des renditions adaptatives (artefacts vidéo) :
    #   off (défaut) = aucune génération automatique (opt-in via le drawer média)
    #   auto_fhd     = à l'upload, génère une rendition FHD si la source > 1080p
    # Cf. EVOLUTIONS.md « Renditions adaptatives par capacité player ».
    rendition_policy: Mapped[str] = mapped_column(
        String(20), server_default="off", default="off", nullable=False
    )
    # Org suspendue (super-admin) → ses users ne peuvent plus se connecter (§II.1).
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default="true", default=True, nullable=False
    )
    # Crédit de l'AI Assistant (§XXVII) sur la période courante. NULL/≤0 = illimité.
    # Unité du crédit : 'tokens' (→ ai_quota_tokens) | 'eur' (→ ai_quota_eur).
    ai_quota_unit: Mapped[str] = mapped_column(
        String(8), server_default="tokens", default="tokens", nullable=False
    )
    ai_quota_tokens: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    ai_quota_eur: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    # Période du crédit : 'weekly' (lundi→) | 'monthly' (1er du mois→).
    ai_quota_period: Mapped[str] = mapped_column(
        String(10), server_default="monthly", default="monthly", nullable=False
    )
    # Seuil d'alerte en % du crédit (0 = aucune alerte).
    ai_alert_threshold_pct: Mapped[int] = mapped_column(
        SmallInteger, server_default="80", default=80, nullable=False
    )
    # Politique d'accès aux providers IA (BYOK §XXVII ; cf. docs/PLAN_BYOK_AI_KEYS.md) :
    #   strict (défaut) = l'org n'utilise QUE ses propres clés ; pas de clé → IA désactivée.
    #   platform        = le super-admin autorise EXPLICITEMENT cette org à consommer la clé
    #                     Anthropic plateforme (sous quota). Aucun repli automatique, jamais.
    # Ne concerne que la clé Anthropic ; la génération (fal/elevenlabs) est strict BYOK d'office.
    ai_byok_mode: Mapped[str] = mapped_column(
        String(10), server_default="strict", default="strict", nullable=False
    )
    # Plafonds de DÉPENSE BYOK (P3.2, migr 0126) — en USD, l'unité des fournisseurs.
    # NULL = aucun plafond (même convention que `ai_quota_tokens`).
    # ⚠️ À ne pas confondre avec `ai_quota_*` ci-dessus : celui-là compte les TOKENS de
    # l'ASSISTANT sur la clé Anthropic ; ceux-ci comptent l'argent réel dépensé chez fal et
    # ElevenLabs avec la clé DU CLIENT. Deux réglages, deux unités, deux périodes.
    ai_spend_cap_usd: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    # Même plafond appliqué à CHAQUE compte de l'org : c'est lui qui arrête la boucle d'une
    # seule personne sans exiger un réglage compte par compte.
    ai_user_spend_cap_usd: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    # Période CALENDAIRE en UTC : day | week (ISO, lundi) | month.
    ai_spend_cap_period: Mapped[str] = mapped_column(
        String(8), server_default="month", default="month", nullable=False
    )
    # Retail media §2.8 S5 : approbation des créatifs de campagne (optionnelle, org-admin).
    # TRUE = tout nouveau créatif naît 'pending' ; seuls les 'approved' sont diffusés.
    campaign_creative_approval: Mapped[bool] = mapped_column(
        Boolean, server_default="false", default=False, nullable=False
    )
    # Inventaire v2 (migr 0082) : tarif SOV PAR DÉFAUT de l'org (€ pour 1 % de SOV par
    # jour et par écran) — surchargé par site puis player. NULL = pas de devis calculé.
    campaign_sov_daily_rate: Mapped[Optional[float]] = mapped_column(Numeric(10, 4), nullable=True)
    # Quotas d'upload créatifs du portail annonceur §3.4, configurables (migr 0084).
    campaign_max_creatives: Mapped[int] = mapped_column(
        Integer, server_default="20", default=20, nullable=False
    )
    campaign_creative_max_mb: Mapped[int] = mapped_column(
        Integer, server_default="1024", default=1024, nullable=False
    )
    # Portail annonceur : autoriser la sélection PAR ÉCRAN dans le self-service
    # (migr 0089 — expose la liste nominative des écrans d'un site à un externe →
    # opt-in prudent, défaut OFF ; demande Ed 2026-07-11, design EVOLUTIONS).
    campaign_portal_player_selection: Mapped[bool] = mapped_column(
        Boolean, server_default="false", default=False, nullable=False
    )
    # Durée MAX d'un créatif de campagne en secondes (migr 0089, décision Ed 12/07 :
    # garde-fou créatif long × boucle courte). NULL = pas de limite. Appliquée à
    # l'ajout (CMS / portail / import) — les créatifs existants ne sont pas touchés.
    campaign_creative_max_duration_s: Mapped[Optional[int]] = mapped_column(
        Integer, server_default="30", default=30, nullable=True
    )
    # Retail Media AUDIO S2 (migr 0094) : plafond de spots/heure par écran (défaut org,
    # héritage player > site > org — décision Ed 16/07 : 12/h) + tarif audio par défaut
    # (€ par spot/heure par JOUR et par écran, miroir de campaign_sov_daily_rate).
    campaign_audio_spots_cap: Mapped[int] = mapped_column(
        Integer, server_default="12", default=12, nullable=False
    )
    campaign_audio_spot_daily_rate: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 4), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class CmsSite(Base):
    __tablename__ = "cms_sites"

    id_site: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False, index=True
    )
    site_name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Pays + numéro/code de site (libres, optionnels) — recherche/filtres de la carte (§24.2)
    country: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    site_number: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    # Coordonnées pour la carte géographique du parc (§24.2) — saisies manuellement, NULL = non placé
    latitude: Mapped[Optional[float]] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Numeric(9, 6), nullable=True)
    # Fuseau horaire du site (multi-pays) — défaut SIGNFLOW_TZ à la résolution si NULL
    timezone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Serveur NTP du site (IP ou nom d'hôte) — hérité au sync par les players sans config
    # NTP propre (rôle 'client'). Horloge juste = prérequis de l'auto-power offline.
    ntp_server: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Allumage/extinction auto des écrans calé sur les heures d'ouverture (§ auto-power)
    auto_power_enabled: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False, nullable=False)
    power_lead_min: Mapped[int] = mapped_column(Integer, server_default="15", default=15, nullable=False)
    power_lag_min: Mapped[int] = mapped_column(Integer, server_default="15", default=15, nullable=False)
    # Si True : les jours fériés (calendrier holiday_region) = fermé par défaut.
    # Défaut False = fériés traités comme jours normaux (écrans allumés aux heures habituelles).
    respect_holidays: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False, nullable=False)
    holiday_region: Mapped[str] = mapped_column(String(8), server_default="FR", default="FR", nullable=False)
    # Inventaire retail media v2 (migr 0082) : plafond d'occupation campagnes (%) pour les
    # players du site (NULL = pas de plafond ; le réglage player prime) + tarif SOV du
    # site (€ / 1 % SOV / jour — NULL = défaut org). Devis seulement, prix contractuel =
    # champ manuel de la campagne.
    campaign_max_occupancy_pct: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    campaign_sov_daily_rate: Mapped[Optional[float]] = mapped_column(Numeric(10, 4), nullable=True)
    # Retail Media AUDIO S2 (migr 0094) : plafond spots/h du site (NULL = défaut org ;
    # le réglage player prime) + tarif audio du site (€/spot/h/jour — NULL = défaut org).
    campaign_audio_spots_cap: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    campaign_audio_spot_daily_rate: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 4), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class CmsSiteHours(Base):
    """Horaire d'ouverture hebdomadaire régulier d'un site (1 ligne par jour défini)."""

    __tablename__ = "cms_site_hours"
    __table_args__ = (UniqueConstraint("id_site", "weekday", name="uq_site_hours_site_weekday"),)

    id_site_hours: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_site: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_sites.id_site", ondelete="CASCADE"), nullable=False, index=True
    )
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0=Lun … 6=Dim
    is_closed: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False, nullable=False)
    open_time: Mapped[Optional[time_cls]] = mapped_column(Time, nullable=True)
    # close < open ⇒ fenêtre nocturne (ex. bar 18:00→02:00)
    close_time: Mapped[Optional[time_cls]] = mapped_column(Time, nullable=True)


class CmsSiteException(Base):
    """Exception datée surchargeant les horaires hebdo (soirée, férié, fermeture)."""

    __tablename__ = "cms_site_exceptions"

    id_exception: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_site: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_sites.id_site", ondelete="CASCADE"), nullable=False, index=True
    )
    date_from: Mapped[date_cls] = mapped_column(Date, nullable=False)
    date_to: Mapped[date_cls] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # closed | hours | open_24h
    open_time: Mapped[Optional[time_cls]] = mapped_column(Time, nullable=True)
    close_time: Mapped[Optional[time_cls]] = mapped_column(Time, nullable=True)
    label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class CmsOrgAuthSettings(Base):
    """Paramètres d'authentification par organisation (§2.1.1)."""

    __tablename__ = "cms_org_auth_settings"

    id_org: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("cms_organizations.id_org", ondelete="CASCADE"),
        primary_key=True,
    )
    # disabled | optional | required
    auth_2fa_policy: Mapped[str] = mapped_column(
        String(20), server_default="optional", nullable=False
    )
    session_lifetime: Mapped[int] = mapped_column(
        Integer, server_default="480", nullable=False
    )
    max_sessions: Mapped[int] = mapped_column(Integer, server_default="5", nullable=False)
    password_min_len: Mapped[int] = mapped_column(Integer, server_default="10", nullable=False)
    password_policy: Mapped[dict] = mapped_column(
        JSONB,
        server_default=text("""'{"uppercase": true, "digit": true, "special": false}'"""),
        nullable=False,
    )
    ip_allowlist: Mapped[Optional[list]] = mapped_column(ARRAY(INET), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class CmsLdapConfig(Base):
    """Config LDAP/AD par organisation — structure Phase 1, logique Phase 2 (§2.1.2)."""

    __tablename__ = "cms_ldap_configs"

    id_ldap_config: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    id_org: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("cms_organizations.id_org", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    server_url: Mapped[str] = mapped_column(String(255), nullable=False, server_default="")
    # simple | ntlm
    auth_type: Mapped[str] = mapped_column(String(10), server_default="simple", nullable=False)
    bind_dn_pattern: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    search_base: Mapped[str] = mapped_column(String(255), nullable=False, server_default="")
    group_attr: Mapped[str] = mapped_column(
        String(50), server_default="memberOf", nullable=False
    )
    group_mappings: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'"), nullable=False)
    auto_provision: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    fallback_enabled: Mapped[bool] = mapped_column(
        Boolean, server_default="true", nullable=False
    )
    tls_verify: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class CmsOrgAiCredential(Base):
    """Clé API d'un provider IA, par organisation (BYOK §XXVII).

    Le secret est chiffré au repos (Fernet, `app.core.crypto`) → stocké en TEXT.
    Une ligne par couple (id_org, provider). TENANT-SCOPED (RLS `id_org`). La clé en
    clair ne ressort JAMAIS de l'API (seul `key_last4` est exposé en lecture).
    """

    __tablename__ = "cms_org_ai_credentials"
    __table_args__ = (
        UniqueConstraint("id_org", "provider", name="uq_org_ai_cred_org_provider"),
    )

    id_credential: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("cms_organizations.id_org", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # anthropic (LLM) | fal | elevenlabs (génération)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    key_last4: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    extra_config: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'"), nullable=False, default=dict
    )
    # unverified | valid | invalid (rempli par le bouton « Tester »)
    status: Mapped[str] = mapped_column(
        String(16), server_default="unverified", default="unverified", nullable=False
    )
    validated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
