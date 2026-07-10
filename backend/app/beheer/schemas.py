from __future__ import annotations

import uuid

from pydantic import BaseModel


class BoekenIngeschakeldDto(BaseModel):
    ingeschakeld: bool


class ProjectVerplichtDto(BaseModel):
    verplicht: bool


class AiExtractieIngeschakeldDto(BaseModel):
    ingeschakeld: bool


class AdministratieInstellingenDto(BaseModel):
    """Eén rij in het instellingen-scherm (design-pass taak 3) — dezelfde twee schakelaars als
    de losse per-administratie GET/PUT-endpoints hierboven, nu in één keer voor de hele lijst."""

    id: uuid.UUID
    naam: str
    boeken_ingeschakeld: bool
    project_verplicht: bool
    ai_extractie_ingeschakeld: bool


class AdministratieInstellingenLijstDto(BaseModel):
    administraties: list[AdministratieInstellingenDto]
