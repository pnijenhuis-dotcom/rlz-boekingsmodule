from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas_basis import StrikteInvoer

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
    # Failsafe kliktest-fix 2026-08-08: gevuld = de laatste versheid-probe faalde onverwacht;
    # `laatste_import` is dan de laatst-bekende (mogelijk verouderde) waarde.
    probe_fout: str | None = None


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


class AfletterKoppelingResponse(BaseModel):
    """Eén werkelijke koppeling uit het PaymentReferenceList-leesspoor (hulzen al uitgefilterd)."""

    rlz_document_id: str | None = None
    boekstuknummer: str | None = None
    bedrag: Decimal | None = None


class AfletterOpdrachtResponse(BaseModel):
    """Levenscyclus van één afletter-opdracht (kliktest 2026-08-08): de UI leidt de chip af uit
    status + laatste_verificatie_poging_op ("klaargezet" vs "wacht op verificatie") en toont bij
    geverifieerd het resultaat (koppelingen + voorstel_gevolgd — false = afwijkend gevolgd)."""

    id: uuid.UUID
    status: str
    payment_item_id: uuid.UUID | None
    klaargezet_op: datetime
    laatste_verificatie_poging_op: datetime | None = None
    geverifieerd_op: datetime | None = None
    voorstel_gevolgd: bool | None = None
    # Hoe de verificatie tot stand kwam: "api" (koppeling door ons gelegd),
    # "al_afgeletterd_in_rlz" (vooraf-toets, kliktest 2026-08-09) of None (sync-verificatie).
    uitvoering: str | None = None
    koppelingen: list[AfletterKoppelingResponse] = []


class AfletterHistorieRegelResponse(BaseModel):
    """Opdracht mét mutatie-context voor de levenscyclus-lijst per rekening."""

    opdracht: AfletterOpdrachtResponse
    boekdatum: date | None
    tegenpartij_naam: str | None
    bedrag: Decimal | None


class AfletterHistorieResponse(BaseModel):
    opdrachten: list[AfletterHistorieRegelResponse]


class AfletterVerifieerResponse(BaseModel):
    geverifieerd: int


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


class AfletterKlaarzettenInput(StrikteInvoer):
    payment_item_id: uuid.UUID


class AfletterKlaarzettenResponse(BaseModel):
    """`uitkomst`: afgeletterd_via_api (koppeling gelegd + direct geverifieerd),
    al_afgeletterd_in_rlz (vooraf-toets zag de mutatie al dicht in RLZ — geverifieerd zonder
    nieuwe koppeling, kliktest 2026-08-09) of wacht_op_mens_in_rlz (assist-fallback ná een
    API-fout — zie `fout`, nooit stil)."""

    opdracht_id: uuid.UUID
    uitkomst: str
    fout: str | None = None


class DirectBoekenRegelInput(StrikteInvoer):
    ledger_id: uuid.UUID
    netto_bedrag: Decimal
    btw_bedrag: Decimal | None = None
    taxrate_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    omschrijving: str | None = None


class DirectBoekenInput(StrikteInvoer):
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


class StornoInput(StrikteInvoer):
    reden: str = Field(min_length=1)


class BankSyncResponse(BaseModel):
    rekeningen_bijgewerkt: int
    mutaties_nieuw: int
    mutaties_bijgewerkt: int
    open_ververst: int
    open_posten_bijgewerkt: int
    afletteren_geverifieerd: int
    automatisch_afgeletterd: int = 0
    afletter_fouten: list[str] = []
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


class NieuweBankRegelInput(StrikteInvoer):
    tegenpartij_naam: str = Field(min_length=1)
    tegenrekening_iban: str | None = None
    ledger_id: uuid.UUID
    taxrate_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    omschrijving: str | None = None
