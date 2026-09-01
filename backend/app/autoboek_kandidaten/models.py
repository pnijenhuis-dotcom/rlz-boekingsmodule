"""Autoboek-kandidaten (mockup autoboek-kandidaten.html, besluit Peter 01-09; migratie 0095): afgeleide,
herrekenbare stand per (administratie, leverancier) — dagelijks in sync-alles én live bij aanzetten —
plus de Beheerder-instelling voor de drempel "N op rij". Snooze ("Kandidaat verbergen") is de enige
menskeuze in deze tabel en overleeft de herberekening. De opt-in zelf leeft ongewijzigd op
`leverancier_voorkeur.autoboeken_ingeschakeld` (ene schrijver: documenten/autoboeken.py)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base

DREMPEL_DEFAULT = 5


class AutoboekKandidaatStand(Base):
    """Eén rij per (administratie, vendor) mét ≥ 1 mens-geboekte inkoopfactuur óf een actieve opt-in.
    `kwalificeert` + `redenen` = de deterministische poort (motor.kwalificeer), `chips` = onderbouwing,
    `heroverweeg_signalen` = advies voor actieve opt-ins (nooit zelf uitzetten). RLS per administratie;
    DELETE-grant omdat het een afgeleide laag is (vervallen rijen worden opgeruimd)."""

    __tablename__ = "autoboek_kandidaat_stand"
    __table_args__ = (
        Index("ix_autoboek_kandidaat_stand_administratie_id", "administratie_id"),
        {"schema": "boekhouding"},
    )

    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), primary_key=True
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    reeks_ongewijzigd: Mapped[int] = mapped_column(default=0)
    correcties: Mapped[int] = mapped_column(default=0)
    mens_boekingen: Mapped[int] = mapped_column(default=0)
    open_vragen: Mapped[int] = mapped_column(default=0)
    kwalificeert: Mapped[bool] = mapped_column(default=False)
    actief: Mapped[bool] = mapped_column(default=False)
    actief_sinds: Mapped[datetime | None] = mapped_column(default=None)
    redenen: Mapped[list] = mapped_column(JSONB, default=list)
    chips: Mapped[list] = mapped_column(JSONB, default=list)
    heroverweeg_signalen: Mapped[list] = mapped_column(JSONB, default=list)
    laatste_factuur_datum: Mapped[date | None] = mapped_column(default=None)
    laatste_factuur_bedrag: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    laatste_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    snooze_reden: Mapped[str | None] = mapped_column(default=None)
    snooze_op: Mapped[datetime | None] = mapped_column(default=None)
    snooze_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    berekend_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class AutoboekInstelling(Base):
    """Beheerder-instelling drempel "N op rij ongewijzigd" (default 5) + tijdstip van de laatste
    motor-run (de tabs tonen "stand van HH:MM"). Singleton, patroon IntakeInstelling."""

    __tablename__ = "autoboek_instelling"
    __table_args__ = (
        CheckConstraint("singleton", name="autoboek_instelling_singleton"),
        CheckConstraint("drempel_op_rij >= 1 AND drempel_op_rij <= 50", name="autoboek_instelling_drempel"),
        {"schema": "platform"},
    )

    singleton: Mapped[bool] = mapped_column(primary_key=True, default=True)
    drempel_op_rij: Mapped[int] = mapped_column(default=DREMPEL_DEFAULT)
    laatste_run_op: Mapped[datetime | None] = mapped_column(default=None)
    gewijzigd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    gewijzigd_op: Mapped[datetime] = mapped_column(server_default=func.now())
