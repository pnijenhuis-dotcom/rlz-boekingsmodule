from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class Verplichting(Base):
    """Eén verplichting per document (migratie 0110, mockup `offerte-matching.html` ①): de door het
    kantoor gecontroleerde kopvelden van een offerte/prijsopgave/opdrachtbevestiging, het bij het
    LAATSTE klant-akkoord vastgelegde `goedgekeurd_bedrag_excl` (+ wie/wanneer — dát is het
    discrepantie-doel: dit bedrag, deze leverancier, dit project, akkoord door die persoon op die
    datum), de cumulatieve verbruiksstand (③ — uitsluitend GEBOEKTE, verrekende facturen) en het
    vervallen-spoor (⑥: vervallen stopt nieuwe matches, gematchte facturen blijven ongemoeid).

    Geen RLZ-/Odoo-boeking: een verplichting is een dossierstuk met een verbruiksstand."""

    __tablename__ = "verplichting"
    __table_args__ = (
        CheckConstraint(
            "soort_label IS NULL OR soort_label IN ('offerte', 'prijsopgave', 'opdrachtbevestiging')",
            name="ck_verplichting_soort_label",
        ),
        Index("ix_verplichting_administratie_vendor", "administratie_id", "vendor_id"),
        {"schema": "boekhouding"},
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.document.id"), primary_key=True
    )
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    soort_label: Mapped[str | None] = mapped_column(default=None)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    offertenummer: Mapped[str | None] = mapped_column(default=None)
    #: Documentdatum van de offerte — de check "Geldigheid" toetst `geldig_tot` hiertegen.
    datum: Mapped[date | None] = mapped_column(default=None)
    totaalbedrag_excl: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    geldig_tot: Mapped[date | None] = mapped_column(default=None)
    omschrijving: Mapped[str | None] = mapped_column(default=None)
    opgeslagen_door: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    opgeslagen_op: Mapped[datetime | None] = mapped_column(default=None)
    goedgekeurd_bedrag_excl: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    goedgekeurd_op: Mapped[datetime | None] = mapped_column(default=None)
    goedgekeurd_door: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    verbruikt_bedrag_excl: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0), server_default="0")
    vervallen_op: Mapped[datetime | None] = mapped_column(default=None)
    vervallen_reden: Mapped[str | None] = mapped_column(default=None)
    vervallen_door: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    gewijzigd_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class VerplichtingMatch(Base):
    """Eén rij per INKOOPdocument (herberekening ververst 'm — geen historie-tabel): de actuele
    matchstand tegen de lopende verplichtingen van dezelfde crediteur (②/③). `verrekend_op` is gezet
    zodra de factuur GEBOEKT is en het verbruik op de verplichting is bijgeschreven — tegenboeken
    draait dat terug. `handmatig_gekoppeld` = de mens koos zelf ("Koppel offerte…"); die keuze wint
    altijd zolang die verplichting lopend is en wordt onthouden voor dezelfde crediteur + project."""

    __tablename__ = "verplichting_match"
    __table_args__ = (
        CheckConstraint(
            "uitkomst IN ('binnen', 'buiten', 'geen_match', 'meerdere_kandidaten', 'niet_toetsbaar', "
            "'geen_verplichting')",
            name="ck_verplichting_match_uitkomst",
        ),
        CheckConstraint(
            "overschrijding_excl IS NULL OR overschrijding_excl >= 0", name="ck_verplichting_match_overschrijding"
        ),
        Index("ix_verplichting_match_administratie_uitkomst", "administratie_id", "uitkomst"),
        {"schema": "boekhouding"},
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.document.id"), primary_key=True
    )
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    verplichting_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.document.id"), default=None
    )
    uitkomst: Mapped[str]
    bedrag_excl: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    verbruik_voor: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    verbruik_na: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    overschrijding_excl: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    handmatig_gekoppeld: Mapped[bool] = mapped_column(default=False, server_default="false")
    verrekend_op: Mapped[datetime | None] = mapped_column(default=None)
    berekend_op: Mapped[datetime] = mapped_column(server_default=func.now())
    details: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
