from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.documenten.schemas import CheckRapportResponse
from app.schemas_basis import StrikteInvoer


class OmzetRegelDto(BaseModel):
    categorie: str
    categorie_sleutel: str | None = None
    omzet_bedrag: Decimal | None = None
    kostprijs_bedrag: Decimal | None = None
    omzet_ledger_id: uuid.UUID | None = None
    taxrate_id: uuid.UUID | None = None
    kostprijs_ledger_id: uuid.UUID | None = None
    # 'mapping' (onthouden per administratie) | 'nieuw' (blokkerend tot ingesteld) | 'default' | 'opgeslagen'.
    herkomst: str = "nieuw"
    # Blok C/D (16-09): herkomst van de voorgestelde btw — 'mapping' | 'instelling' | 'default_laag' | 'default_hoog' |
    # 'verlegd' | 'opgeslagen' | None; `btw_herkomst_detail` = chip-tekst ("Stripe · EU-dienst verlegd").
    btw_herkomst: str | None = None
    btw_herkomst_detail: str | None = None


class OmzetVoorstelResponse(BaseModel):
    document_id: uuid.UUID
    periode_start: date | None = None
    periode_eind: date | None = None
    rapport_totaal_omzet: Decimal | None = None
    rapport_totaal_kostprijs: Decimal | None = None
    # In code berekend (nooit AI): omzet / kostprijs × 100, 1 decimaal.
    marge_pct: Decimal | None = None
    regels: list[OmzetRegelDto]
    voorraad_ledger_id: uuid.UUID | None = None
    opgeslagen: bool
    rapport_titel: str | None = None
    entiteit_naam: str | None = None
    # Omzetbronnen (Peter 15-09): herkomst + bron-detail (betaalwijzen, kas, controles, batch) voor het controlescherm.
    bron: str | None = None
    bron_detail: dict | None = None
    # Peter 16-09 (Van Boxtel): "Boekt in Reeleezee als: ‹binder› · ‹categorie›" mét herkomst, plus de keuzelijst
    # (gesynchroniseerde DocumentType-10-categorieën mét binder) voor de klikbare keuze in het scherm.
    verkoop_categorie: VerkoopCategorieDto | None = None
    verkoop_categorieen: list[VerkoopCategorieKeuzeDto] = []


class VerkoopCategorieDto(BaseModel):
    id: uuid.UUID | None = None
    naam: str | None = None
    binder: str | None = None
    # 'mens' | 'automatisch' | None
    bron: str | None = None
    is_inkomsten: bool = False


class VerkoopCategorieKeuzeDto(BaseModel):
    id: uuid.UUID
    naam: str
    binder: str | None = None
    is_inkomsten: bool = False


class VerkoopCategorieInput(StrikteInvoer):
    categorie_id: uuid.UUID
    document_id: uuid.UUID | None = None


class RekeningKeuzeDto(BaseModel):
    ledger_id: uuid.UUID
    code: str
    naam: str


class TariefKeuzeDto(BaseModel):
    taxrate_id: uuid.UUID
    naam: str | None = None
    percentage: Decimal | None = None
    is_verlegd: bool = False


class OmzetBronInstellingenDto(BaseModel):
    """Contract opdracht 4 (16-09): `omzet_instelling.bron_instellingen` additief + read-only `defaults` (wat de code
    zou kiezen) en de keuzelijsten `rekeningen`/`tarieven` voor de comboboxen — geen extra routes nodig.
    `stores` is sinds 0151 (Peter 16-09 avond) een AFGELEIDE weergave uit de platformbrede store-routering
    ("stores die hier landen") — beheren op Instellingen › Boeken › Stores, niet via de PUT hieronder."""

    stores: list[str] = []
    product_categorieen: dict[str, str] = {}
    tegenrekeningen: dict[str, uuid.UUID | None] = {}
    categorie_btw: dict[str, uuid.UUID | None] = {}
    combi_regel: str = "pro_rato_batch"
    psp: str | None = "stripe"
    psp_kosten_ledger_id: uuid.UUID | None = None
    eten_drinken_tarief: str = "laag"
    defaults: dict = {}
    rekeningen: list[RekeningKeuzeDto] = []
    tarieven: list[TariefKeuzeDto] = []


class OmzetBronInstellingenInput(StrikteInvoer):
    """Geen `stores` meer (0151): die sleutel wordt door de service geweigerd mét verwijzing naar het Stores-blok."""

    product_categorieen: dict[str, str] = {}
    tegenrekeningen: dict[str, uuid.UUID | None] = {}
    categorie_btw: dict[str, uuid.UUID | None] = {}
    combi_regel: str | None = None
    psp: str | None = None
    psp_kosten_ledger_id: uuid.UUID | None = None
    eten_drinken_tarief: str | None = None


class OmzetVoorstelMetChecksResponse(BaseModel):
    voorstel: OmzetVoorstelResponse
    checks: CheckRapportResponse


class OmzetRegelInputDto(StrikteInvoer):
    categorie: str
    omzet_bedrag: Decimal | None = None
    kostprijs_bedrag: Decimal | None = None
    omzet_ledger_id: uuid.UUID | None = None
    taxrate_id: uuid.UUID | None = None
    kostprijs_ledger_id: uuid.UUID | None = None


class OmzetVoorstelInput(StrikteInvoer):
    periode_start: date | None = None
    periode_eind: date | None = None
    rapport_totaal_omzet: Decimal | None = None
    rapport_totaal_kostprijs: Decimal | None = None
    regels: list[OmzetRegelInputDto]
    voorraad_ledger_id: uuid.UUID | None = None
    # Mockup: "mapping onthouden per administratie" — default aan; uitzetten bewaart alleen dit
    # voorstel zonder de mapping voor volgende rapporten te wijzigen.
    mapping_onthouden: bool = True


class OmzetBoekenResponse(BaseModel):
    document_id: uuid.UUID
    status: str
    verkoop_rlz_id: uuid.UUID
    verkoop_referentie: str | None = None
    verkoop_boekstuknummer: str | None = None
    memoriaal_rlz_id: uuid.UUID | None = None
    memoriaal_boekstuknummer: str | None = None


class OmzetMappingDto(BaseModel):
    categorie_sleutel: str
    weergave_naam: str
    omzet_ledger_id: uuid.UUID
    taxrate_id: uuid.UUID
    kostprijs_ledger_id: uuid.UUID | None = None


class OmzetMappingLijstResponse(BaseModel):
    mappingen: list[OmzetMappingDto]


class OmzetStoreDto(BaseModel):
    """Eén rij van de platformbrede store-routering (0151): store → administratie, actief, herkomst."""

    id: uuid.UUID
    store_naam: str
    store_norm: str
    administratie_id: uuid.UUID
    administratie_naam: str
    actief: bool
    bron: str
    gewijzigd_op: datetime | None = None


class OmzetStoresDto(BaseModel):
    stores: list[OmzetStoreDto] = []
    #: Deeplink die de verzamelbak-rij en de LET-OP dragen (één bron voor frontend-teksten).
    doel_pad: str = "/instellingen/boeken#stores"


class OmzetStoreKoppelInput(StrikteInvoer):
    store: str = Field(min_length=1, max_length=120)
    administratie_id: uuid.UUID


class OmzetStoreWijzigInput(StrikteInvoer):
    administratie_id: uuid.UUID | None = None
    actief: bool | None = None
