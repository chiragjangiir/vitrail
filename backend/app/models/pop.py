from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsProofOfPlay(Base):
    """
    Partitionnée par RANGE sur played_at en production (migration 0007).
    create_all (tests) crée une table plain — comportement identique pour les inserts/selects.
    """

    __tablename__ = "cms_proof_of_play"

    id_pop: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    id_player: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    id_playlist: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    id_media: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    played_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    merkle_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Signature Ed25519 base64 de la preuve par la clé device du player (P2, §XXIV).
    # NULL = player legacy non signant. Vérifiée à l'ingestion contre cms_players.pop_public_key.
    signature: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Écran coupé au moment de la diffusion (auto-power §heures d'ouverture, migr 0102) :
    # le média a bien été joué, mais la sortie vidéo était éteinte → preuve conservée
    # (et incluse dans la chaîne Merkle) mais JAMAIS comptabilisée comme de l'antenne.
    # Visuel uniquement : une preuve audio n'est jamais marquée (cf. services/pop_screen).
    screen_off: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    # Zone RECOUVERTE au moment de la diffusion (migr 0125) : en multi-zones, un spot de
    # campagne plein écran (P3.6) ou un takeover VOD recouvre les autres zones, qui ne sont
    # volontairement pas suspendues (leur wall-clock doit rester vrai) et continuent donc
    # d'émettre. Déclaré PAR LE PLAYER — lui seul sait qu'un overlay le masquait — là où
    # `screen_off` est calculé par le serveur. Même traitement : preuve conservée, dans la
    # chaîne Merkle, jamais comptée comme de l'antenne.
    covered: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
