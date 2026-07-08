from __future__ import annotations

from pydantic import BaseModel


class SyncTellingResponse(BaseModel):
    aangemaakt: int
    bijgewerkt: int
    verdwenen: int
