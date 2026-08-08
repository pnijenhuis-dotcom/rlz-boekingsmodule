from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class OmzetCategorieMapping(Base):
    """Categorie→GB+btw-mapping per administratie (migratie 0027, mockup #omzetreview
    "mapping onthouden per administratie"): eerste keer instellen, daarna onthouden — zelfde
    principe als het boekingsgeheugen, maar deterministisch (één actieve mapping per
    genormaliseerde categorie-sleutel, geen weging). `kostprijs_ledger_id` is nullable: een
    rapport zonder kostprijskolom heeft alleen de omzetkant. Deactiveren i.p.v. verwijderen
    (historie blijft); een nieuwe mapping voor dezelfde sleutel deactiveert de oude."""

    __tablename__ = "omzet_categorie_mapping"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    categorie_sleutel: Mapped[str]
    weergave_naam: Mapped[str]
    omzet_ledger_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    taxrate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    kostprijs_ledger_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    actief: Mapped[bool] = mapped_column(default=True)
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    gewijzigd_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    gedeactiveerd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    gedeactiveerd_op: Mapped[datetime | None] = mapped_column(default=None)


class OmzetInstelling(Base):
    """Omzetconfig per administratie (migratie 0027 + 0031): de voorraad-tegenrekening van het
    kostprijsmemoriaal en de gecachte administratie-specifieke RLZ-GUID's — het
    memoriaal-dagboek (JournalEntryDiaries, STAP 0 §3) en de DocumentCategory "Verkoopfactuur
    (Omzet)" voor de entity-loze Receipt-boeking (Receipts-verkenning); beide per administratie
    opgevraagd, nooit hardcoden."""

    __tablename__ = "omzet_instelling"
    __table_args__ = {"schema": "boekhouding"}

    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), primary_key=True
    )
    # VERVALLEN (besluit Peter 2026-08-08, omzetmotor → entity-loze Receipts): de systeemdebiteur
    # "Kasomzet" wordt niet meer aangemaakt of gebruikt. Kolommen blijven als historisch spoor
    # voor administraties waar de debiteur al bestond — RLZ-data wordt nooit verwijderd.
    kasomzet_customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    kasomzet_naam: Mapped[str | None] = mapped_column(default=None)
    voorraad_ledger_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    memoriaal_diary_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    verkoop_categorie_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    gewijzigd_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class OmzetVoorstel(Base):
    """Kop van het omzetreview-voorstel per kassarapport-document (mockup #omzetreview):
    periode + de rapport-totalen zoals gelezen. Nullable zolang de controleur nog bezig is —
    de harde checks (app/omzet/checks.py) bepalen boekbaarheid, niet het schema (zelfde
    afweging als Boekvoorstel)."""

    __tablename__ = "omzet_voorstel"
    __table_args__ = {"schema": "boekhouding"}

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.document.id"), primary_key=True
    )
    periode_start: Mapped[date | None] = mapped_column(default=None)
    periode_eind: Mapped[date | None] = mapped_column(default=None)
    rapport_totaal_omzet: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    rapport_totaal_kostprijs: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    bijgewerkt_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class OmzetVoorstelRegel(Base):
    """Eén categorie-regel binnen het omzetvoorstel: de gelezen bedragen (omzet/kostprijs) +
    de gekozen GB/btw/kostprijs-GB (uit de mapping voorgevuld, per regel overschrijfbaar).
    `categorie_sleutel` is de genormaliseerde vorm waarop de mapping matcht
    (app/omzet/mapping.py::normaliseer_categorie_sleutel)."""

    __tablename__ = "omzet_voorstel_regel"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.omzet_voorstel.document_id")
    )
    volgnummer: Mapped[int]
    categorie: Mapped[str]
    categorie_sleutel: Mapped[str]
    omzet_bedrag: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    kostprijs_bedrag: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    omzet_ledger_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    taxrate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    kostprijs_ledger_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)


class OmzetBoekingStatus(enum.StrEnum):
    """GEBOEKT = beide documenten (verkoopfactuur + kostprijsmemoriaal) staan geboekt in RLZ.
    HALF_GEBOEKT = de zichtbare foutstatus wanneer het memoriaal faalde ná een geboekte
    verkoopfactuur én de storno (actie 19) van die verkoop óók faalde — "nooit stil één helft
    laten staan"; de omzet-reconciliatie rapporteert deze rijen tot een mens ze oplost.
    GESTORNEERD = beide documenten via actie 19 teruggedraaid (of de halve boeking alsnog
    hersteld); de periode is dan weer vrij voor een nieuwe boeking (partiële unique index)."""

    GEBOEKT = "geboekt"
    HALF_GEBOEKT = "half_geboekt"
    GESTORNEERD = "gestorneerd"


class OmzetBoeking(Base):
    """Registratie per geboekte periode (migratie 0027) — dé duplicaatbewaking per periode
    (STAP 0 §2: de SalesInvoices-collectie ziet API-aangemaakte facturen niet, dus lokaal +
    DB-uniek is hier de primaire waarborg) én de werkstaat voor de reconciliatie
    (eigen status ↔ werkelijke RLZ-staat van beide documenten)."""

    __tablename__ = "omzet_boeking"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("boekhouding.document.id"))
    periode_start: Mapped[date]
    periode_eind: Mapped[date]
    totaal_omzet: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    totaal_kostprijs: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    verkoop_rlz_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    verkoop_invoice_number: Mapped[int | None] = mapped_column(default=None)
    verkoop_referentie: Mapped[str | None] = mapped_column(default=None)
    verkoop_boekstuknummer: Mapped[str | None] = mapped_column(default=None)
    # Nullable: een rapport zonder kostprijskolom heeft geen kostprijsmemoriaal.
    memoriaal_rlz_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    memoriaal_referentie: Mapped[str | None] = mapped_column(default=None)
    memoriaal_boekstuknummer: Mapped[str | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(default=OmzetBoekingStatus.GEBOEKT.value)
    half_geboekt_detail: Mapped[dict | None] = mapped_column(JSONB, default=None)
    geboekt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    geboekt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    gestorneerd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    gestorneerd_op: Mapped[datetime | None] = mapped_column(default=None)
    storno_reden: Mapped[str | None] = mapped_column(default=None)
