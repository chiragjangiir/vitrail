from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsMedia(Base):
    """Médiathèque multi-tenant (§XVI.2)."""

    __tablename__ = "cms_media"

    id_media: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False, index=True
    )
    # Dossier de classement (NULL = racine / non classé). FK SET NULL (migr 0030).
    id_folder: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_media_folders.id_folder", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    # Gouvernance §XVIII contenu (R14/R15, D9) : nœud propriétaire du média. NULL = média
    # d'organisation (comportement historique). Non NULL = seul un admin du nœud (ou d'un
    # ancêtre) peut le modifier/supprimer ; un responsable local ne supprime pas un média
    # national. Lecture filtrée comme les playlists. Miroir de cms_playlists.
    id_governance_node: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_governance_nodes.id_node", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    media_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # video | image | audio | document | html_package
    media_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    cdn_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    checksum_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    # Documents multipages (PDF/PPT/PPTX) : nb de pages converties en images par le
    # worker (NULL = pas un document converti). Détail dans metadata["document"].
    page_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # upload | stock_unsplash | stock_pexels | import | generated_ai
    source: Mapped[str] = mapped_column(String(20), server_default="upload", nullable=False)
    # Obligatoire si source=stock_* (§XVI.2)
    attribution_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Code ISRC pour les assets audio (§XIX.6)
    isrc: Mapped[Optional[str]] = mapped_column(String(12), nullable=True, index=True)
    rights_metadata: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"), nullable=False)
    media_metadata: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'"), nullable=False)
    # pending | processing | done | error
    transcode_status: Mapped[str] = mapped_column(
        String(20), server_default="pending", nullable=False
    )
    # auto = ré-encodage pipeline §XVI.2 (défaut) ; passthrough = fichier conservé tel quel
    encode_mode: Mapped[str] = mapped_column(
        String(20), server_default="auto", default="auto", nullable=False
    )
    # Verdict conformité & sync-readiness (passthrough) : null|ready|playable|nonconform.
    # Rapport détaillé dans media_metadata["conformance"]. Cf. services/media_conformance.py
    conformance_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    is_encrypted: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    # Quarantaine / kill-switch (§ Q5) : un média bloqué n'est JAMAIS diffusé (filtré
    # server-side dans _resolve_sync_payload + poussé dans blocked_media pour la garde player).
    is_blocked: Mapped[bool] = mapped_column(
        Boolean, server_default="false", default=False, nullable=False
    )
    block_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    blocked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    blocked_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    # Embargo : le média ne peut être diffusé avant cette date/heure UTC
    not_before_utc: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Lié à un event sous embargo — hérite de event.not_before_utc (SET NULL si event supprimé)
    embargo_event_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_events.id_event", ondelete="SET NULL"), nullable=True, index=True
    )
    # Renditions adaptatives (« artefacts » vidéo) : ce média (parent/originale) a-t-il
    # des ré-encodages de résolution inférieure ? Drapeau de présence (badge médiathèque,
    # drawer). Les artefacts vivent dans cms_media_renditions ; embargo/quarantaine/blocage
    # ne sont JAMAIS gérés sur l'artefact — ils cascadent du parent. Cf. EVOLUTIONS.md.
    has_renditions: Mapped[bool] = mapped_column(
        Boolean, server_default="false", default=False, nullable=False
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user"), nullable=True
    )
    # ⚠️ `DateTime(timezone=True)` EXPLICITE, comme cms_events / cms_audio_baskets. Sans lui,
    # SQLAlchemy déduit de l'annotation `datetime` un TIMESTAMP **SANS** fuseau, alors que la
    # colonne réelle en porte un : asyncpg refusait alors tout datetime aware écrit ici.
    # Conséquence mesurée en production le 2026-07-28 : `PATCH /media/{id}/embargo` répondait
    # **500** à chaque appel — la mise sous embargo d'un média était purement inutilisable,
    # et aucun test ne couvrait cette route.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class CmsMediaRendition(Base):
    """Artefact d'un média vidéo (rendition adaptative par capacité player).

    Ré-encodage de résolution/codec inférieur de l'originale (le « parent »). Au sync,
    chaque player reçoit la rendition adaptée à sa capacité de décodage (et, en groupe
    LAN sync, celle du membre le plus faible pour TOUS). L'utilisateur ne manipule QUE
    le parent ; les artefacts sont masqués de la grille médiathèque (table séparée).

    Embargo / quarantaine (is_blocked) / blocage CASCADENT du parent — jamais portés ici.
    FK ondelete=CASCADE : supprimer le parent purge ses renditions. Cf. EVOLUTIONS.md.
    """

    __tablename__ = "cms_media_renditions"

    id_rendition: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_parent: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("cms_media.id_media", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # uhd | fhd | hd720 (extensible) — UNIQUE par parent
    profile: Mapped[str] = mapped_column(String(20), nullable=False)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    codec: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    storage_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    file_meta: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"), nullable=False)
    conformance_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # pending | processing | ready | failed
    status: Mapped[str] = mapped_column(
        String(20), server_default="pending", default="pending", nullable=False
    )
    error_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
