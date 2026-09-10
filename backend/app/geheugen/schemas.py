from __future__ import annotations

import uuid

from pydantic import BaseModel

from app.schemas_basis import StrikteInvoer


class GeheugenVoorstelInput(StrikteInvoer):
    """De regelomschrijving reist in de request-body, nooit in de URL (zelfde privacy-regel als
    IBAN's: URL's belanden in access-logs)."""

    vendor_id: uuid.UUID
    regel_omschrijving: str | None = None


class VeldVoorstelResponse(BaseModel):
    waarde: uuid.UUID | None
    confidence: float
    telling: int
    oranje: bool
    reden: str | None
    # True zodra >=1 app-observatie de winnende waarde dekt; False = uitsluitend rlz_seed
    # ("uit historie, nog niet bevestigd" in de UI). Peters ontwerp 2026-07-14.
    app_bevestigd: bool
    # Blok 3 vervolgrun 10-09 avond ("recency wint"): True = de laatste drie mens-boekingen waren identiek → groen,
    # ook al kende de historie eerder een andere waarde; die oudere waarden staan in `eerder_ook` (historie-chip
    # "eerder ook: …" in het controlescherm — zichtbaar, niet meer bepalend).
    recent_consensus: bool = False
    eerder_ook: list[uuid.UUID] = []


class GeheugenVoorstelResponse(BaseModel):
    gb: VeldVoorstelResponse
    btw: VeldVoorstelResponse
    project: VeldVoorstelResponse
