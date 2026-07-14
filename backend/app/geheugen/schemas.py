from __future__ import annotations

import uuid

from pydantic import BaseModel


class GeheugenVoorstelInput(BaseModel):
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


class GeheugenVoorstelResponse(BaseModel):
    gb: VeldVoorstelResponse
    btw: VeldVoorstelResponse
    project: VeldVoorstelResponse
