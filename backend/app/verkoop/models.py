from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class VerkoopVoorstel(Base):
    """Kop van het verkoopfactuur-reviewvoorstel per VASTLY-VERKOOP-document (koppelcontract
    §2d v1.10/v1.11, migratie 0035): de deterministisch uit de UBL gelezen kopvelden, door de
    controleur te bevestigen. Nullable zolang de controleur bezig is — de harde checks
    (app/verkoop/checks.py) bepalen boekbaarheid, niet het schema (zelfde afweging als
    Boekvoorstel/OmzetVoorstel). `factuurnummer` is het Vastly-factuurnummer (cbc:ID) — dat
    wordt óók de webhook-referentie (§3 v1.10: vastgoeds koppelsleutel); RLZ's eigen Reference
    is niet zetbaar (RLZ overschrijft met RLZ-{InvoiceNumber})."""

    __tablename__ = "verkoop_voorstel"
    __table_args__ = {"schema": "boekhouding"}

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.document.id"), primary_key=True
    )
    debiteur_naam: Mapped[str | None] = mapped_column(default=None)
    factuurnummer: Mapped[str | None] = mapped_column(default=None)
    factuurdatum: Mapped[date | None] = mapped_column(default=None)
    totaalbedrag_incl: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    # CreditNote 381 (§2d-creditnota's v1.11): creditboeking omzetkant, herleid via
    # BillingReference naar het oorspronkelijke Vastly-factuurnummer.
    is_creditnota: Mapped[bool] = mapped_column(default=False)
    gecrediteerd_factuurnummer: Mapped[str | None] = mapped_column(default=None)
    rlz_boekstuknummer: Mapped[str | None] = mapped_column(default=None)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    bijgewerkt_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class VerkoopVoorstelRegel(Base):
    """Eén factuurregel binnen het verkoopvoorstel: bedragen + GB-code zoals uit de UBL gelezen
    (`gb_code` = cbc:AccountingCost, herleidbaarheid) en de gekozen/bevestigde ledger + btw-code.
    `ledger_id` nullable: een regel zónder AccountingCost is contractueel géén fout — de mens
    kiest bij het boeken (§2d-GB-uitbreiding v1.10); de verplichte-velden-check blokkeert tot
    dat gebeurd is."""

    __tablename__ = "verkoop_voorstel_regel"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.verkoop_voorstel.document_id")
    )
    volgnummer: Mapped[int]
    omschrijving: Mapped[str | None] = mapped_column(default=None)
    netto_bedrag: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    btw_bedrag: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    gb_code: Mapped[str | None] = mapped_column(default=None)
    ledger_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    taxrate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)


class VerkoopBoekingStatus(enum.StrEnum):
    GEBOEKT = "geboekt"
    GESTORNEERD = "gestorneerd"


class VerkoopBoeking(Base):
    """Registratie per geboekte Vastly-verkoopfactuur/creditnota (migratie 0035) — dé lokale
    duplicaatbewaking per (administratie, Vastly-factuurnummer) én de bron voor het lokale
    nummer-herstel (de SalesInvoices-collectie ziet API-facturen niet, omzet-STAP-0). De
    creditnota-herleiding (§2d v1.11) toetst hierop: een 381 kan alleen boeken als het
    gecrediteerde factuurnummer hier als geboekt bekend is."""

    __tablename__ = "verkoop_boeking"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("boekhouding.document.id"))
    factuurnummer: Mapped[str]
    is_creditnota: Mapped[bool] = mapped_column(default=False)
    totaalbedrag_incl: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    debiteur_customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    debiteur_naam: Mapped[str]
    verkoop_rlz_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    verkoop_invoice_number: Mapped[int | None] = mapped_column(default=None)
    verkoop_referentie: Mapped[str | None] = mapped_column(default=None)
    verkoop_boekstuknummer: Mapped[str | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(default=VerkoopBoekingStatus.GEBOEKT.value)
    geboekt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    geboekt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    gestorneerd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    gestorneerd_op: Mapped[datetime | None] = mapped_column(default=None)
    storno_reden: Mapped[str | None] = mapped_column(default=None)
