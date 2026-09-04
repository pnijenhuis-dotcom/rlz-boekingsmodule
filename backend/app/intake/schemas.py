from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas_basis import StrikteInvoer


class IntakeBijlageResultaatDto(BaseModel):
    bestandsnaam: str
    # 'toegewezen' | 'verzamelbak' | 'splitsingsvoorstel' | 'vgb_genegeerd' | 'niet_verwerkbaar'
    uitkomst: str
    document_id: uuid.UUID | None = None
    detail: str | None = None


class IntakeVerwerkResponse(BaseModel):
    bericht_id: uuid.UUID | None
    al_eerder_verwerkt: bool
    bijlagen: list[IntakeBijlageResultaatDto]


class SplitsSegmentDto(BaseModel):
    start_pagina: int
    eind_pagina: int
    tenaamstelling: str | None = None
    leverancier: str | None = None
    factuurnummer: str | None = None
    zekerheid: float = 0.0
    # Proportionele validatie (02-09): dít deel doorstond de paginabereik-toets niet — mens beslist.
    ongeldig_reden: str | None = None
    # Bijlage-bewust (blok B 04-09): pagina's van de factuur zelf (AI, informatief) + door code afgeleide
    # bijlagepagina's; None = onbekend (óók voor voorstellen van vóór 04-09).
    factuur_paginas: int | None = None
    bijlage_paginas: int | None = None


class VerzamelbakItemDto(BaseModel):
    document_id: uuid.UUID
    bestandsnaam: str
    soort: str
    bron: str
    afzender_hint: str | None = None
    tenaamstelling: str | None = None
    suggestie_administratie_id: uuid.UUID | None = None
    suggestie_bron: str | None = None
    # Intake-reden (02-09): technisch + leesbaar label voor de rij — "geen tenaamstelling gelezen"
    # alleen nog als de AI werkelijk niets las (app/intake/redenen.py).
    reden: str | None = None
    reden_label: str | None = None
    aangemaakt_op: datetime
    splitsing_id: uuid.UUID | None = None
    splitsing_voorstel: list[SplitsSegmentDto] | None = None
    # Bundeling/samenvoegen (02-09): beeld naast een UBL-document, samengevoegde tweede rij, herkomst-mail.
    beeld_bestandsnaam: str | None = None
    samengevoegd_document_id: uuid.UUID | None = None
    samengevoegd_bestandsnaam: str | None = None
    intake_bericht_id: uuid.UUID | None = None
    # Zusje-signaal (02-09): de PDF/UBL van dezelfde factuur uit dezelfde mail is al toegewezen — toewijzen
    # van deze rij zou een tweede document maken.
    zusje_document_id: uuid.UUID | None = None
    zusje_bestandsnaam: str | None = None
    zusje_administratie_id: uuid.UUID | None = None


class VerzamelbakLijstResponse(BaseModel):
    items: list[VerzamelbakItemDto]


class ToewijzenInput(StrikteInvoer):
    administratie_id: uuid.UUID


class HoortNietBijOnsInput(StrikteInvoer):
    reden: str


class SplitsDeelInputDto(StrikteInvoer):
    start_pagina: int
    eind_pagina: int
    tenaamstelling: str | None = None


class SplitsingBevestigenInput(StrikteInvoer):
    delen: list[SplitsDeelInputDto]


class SplitsingAfwijzenInput(StrikteInvoer):
    reden: str | None = None
    # Blok B 04-09: "Onthoud: mails van ‹afzender› voor ‹administratie› nooit splitsen" — vink default UIT;
    # mét vink is administratie_id verplicht (422 zonder).
    onthoud_niet_splitsen: bool = False
    administratie_id: uuid.UUID | None = None


class SplitsingAfwijzenResponse(BaseModel):
    splitsing_id: uuid.UUID
    nooit_splitsen_regel_id: uuid.UUID | None = None


class SplitsingUitsluitingDto(BaseModel):
    id: uuid.UUID
    administratie_id: uuid.UUID
    afzender_adres: str
    leverancier_naam: str | None = None
    reden: str | None = None
    aangemaakt_op: datetime
    aangemaakt_door: uuid.UUID
    aangemaakt_door_naam: str | None = None


class SplitsingUitsluitingLijstResponse(BaseModel):
    regels: list[SplitsingUitsluitingDto]


class SplitsDeelResultaatDto(BaseModel):
    document_id: uuid.UUID
    bestandsnaam: str
    uitkomst: str
    administratie_id: uuid.UUID | None = None


class SplitsingBevestigenResponse(BaseModel):
    delen: list[SplitsDeelResultaatDto]


class DocumentStatusResponse(BaseModel):
    document_id: uuid.UUID
    status: str
    # Avondrun 26-08 (optimistisch verzamelbak-paneel): de actie was al eerder gedaan — geen
    # fout, rustig melden; `melding` is leesbare tekst voor de gebruiker.
    al_verwerkt: bool = False
    melding: str | None = None


class SamenvoegenInput(StrikteInvoer):
    leidend_document_id: uuid.UUID
    ander_document_id: uuid.UUID
    # Twee UBL's of twee PDF's alleen mét expliciete bevestiging (nooit stil).
    bevestig_zelfde_type: bool = False


class SamenvoegenResponse(BaseModel):
    document_id: uuid.UUID
    samengevoegd_document_id: uuid.UUID
    beeld_bestandsnaam: str
    waarschuwingen: list[str]


class SamenvoegenOngedaanResponse(BaseModel):
    document_id: uuid.UUID
    teruggezet_document_id: uuid.UUID


class UblSamenvattingRegelDto(BaseModel):
    omschrijving: str | None = None
    netto_bedrag: str | None = None
    aantal: str | None = None


class UblSamenvattingResponse(BaseModel):
    leverancier: str | None
    afnemer: str | None
    factuurnummer: str | None
    factuurdatum: str | None
    totaal_excl: str | None
    totaal_incl: str | None
    valuta: str | None
    regelaantal: int
    regels: list[UblSamenvattingRegelDto]


# ---- Bulk-toewijzen / bulk "hoort niet bij ons" (blok B 02-09, casus IC-stapel) ------------------------


class BulkToewijzenInput(StrikteInvoer):
    """Eén administratie voor álle geselecteerde rijen — server-side een orkestratie over de bestaande
    per-rij-route `wijs_toe` (geen tweede schrijver), uitkomst per rij (patroon bulk-accordering)."""

    document_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    administratie_id: uuid.UUID


class BulkHoortNietBijOnsInput(StrikteInvoer):
    document_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    reden: str


class BulkRijUitkomstDto(BaseModel):
    """Eén regel van de uitkomstenlijst — dezelfde vorm voor toewijzen en hoort-niet-bij-ons."""

    document_id: uuid.UUID
    bestandsnaam: str | None = None
    # 'verwerkt' | 'al_verwerkt' | 'fout'
    uitkomst: str
    status: str | None = None
    reden: str | None = None


class BulkVerzamelbakResponse(BaseModel):
    uitkomsten: list[BulkRijUitkomstDto]
    verwerkt: int
    al_verwerkt: int
    fout: int
