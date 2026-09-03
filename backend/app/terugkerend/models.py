"""Terugkerende-facturen-signaal (opdracht 30-08 blok B, benchmark gap #3; migratie 0090): afgeleide,
herrekenbare signaallaag per (administratie, crediteur) — deterministisch uit de documenthistorie
(Boekvoorstel: factuurdatum + totaalbedrag) en het RLZ-boekingsgeheugen (BoekingObservatie: bron_datum
per boekstuk). Alleen signaleren: nooit blokkeren, nooit muteren, nooit AI."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base

PATRONEN = ("maand", "kwartaal")


class TerugkerendSignaal(Base):
    """Eén rij per (administratie, vendor) met een herkend patroon. `ontbreekt_sinds` = signaal 1
    (verwachte factuur ontbreekt: uiterlijk_op verstreken zonder nieuwe factuur), `prijsstijging_pct` =
    signaal 2 (laatste factuur > drempel boven de vorige). Snooze (tot datum) en afmelden (per
    leverancier, omkeerbaar) zijn menskeuzes met audit; de dagelijkse herberekening laat ze staan."""

    __tablename__ = "terugkerend_signaal"
    __table_args__ = (
        UniqueConstraint("administratie_id", "vendor_id", name="uq_terugkerend_signaal_vendor"),
        Index("ix_terugkerend_signaal_administratie_id", "administratie_id"),
        CheckConstraint("patroon IN ('maand', 'kwartaal')", name="ck_terugkerend_signaal_patroon"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    patroon: Mapped[str]
    interval_dagen: Mapped[int]
    aantal_facturen: Mapped[int]
    laatste_datum: Mapped[date]
    laatste_bedrag: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    laatste_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.document.id"), default=None
    )
    vorige_datum: Mapped[date | None] = mapped_column(default=None)
    vorige_bedrag: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    verwacht_op: Mapped[date]
    uiterlijk_op: Mapped[date]
    ontbreekt_sinds: Mapped[date | None] = mapped_column(default=None)
    prijsstijging_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), default=None)
    snooze_tot: Mapped[date | None] = mapped_column(default=None)
    afgemeld_op: Mapped[datetime | None] = mapped_column(default=None)
    afgemeld_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    berekend_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class HerberekenRunStatus(enum.StrEnum):
    WACHTEND = "wachtend"
    BEZIG = "bezig"
    KLAAR = "klaar"
    FOUT = "fout"


class TerugkerendHerberekenRun(Base):
    """Kantoorbrede achtergrond-herberekening (design-ronde 03-09 blok B1, mockup inzicht-kantoorbreed ③,
    migratie 0099): "⟳ Herbereken alles" maakt één rij (202), het voertuig (thread in dev, on-demand
    Cloud Run-job in de cloud) claimt 'm en draait `herbereken_alle()`; de UI pollt de status. PLATFORM-
    BREED (geen administratie_id, geen RLS): `resultaat` = tellers óf foutreden per administratie. Een
    stille dood van het voertuig wordt via `laatst_actief_op` als zichtbare fout vertaald."""

    __tablename__ = "terugkerend_herbereken_run"
    __table_args__ = (
        Index("ix_terugkerend_herbereken_run_status", "status"),
        Index("ix_terugkerend_herbereken_run_aangevraagd_op", "aangevraagd_op"),
        CheckConstraint(
            "status IN ('wachtend', 'bezig', 'klaar', 'fout')", name="ck_terugkerend_herbereken_run_status"
        ),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(default=HerberekenRunStatus.WACHTEND.value, server_default="wachtend")
    gestart_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    aangevraagd_op: Mapped[datetime] = mapped_column(server_default=func.now())
    gestart_op: Mapped[datetime | None] = mapped_column(default=None)
    laatst_actief_op: Mapped[datetime | None] = mapped_column(default=None)
    klaar_op: Mapped[datetime | None] = mapped_column(default=None)
    aantal_administraties: Mapped[int] = mapped_column(default=0, server_default="0")
    aantal_verwerkt: Mapped[int] = mapped_column(default=0, server_default="0")
    aantal_fouten: Mapped[int] = mapped_column(default=0, server_default="0")
    foutreden: Mapped[str | None] = mapped_column(default=None)
    resultaat: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), default=None)
