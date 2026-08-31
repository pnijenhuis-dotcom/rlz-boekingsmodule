"""DTO's transportplanning + bestellingen + materiaalstand + materiaalmatch (blok D)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas_basis import StrikteInvoer


class LeverancierDto(BaseModel):
    id: uuid.UUID
    naam: str
    bestel_email: str | None = None
    telefoon: str | None = None
    adres: str | None = None
    vendor_id: uuid.UUID | None = None
    actief: bool
    aantal_producten: int
    # Contactpersonen (31-08): transport-contact (bevestig-mail), materiaal-contact (lijst/delta).
    transport_contact_naam: str | None = None
    transport_contact_email: str | None = None
    materiaal_contact_naam: str | None = None
    materiaal_contact_email: str | None = None


class LeverancierZettenRequest(StrikteInvoer):
    id: uuid.UUID | None = None
    naam: str = Field(min_length=1, max_length=120)
    bestel_email: str | None = Field(default=None, max_length=254)
    telefoon: str | None = Field(default=None, max_length=40)
    adres: str | None = Field(default=None, max_length=200)
    vendor_id: uuid.UUID | None = None
    actief: bool = True
    transport_contact_naam: str | None = Field(default=None, max_length=120)
    transport_contact_email: str | None = Field(default=None, max_length=254)
    materiaal_contact_naam: str | None = Field(default=None, max_length=120)
    materiaal_contact_email: str | None = Field(default=None, max_length=254)


class ProductDto(BaseModel):
    id: uuid.UUID
    leverancier_id: uuid.UUID
    categorie_id: uuid.UUID
    categorie_naam: str
    bundel: str
    naam: str
    verpakking: str | None = None
    eenheid: str
    m2_lengte: Decimal | None = None
    volgorde: int
    actief: bool
    nummer: str = ""


class CategorieDto(BaseModel):
    id: uuid.UUID
    naam: str
    bundel: str
    volgorde: int
    actief: bool
    producten: list[ProductDto]


class ProductenPaginaDto(BaseModel):
    items: list[ProductDto]
    totaal: int
    pagina: int
    per_pagina: int


class CategorieZettenRequest(StrikteInvoer):
    id: uuid.UUID | None = None
    leverancier_id: uuid.UUID
    naam: str = Field(min_length=1, max_length=80)
    bundel: str = "steiger"
    volgorde: int = 0
    actief: bool = True


class ProductZettenRequest(StrikteInvoer):
    id: uuid.UUID | None = None
    leverancier_id: uuid.UUID
    categorie_id: uuid.UUID
    naam: str = Field(min_length=1, max_length=120)
    verpakking: str | None = Field(default=None, max_length=40)
    eenheid: str = "stuks"
    m2_lengte: Decimal | None = None
    volgorde: int = 0
    actief: bool = True


class SeedResultaatDto(BaseModel):
    leverancier_id: uuid.UUID
    categorieen_nieuw: int
    producten_nieuw: int
    producten_bestaand: int


class BestelRegelDto(BaseModel):
    product: ProductDto
    aantal: int
    was: int | None = None
    geleverd: int = 0


class RevisieDto(BaseModel):
    revisie: int
    verstuurd_op: datetime
    verstuurd_door_naam: str | None = None
    verzonden_naar: str
    mail_status: str
    mail_fout: str | None = None
    m2_totaal: Decimal
    delta: list | None = None
    aantal_regels: int


class BestellingDto(BaseModel):
    id: uuid.UUID
    nummer: str
    project_id: uuid.UUID
    project_naam: str | None = None
    leverancier_id: uuid.UUID
    leverancier_naam: str
    leverancier_email: str | None = None
    status: str
    revisie: int
    heeft_concept_wijzigingen: bool
    gewenste_leverdatum: date | None = None
    gewenste_levertijd: time | None = None
    leveradres: str | None = None
    contactpersoon: str | None = None
    opmerking: str | None = None
    annulering_reden: str | None = None
    m2_totaal: Decimal
    aantal_regels: int
    aangemaakt_op: datetime
    bijgewerkt_op: datetime
    regels: list[BestelRegelDto] = []
    revisies: list[RevisieDto] = []
    transport_ids: list[uuid.UUID] = []


class BestellingenPaginaDto(BaseModel):
    items: list[BestellingDto]
    totaal: int
    pagina: int
    per_pagina: int


class BestellingAanmakenRequest(StrikteInvoer):
    project_id: uuid.UUID
    leverancier_id: uuid.UUID
    gewenste_leverdatum: date | None = None
    gewenste_levertijd: time | None = None


class BestellingConceptRequest(StrikteInvoer):
    regels: dict[str, int]
    gewenste_leverdatum: date | None = None
    gewenste_levertijd: time | None = None
    leveradres: str | None = Field(default=None, max_length=300)
    contactpersoon: str | None = Field(default=None, max_length=120)
    opmerking: str | None = Field(default=None, max_length=1000)


class VersturenRequest(StrikteInvoer):
    koppel_levering: bool = True


class RedenRequest(StrikteInvoer):
    reden: str = Field(min_length=1, max_length=500)


class TransportDto(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_naam: str | None = None
    leverancier_id: uuid.UUID
    leverancier_naam: str
    bestelling_id: uuid.UUID | None = None
    bestelling_nummer: str | None = None
    soort: str
    datum: date
    tijdstip: time | None = None
    status: str
    status_bron: str
    status_reden: str | None = None
    regels: list[dict]
    samenvatting: str
    m2: Decimal
    omschrijving: str | None = None
    # Dag-agenda-kaart (31-08): zelfstandig leesbaar.
    voertuig: str | None = None
    transportplanner: str | None = None
    opdrachtgever: str | None = None
    project_adres: str | None = None


class TransportPlannenRequest(StrikteInvoer):
    project_id: uuid.UUID
    leverancier_id: uuid.UUID
    soort: str
    datum: date
    tijdstip: time | None = None
    regels: dict[str, int] = {}
    omschrijving: str | None = Field(default=None, max_length=300)
    bestelling_id: uuid.UUID | None = None


class TransportWijzigenRequest(StrikteInvoer):
    datum: date | None = None
    tijdstip: time | None = None
    regels: dict[str, int] | None = None
    omschrijving: str | None = Field(default=None, max_length=300)
    project_id: uuid.UUID | None = None
    soort: str | None = None  # alleen zolang gereserveerd (werkbakje-kaart wisselen ▲/▼)


class TransportStatusRequest(StrikteInvoer):
    status: str
    reden: str | None = Field(default=None, max_length=500)


class TransportBevestigRequest(StrikteInvoer):
    """Rood → oranje: de voertuigtoezegging van het transport-contact is verplicht (31-08)."""

    voertuig: str  # combi | voorwagen


class TransportDefinitiefRequest(StrikteInvoer):
    """Oranje → groen: materiaallijst + transportplanner — lijst gaat naar het materiaal-contact."""

    regels: dict[str, int]
    transportplanner: str = Field(min_length=1, max_length=120)


class TransportMateriaallijstRequest(StrikteInvoer):
    """Delta-flow ná definitief: alleen de gewijzigde regels gaan oud → nieuw per mail."""

    regels: dict[str, int]
    transportplanner: str | None = Field(default=None, max_length=120)


class TransportVerschuifRequest(StrikteInvoer):
    """Dag verschuiven (slepen): terug naar gereserveerd — opnieuw bevestigen."""

    datum: date


class WachtrisicoDto(BaseModel):
    project_id: uuid.UUID
    project_naam: str | None = None
    datum: date
    aantal_personen: int
    transport_id: uuid.UUID | None = None
    leverancier_naam: str | None = None
    samenvatting: str


class TransportProjectRijDto(BaseModel):
    project_id: uuid.UUID
    project_naam: str | None = None
    opdrachtgever: str | None = None
    is_actief: bool
    per_datum: dict[str, list[TransportDto]]
    week_transporten: int
    ploeg_label: str | None = None


class TePlannenDto(BaseModel):
    """Signaalkaart "nog te plannen" (31-08): verstuurde bestelling mét leverdatum in de week
    zónder transportregel — rood gestippeld in de dagkolom."""

    bestelling_id: uuid.UUID
    bestelling_nummer: str
    project_id: uuid.UUID
    project_naam: str | None = None
    leverancier_naam: str
    datum: date


class TransportWeekDto(BaseModel):
    jaar: int
    weeknummer: int
    maandag: date
    zondag: date
    projecten: list[TransportProjectRijDto]
    wachtrisico: list[WachtrisicoDto]
    aantal_transporten: int
    bestellingen_concept: int
    bestellingen_met_wijzigingen: int
    materiaalmatch_open: int
    te_plannen: list[TePlannenDto] = []


class StandRegelDto(BaseModel):
    product_id: uuid.UUID
    naam: str
    categorie: str
    eenheid: str
    geleverd: int
    retour: int
    op_locatie: int
    eerste_levering: date | None = None
    laatste_retour: date | None = None
    huurdagen_tot_vandaag: int
    huur_eenheden: Decimal
    leveranciers: list[str]
    m2: Decimal


class MateriaalStandDto(BaseModel):
    project_id: uuid.UUID
    project_naam: str | None = None
    tot_en_met: date
    regels: list[StandRegelDto]
    m2_op_locatie: Decimal
    totaal_items: int
    leveranciers: list[str]


class MateriaalmatchDto(BaseModel):
    document_id: uuid.UUID
    leverancier_id: uuid.UUID
    leverancier_naam: str | None = None
    project_id: uuid.UUID | None = None
    project_naam: str | None = None
    uitkomst: str
    aantal_regels_getoetst: int
    aantal_regels_afwijkend: int
    aantal_regels_onbekend: int
    details: dict | None = None
    berekend_op: datetime
    afwijking_bevestigd: bool
    afwijking_bevestigd_op: datetime | None = None
