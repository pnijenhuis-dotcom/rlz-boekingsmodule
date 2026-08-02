from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, SmallInteger, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base

# Bankmodule-datamodel (migratie 0026). Leeskant = caches van RLZ (RLZ blijft de bron van
# waarheid, kernprincipe 1); app-werkstaat (afletter-opdrachten, directe boekingen, vaste
# regels) staat bewust in EIGEN tabellen, nooit als kolommen op de caches — de sync mag een
# cache-rij altijd volledig overschrijven zonder werkstaat te kunnen vernielen.
#
# ⚠️ Afgeletterd-status: ALTIJD op `open_bedrag` toetsen, nooit op RLZ's IsComplete — dat veld
# blijft na een storno stale op true (schrijf-PoC §6, vier keer gereproduceerd). IsComplete
# wordt daarom bewust niet eens gemodelleerd; wie het nodig denkt te hebben leest brondata.


class PaymentAccountCache(Base):
    """Rekeningen per administratie — bank én kas via dezelfde route (`GET PaymentAccounts`,
    STAP 0 §1: kas = Type 3, PaymentAccountTypes-enum 1 Bank … 8 Cheque). `laatste_import` is de
    versheid-probe (`PaymentAccounts/{id}/LastBankImport`, STAP 0 §3): bestandsnaam, datum,
    BankImportSource/-Type — óók de onboarding-check "heeft deze klant wel bankaanlevering?".
    NULL = nooit een aanlevering gezien. `gateway_state`/`gateway_type` zijn de PSD2-velden
    (BankGatewayStates 0=Active…3=Deleted, BankGatewayTypes 0=NonPsd2/1=Psd2)."""

    __tablename__ = "payment_account_cache"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), primary_key=True
    )
    naam: Mapped[str | None] = mapped_column(default=None)
    iban: Mapped[str | None] = mapped_column(default=None)
    rekening_type: Mapped[int | None] = mapped_column(SmallInteger, default=None)
    saldo: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    saldo_datum: Mapped[date | None] = mapped_column(default=None)
    is_gearchiveerd: Mapped[bool | None] = mapped_column(default=None)
    gateway_state: Mapped[int | None] = mapped_column(SmallInteger, default=None)
    gateway_type: Mapped[int | None] = mapped_column(SmallInteger, default=None)
    # none_as_null: een rekening zónder aanlevering moet echt SQL NULL zijn (de onboarding-check
    # toetst op IS NULL), niet een JSON-'null'-waarde.
    laatste_import: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), default=None)
    brondata: Mapped[dict] = mapped_column(JSONB)
    laatst_gesynchroniseerd: Mapped[datetime] = mapped_column(server_default=func.now())
    verdwenen_uit_bron_op: Mapped[datetime | None] = mapped_column(default=None)


class BankMutatie(Base):
    """Ruwe bankmutatie (`GET PaymentTransactions`, STAP 0 §2 — dé bron, niet Statements).
    `open_bedrag` (RLZ's OpenAmount) is de leidende afgeletterd-indicator: != 0 betekent nog
    (deels) onverwerkt. `rlz_voorstel_item_id` is RLZ's eigen matchvoorstel (auto-gevuld
    `MatchedPaymentItem` bij exacte bedrag-match, schrijf-PoC §1) — voorstel-volgorde stap 4,
    mét bronvermelding. `rlz_create_date` voedt de incrementele sync (CreateDate-watermark pakt
    ook laat binnengekomen mutaties met een oudere boekdatum). Rijen worden nooit verwijderd
    (kernprincipe 3 — er bestaat een DELETE-route bij RLZ, die gebruiken we nooit)."""

    __tablename__ = "bank_mutatie"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), primary_key=True
    )
    payment_account_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    boekdatum: Mapped[date | None] = mapped_column(default=None)
    bedrag: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    open_bedrag: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    tegenrekening_iban: Mapped[str | None] = mapped_column(default=None)
    tegenpartij_naam: Mapped[str | None] = mapped_column(default=None)
    omschrijving: Mapped[str | None] = mapped_column(default=None)
    mutatie_type: Mapped[int | None] = mapped_column(SmallInteger, default=None)
    rlz_voorstel_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    rlz_create_date: Mapped[datetime | None] = mapped_column(default=None)
    brondata: Mapped[dict] = mapped_column(JSONB)
    laatst_gesynchroniseerd: Mapped[datetime] = mapped_column(server_default=func.now())
    verdwenen_uit_bron_op: Mapped[datetime | None] = mapped_column(default=None)


class PaymentItemCache(Base):
    """Open posten om tegen af te letteren (`GET PaymentItems`, STAP 0 §5). `referentie` is de
    factuurreferentie, `referentie2` RLZ's boekstuknummer+datum, `rlz_document_id` het
    achterliggende document. Een post die uit de collectie verdwijnt (betaald/verrekend) krijgt
    `verdwenen_uit_bron_op` — zelfde patroon als de sync-caches, nooit hard verwijderen."""

    __tablename__ = "payment_item_cache"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), primary_key=True
    )
    bedrag: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    boekdatum: Mapped[date | None] = mapped_column(default=None)
    vervaldatum: Mapped[date | None] = mapped_column(default=None)
    referentie: Mapped[str | None] = mapped_column(default=None)
    referentie2: Mapped[str | None] = mapped_column(default=None)
    rlz_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    payment_status: Mapped[int | None] = mapped_column(SmallInteger, default=None)
    brondata: Mapped[dict] = mapped_column(JSONB)
    laatst_gesynchroniseerd: Mapped[datetime] = mapped_column(server_default=func.now())
    verdwenen_uit_bron_op: Mapped[datetime | None] = mapped_column(default=None)


class BankSyncStand(Base):
    """Sync-boekhouding per administratie: de CreateDate-watermark voor de incrementele
    mutatie-sync + het laatste sync-moment (UI-versheid: "gesynchroniseerd om …")."""

    __tablename__ = "bank_sync_stand"
    __table_args__ = {"schema": "boekhouding"}

    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), primary_key=True
    )
    mutaties_watermark: Mapped[datetime | None] = mapped_column(default=None)
    laatste_sync_op: Mapped[datetime | None] = mapped_column(default=None)


class AfletterOpdrachtStatus(enum.StrEnum):
    """Assist-model (fallback-PoC-consequentie 2: afletteren-tegen-open-post kan via de API in
    géén enkele vorm — 15/16, 34 én 218 dicht): KLAARGEZET = de app heeft het matchvoorstel
    gemarkeerd "af te letteren in Reeleezee", de mens legt de koppeling in de RLZ-UI;
    GEVERIFIEERD = de eerstvolgende sync zag OpenAmount 0 en heeft het leesspoor vastgelegd;
    INGETROKKEN = bewust geannuleerd (met actor + audit, nooit stil verwijderd)."""

    KLAARGEZET = "klaargezet"
    GEVERIFIEERD = "geverifieerd"
    INGETROKKEN = "ingetrokken"


class BankAfletterOpdracht(Base):
    """Eén klaargezette afletter-actie voor één bankmutatie (assist-model, zie
    app/bank/afletteren.py — de uitvoerings-seam). `payment_item_id`/`rlz_document_id` zijn het
    vóórgestelde doel; `verificatie_detail` legt bij verificatie vast waartegen RLZ de mutatie
    wérkelijk heeft afgeletterd (PaymentReferenceList-leesspoor, hulzen uitgefilterd op
    DocumentType 19 + Status 1 — nooit op IsSystemGenerated alleen, fallback-PoC §5) — wijkt de
    mens in RLZ af van het voorstel, dan is dat zichtbaar, nooit stil. Hooguit één klaargezette
    opdracht per mutatie (partiële unique index, migratie 0026); historie blijft staan."""

    __tablename__ = "bank_afletter_opdracht"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id")
    )
    payment_transaction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    payment_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    rlz_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    voorstel_detail: Mapped[dict | None] = mapped_column(JSONB, default=None)
    status: Mapped[str] = mapped_column(default=AfletterOpdrachtStatus.KLAARGEZET.value)
    klaargezet_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    klaargezet_op: Mapped[datetime] = mapped_column(server_default=func.now())
    geverifieerd_op: Mapped[datetime | None] = mapped_column(default=None)
    verificatie_detail: Mapped[dict | None] = mapped_column(JSONB, default=None)
    ingetrokken_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    ingetrokken_op: Mapped[datetime | None] = mapped_column(default=None)


class BankBoekingStatus(enum.StrEnum):
    GEBOEKT = "geboekt"
    GESTORNEERD = "gestorneerd"


class BankBoekingBron(enum.StrEnum):
    """Waar de boekbeslissing vandaan kwam (herkomst-chip + 3×-regelteller): HANDMATIG = de
    controleur koos zelf; VASTE_REGEL = mens klikte akkoord op een regel-voorstel; AUTOMATISCH =
    de opt-in autoboek-verwerking (systeem-actor) paste een vaste regel zelf toe."""

    HANDMATIG = "handmatig"
    VASTE_REGEL = "vaste_regel"
    AUTOMATISCH = "automatisch"


class BankBoeking(Base):
    """Eén directe grootboekboeking van een bankmutatie (`PUT BankMutationDirectBookings`,
    schrijf-PoC §3 — boekt direct op Status 3 én lettert af). `rlz_document_id` is het
    deterministische RLZ-client-GUID (rlz_ids.rlz_bank_boeking_id, UUIDv5 op de mutatie-id):
    een retry raakt hetzelfde RLZ-document, en ook een herboeking ná storno hergebruikt
    datzelfde RLZ-document (PUT op hetzelfde GUID). Lokaal krijgt élke boekronde een eigen rij
    (surrogaat-`id`): de gestorneerde rij blijft als historie staan — vandaar geen unique op
    payment_transaction_id maar een partiële ("één GEBOEKTE per mutatie", migratie 0026)."""

    __tablename__ = "bank_boeking"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id")
    )
    payment_transaction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    rlz_document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    omschrijving: Mapped[str | None] = mapped_column(default=None)
    rlz_boekstuknummer: Mapped[str | None] = mapped_column(default=None)
    bron: Mapped[str] = mapped_column(default=BankBoekingBron.HANDMATIG.value)
    status: Mapped[str] = mapped_column(default=BankBoekingStatus.GEBOEKT.value)
    geboekt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    geboekt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    gestorneerd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    gestorneerd_op: Mapped[datetime | None] = mapped_column(default=None)
    storno_reden: Mapped[str | None] = mapped_column(default=None)


class BankBoekingRegel(Base):
    """Eén grootboekregel binnen een directe bankboeking. Bedragen dragen het TEKEN VAN DE
    MUTATIE (schrijf-PoC: NetAmount = Amount van de transactie) en moeten samen exact het
    mutatiebedrag dekken — hard afgedwongen in app/bank/boeken.py, code rekent, nooit AI."""

    __tablename__ = "bank_boeking_regel"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bank_boeking_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.bank_boeking.id")
    )
    volgnummer: Mapped[int]
    ledger_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    taxrate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    netto_bedrag: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    btw_bedrag: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    omschrijving: Mapped[str | None] = mapped_column(default=None)


class BankRegel(Base):
    """Vaste regel uit het geheugen (voorstel-volgorde stap 3, mockup: "vaste regel (elke
    maand)"): tegenpartij → grootboek/btw/project. `tegenpartij_sleutel` is de genormaliseerde
    naam (app/geheugen/normalisatie.py — zelfde normalisatie als het boekingsgeheugen);
    `tegenrekening_iban` matcht daarnaast exact als hij gevuld is. Regels ontstaan alleen door
    een mens (bevestiging van het 3×-voorstel of expliciet aanmaken) — nooit stil. Deactiveren
    i.p.v. verwijderen (`actief`), historie blijft."""

    __tablename__ = "bank_regel"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id")
    )
    tegenpartij_sleutel: Mapped[str]
    tegenrekening_iban: Mapped[str | None] = mapped_column(default=None)
    ledger_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    taxrate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    omschrijving: Mapped[str | None] = mapped_column(default=None)
    actief: Mapped[bool] = mapped_column(default=True)
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    gedeactiveerd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    gedeactiveerd_op: Mapped[datetime | None] = mapped_column(default=None)
