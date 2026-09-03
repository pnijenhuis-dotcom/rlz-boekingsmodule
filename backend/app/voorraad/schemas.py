from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas_basis import StrikteInvoer


class GroepAansluitingDto(BaseModel):
    artikelgroep_id: uuid.UUID
    naam: str
    eenheid: str
    tolerantie_pct: Decimal
    begin: Decimal
    inkoop: Decimal
    verkoop: Decimal
    theoretisch: Decimal
    systeemstand: Decimal | None = None
    telling_datum: date | None = None
    verschil: Decimal | None = None
    verschil_pct: Decimal | None = None
    signaal: str
    onzeker_pct: Decimal
    regels_in: int
    regels_uit: int


class AansluitingDto(BaseModel):
    administratie_id: uuid.UUID
    van: date
    tot: date
    groepen: list[GroepAansluitingDto]
    niet_genormaliseerd_in: int
    niet_genormaliseerd_uit: int
    onzeker_totaal: int
    regels_totaal: int
    # v2 (30-08): dienst-/transportregels in de periode — soort-label, tellen niet in de aansluiting.
    dienst_regels: int = 0
    transport_regels: int = 0
    # Bron per kolom (mockup-beslispunt 2: "instroom extern vs uitstroom intern" altijd herleidbaar).
    bronnen: dict[str, str]


class DagStandDto(BaseModel):
    datum: date
    inkoop: Decimal
    verkoop: Decimal
    stand: Decimal


class RegelDto(BaseModel):
    id: uuid.UUID
    # Herkomst (migratie 0087): een lokaal document óf een RLZ-verkoopfactuur (bron rlz_verkoop).
    document_id: uuid.UUID | None = None
    rlz_document_id: uuid.UUID | None = None
    rlz_referentie: str | None = None
    richting: str
    bron: str
    datum: date
    relatie_naam: str | None = None
    artikeltekst: str
    # v2: artikelcode (normalisatiesleutel) + soort artikel/dienst/transport.
    artikelcode: str | None = None
    soort: str = "artikel"
    aantal: Decimal | None = None
    eenheid: str | None = None
    prijs: Decimal | None = None
    netto_bedrag: Decimal | None = None
    artikelgroep_id: uuid.UUID | None = None
    artikelgroep_naam: str | None = None
    normalisatie_status: str
    normalisatie_zekerheid: Decimal | None = None


class DienstTekstDto(BaseModel):
    """ "Als dienst geclassificeerd" — één rij per unieke (leverancier, tekst) mét aantallen (v2, blok B)."""

    voorbeeld_regel_id: uuid.UUID
    artikeltekst: str
    artikeltekst_norm: str
    vendor_id: uuid.UUID | None = None
    relatie_naam: str | None = None
    soort: str
    bron: str
    richtingen: str
    regels: int
    som_aantal: Decimal
    som_netto: Decimal


class ArtikelcodeDto(BaseModel):
    """Codes-inzage: koppeling code → groep/soort per richting + leverancier (v2, blok C)."""

    id: uuid.UUID
    richting: str
    vendor_id: uuid.UUID | None = None
    relatie_naam: str | None = None
    code: str
    soort: str
    artikelgroep_id: uuid.UUID | None = None
    artikelgroep_naam: str | None = None
    zekerheid: Decimal | None = None
    bron: str
    voorbeeld_tekst: str | None = None
    regels: int
    teksten: int


class GroepDto(BaseModel):
    id: uuid.UUID
    naam: str
    eenheid: str
    tolerantie_pct: Decimal
    actief: bool


class GroepAanmakenDto(StrikteInvoer):
    naam: str = Field(min_length=1, max_length=80)
    eenheid: str = Field(default="st", max_length=16)
    tolerantie_pct: Decimal = Field(default=Decimal("1.00"), ge=0, le=100)


class TolerantieDto(StrikteInvoer):
    tolerantie_pct: Decimal = Field(ge=0, le=100)


class TellingInvoerDto(StrikteInvoer):
    artikelgroep_id: uuid.UUID
    datum: date
    aantal: Decimal = Field(ge=0)
    opmerking: str | None = Field(default=None, max_length=500)


class CorrectieDto(StrikteInvoer):
    """Correctie per regel(tekst): soort artikel (mét groep) óf dienst/transport (zonder groep) — v2
    vervangt het oude `uitgesloten`-vlagje door het soort-label."""

    regel_id: uuid.UUID
    soort: Literal["artikel", "dienst", "transport"] = "artikel"
    artikelgroep_id: uuid.UUID | None = None


class ArtikelcodeCorrectieDto(StrikteInvoer):
    soort: Literal["artikel", "dienst", "transport"] = "artikel"
    artikelgroep_id: uuid.UUID | None = None


class RegelsPaginaDto(BaseModel):
    """Server-side gepagineerde regel-lijst (B3.3, 03-09): `rijen` + `totaal` + `pagina`/`per_pagina`."""

    rijen: list[RegelDto]
    totaal: int
    pagina: int
    per_pagina: int


class DienstenPaginaDto(BaseModel):
    rijen: list[DienstTekstDto]
    totaal: int
    pagina: int
    per_pagina: int


class ArtikelcodesPaginaDto(BaseModel):
    rijen: list[ArtikelcodeDto]
    totaal: int
    pagina: int
    per_pagina: int


class VerschilRijDto(BaseModel):
    """Eén artikelgroep buiten tolerantie op de kantoorbrede landing Inzicht › Voorraad (B3, 03-09)."""

    administratie_id: uuid.UUID
    administratie_naam: str
    artikelgroep_id: uuid.UUID
    naam: str
    eenheid: str
    tolerantie_pct: Decimal
    theoretisch: Decimal
    systeemstand: Decimal
    telling_datum: date
    verschil: Decimal
    verschil_pct: Decimal | None
    # STATUS-kleur op de lijst: oranje | rood (server bepaalt de zwaarte, de client kleurt alleen).
    zwaarte: str
    tot: date


class VerschilTellersDto(BaseModel):
    groepen: int
    administraties: int
    administraties_met_voorraad: int


class VerschilFacetAdministratieDto(BaseModel):
    id: uuid.UUID
    naam: str
    aantal: int


class VerschillenLijstDto(BaseModel):
    rijen: list[VerschilRijDto]
    totaal: int
    pagina: int
    per_pagina: int
    tellers: VerschilTellersDto
    facetten: list[VerschilFacetAdministratieDto]
    # Periode waarmee de drill-down per administratie geopend wordt (theoretisch is van-onafhankelijk).
    van: date
    tot: date


class HerrekenResultaatDto(BaseModel):
    inkoop_documenten: int
    inkoop_regels: int
    verkoop_documenten: int
    verkoop_regels: int
    # Opgeslagen RLZ-verkoopregels opnieuw genormaliseerd (het lezen uit RLZ zit in de dagelijkse sync).
    rlz_regels: int = 0
    # Idem voor de Odoo-verkoopregels (blok D 03-09: Odoo als leesbron vanaf de voorraad-knip).
    odoo_regels: int = 0


class CorrectieResultaatDto(BaseModel):
    herrekend: int
