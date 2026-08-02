from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

# --- bank-overzicht (klantenlijst) ---------------------------------------------------------------


class BankKlantResponse(BaseModel):
    administratie_id: uuid.UUID
    naam: str
    open_mutaties: int
    oudste_open_datum: date | None
    rekeningen: list[str]
    laatste_sync_op: datetime | None
    ooit_gesynchroniseerd: bool


class BankOverzichtResponse(BaseModel):
    klanten: list[BankKlantResponse]


# --- rekeningen ----------------------------------------------------------------------------------


class LaatsteImportResponse(BaseModel):
    datum: str | None = None
    bron: str | None = None
    type: str | None = None
    bestandsnaam: str | None = None


class RekeningResponse(BaseModel):
    id: uuid.UUID
    naam: str | None
    iban: str | None
    rekening_type: int | None
    is_kas: bool
    saldo: Decimal | None
    saldo_datum: date | None
    open_mutaties: int
    heeft_aanlevering: bool
    laatste_import: LaatsteImportResponse | None


class RekeningenResponse(BaseModel):
    rekeningen: list[RekeningResponse]
    laatste_sync_op: datetime | None
    ooit_gesynchroniseerd: bool
    heeft_bankaanlevering: bool


# --- mutaties + voorstellen ----------------------------------------------------------------------


class OpenPostResponse(BaseModel):
    id: uuid.UUID
    bedrag: Decimal | None
    referentie: str | None
    referentie2: str | None
    rlz_document_id: uuid.UUID | None


class BoekRegelResponse(BaseModel):
    ledger_id: uuid.UUID
    netto_bedrag: Decimal
    btw_bedrag: Decimal | None
    taxrate_id: uuid.UUID | None
    project_id: uuid.UUID | None
    omschrijving: str | None


class VoorstelResponse(BaseModel):
    soort: str
    kleur: str
    bron: str
    reden: str
    payment_item_id: uuid.UUID | None
    open_post: OpenPostResponse | None
    regel_id: uuid.UUID | None
    regels: list[BoekRegelResponse]


class AfletterOpdrachtResponse(BaseModel):
    id: uuid.UUID
    status: str
    payment_item_id: uuid.UUID | None
    klaargezet_op: datetime


class RegelVoorstelResponse(BaseModel):
    tegenpartij_sleutel: str
    ledger_id: uuid.UUID
    taxrate_id: uuid.UUID | None
    aantal_boekingen: int


class MutatieResponse(BaseModel):
    id: uuid.UUID
    boekdatum: date | None
    bedrag: Decimal | None
    open_bedrag: Decimal | None
    tegenpartij_naam: str | None
    omschrijving: str | None
    tegenrekening_iban: str | None
    voorstel: VoorstelResponse
    afletter_opdracht: AfletterOpdrachtResponse | None
    regel_voorstel: RegelVoorstelResponse | None


class MutatiesResponse(BaseModel):
    mutaties: list[MutatieResponse]


# --- acties --------------------------------------------------------------------------------------


class AfletterKlaarzettenInput(BaseModel):
    payment_item_id: uuid.UUID


class AfletterKlaarzettenResponse(BaseModel):
    opdracht_id: uuid.UUID
    uitkomst: str


class DirectBoekenRegelInput(BaseModel):
    ledger_id: uuid.UUID
    netto_bedrag: Decimal
    btw_bedrag: Decimal | None = None
    taxrate_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    omschrijving: str | None = None


class DirectBoekenInput(BaseModel):
    regels: list[DirectBoekenRegelInput] = Field(min_length=1)
    omschrijving: str | None = None
    # Herkomst voor de audit/regelteller: 'handmatig' of 'vaste_regel' (akkoord op een
    # regel-voorstel); 'automatisch' is exclusief voor de achtergrondverwerking.
    bron: str = "handmatig"
    # Mockup: "Na 3× dezelfde handmatige boeking stelt de app een vaste regel voor" — de
    # bevestiging van dat voorstel reist mee met de boekactie.
    vaste_regel_opslaan: bool = False


class DirectBoekenResponse(BaseModel):
    boeking_id: uuid.UUID
    rlz_boekstuknummer: str | None
    al_eerder_geboekt: bool
    vaste_regel_aangemaakt: bool


class StornoInput(BaseModel):
    reden: str = Field(min_length=1)


class BankSyncResponse(BaseModel):
    rekeningen_bijgewerkt: int
    mutaties_nieuw: int
    mutaties_bijgewerkt: int
    open_ververst: int
    open_posten_bijgewerkt: int
    afletteren_geverifieerd: int
    vastly_gemeld: int
    automatisch_geboekt: int
    automatisch_fouten: list[str]


class BankRegelResponse(BaseModel):
    id: uuid.UUID
    tegenpartij_sleutel: str
    tegenrekening_iban: str | None
    ledger_id: uuid.UUID
    taxrate_id: uuid.UUID | None
    project_id: uuid.UUID | None
    omschrijving: str | None
    actief: bool


class BankRegelLijstResponse(BaseModel):
    regels: list[BankRegelResponse]


class NieuweBankRegelInput(BaseModel):
    tegenpartij_naam: str = Field(min_length=1)
    tegenrekening_iban: str | None = None
    ledger_id: uuid.UUID
    taxrate_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    omschrijving: str | None = None
