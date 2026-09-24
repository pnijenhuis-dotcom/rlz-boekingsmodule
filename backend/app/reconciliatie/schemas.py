"""DTO's Inzicht › Reconciliatie (opdracht 06-09) — spiegel in frontend/src/reconciliatie/reconciliatieApi.ts."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ReconciliatieRunDto(BaseModel):
    """Eén reconciliatie-alles-run (202-antwoord + status-poll, bank_sync_run-patroon)."""

    run_id: uuid.UUID
    status: str  # wachtend | bezig | klaar | fout
    bron: str  # scheduler | cli | handmatig
    aangevraagd_op: datetime
    gestart_op: datetime | None = None
    afgerond_op: datetime | None = None
    exit_code: int | None = None
    # per blok: {status: ok|actie|fout, exit_code, gecontroleerd, afwijkingen, geaccepteerd, uitgesloten,
    # let_op, fouten, foutmelding}
    samenvatting: dict | None = None
    fout_reden: str | None = None
    # Sinds 09-09 samengesteld: "actie=<s>;systeem=<s>" (s ∈ niet_nodig | verzonden | mislukt | niet_geconfigureerd);
    # oudere runs één kale status. Client: reconciliatieApi.mailStatusTekst.
    mail_status: str | None = None
    mail_detail: str | None = None


class AcceptatieWeergaveDto(BaseModel):
    reden: str
    geaccepteerd_op: datetime
    geaccepteerd_door_naam: str | None = None


class GezienWeergaveDto(BaseModel):
    reden: str
    gezien_op: datetime
    vervalt_op: datetime
    gezien_door_naam: str | None = None


class DetailRegelDto(BaseModel):
    """Eén technische sleutel in de uitklap "details" (GUID, vingerafdruk, ruwe regel)."""

    label: str
    waarde: str


class BevindingDto(BaseModel):
    """Eén rij = één bevinding uit de laatste afgeronde run, mét precies één handeling. Sinds 07-09 (blok A8)
    draagt ze de leesbare laag `titel`/`wat`/`doe` (namen, geen GUID's) + `details`; `tekst` = de CLI-regel."""

    id: uuid.UUID
    run_id: uuid.UUID
    blok: str  # bank | documenten | omzet | doorbelasting | run
    soort: str  # afwijking | let_op | fout | geaccepteerd | uitgesloten | gezien
    administratie_id: uuid.UUID | None = None
    administratie_naam: str | None = None
    vingerafdruk: str
    tekst: str
    titel: str = ""
    wat: str = ""
    doe: str = ""
    details: list[DetailRegelDto] = []
    sinds: datetime
    nieuw: bool
    acceptatie: AcceptatieWeergaveDto | None = None
    gezien: GezienWeergaveDto | None = None
    detail: dict | None = None
    doel_pad: str | None = None


class TellersDto(BaseModel):
    afwijkingen: int
    let_op: int
    fouten: int
    geaccepteerd: int
    uitgesloten: int
    gezien: int
    administraties: int
    meten: int = 0  # SPOED 17-09: afwijkingen van bevindingssoorten in stand `meten`


class AdministratieFacetDto(BaseModel):
    administratie_id: uuid.UUID
    naam: str
    aantal: int


class FacettenDto(BaseModel):
    soort: dict[str, int]
    administraties: list[AdministratieFacetDto]


class BevindingenLijstDto(BaseModel):
    rijen: list[BevindingDto]
    totaal: int
    pagina: int
    per_pagina: int
    administraties_in_selectie: int
    tellers: TellersDto
    facetten: FacettenDto
    laatste_run: ReconciliatieRunDto | None = None


class StandDto(BaseModel):
    """KPI-kaart werkvoorraad: teller = open afwijkingen + fouten + open LET-OP's."""

    teller: int
    afwijkingen: int
    let_op: int
    fouten: int
    laatste_run: ReconciliatieRunDto | None = None


class RedenInvoerDto(BaseModel):
    administratie_id: uuid.UUID
    reden: str = Field(min_length=1, max_length=2000)


class ActieResultaatDto(BaseModel):
    id: uuid.UUID


class IntakeNuVerwerkenDto(BaseModel):
    """"Nu verwerken" op de postvak-bevinding (blok `intake`, Peter 22-09): de intake-job van het kanaal is gestart
    (cloud: Cloud Run-job on-demand; dev: thread). De uitkomst staat ná de run in de verwerkt-administratie en bij de
    volgende reconciliatie-run; een mislukte start is een 502, nooit een stille 202."""

    kanaal: str
    postvak_adres: str | None
    voertuig: str
    job_resource: str | None


class SoortStandDto(BaseModel):
    """SPOED 17-09: stand per bevindingssoort — `meten` (telt, geen handeling) of `actie` (actiemail + KPI)."""

    soort: str
    blok: str
    sinds: str
    default: str
    override: str | None = None
    stand: str


class InstellingDto(BaseModel):
    gezien_dagen: int = Field(ge=1, le=3650)
    soort_standen: list[SoortStandDto] = []


class SoortStandInvoerDto(BaseModel):
    soort: str = Field(min_length=1, max_length=80)
    stand: str = Field(pattern="^(meten|actie)$")
    reden: str = Field(min_length=1, max_length=2000)


class OpnieuwBoekenInvoerDto(RedenInvoerDto):
    """Invoer van "Opnieuw boeken (extern document verdwenen)". De twee extra velden zijn de Beheerder-doorzet ná een
    409 `btw_mogelijk_aangegeven` (correctie Peter 07-09 op A11): de boekdatum van de verdwenen boeking valt in een
    ingediende btw-aangifte. `btw_niet_in_aangifte_bevestigd=True` mag ALLEEN een Beheerder zetten (server-side
    rolcheck, anders 403) en vereist `bevestiging_reden` (≥ 5 tekens, anders 422)."""

    btw_niet_in_aangifte_bevestigd: bool = False
    bevestiging_reden: str | None = Field(default=None, max_length=2000)


class OpnieuwBoekenResultaatDto(BaseModel):
    """Antwoord van "Opnieuw boeken (extern document verdwenen)" (A11, 07-09): het document staat weer klaar om te
    boeken mét een nieuwe boek_cyclus; `doel_pad` = het controlescherm waar de mens de boeking afmaakt."""

    document_id: uuid.UUID
    status: str
    boek_cyclus: int
    doel_pad: str


class TypeWijzigenKassarapportInvoerDto(BaseModel):
    """Invoer van "Type wijzigen → kassarapport" (blok C 16-09 avond): alleen de administratie (scope-toets); de soort-wissel
    zelf vraagt geen reden (zelfde route als de bulk-actie in de documentenlijst)."""

    administratie_id: uuid.UUID


class TypeWijzigenKassarapportResultaatDto(BaseModel):
    document_id: uuid.UUID
    status: str
    van_soort: str
    naar_soort: str
    doel_pad: str


class BundelenInvoerDto(BaseModel):
    """Invoer van "Bundelen" (blok 1 bundelrun 24-09, bevinding `ubl_pdf_ongebundeld`): alleen de administratie
    (scope-toets); het paar wordt server-side opnieuw bepaald, nooit uit de client vertrouwd."""

    administratie_id: uuid.UUID


class BundelenResultaatDto(BaseModel):
    document_id: uuid.UUID
    ubl_document_id: uuid.UUID
    status: str
    match_basis: str | None
    rlz_bijlage: str | None
    doel_pad: str


class FactuurPdfHerstellenInvoerDto(BaseModel):
    """Invoer van "Factuur-PDF herstellen" (24-09 stap 4, bevinding `doorbelasting_factuur_pdf_ontbreekt`): alleen de
    bron-administratie (scope-toets); de boeking wordt server-side gelezen, nooit uit de client vertrouwd."""

    administratie_id: uuid.UUID


class FactuurPdfHerstellenResultaatDto(BaseModel):
    boeking_id: uuid.UUID
    document_id: uuid.UUID
    doelentiteit_naam: str
    verkoop_referentie: str | None
    factuur_pdf_status: str
    doel_pad: str


class HerboekenAlsOmzetResultaatDto(BaseModel):
    """Antwoord van "Herboeken als omzet" (Peter 16-09, Van Boxtel): de inkoopfactuur is gestorneerd (of bestond al
    niet meer) en het document is nu een kassarapport in de werkvoorraad; `doel_pad` = waar de mens 'm als omzet boekt."""

    document_id: uuid.UUID
    status: str
    gestorneerd: bool
    doel_pad: str


class BewustVerwijderdInvoerDto(BaseModel):
    """Invoer van "Bewust verwijderd in RLZ" (blok D 16-09): geen vrije reden — de reden is vast
    (`bewust_verwijderd.VASTE_REDEN`), een toelichting is optioneel (≤ 500 tekens)."""

    administratie_id: uuid.UUID
    toelichting: str | None = Field(default=None, max_length=500)


class BewustVerwijderdResultaatDto(BaseModel):
    """Antwoord: de acceptatie + wat er met het document gebeurde. `document_status_gewijzigd=False` = het document
    stond niet op geboekt en is alleen geaccepteerd (status ongewijzigd, zichtbaar gemeld)."""

    acceptatie_id: uuid.UUID
    document_id: uuid.UUID
    document_status_nieuw: str
    boekstuknummer: str | None
    document_status_gewijzigd: bool
    reden: str


class BewustVerwijderdHerstelInvoerDto(RedenInvoerDto):
    """Terugweg van "Bewust verwijderd in RLZ": document terug naar geboekt + acceptatie ingetrokken (Beheerder,
    verplichte reden — dezelfde maat als intrekken)."""


class BewustVerwijderdHerstelResultaatDto(BaseModel):
    document_id: uuid.UUID
    document_status_nieuw: str
    acceptatie_ingetrokken_id: uuid.UUID | None


class ExternGeboektAfwijzenInvoerDto(BaseModel):
    """Invoer van "Afwijzen — al geboekt als ‹boekstuk›" (Peter 22-09): het externe stuk uit de bevinding (of uit de
    boekfout ná het laatste akkoord); toelichting optioneel — de reden is voorgevuld."""

    administratie_id: uuid.UUID
    extern_id: str | None = Field(default=None, max_length=120)
    extern_boekstuk: str | None = Field(default=None, max_length=60)
    systeem: str = Field(default="Reeleezee", max_length=20)
    toelichting: str | None = Field(default=None, max_length=500)


class ExternGeboektAfwijzenResultaatDto(BaseModel):
    document_id: uuid.UUID
    status: str
    reden: str
    accordering_vervallen: bool
    afwijzing_id: uuid.UUID


class ExternGeboektTochVerschillendInvoerDto(BaseModel):
    """Invoer van "Toch verschillend — doorgaan" (Peter 22-09): reden verplicht (≥ 5 tekens), `extern_id` verplicht
    (dát stuk wordt uitgezonderd); `bevinding_id` optioneel — een Beheerder accepteert dan óók de open bevinding."""

    administratie_id: uuid.UUID
    extern_id: str = Field(min_length=1, max_length=120)
    extern_boekstuk: str | None = Field(default=None, max_length=60)
    reden: str = Field(min_length=1, max_length=2000)
    bevinding_id: uuid.UUID | None = None


class ExternGeboektTochVerschillendResultaatDto(BaseModel):
    document_id: uuid.UUID
    extern_ids: list[str]
    reden: str
    bevinding_geaccepteerd: bool
    checks_cache_ongeldig: int
