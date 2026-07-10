from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, func
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class DocumentBron(enum.StrEnum):
    """Intake-kanaal. EMAIL is nog niet gebouwd (fase 3, e-mail-intake) maar hoort al in de
    statusmachine/het schema thuis — 'niet_toegewezen' (zie DocumentStatus) is primair voor die
    flow bedoeld."""

    UPLOAD = "upload"
    EMAIL = "email"


class DocumentStatus(enum.StrEnum):
    """Hoofdpad: ontvangen -> extractie_bezig -> te_controleren -> klaar_om_te_boeken -> geboekt.
    Zijtakken: vraag_open (blokkeert boeken), afgewezen (verplichte reden, eindstatus),
    boeken_mislukt (RLZ-fout, retry mogelijk), niet_toegewezen (verzamelbak — geen administratie
    gekoppeld, zie Document.administratie_id), handmatig_afmaken (migratie 0015, waarborg
    projectadministratie: AI-extractie kreeg de regelset niet aantoonbaar compleet bij een
    administratie met projectplicht — er is bewust GEEN veldvoorstel opgeslagen, de controleur
    vult alles handmatig in of probeert de extractie opnieuw), verwijderd (soft-delete,
    design-pass taak 4: bewust géén harde delete — "niets verdwijnt stil" — bestand en record
    blijven bestaan, alleen geboekte documenten kunnen hier nooit naartoe vanwege de
    bewaarplicht). Toegestane overgangen: zie app/documenten/statusmachine.py — nooit hier of
    elders losse status-writes."""

    ONTVANGEN = "ontvangen"
    EXTRACTIE_BEZIG = "extractie_bezig"
    TE_CONTROLEREN = "te_controleren"
    KLAAR_OM_TE_BOEKEN = "klaar_om_te_boeken"
    GEBOEKT = "geboekt"
    VRAAG_OPEN = "vraag_open"
    AFGEWEZEN = "afgewezen"
    BOEKEN_MISLUKT = "boeken_mislukt"
    NIET_TOEGEWEZEN = "niet_toegewezen"
    HANDMATIG_AFMAKEN = "handmatig_afmaken"
    VERWIJDERD = "verwijderd"


def _enum_waarden(python_enum: type[enum.StrEnum]) -> list[str]:
    return [member.value for member in python_enum]


_DOCUMENT_BRON_ENUM = ENUM(
    DocumentBron, name="document_bron", schema="boekhouding", create_type=False, values_callable=_enum_waarden
)
_DOCUMENT_STATUS_ENUM = ENUM(
    DocumentStatus, name="document_status", schema="boekhouding", create_type=False, values_callable=_enum_waarden
)


class Document(Base):
    """Eén binnengekomen document (fundament van de werkvoorraad). `administratie_id` is NULL
    voor 'niet_toegewezen' documenten (verzamelbak, zie CLAUDE.md) — zelfde RLS-patroon als
    platform.audit_event: platformbrede rijen (NULL) zijn zichtbaar ongeacht scope, geen
    uitzondering op RLS zelf. `mogelijk_duplicaat_van_id` is een losse vlag, geen statusmachine-
    tak: het document doorloopt gewoon de normale flow, met dit signaal erbovenop voor de
    controleur (zie mockup: chip 'Mogelijk duplicaat van ... — beoordelen')."""

    __tablename__ = "document"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    administratie_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), default=None
    )
    bron: Mapped[DocumentBron] = mapped_column(_DOCUMENT_BRON_ENUM)
    bestandsnaam: Mapped[str]
    sha256_hash: Mapped[str]
    status: Mapped[DocumentStatus] = mapped_column(_DOCUMENT_STATUS_ENUM, default=DocumentStatus.ONTVANGEN)
    toegewezen_aan: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    mogelijk_duplicaat_van_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.document.id"), default=None
    )
    opslag_pad: Mapped[str]
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    laatst_gewijzigd_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class DocumentGebeurtenis(Base):
    """Append-only tijdlijn (voedt de mockup-tijdlijn: binnenkomst -> extractie -> vraag ->
    accordering -> boeking). `van_status` is NULL voor de allereerste gebeurtenis (aanmaak).
    `actor_id` is bewust verplicht (zie service.py): er is nog geen achtergrondproces zonder
    menselijke aanroeper in deze fase, dus geen systeem-actor-sentinel nodig — open aandachtspunt
    voor een latere, echt-asynchrone extractieworker."""

    __tablename__ = "document_gebeurtenis"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("boekhouding.document.id"))
    van_status: Mapped[DocumentStatus | None] = mapped_column(_DOCUMENT_STATUS_ENUM, default=None)
    naar_status: Mapped[DocumentStatus] = mapped_column(_DOCUMENT_STATUS_ENUM)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    detail: Mapped[dict | None] = mapped_column(JSONB, default=None)
    tijdstip: Mapped[datetime] = mapped_column(server_default=func.now())


class Boekvoorstel(Base):
    """Kopgegevens van het controlescherm-boekvoorstel (migratie 0008) — één per document. Alle
    velden zijn nullable in de DB (een half ingevuld voorstel mag bewaard worden terwijl de
    controleur nog aan het werk is); de harde checks (app/documenten/checks.py) bepalen of het
    voorstel al *boekbaar* is, niet het schema. `vendor_id`/`ledger_id`/`taxrate_id`/`project_id`
    zijn RLZ-GUID's (Vendor/Ledger/TaxRate/Project) — bewust geen FK naar de eigen caches (die
    zijn per-administratie samengestelde PK's en puur read-side, geen brondata om op te FK'en).
    `rlz_boekstuknummer` is RLZ's `ReceiptNumber` (geverifieerd: al gezet bij de PUT, niet pas na
    boeken — zie verkenning/api-verkenning.md), leeg totdat de eerste PUT gelukt is."""

    __tablename__ = "boekvoorstel"
    __table_args__ = {"schema": "boekhouding"}

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.document.id"), primary_key=True
    )
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    referentie: Mapped[str | None] = mapped_column(default=None)
    factuurdatum: Mapped[date | None] = mapped_column(default=None)
    totaalbedrag: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    rlz_boekstuknummer: Mapped[str | None] = mapped_column(default=None)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    bijgewerkt_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class BoekvoorstelRegel(Base):
    """Eén boekingsregel binnen een Boekvoorstel. `volgnummer` bepaalt de weergave-/PUT-volgorde
    (geen betekenis in RLZ zelf, puur voor een stabiele, voorspelbare regelvolgorde in het
    controlescherm en de RLZ-PUT)."""

    __tablename__ = "boekvoorstel_regel"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.boekvoorstel.document_id")
    )
    volgnummer: Mapped[int]
    ledger_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    taxrate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    netto_bedrag: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    btw_bedrag: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    omschrijving: Mapped[str | None] = mapped_column(default=None)


class WebhookUitgaand(Base):
    """Outbox voor het "factuur geboekt"-webhook-stub (migratie 0009, koppelcontract §3): de
    getekende payload ligt hier per boeking al vast, aflevering (HTTP-push) is een fase-vervolg.
    `afgeleverd_op` blijft NULL totdat die job bestaat — geen achtergrondproces zet 'm nu."""

    __tablename__ = "webhook_uitgaand"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("boekhouding.document.id"))
    event: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSONB)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    afgeleverd_op: Mapped[datetime | None] = mapped_column(default=None)
