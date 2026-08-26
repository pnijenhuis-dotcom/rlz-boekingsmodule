from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas_basis import StrikteInvoer


class BoekenIngeschakeldDto(StrikteInvoer):
    ingeschakeld: bool


class WebhookAfleveringDto(StrikteInvoer):
    ingeschakeld: bool


class IntakeAiDto(StrikteInvoer):
    ingeschakeld: bool


class AiKostenStatusDto(BaseModel):
    """Verbruiksblok Instellingen + werkvoorraad-banner (AI-kostenmeter, besluit 2026-08-14).
    Bedragen als string (Decimal-precisie, nooit float-drift richting de UI)."""

    maand: str  # "2026-08"
    verbruik_eur: str
    limiet_eur: str
    percentage: int
    waarschuwing_80: bool
    limiet_bereikt: bool
    geblokkeerd: bool


class AiKostenLimietInput(StrikteInvoer):
    maandlimiet_eur: Decimal = Field(gt=0, le=Decimal("100000"))


class ProjectVerplichtDto(StrikteInvoer):
    verplicht: bool


class AiExtractieIngeschakeldDto(StrikteInvoer):
    ingeschakeld: bool


class DoorbelastingIngeschakeldDto(StrikteInvoer):
    ingeschakeld: bool


class UrenMeerwerkDto(StrikteInvoer):
    ingeschakeld: bool


class UrenDagmaxDto(StrikteInvoer):
    """Drempel voor het >N-uur-per-dag-signaal (steigerbouw-run A6, migratie 0072): 0 < N ≤ 24."""

    dagmax_uren: Decimal = Field(gt=0, le=24)


class VerkoopAutoboekenDto(StrikteInvoer):
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
    # Verkoop-autoboeken (migratie 0051): alleen bedienbaar wanneer is_vastgoed — de UI toont
    # de schakelaar uitsluitend voor vastgoed-administraties.
    is_vastgoed: bool = False
    verkoop_autoboeken_ingeschakeld: bool = False
    # Uren & meerwerk (migratie 0056): steigerbouw-tak, opt-in per administratie.
    uren_meerwerk_ingeschakeld: bool = False
    # Signaal >N uur per dag (A6, migratie 0072).
    uren_dagmax_uren: Decimal = Decimal("12")
    # Koppelstand (wizard 26-08 punt 5): RLZ-administratie-id, webservice-gebruiker (None = geen
    # credential in de store — nooit het wachtwoord) en of de laatste rechten-probe groen was.
    rlz_admin_id: str | None = None
    webservice_username: str | None = None
    probe_groen: bool | None = None


class AdministratieInstellingenLijstDto(BaseModel):
    administraties: list[AdministratieInstellingenDto]


# --- Administratie toevoegen (wizard, feedbackronde 26-08 punt 5) -------------------------------


class WebserviceGegevensDto(StrikteInvoer):
    """Login voor de RLZ-webservice — alleen inkomend; komt nooit terug in een response."""

    webservice_username: str = Field(min_length=1, max_length=200)
    wachtwoord: str = Field(min_length=1, max_length=500)


class GevondenAdministratieDto(BaseModel):
    rlz_admin_id: str
    naam: str
    al_aangesloten: bool


class VerbindingTestDto(BaseModel):
    administraties: list[GevondenAdministratieDto]


class AdministratiesAanmakenDto(WebserviceGegevensDto):
    rlz_admin_ids: list[str] = Field(min_length=1)


class AangemaakteAdministratieDto(BaseModel):
    id: uuid.UUID
    naam: str
    rlz_admin_id: str
    probe: dict[str, str]
    sync_run_id: uuid.UUID | None


class AdministratiesAangemaaktDto(BaseModel):
    administraties: list[AangemaakteAdministratieDto]


class EersteSyncRunDto(BaseModel):
    run_id: uuid.UUID | None
    status: str
    onderdelen: dict[str, dict] | None = None
    aangevraagd_op: datetime | None = None
    beeindigd_op: datetime | None = None
    fout_reden: str | None = None


class SchrijftestStapDto(BaseModel):
    stap: str
    status: str
    detail: str | None = None


class SchrijftestResultaatDto(BaseModel):
    uitkomst: str
    referentie: str
    document_id: uuid.UUID
    stappen: list[SchrijftestStapDto]


class ProbeRapportDto(BaseModel):
    rapport: dict[str, str]


class MedewerkerDto(BaseModel):
    """Toewijsbare medewerker (vraagmodal): bewust alleen id + naam, geen e-mail/rol —
    plus (blok B5 26-08) of het een klant-accordeur is (vraag aan de klant, chip "bij de klant")."""

    id: uuid.UUID
    naam: str
    is_klant_accordeur: bool = False


class MedewerkersLijstDto(BaseModel):
    medewerkers: list[MedewerkerDto]


class EigenaarDto(StrikteInvoer):
    """Mockup Instellingen "Eigenaar (krijgt vragen)": default-toewijzing voor nieuwe vragen.
    None = geen eigenaar (vraag stellen vereist dan een expliciete toewijzing)."""

    eigenaar_gebruiker_id: uuid.UUID | None = None
