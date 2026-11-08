from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class FirmwareVersionRead(BaseModel):
    """Une version firmware enregistrée (track='firmware', §XXX / P1.1)."""
    model_config = ConfigDict(from_attributes=True)

    id_version: int
    version: str
    model_family: Optional[str] = None
    channel: str = "stable"
    is_pinned: bool = False
    file_size: Optional[int] = None
    original_filename: Optional[str] = None
    sha256_checksum: Optional[str] = None
    release_notes: Optional[str] = None
    created_at: datetime


class FirmwarePushResponse(BaseModel):
    status: str
    id_deployment: int
    version: str
    previous_version: Optional[str] = None


class FirmwareUpdateState(BaseModel):
    """État de MAJ firmware d'un player (pour le drawer)."""
    current_version: Optional[str] = None      # bs_bos remonté par le device
    model_family: Optional[str] = None
    pinned_version: Optional[str] = None        # version épinglée pour cette famille (None = aucune)
    update_available: bool = False              # une version épinglée existe ET diffère de la courante
    last_status: Optional[str] = None           # dernier statut de déploiement (queued|installing|success|failed)


class PinnedFirmwareRead(BaseModel):
    """Firmware épinglé d'une famille, à bundler à la racine du ZIP SD d'un nouveau player.

    Le bootloader applique tout `.bsfw` racine au 1er boot ; `download_url` = URL signée."""
    model_family: Optional[str] = None
    version: str
    original_filename: Optional[str] = None
    file_size: Optional[int] = None
    download_url: str
