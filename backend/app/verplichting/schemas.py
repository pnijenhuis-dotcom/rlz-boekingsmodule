"""API-modellen documenttype "verplichting" (CONTRACT_B — bindend voor de frontend)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.schemas_basis import StrikteInvoer


class CheckDto(BaseModel):
    naam: str
    #: 'ok' | 'blokkerend' | 'signaal' | 'niet_van_toepassing'
    status: str
    melding: str


class SuggestieDto(BaseModel):
    vendor_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    naam: str | None = None
    match: str | None = None


class GoedgekeurdDto(BaseModel):
    bedrag_excl: Decimal | None
    op: datetime | None
    door_naam: str | None


class VerbruikDto(BaseModel):
    verbruikt_excl: Decimal
    totaal_excl: Decimal
    percentage: int
    over_excl: Decimal | None = None
    #: Voorwaarschuwing 0.1: gematchte, nog niet geboekte facturen — informatief, buiten het verbruik.
    open_facturen_aantal: int = 0
    open_facturen_excl: Decimal = Decimal("0.00")


class VervallenDto(BaseModel):
    op: datetime
    reden: str | None
    door_naam: str | None


class GekoppeldeFactuurDto(BaseModel):
    document_id: uuid.UUID
    referentie: str | None = None
    factuurdatum: date | None = None
    bedrag_excl: Decimal | None = None
    status: str
    verrekend: bool


class VerplichtingVoorstelDto(BaseModel):
    document_id: uuid.UUID
    status: str
    soort_label: str | None = None
    vendor_id: uuid.UUID | None = None
    vendor_naam: str | None = None
    project_id: uuid.UUID | None = None
    project_naam: str | None = None
    offertenummer: str | None = None
    datum: date | None = None
    totaalbedrag_excl: Decimal | None = None
    geldig_tot: date | None = None
    omschrijving: str | None = None
    opgeslagen: bool = False
    #: veld -> 'ai' | 'template' | 'mens' | null (velden: soort_label, leverancier, project,
    #: offertenummer, totaalbedrag_excl, geldig_tot, omschrijving)
    herkomst: dict[str, str | None] = {}
    zekerheid: dict[str, float] = {}
    zekerheid_drempel: float = 0.0
    vendor_suggestie: SuggestieDto | None = None
    project_suggestie: SuggestieDto | None = None
    goedgekeurd: GoedgekeurdDto | None = None
    verbruik: VerbruikDto | None = None
    vervallen: VervallenDto | None = None
    gekoppelde_facturen: list[GekoppeldeFactuurDto] = []
    checks: list[CheckDto] = []
    ai_overgeslagen_reden: str | None = None


class VerplichtingVoorstelInput(StrikteInvoer):
    soort_label: str | None = None
    vendor_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    offertenummer: str | None = None
    datum: date | None = None
    totaalbedrag_excl: Decimal | None = None
    geldig_tot: date | None = None
    omschrijving: str | None = None


class ChecksDto(BaseModel):
    checks: list[CheckDto]
    geblokkeerd: bool


class VervallenInput(StrikteInvoer):
    reden: str


class MatchVerplichtingDto(BaseModel):
    document_id: uuid.UUID
    offertenummer: str | None = None
    soort_label: str | None = None
    leverancier_naam: str | None = None
    project_naam: str | None = None
    totaal_excl: Decimal | None = None
    goedgekeurd_op: datetime | None = None
    goedgekeurd_door_naam: str | None = None


class MatchKandidaatDto(BaseModel):
    document_id: uuid.UUID
    offertenummer: str | None = None
    soort_label: str | None = None
    totaal_excl: Decimal | None = None
    verbruikt_excl: Decimal
    project_naam: str | None = None
    geldig_tot: date | None = None


class VerplichtingMatchDto(BaseModel):
    document_id: uuid.UUID
    #: 'binnen' | 'buiten' | 'geen_match' | 'meerdere_kandidaten' | 'niet_toetsbaar' | 'geen_verplichting'
    uitkomst: str
    verplichting: MatchVerplichtingDto | None = None
    bedrag_excl: Decimal | None = None
    verbruik_voor: Decimal | None = None
    verbruik_na: Decimal | None = None
    percentage_na: int | None = None
    overschrijding_excl: Decimal | None = None
    handmatig_gekoppeld: bool = False
    kandidaten: list[MatchKandidaatDto] = []
    berekend_op: datetime | None = None
    melding: str = ""


class KoppelInput(StrikteInvoer):
    #: null = ontkoppelen.
    verplichting_document_id: uuid.UUID | None = None


class OfferteMatchKortDto(BaseModel):
    """Compacte melding voor de accordeur-kaart (OPTIE A, ④) — alleen bij binnen/buiten."""

    uitkomst: str
    offertenummer: str | None = None
    leverancier_naam: str | None = None
    goedgekeurd_door_naam: str | None = None
    goedgekeurd_op: datetime | None = None
    bedrag_excl: Decimal | None = None
    verbruik_na: Decimal | None = None
    totaal_excl: Decimal | None = None
    percentage_na: int | None = None
    overschrijding_excl: Decimal | None = None


class VerplichtingKortDto(BaseModel):
    """Kaart-gegevens van een verplichting-document in de accordeur-wachtrij (mockup blok 1)."""

    soort_label: str | None = None
    project_naam: str | None = None
    totaal_excl: Decimal | None = None
    geldig_tot: date | None = None
    omschrijving: str | None = None


# --- kantoorbreed (Inzicht › Verplichtingen) -----------------------------------------------------


class KantoorFactuurDto(BaseModel):
    document_id: uuid.UUID
    referentie: str | None = None
    factuurdatum: date | None = None
    bedrag_excl: Decimal | None = None
    status: str
    verrekend: bool


class KantoorRijDto(BaseModel):
    document_id: uuid.UUID
    administratie_id: uuid.UUID
    administratie_naam: str
    offertenummer: str | None = None
    soort_label: str | None = None
    leverancier_naam: str | None = None
    project_naam: str | None = None
    totaal_excl: Decimal | None = None
    verbruikt_excl: Decimal
    percentage: int | None = None
    over_excl: Decimal | None = None
    goedgekeurd_op: datetime | None = None
    goedgekeurd_door_naam: str | None = None
    geldig_tot: date | None = None
    status: str
    open_facturen_aantal: int = 0
    open_facturen_excl: Decimal = Decimal("0.00")
    facturen: list[KantoorFactuurDto] = []


class KantoorTellersDto(BaseModel):
    lopend: int
    overschreden: int
    vervallen: int


class AdministratieFacetDto(BaseModel):
    administratie_id: uuid.UUID
    naam: str
    aantal: int


class KantoorFacettenDto(BaseModel):
    status: dict[str, int]
    administraties: list[AdministratieFacetDto]


class VerplichtingKantoorLijstDto(BaseModel):
    rijen: list[KantoorRijDto]
    totaal: int
    pagina: int
    per_pagina: int
    administraties_in_selectie: int
    tellers: KantoorTellersDto
    facetten: KantoorFacettenDto
