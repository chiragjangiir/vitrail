from datetime import date
from typing import Optional

from pydantic import BaseModel


class RightsReportRow(BaseModel):
    """Une œuvre diffusée sur la période (rapport SACEM/SOCAN §XIX.6)."""
    id_media: int
    isrc: Optional[str] = None
    title: str
    composer: Optional[str] = None
    publisher: Optional[str] = None
    rights_org: Optional[str] = None
    rights_cleared: bool = False
    plays: int
    total_sec: int
    players: int
    sites: int


class RightsReportResponse(BaseModel):
    from_date: date
    until_date: date
    rights_org: Optional[str] = None
    total_plays: int
    total_sec: int
    rows: list[RightsReportRow]
