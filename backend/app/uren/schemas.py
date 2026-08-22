"""DTO's voor de uren-&-meerwerk-veld-API (fase 2, mockup uren-uitvoerder.html): de native
app-endpoints voor ZZP'er / uitvoerder / detacheerder. De kantoor-DTO's (meerwerklijst,
beoordeel-paneel, beheer) volgen in fase 3 op dezelfde schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.schemas_basis import StrikteInvoer


class DagDto(BaseModel):
    id: uuid.UUID
    datum: date
    uren: Decimal
    m2: Decimal | None = None
    opmerking: str | None = None
    ingevuld_door_naam: str | None = None
    namens: bool
    # Correctievoorstel van de laatste afkeuring (hybride keuring, besluit 22-08) — de app
    # toont ze alleen in status `corrigeren`.
    voorstel_uren: Decimal | None = None
    voorstel_m2: Decimal | None = None
    voorstel_opmerking: str | None = None


class WeekstaatDto(BaseModel):
    id: uuid.UUID
    administratie_id: uuid.UUID
    gebruiker_id: uuid.UUID
    gebruiker_naam: str | None = None
    project_id: uuid.UUID
    project_naam: str | None = None
    jaar: int
    weeknummer: int
    status: str
    totaal_uren: Decimal
    totaal_m2: Decimal
    dagen: list[DagDto]
    ingediend_op: datetime | None = None
    ingediend_door_naam: str | None = None
    ingediend_namens: bool = False
    goedgekeurd_op: datetime | None = None
    goedgekeurd_door_naam: str | None = None
    afgekeurd_op: datetime | None = None
    afgekeurd_door_naam: str | None = None
    afkeur_reden: str | None = None


class ProjectKaartDto(BaseModel):
    administratie_id: uuid.UUID
    administratie_naam: str | None = None
    project_id: uuid.UUID
    project_naam: str | None = None
    soort_werk: str | None = None
    open_weken: int
    laatste_invoer: date | None = None


class WeekKaartDto(BaseModel):
    jaar: int
    weeknummer: int
    maandag: date
    zondag: date
    status: str  # 'nieuw' = nog geen staat
    weekstaat_id: uuid.UUID | None = None
    dagen_ingevuld: int
    totaal_uren: Decimal
    totaal_m2: Decimal
    ingediend_op: datetime | None = None
    goedgekeurd_door_naam: str | None = None
    afgekeurd_door_naam: str | None = None
    afkeur_reden: str | None = None


class IngediendeWeekDto(BaseModel):
    weekstaat_id: uuid.UUID
    administratie_id: uuid.UUID
    administratie_naam: str | None = None
    project_id: uuid.UUID
    project_naam: str | None = None
    jaar: int
    weeknummer: int
    status: str
    totaal_uren: Decimal
    totaal_m2: Decimal
    ingediend_op: datetime | None = None
    ingediend_namens: bool = False
    goedgekeurd_door_naam: str | None = None
    afgekeurd_door_naam: str | None = None
    afkeur_reden: str | None = None


class ZzperKaartDto(BaseModel):
    gebruiker_id: uuid.UUID
    naam: str
    aantal_projecten: int
    open_weken: int
    laatste_invoer: date | None = None


class TeKeurenItemDto(BaseModel):
    weekstaat_id: uuid.UUID
    administratie_id: uuid.UUID
    administratie_naam: str | None = None
    zzper_id: uuid.UUID
    zzper_naam: str | None = None
    project_id: uuid.UUID
    project_naam: str | None = None
    jaar: int
    weeknummer: int
    totaal_uren: Decimal
    totaal_m2: Decimal
    ingediend_op: datetime | None = None
    ingediend_namens: bool = False
    ingediend_door_naam: str | None = None


class MeerwerkDto(BaseModel):
    id: uuid.UUID
    administratie_id: uuid.UUID
    project_id: uuid.UUID
    project_naam: str | None = None
    omschrijving: str
    aantal: Decimal
    eenheid: str
    datum_uitgevoerd: date
    in_opdracht_van: str | None = None
    heeft_foto: bool
    foto_bestandsnaam: str | None = None
    gemeld_door_naam: str | None = None
    gemeld_op: datetime
    status: str
    prijs_per_eenheid: Decimal | None = None
    bedrag: Decimal | None = None
    facturatie_notitie: str | None = None
    beoordeeld_op: datetime | None = None
    beoordeeld_door_naam: str | None = None
    afwijs_reden: str | None = None
    doorbelast_op: datetime | None = None
    verkoopfactuur_referentie: str | None = None
    vraag_tekst: str | None = None
    vraag_gesteld_op: datetime | None = None
    vraag_antwoord: str | None = None
    vraag_beantwoord_op: datetime | None = None


class ProjectDocumentKaartDto(BaseModel):
    id: uuid.UUID
    soort: str
    titel: str
    versie_omschrijving: str | None = None
    bestandsnaam: str


class ProjectDetailDto(BaseModel):
    administratie_id: uuid.UUID
    project_id: uuid.UUID
    project_naam: str | None = None
    opdrachtgever: str | None = None
    werknummer_opdrachtgever: str | None = None
    soort_werk: str | None = None
    contract_m2: Decimal | None = None
    gebouwd_m2: Decimal
    looptijd_van: date | None = None
    looptijd_tot: date | None = None
    huurtijd_omschrijving: str | None = None
    doorlopende_huur_omschrijving: str | None = None
    documenten: list[ProjectDocumentKaartDto]
    meerwerk: list[MeerwerkDto]


class UitvoerderProjectKaartDto(BaseModel):
    administratie_id: uuid.UUID
    administratie_naam: str | None = None
    project_id: uuid.UUID
    project_naam: str | None = None
    soort_werk: str | None = None
    contract_m2: Decimal | None = None
    gebouwd_m2: Decimal
    looptijd_tot: date | None = None
    huurtijd_omschrijving: str | None = None
    meerwerk_gemeld: int
    te_keuren: int


# --- requests ---------------------------------------------------------------------------------


class DagZettenRequest(StrikteInvoer):
    administratie_id: uuid.UUID
    project_id: uuid.UUID
    jaar: int
    weeknummer: int
    datum: date
    uren: Decimal
    m2: Decimal | None = None
    opmerking: str | None = None
    # Detacheerder-namens-flow (besluit 21-08): de ZZP'er van wie de staat is. Weglaten = de
    # actor zelf (moet dan een ZZP'er zijn).
    namens_zzper_id: uuid.UUID | None = None


class WeekIndienenRequest(StrikteInvoer):
    administratie_id: uuid.UUID
    project_id: uuid.UUID
    jaar: int
    weeknummer: int
    namens_zzper_id: uuid.UUID | None = None


class DagCorrectieDto(StrikteInvoer):
    """Correctievoorstel per bestaande dagregel bij het afkeuren (hybride keuring, besluit
    22-08): minstens één van uren/m²/opmerking gevuld — de service valideert hard."""

    datum: date
    uren: Decimal | None = None
    m2: Decimal | None = None
    opmerking: str | None = None


class WeekAfkeurenRequest(StrikteInvoer):
    reden: str
    correcties: list[DagCorrectieDto] = []


class VraagAntwoordRequest(StrikteInvoer):
    tekst: str


# --- kantoor (fase 3) ---------------------------------------------------------------------------


class UrenStandDto(BaseModel):
    meerwerk_te_beoordelen: int
    meerwerk_nog_doorbelasten: int
    meerwerk_te_lang_niet_doorbelast: int
    urenstaten_wachten_op_keuring: int


class StaffelRegelDto(BaseModel):
    id: uuid.UUID
    omschrijving: str
    eenheid: str
    prijs_per_eenheid: Decimal
    verrekenbaar: bool
    bron: str | None = None


class MeerwerkGoedkeurenRequest(StrikteInvoer):
    prijs_per_eenheid: Decimal
    bedrag: Decimal
    facturatie_notitie: str | None = None


class MeerwerkAfwijzenRequest(StrikteInvoer):
    reden: str


class MeerwerkDoorbelastRequest(StrikteInvoer):
    verkoopfactuur_referentie: str


class ToewijzingDto(BaseModel):
    administratie_id: uuid.UUID
    administratie_naam: str | None = None
    project_id: uuid.UUID
    project_naam: str | None = None


class GekoppeldeZzperDto(BaseModel):
    gebruiker_id: uuid.UUID
    naam: str
    # Bureau-tarief per detacheerder↔zzp'er-koppeling (besluit 1, 21-08 — het hoofdmechanisme
    # van de bureaufactuurmatch). None = "geen tarief bekend" (match alleen op uren, oranje).
    uurtarief: Decimal | None = None


class CrediteurKoppelingDto(BaseModel):
    """Veldwerker↔RLZ-crediteur per administratie (factuurmatch fase 3) + het losse
    ZZP-uurtarief op die koppeling."""

    administratie_id: uuid.UUID
    administratie_naam: str | None = None
    vendor_id: uuid.UUID
    vendor_naam: str | None = None
    uurtarief: Decimal | None = None


class VeldgebruikerDto(BaseModel):
    gebruiker_id: uuid.UUID
    naam: str
    e_mail: str
    rol: str
    status: str
    projecten: list[ToewijzingDto]
    zzpers: list[GekoppeldeZzperDto]
    crediteuren: list[CrediteurKoppelingDto] = []
    # Afwijkings-logging (besluit 22-08, kantoor-only — de veld-API exposeert dit nooit):
    # afkeuringen mét correctievoorstel + opgetelde uren-delta (ingediend − goedgekeurd).
    uren_afwijking_aantal: int = 0
    uren_afwijking_som: Decimal = Decimal("0")


class ProjectKoppelingRequest(StrikteInvoer):
    administratie_id: uuid.UUID
    gebruiker_id: uuid.UUID
    project_id: uuid.UUID


class DetacheerderKoppelingRequest(StrikteInvoer):
    detacheerder_id: uuid.UUID
    zzper_id: uuid.UUID


class VeldwerkerCrediteurRequest(StrikteInvoer):
    """Crediteur-koppeling + los ZZP-uurtarief (upsert per veldwerker; Beheerder-only)."""

    administratie_id: uuid.UUID
    gebruiker_id: uuid.UUID
    vendor_id: uuid.UUID
    uurtarief: Decimal | None = None


class VeldwerkerCrediteurVerwijderRequest(StrikteInvoer):
    administratie_id: uuid.UUID
    gebruiker_id: uuid.UUID


class DetacheerderTariefRequest(StrikteInvoer):
    """Bureau-tarief op een bestaande detacheerder↔zzp'er-koppeling; None wist het tarief."""

    detacheerder_id: uuid.UUID
    zzper_id: uuid.UUID
    uurtarief: Decimal | None = None


class ModuleRechtRequest(StrikteInvoer):
    gebruiker_id: uuid.UUID
    ingeschakeld: bool


class ModuleRechtDto(BaseModel):
    gebruiker_id: uuid.UUID
    ingeschakeld: bool


class ModuleRechtHoudersDto(BaseModel):
    gebruiker_ids: list[uuid.UUID]
