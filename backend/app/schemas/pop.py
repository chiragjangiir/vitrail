from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class PopLogEntry(BaseModel):
    id_media: Optional[int] = None
    id_playlist: Optional[int] = None
    played_at: datetime
    duration_ms: int = 0
    signature: Optional[str] = None   # signature Ed25519 base64 (P2) — absente = player legacy
    # Zone RECOUVERTE par un overlay plein écran au démarrage du média (migr 0125) : spot de
    # campagne P3.6 ou takeover VOD. Déclaré par le player — lui seul le sait. Absent =
    # False : un player antérieur au correctif ne ment pas, il ne sait simplement pas.
    # Hors du message signé (comme `screen_off`) : le player est déjà la racine de confiance
    # de l'existence même des preuves.
    covered: bool = False


class PopBatchRequest(BaseModel):
    logs: list[PopLogEntry]
    # Clé publique Ed25519 du player (PEM) — enregistrée en TOFU à la 1re remontée signée (P2).
    pop_public_key: Optional[str] = None


class PopBatchResponse(BaseModel):
    inserted: int
    first_hash: str
    last_hash: str
    signed: int = 0   # nb de preuves du lot effectivement signées + vérifiées
    # nb de preuves du lot jouées ÉCRAN COUPÉ (conservées, jamais comptées — migr 0102)
    screen_off: int = 0
    # nb de preuves du lot jouées ZONE RECOUVERTE (conservées, jamais comptées — migr 0125)
    covered: int = 0


class PopVerifyResponse(BaseModel):
    """Vérification de chaîne + signatures sur une période (P1)."""
    period_days: int
    total: int
    chain_valid: bool          # la chaîne de hash est-elle continue et recalculable ?
    broken_at_id: Optional[int] = None
    signed: int
    unsigned: int
    signature_invalid: int
    merkle_root: Optional[str] = None
    # Début de la fenêtre vérifiable en base : après DROP des vieilles partitions archivées,
    # la chaîne ne se recompose que sur le chaud (le segment sorti est attesté par le
    # merkle_root de son archive). None = aucune archive → chaîne complète. Voir §9 du plan.
    chain_from: Optional[str] = None


class PopCertificateResponse(BaseModel):
    """Attestation certifiée (P1) — Merkle root + résumé par player."""
    id_org: int
    from_date: str
    until_date: str
    total_plays: int           # diffusions COMPTABILISÉES (écran coupé exclu)
    # Preuves jouées écran coupé (migr 0102) : présentes dans la chaîne et dans le
    # merkle_root — qui reste calculé sur TOUTES les lignes, sinon l'attestation ne
    # serait plus recalculable — mais exclues du total d'antenne. Le certificat est
    # ainsi explicite plutôt que silencieusement différent de la chaîne.
    total_screen_off: int = 0
    # Idem pour les preuves émises par une zone RECOUVERTE par un overlay plein écran
    # (spot P3.6 ou takeover VOD, migr 0125). Une même preuve peut porter les deux causes :
    # les deux compteurs se recoupent, `total_plays` n'en déduit la ligne qu'une fois.
    total_covered: int = 0
    merkle_root: Optional[str]
    players: list[dict]        # [{id_player, plays, screen_off, covered, chain_head, signed, unsigned}]
    generated_at: str


class PopPlayRow(BaseModel):
    """Une preuve de diffusion individuelle (ligne du tableau Proof of Play sous Rapports)."""
    id_pop: int
    id_player: int
    player_name: Optional[str] = None
    id_media: Optional[int] = None
    media_name: Optional[str] = None
    played_at: datetime
    duration_ms: int
    signed: bool          # signature Ed25519 présente (✓) ou non (✗)
    merkle_hash: str
    # Média de type document (PDF/PPT déroulé en N pages → N preuves) : permet à l'UI de
    # regrouper les preuves consécutives en une ligne « document » (durée cumulée + nb pages)
    # SANS toucher aux preuves stockées (chaîne/signatures intactes).
    is_document: bool = False
    # Joué alors que la sortie vidéo était coupée (auto-power, migr 0102) : la ligne reste
    # VISIBLE ici — c'est la vue forensique, la masquer rendrait le phénomène indétectable —
    # mais elle est exclue de tous les agrégats d'antenne.
    screen_off: bool = False
    # Joué dans une zone RECOUVERTE par un overlay plein écran (spot P3.6 / takeover VOD,
    # migr 0125). Même traitement : visible ici, exclu des agrégats.
    covered: bool = False


class PopPlaysResponse(BaseModel):
    total: int            # nombre total de preuves correspondant au filtre (pour la pagination)
    limit: int
    offset: int
    rows: list[PopPlayRow]


class PopDayStats(BaseModel):
    date: str
    count: int
    duration_ms: int


class PopTopItem(BaseModel):
    id: int
    name: str
    count: int


class PopAnalyticsResponse(BaseModel):
    period_days: int
    total_plays: int
    total_duration_ms: int
    plays_by_day: list[PopDayStats]
    top_media: list[PopTopItem]


class PopTypeGroup(BaseModel):
    media_type: str
    items: list[PopTopItem]


class PopTopByTypeResponse(BaseModel):
    period_days: int
    groups: list[PopTypeGroup]


class PopArchiveRow(BaseModel):
    """Une période de Proof of Play archivée hors base (§XXIV, archivage)."""
    id_archive: int
    period_start: str          # ISO date (borne incluse)
    period_end: str            # ISO date (borne excluse)
    row_count: int
    merkle_root: Optional[str] = None
    has_pdf: bool
    bytes_csv: Optional[int] = None
    players: list[dict]        # résumé par player (plays/signed/unsigned/merkle_root/chain_valid)
    created_at: datetime


class PopArchivesResponse(BaseModel):
    total: int
    rows: list[PopArchiveRow]


class PopArchiveVerifyResponse(BaseModel):
    """Vérification hors ligne de l'intégrité d'une archive : re-télécharge le CSV.gz,
    recalcule le merkle_root et le compare à celui stocké."""
    id_archive: int
    ok: bool                   # merkle_root recalculé == stocké ET row_count identique
    stored_merkle_root: Optional[str] = None
    computed_merkle_root: Optional[str] = None
    stored_row_count: int
    computed_row_count: int
