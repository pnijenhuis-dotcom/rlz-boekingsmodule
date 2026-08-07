from __future__ import annotations

import uuid

from pydantic import BaseModel

from app.schemas_basis import StrikteInvoer


class BoekenIngeschakeldDto(StrikteInvoer):
    ingeschakeld: bool


class WebhookAfleveringDto(StrikteInvoer):
    ingeschakeld: bool


class IntakeAiDto(StrikteInvoer):
    ingeschakeld: bool


class ProjectVerplichtDto(StrikteInvoer):
    verplicht: bool


class AiExtractieIngeschakeldDto(StrikteInvoer):
    ingeschakeld: bool


class AdministratieInstellingenDto(BaseModel):
    """Eén rij in het instellingen-scherm (design-pass taak 3) — dezelfde twee schakelaars als
    de losse per-administratie GET/PUT-endpoints hierboven, nu in één keer voor de hele lijst."""

    id: uuid.UUID
    naam: str
    boeken_ingeschakeld: bool
    project_verplicht: bool
    ai_extractie_ingeschakeld: bool
    eigenaar_gebruiker_id: uuid.UUID | None = None


class AdministratieInstellingenLijstDto(BaseModel):
    administraties: list[AdministratieInstellingenDto]


class MedewerkerDto(BaseModel):
    """Toewijsbare medewerker (vraagmodal): bewust alleen id + naam, geen e-mail/rol."""

    id: uuid.UUID
    naam: str


class MedewerkersLijstDto(BaseModel):
    medewerkers: list[MedewerkerDto]


class EigenaarDto(StrikteInvoer):
    """Mockup Instellingen "Eigenaar (krijgt vragen)": default-toewijzing voor nieuwe vragen.
    None = geen eigenaar (vraag stellen vereist dan een expliciete toewijzing)."""

    eigenaar_gebruiker_id: uuid.UUID | None = None
