"""Datalaag intercompany (migratie 0148, Peter 16-09). Vier tabellen in `boekhouding`, RLS als referentietabel over
administraties heen (lezen voor iedereen in de app-rol, schrijven door systeem én Beheerder — de mutatie-poort voor
mens-wijzigingen zit server-side in de service), nooit DELETE.

- `administratie_identiteit`: KvK/btw/naam per administratie uit de bron (RLZ `AdministrationSettings`: CompanyName +
  ChamberOfCommerceNumber; Odoo `res.company`: name/vat/company_registry) — het fundament voor de afleiding.
- `intercompany_relatie`: entity_in_a (RLZ Vendor-/Customer-GUID of Odoo-partner-uuid in administratie A) ↔
  administratie B; `richting` vanuit A gezien ('crediteur' = B levert aan A; 'debiteur' = A verkoopt aan B); `basis`
  kvk|btw|naam|doorbelasting;
  `status` afgeleid|bevestigd|uitgesloten; `bron` afgeleid|mens. Naam-only telt pas mee ná bevestiging (beslispunt 3).
- `rc_koppeling`: RC-grootboekrekening in A ↔ tegenrekening in B (rekening_b NULL = "RC zonder tegenrekening").
- `rc_stand`: laatste gemeten stand per koppeling per dag (vensterbegin voor de verklaring)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base

RICHTINGEN = ("crediteur", "debiteur")
BASES = ("kvk", "btw", "naam", "doorbelasting")
STATUSSEN = ("afgeleid", "bevestigd", "uitgesloten")
BRONNEN = ("afgeleid", "mens")
RC_BASES = ("naam", "afkorting", "mens")
IDENTITEIT_BRONNEN = ("rlz", "odoo", "mens")


def _in(kolom: str, waarden: tuple[str, ...]) -> str:
    return f"{kolom} IN ({', '.join(repr(w) for w in waarden)})"


class AdministratieIdentiteit(Base):
    __tablename__ = "administratie_identiteit"
    __table_args__ = (
        CheckConstraint(_in("bron", IDENTITEIT_BRONNEN), name="ck_administratie_identiteit_bron"),
        {"schema": "boekhouding"},
    )

    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), primary_key=True
    )
    kvk: Mapped[str | None] = mapped_column(default=None)
    btw: Mapped[str | None] = mapped_column(default=None)
    naam: Mapped[str | None] = mapped_column(default=None)
    naam_norm: Mapped[str | None] = mapped_column(default=None)
    sbi: Mapped[str | None] = mapped_column(default=None)
    #: Beheerder-afkortingen (lijst strings) die in grootboek-/relatienamen naar deze administratie verwijzen ("KF").
    afkortingen: Mapped[list | None] = mapped_column(JSONB(none_as_null=True), default=None)
    bron: Mapped[str] = mapped_column(default="rlz", server_default="rlz")
    gelezen_op: Mapped[datetime | None] = mapped_column(default=None)


class IntercompanyRelatie(Base):
    __tablename__ = "intercompany_relatie"
    __table_args__ = (
        UniqueConstraint("administratie_a_id", "entity_in_a", "administratie_b_id", name="uq_intercompany_relatie"),
        CheckConstraint(_in("richting", RICHTINGEN), name="ck_intercompany_relatie_richting"),
        CheckConstraint(_in("basis", BASES), name="ck_intercompany_relatie_basis"),
        CheckConstraint(_in("status", STATUSSEN), name="ck_intercompany_relatie_status"),
        CheckConstraint(_in("bron", BRONNEN), name="ck_intercompany_relatie_bron"),
        Index("ix_intercompany_relatie_a", "administratie_a_id"),
        Index("ix_intercompany_relatie_b", "administratie_b_id"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_a_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    entity_in_a: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    entity_naam: Mapped[str | None] = mapped_column(default=None)
    administratie_b_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    richting: Mapped[str] = mapped_column()
    basis: Mapped[str] = mapped_column()
    status: Mapped[str] = mapped_column(default="afgeleid", server_default="afgeleid")
    bron: Mapped[str] = mapped_column(default="afgeleid", server_default="afgeleid")
    reden: Mapped[str | None] = mapped_column(default=None)
    gewijzigd_door: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    gewijzigd_op: Mapped[datetime | None] = mapped_column(default=None)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())


class RcKoppeling(Base):
    __tablename__ = "rc_koppeling"
    __table_args__ = (
        UniqueConstraint("administratie_a_id", "rekening_a", "administratie_b_id", name="uq_rc_koppeling"),
        CheckConstraint(_in("basis", RC_BASES), name="ck_rc_koppeling_basis"),
        CheckConstraint(_in("status", STATUSSEN), name="ck_rc_koppeling_status"),
        CheckConstraint(_in("bron", BRONNEN), name="ck_rc_koppeling_bron"),
        Index("ix_rc_koppeling_a", "administratie_a_id"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_a_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    rekening_a: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    rekening_a_code: Mapped[str | None] = mapped_column(default=None)
    rekening_a_naam: Mapped[str | None] = mapped_column(default=None)
    administratie_b_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    rekening_b: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    rekening_b_code: Mapped[str | None] = mapped_column(default=None)
    rekening_b_naam: Mapped[str | None] = mapped_column(default=None)
    basis: Mapped[str] = mapped_column(default="naam", server_default="naam")
    status: Mapped[str] = mapped_column(default="afgeleid", server_default="afgeleid")
    bron: Mapped[str] = mapped_column(default="afgeleid", server_default="afgeleid")
    reden: Mapped[str | None] = mapped_column(default=None)
    gewijzigd_door: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    gewijzigd_op: Mapped[datetime | None] = mapped_column(default=None)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())


class RcStand(Base):
    __tablename__ = "rc_stand"
    __table_args__ = ({"schema": "boekhouding"},)

    koppeling_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.rc_koppeling.id"), primary_key=True
    )
    datum: Mapped[date] = mapped_column(primary_key=True)
    saldo_a: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    saldo_b: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    sluit: Mapped[bool] = mapped_column(default=False, server_default="false")
    gemeten_op: Mapped[datetime] = mapped_column(server_default=func.now())
