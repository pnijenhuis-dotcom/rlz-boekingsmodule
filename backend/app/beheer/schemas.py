from __future__ import annotations

from pydantic import BaseModel


class BoekenIngeschakeldDto(BaseModel):
    ingeschakeld: bool


class ProjectVerplichtDto(BaseModel):
    verplicht: bool
