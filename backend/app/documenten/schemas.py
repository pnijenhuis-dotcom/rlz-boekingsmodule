from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated

from pydantic import BaseModel, BeforeValidator


def _naar_decimal_met_komma(waarde: object) -> object:
    """Accepteert zowel '1234.56' als NL-notatie '1.234,56' — de frontend normaliseert vóór
    verzending altijd naar punt-decimaal (design-pass taak P2), maar deze validator maakt de API
    zelf ook robuust voor directe aanroepen (curl/scripts/oude clients) met een komma-decimaal.
    Een komma in de string is het onderscheidende signaal: zonder komma nemen we de waarde als
    al-genormaliseerd punt-decimaal aan (geen giswerk over duizendtal-punten)."""
    if isinstance(waarde, str) and "," in waarde:
        schoon = waarde.strip().replace(".", "").replace(",", ".")
        try:
            Decimal(schoon)
        except InvalidOperation:
            return waarde  # laat pydantic zelf de oorspronkelijke waarde afwijzen met een nette fout
        return schoon
    return waarde


DecimalMetKomma = Annotated[Decimal, BeforeValidator(_naar_decimal_met_komma)]


class DuplicaatReferentieResponse(BaseModel):
    """Genoeg om in de UI een klikbare link te tonen (design-pass taak 5) — bestandsnaam +
    uploaddatum van het vermoedelijke origineel, nooit een kale UUID."""

    document_id: uuid.UUID
    bestandsnaam: str
    aangemaakt_op: datetime


class DocumentUploadResponse(BaseModel):
    document_id: uuid.UUID
    status: str
    mogelijk_duplicaat_van: DuplicaatReferentieResponse | None = None


class DocumentListItemResponse(BaseModel):
    id: uuid.UUID
    bestandsnaam: str
    status: str
    bron: str
    mogelijk_duplicaat_van: DuplicaatReferentieResponse | None = None
    toegewezen_aan: uuid.UUID | None = None
    aangemaakt_op: datetime
    laatst_gewijzigd_op: datetime


class DocumentListResponse(BaseModel):
    documenten: list[DocumentListItemResponse]


class DocumentGebeurtenisResponse(BaseModel):
    van_status: str | None
    naar_status: str
    actor_id: uuid.UUID
    detail: dict | None
    tijdstip: datetime


class DocumentDetailResponse(BaseModel):
    id: uuid.UUID
    administratie_id: uuid.UUID | None
    bestandsnaam: str
    status: str
    bron: str
    mogelijk_duplicaat_van: DuplicaatReferentieResponse | None = None
    toegewezen_aan: uuid.UUID | None = None
    aangemaakt_op: datetime
    laatst_gewijzigd_op: datetime
    veldvoorstel: dict | None = None
    tijdlijn: list[DocumentGebeurtenisResponse]


class BoekvoorstelRegelDto(BaseModel):
    ledger_id: uuid.UUID | None = None
    taxrate_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    netto_bedrag: DecimalMetKomma | None = None
    btw_bedrag: DecimalMetKomma | None = None
    omschrijving: str | None = None


class BoekvoorstelResponse(BaseModel):
    document_id: uuid.UUID
    vendor_id: uuid.UUID | None = None
    referentie: str | None = None
    factuurdatum: date | None = None
    totaalbedrag: DecimalMetKomma | None = None
    rlz_boekstuknummer: str | None = None
    opgeslagen: bool
    regels: list[BoekvoorstelRegelDto]


class BoekvoorstelInput(BaseModel):
    vendor_id: uuid.UUID | None = None
    referentie: str | None = None
    factuurdatum: date | None = None
    totaalbedrag: DecimalMetKomma | None = None
    regels: list[BoekvoorstelRegelDto] = []


class CheckResultaatDto(BaseModel):
    naam: str
    ok: bool
    melding: str


class CheckRapportResponse(BaseModel):
    geblokkeerd: bool
    resultaten: list[CheckResultaatDto]


class BoekvoorstelMetChecksResponse(BaseModel):
    boekvoorstel: BoekvoorstelResponse
    checks: CheckRapportResponse


class BoekenResponse(BaseModel):
    document_id: uuid.UUID
    status: str
    rlz_document_id: uuid.UUID
    rlz_boekstuknummer: str | None = None
