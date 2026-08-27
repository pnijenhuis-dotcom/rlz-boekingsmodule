"""DTO's voor de klant-accorderingsflow (migratie 0033). De endpoints zijn ontworpen voor de
latere accordeur-PWA (wachtrij/akkoord/afwijzen/staande regel) én de kantoor-UI (instellingen,
accorderingshistorie) — zelfde scope-regels als overal (RLS + server-side checks)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas_basis import StrikteInvoer


class LaagDto(BaseModel):
    volgnummer: int
    accordeur_gebruiker_id: uuid.UUID
    accordeur_naam: str | None = None
    bedrag_drempel: Decimal | None = None


class InstellingenResponse(BaseModel):
    ingeschakeld: bool
    lagen: list[LaagDto]
    # Alleen gevuld op de PUT-response (punt 2a): aantal lopende rondes dat door déze wijziging
    # verviel — de UI meldt het direct ("N accorderingen vervallen — opnieuw aanbieden").
    rondes_vervallen: int = 0


class LaagInputDto(StrikteInvoer):
    volgnummer: int
    accordeur_gebruiker_id: uuid.UUID
    bedrag_drempel: Decimal | None = None


class InstellingenInput(StrikteInvoer):
    ingeschakeld: bool
    lagen: list[LaagInputDto]


class KandidaatDto(BaseModel):
    id: uuid.UUID
    naam: str


class KandidatenResponse(BaseModel):
    kandidaten: list[KandidaatDto]


class StapResponse(BaseModel):
    volgnummer: int
    accordeur_gebruiker_id: uuid.UUID
    accordeur_naam: str | None
    bedrag_drempel: Decimal | None
    vereist: bool
    besluit: str | None
    besluit_bron: str | None
    reden: str | None
    besloten_op: datetime | None
    aan_de_beurt: bool


class AccorderingResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    status: str
    aangeboden_op: datetime
    afgerond_op: datetime | None
    stappen: list[StapResponse]


class HerinneringResponse(BaseModel):
    """Uitkomst van een handmatige herinnering (beheer-mini 2026-08-16, migratie 0053)."""

    document_id: uuid.UUID
    accordeur_naam: str
    verzonden_op: datetime
    kanaal: str


class HerinneringenOverzichtResponse(BaseModel):
    """document_id -> laatste geslaagde handmatige herinnering ("laatst herinnerd")."""

    laatst_herinnerd: dict[uuid.UUID, datetime]


class AanbiedenInput(StrikteInvoer):
    """Optionele body van de aanbieden-route (factuurmatch fase 2): de expliciete
    kantoor-bevestiging "aanbieden ondanks match-afwijking" — zelfde vlag als de boek-route."""

    match_afwijking_bevestigd: bool = False
    materiaal_afwijking_bevestigd: bool = False


class BulkAanbiedenInput(StrikteInvoer):
    """Bulk "Ter accordering aanbieden" (werkstroom-run 27/28-08, punt 2b): selectie van de
    documentenlijst. Begrensd — de UI biedt één lijstpagina aan, geen onbegrensde batch."""

    document_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class BulkAanbiedResultaatDto(BaseModel):
    document_id: uuid.UUID
    bestandsnaam: str | None
    # 'aangeboden' | 'geboekt' (staande goedkeuringen dekten alles) | 'overgeslagen'
    uitkomst: str
    reden: str | None = None
    boek_fout: str | None = None


class BulkAanbiedenResponse(BaseModel):
    resultaten: list[BulkAanbiedResultaatDto]
    aangeboden: int
    geboekt: int
    overgeslagen: int


class VervallenMeldingDto(BaseModel):
    """Eén configuratiewijziging die lopende rondes liet vervallen (punt 2a) — voedt de eenmalige
    banner op de documentenlijst; `nog_niet_opnieuw_aangeboden` 0 = klaar."""

    batch_id: uuid.UUID
    tijdstip: datetime
    door_gebruiker_id: uuid.UUID
    door_naam: str | None = None
    aantal: int
    nog_niet_opnieuw_aangeboden: int
    reden: str


class AkkoordInput(StrikteInvoer):
    staande_regel_aanmaken: bool = False


class AfwijsInput(StrikteInvoer):
    reden: str


class BesluitResponse(BaseModel):
    accordering: AccorderingResponse
    alles_akkoord: bool
    geboekt: bool
    boek_fout: str | None
    staande_regel_id: uuid.UUID | None


class WachtrijDoorbelastingRegelResponse(BaseModel):
    """Alleen-lezen doorbelasting-samenvatting voor de accordeur (besluit 25-08, A3)."""

    doelentiteit_naam: str
    percentage: Decimal
    netto_totaal: Decimal
    provisie_bedrag: Decimal


class AccordeurVraagBerichtInput(StrikteInvoer):
    tekst: str


class AccordeurVraagBerichtResponse(BaseModel):
    id: uuid.UUID
    auteur_id: uuid.UUID
    van_mij: bool
    tekst: str
    geplaatst_op: datetime


class AccordeurVraagResponse(BaseModel):
    """Vraag-thread zoals de accordeur-app 'm toont (blok B5 26-08): uitsluitend vragen die aan de
    ingelogde accordeur gericht zijn. Namen van kantoormedewerkers reizen niet mee (alleen
    'kantoor' vs 'u') — dataminimalisatie; `ik_ben_aan_de_beurt` stuurt de chip + antwoordbalk."""

    id: uuid.UUID
    administratie_id: uuid.UUID
    administratie_naam: str | None
    document_id: uuid.UUID
    document_status: str
    leverancier_naam: str | None
    totaalbedrag: Decimal | None
    vraag_tekst: str
    gesteld_op: datetime
    ik_ben_aan_de_beurt: bool
    berichten: list[AccordeurVraagBerichtResponse]


class VragenAanMijResponse(BaseModel):
    items: list[AccordeurVraagResponse]


class WachtrijItemResponse(BaseModel):
    document_id: uuid.UUID
    administratie_id: uuid.UUID
    administratie_naam: str | None
    leverancier_naam: str | None
    referentie: str | None
    factuurdatum: date | None
    totaalbedrag: Decimal | None
    aangeboden_op: datetime
    laag_volgnummer: int
    boeking_omschrijving: str | None = None
    staande_regel_kandidaat: bool = False
    doorbelasting: list[WachtrijDoorbelastingRegelResponse] | None = None
    # Open vraag aan déze accordeur op dit document (blok B5) — None = geen.
    vraag: AccordeurVraagResponse | None = None


class WachtrijResponse(BaseModel):
    items: list[WachtrijItemResponse]


class StaandeRegelResponse(BaseModel):
    id: uuid.UUID
    accordeur_gebruiker_id: uuid.UUID
    accordeur_naam: str | None
    vendor_id: uuid.UUID
    leverancier_naam: str | None
    bedrag: Decimal
    actief: bool
    aangemaakt_op: datetime
    ingetrokken_op: datetime | None


class StaandeRegelsResponse(BaseModel):
    regels: list[StaandeRegelResponse]
