"""Pydantic-schema's kantoor-projectenmodule (mockup projecten-invoer.html, akkoord Peter
22-08). Bedragen/Decimals serialiseren als string (client rekent nooit zelf)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.schemas_basis import StrikteInvoer


class ProjectLijstRijDto(BaseModel):
    project_id: uuid.UUID
    naam: str | None = None
    is_actief: bool
    opdrachtgever: str | None = None
    werknummer_opdrachtgever: str | None = None
    specs_status: str  # 'compleet' | 'onvolledig' | 'geen'
    documenten: dict[str, int]
    staffels: int
    gebouwd_m2: Decimal
    contract_m2: Decimal | None = None
    doorlopende_huur: bool
    heeft_activiteit: bool


class ProjectenLijstResponse(BaseModel):
    projecten: list[ProjectLijstRijDto]
    zonder_specs: int  # alleen projecten mét uren-/meerwerk-activiteit (mockup-keuze 5)


class SpecificatieDto(BaseModel):
    opdrachtgever: str | None = None
    werknummer_opdrachtgever: str | None = None
    soort_werk: str | None = None
    contract_m2: Decimal | None = None
    looptijd_van: date | None = None
    looptijd_tot: date | None = None
    huurtijd_omschrijving: str | None = None
    doorlopende_huur_omschrijving: str | None = None
    # Projectzone werkstempels (blok C 28-08): zonder lat/lon = geen geofence voor dit project.
    locatie_adres: str | None = None
    locatie_lat: Decimal | None = None
    locatie_lon: Decimal | None = None
    zone_straal_m: int | None = None
    # D6 (migratie 0118): herkomst per veld — 'contract' (chip "uit contract") | 'mens'; ontbrekend = onbekend
    # (rij van vóór 0118).
    veld_herkomst: dict[str, str] = {}


class SpecificatieInput(StrikteInvoer):
    opdrachtgever: str | None = None
    werknummer_opdrachtgever: str | None = None
    soort_werk: str | None = None
    contract_m2: Decimal | None = None
    looptijd_van: date | None = None
    looptijd_tot: date | None = None
    huurtijd_omschrijving: str | None = None
    doorlopende_huur_omschrijving: str | None = None
    locatie_adres: str | None = None
    locatie_lat: Decimal | None = None
    locatie_lon: Decimal | None = None
    zone_straal_m: int | None = None


class ProjectDocumentDto(BaseModel):
    id: uuid.UUID
    soort: str
    titel: str
    versie_omschrijving: str | None = None
    bestandsnaam: str
    aangemaakt_op: datetime
    ontleed: bool


class StaffelDto(BaseModel):
    id: uuid.UUID
    omschrijving: str
    eenheid: str
    prijs_per_eenheid: Decimal
    verrekenbaar: bool
    bron: str | None = None
    aangemaakt_op: datetime
    # D6: 'contract' | 'mens' | None (vóór 0118 — client leidt dan af uit `bron`).
    herkomst: str | None = None
    herkomst_document_id: uuid.UUID | None = None


class StaffelInput(StrikteInvoer):
    omschrijving: str
    eenheid: Literal["m2", "m1", "stuks", "manuren"]
    prijs_per_eenheid: Decimal
    verrekenbaar: bool = True
    bron: str | None = None


class WerknummerDto(BaseModel):
    id: uuid.UUID
    vendor_id: uuid.UUID
    leverancier_naam: str | None = None
    werknummer: str
    bron: str
    bevestigd: bool
    aangemaakt_op: datetime


class WerknummerInput(StrikteInvoer):
    vendor_id: uuid.UUID
    werknummer: str


class OntledingRegelDto(BaseModel):
    id: uuid.UUID
    project_document_id: uuid.UUID
    soort: str
    omschrijving: str
    citaat: str | None = None
    waarde: dict | None = None
    zekerheid: Decimal | None = None
    status: str


class OntledingBeslisInput(StrikteInvoer):
    bevestigen: bool
    # Alleen bij een staffel-regel: de mens kiest de eenheid uit de vaste vier (de AI-eenheid
    # is alleen het voorstel) + de verrekenbaarheid.
    eenheid: Literal["m2", "m1", "stuks", "manuren"] | None = None
    verrekenbaar: bool = True


class PrijsafspraakDto(BaseModel):
    """Projectafspraak per veldwerker (steigerbouw-run B1, mockup projecten-invoer
    "Prijsafspraken veldwerkers — dit project")."""

    id: uuid.UUID
    gebruiker_id: uuid.UUID
    veldwerker_naam: str | None = None
    via_bureau_naam: str | None = None
    eenheid: Literal["uur", "m2"]
    tarief: Decimal
    geldig_vanaf_jaar: int | None = None
    geldig_vanaf_week: int | None = None
    geldig_tm_jaar: int | None = None
    geldig_tm_week: int | None = None
    toelichting: str | None = None
    standaard_tarief: Decimal | None = None
    aangemaakt_op: datetime
    aangemaakt_door_naam: str | None = None
    ingetrokken_op: datetime | None = None
    ingetrokken_reden: str | None = None


class VeldwerkerKeuzeDto(BaseModel):
    gebruiker_id: uuid.UUID
    naam: str
    via_bureau_naam: str | None = None
    standaard_tarief: Decimal | None = None


class PrijsafspraakInput(StrikteInvoer):
    gebruiker_id: uuid.UUID
    eenheid: Literal["uur", "m2"]
    tarief: Decimal
    geldig_vanaf_jaar: int | None = None
    geldig_vanaf_week: int | None = None
    geldig_tm_jaar: int | None = None
    geldig_tm_week: int | None = None
    toelichting: str | None = None


class PrijsafspraakIntrekkenInput(StrikteInvoer):
    reden: str


class ProjectDetailResponse(BaseModel):
    project_id: uuid.UUID
    naam: str | None = None
    is_actief: bool
    specificatie: SpecificatieDto | None = None
    documenten: list[ProjectDocumentDto]
    staffels: list[StaffelDto]
    werknummers: list[WerknummerDto]
    ontleding: list[OntledingRegelDto]
    gebouwd_m2: Decimal
    prijsafspraken: list[PrijsafspraakDto] = []
    veldwerkers: list[VeldwerkerKeuzeDto] = []
    # Additief (fixrun 07-09 blok C5): verplichtingen mét verbruiksstand + weekstaten-/planningstand
    # (DTO's onderaan dit bestand; `from __future__ import annotations` maakt de vooruitverwijzing mogelijk).
    verplichtingen: list[ProjectVerplichtingDto] = []
    weekstaten_stand: WeekstatenStandDto | None = None


class NieuwProjectInput(StrikteInvoer):
    projectnummer: str
    plaats: str
    opdrachtgever: str
    startdatum: date | None = None


class NieuwProjectResponse(BaseModel):
    rlz_project_id: uuid.UUID
    projectnaam: str
    bestond_al: bool


class VolgendNummerResponse(BaseModel):
    projectnummer: str


class OntleedResponse(BaseModel):
    project_document_id: uuid.UUID
    aantal_regels: int
    # D6 auto-first: tellers per uitkomst (direct ingevuld / expliciet niet aangetroffen / niet plaatsbaar /
    # mens-waarde behouden) + of doorlopende huur uit de huurstaffel is afgeleid (code, geen AI).
    overgenomen: int = 0
    niet_aangetroffen: int = 0
    ongeldig: int = 0
    mens_behouden: int = 0
    doorlopende_huur_afgeleid: bool = False


class CijfersSyncStartResponse(BaseModel):
    """202-antwoord van de sync-knop (achtergrondrun-fix 23-08): de run is gestart of
    hergebruikt (dubbelklik = zelfde run); de UI pollt de status-leesroute."""

    run_id: uuid.UUID
    status: str


class CijfersSyncStatusResponse(BaseModel):
    """Status van de recentste syncrun — `status` 'geen' als er nog nooit één draaide.
    `leesfouten` > 0 betekent: N documenten bleven onleesbaar in RLZ (cijfers mogelijk
    onvolledig, hun cache-rijen zijn bewust niet als verdwenen gemarkeerd)."""

    status: str
    run_id: uuid.UUID | None = None
    aangevraagd_op: datetime | None = None
    gestart_op: datetime | None = None
    beeindigd_op: datetime | None = None
    documenten: int | None = None
    regels: int | None = None
    verdwenen: int | None = None
    leesfouten: int | None = None
    fout_reden: str | None = None


# --- resultaat (analytische laag) ----------------------------------------------------------------


class ProjectWeekDto(BaseModel):
    jaar: int
    weeknummer: int
    baten: Decimal
    kosten_geboekt: Decimal
    kosten_onderweg: Decimal
    onderweg_onbepaalbaar_uren: Decimal
    saldo: Decimal
    cumulatief: Decimal
    baten_detail: list[str]
    kosten_detail: list[str]


class ProjectResultaatResponse(BaseModel):
    project_id: uuid.UUID
    project_naam: str | None = None
    opdrachtgever: str | None = None
    baten_geboekt: Decimal
    kosten_geboekt: Decimal
    uren_onderweg_bedrag: Decimal
    uren_onderweg_uren: Decimal
    onbepaalbaar_uren: Decimal
    meerwerk_onderweg_bedrag: Decimal
    onderweg_saldo: Decimal
    verwachte_marge: Decimal
    marge_pct: Decimal | None = None
    weken: list[ProjectWeekDto]


class OverzichtRijDto(BaseModel):
    project_id: uuid.UUID
    project_naam: str | None = None
    opdrachtgever: str | None = None
    baten: Decimal  # geboekt + meerwerk-onderweg
    kosten_incl_onderweg: Decimal
    marge: Decimal
    marge_pct: Decimal | None = None
    trend: str  # 'stijgend' | 'dalend' | 'stabiel'
    kosten_zonder_omzet_weken: int
    meerwerk_te_lang_niet_doorbelast: int
    doorlopende_huur: bool
    onbepaalbaar_uren: Decimal


class ProjectenOverzichtResponse(BaseModel):
    baten_totaal: Decimal
    kosten_totaal_incl_onderweg: Decimal
    uren_onderweg_totaal: Decimal
    onbepaalbaar_uren_totaal: Decimal
    meerwerk_onderweg_totaal: Decimal
    marge_totaal: Decimal
    marge_pct: Decimal | None = None
    aandacht: int
    rijen: list[OverzichtRijDto]


# --- Inzicht › Projecten kantoorbreed + detail-verrijking (fixrun 07-09 blok C5) --------------------


class ResultaatChipDto(BaseModel):
    baten: Decimal
    kosten: Decimal
    marge: Decimal
    marge_pct: Decimal | None = None
    onbepaalbaar_uren: Decimal
    heeft_cijfers: bool


class VerplichtingenChipDto(BaseModel):
    aantal: int
    goedgekeurd_excl: Decimal
    verbruikt_excl: Decimal
    percentage: int | None = None
    overschreden: int


class WeekstatenChipDto(BaseModel):
    van_toepassing: bool
    ontbrekend: int
    oudste_ontbrekende_jaar: int | None = None
    oudste_ontbrekende_week: int | None = None
    te_keuren: int
    concept: int


class M2ChipDto(BaseModel):
    gebouwd_m2: Decimal
    contract_m2: Decimal | None = None
    percentage: int | None = None
    doorlopende_huur: bool


class ProjectKantoorbreedRijDto(BaseModel):
    administratie_id: uuid.UUID
    administratie_naam: str
    project_id: uuid.UUID
    naam: str | None = None
    opdrachtgever: str | None = None
    werknummer_opdrachtgever: str | None = None
    looptijd_tot: date | None = None
    resultaat: ResultaatChipDto
    verplichtingen: VerplichtingenChipDto
    weekstaten: WeekstatenChipDto
    m2: M2ChipDto
    signalen: list[str]
    urgentie: int


class ProjectenKantoorbreedTellersDto(BaseModel):
    projecten: int
    administraties: int
    met_signaal: int
    verplichting_overschreden: int
    marge_negatief: int
    weekstaat_ontbreekt: int
    te_keuren: int


class ProjectenAdministratieFacetDto(BaseModel):
    administratie_id: uuid.UUID
    naam: str
    aantal: int


class ProjectenKantoorbreedResponse(BaseModel):
    rijen: list[ProjectKantoorbreedRijDto]
    totaal: int
    pagina: int
    per_pagina: int
    administraties_in_selectie: int
    tellers: ProjectenKantoorbreedTellersDto
    facetten: dict  # {"status": {facet: n}, "administraties": [ProjectenAdministratieFacetDto]}


class ProjectVerplichtingDto(BaseModel):
    """Eén verplichting op het projectdetail mét verbruiksstand (VerbruiksBalk-patroon)."""

    document_id: uuid.UUID
    offertenummer: str | None = None
    soort_label: str | None = None
    leverancier_naam: str | None = None
    omschrijving: str | None = None
    goedgekeurd_excl: Decimal | None = None
    verbruikt_excl: Decimal
    percentage: int | None = None
    over_excl: Decimal | None = None
    geldig_tot: date | None = None
    status: str  # lopend | overschreden | vervallen
    open_facturen_aantal: int = 0
    open_facturen_excl: Decimal = Decimal("0.00")


class WeekStandDto(BaseModel):
    jaar: int
    weeknummer: int
    maandag: date
    gepland_personen: int
    gepland_dagen: Decimal
    concept: int
    ingediend: int
    goedgekeurd: int
    corrigeren: int
    ontbrekend: int
    afgemeld: int


class WeekstatenStandDto(BaseModel):
    van_toepassing: bool
    weken: list[WeekStandDto] = []
    ontbrekend_totaal: int = 0
    te_keuren_totaal: int = 0
    oudste_ontbrekende_jaar: int | None = None
    oudste_ontbrekende_week: int | None = None
