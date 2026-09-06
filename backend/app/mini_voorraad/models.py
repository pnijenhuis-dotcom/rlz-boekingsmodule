"""Mini-voorraad speciale producten (migratie 0116, `mi`-schema) — spiegel van de migratie.

Twee tabellen: het PRODUCT (sleutel = LETTERLIJKE factuuromschrijving per leverancier, ⑦) en de APPEND-ONLY
MUTATIE (getekend aantal per soort, altijd aan een brondocument óf een beschadigingsgebeurtenis gebonden). De
stand per product is SUM(aantal) over de mutaties — een query, nooit een kolom (⑧: geen enkel pad muteert een
stand direct). GRANT: product zonder DELETE, mutatie zonder UPDATE én DELETE (0091-patroon `werkopdracht`)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base

SCHEMA = "mi"

SOORT_INSTROOM = "instroom"
SOORT_STORNO = "storno"
SOORT_UITSTROOM = "uitstroom"
SOORT_BESCHADIGING = "beschadiging"
MUTATIE_SOORTEN = (SOORT_INSTROOM, SOORT_STORNO, SOORT_UITSTROOM, SOORT_BESCHADIGING)


class MiniProduct(Base):
    """Eén product per (administratie, leverancier, genormaliseerde factuuromschrijving). `omschrijving` is de
    letterlijke factuurtekst (en de match-sleutel), `weergavenaam` wijzigt alleen via "Naam bevestigen";
    `nieuw_controleren` (④) tot een mens de naam bevestigt. Archiveren = kolom, nooit verwijderen (⑥); een
    gearchiveerd product dat opnieuw op een factuur staat herleeft — nooit een tweede rij met dezelfde sleutel."""

    __tablename__ = "mini_product"
    __table_args__ = (
        UniqueConstraint("administratie_id", "vendor_id", "omschrijving_norm", name="uq_mini_product_sleutel"),
        Index("ix_mini_product_administratie_id", "administratie_id"),
        Index("ix_mini_product_artikelcode", "administratie_id", "vendor_id", "artikelcode"),
        CheckConstraint("length(btrim(omschrijving)) > 0", name="ck_mini_product_omschrijving"),
        CheckConstraint("length(btrim(omschrijving_norm)) > 0", name="ck_mini_product_omschrijving_norm"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    leverancier_naam: Mapped[str | None] = mapped_column(default=None)
    artikelcode: Mapped[str | None] = mapped_column(default=None)
    omschrijving: Mapped[str]
    omschrijving_norm: Mapped[str]
    weergavenaam: Mapped[str | None] = mapped_column(default=None)
    eenheid: Mapped[str | None] = mapped_column(default=None)
    nieuw_controleren: Mapped[bool] = mapped_column(default=True, server_default="true")
    naam_bevestigd_op: Mapped[datetime | None] = mapped_column(default=None)
    naam_bevestigd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    gearchiveerd: Mapped[bool] = mapped_column(default=False, server_default="false")
    gearchiveerd_op: Mapped[datetime | None] = mapped_column(default=None)
    gearchiveerd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    bron_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.document.id"), default=None
    )


class MiniVoorraadMutatie(Base):
    """APPEND-ONLY mutatie: `aantal` GETEKEND (instroom +, storno − als spiegel van de instroom, uitstroom −,
    beschadiging −). Herkomst = document + regel + boek_cyclus (instroom/storno/uitstroom) óf een
    beschadigingsgebeurtenis (project VERPLICHT via CHECK, gemeld_door = wie, toelichting). `aangemaakt_door` =
    de actor (systeem-actor bij achtergrondpaden)."""

    __tablename__ = "mini_voorraad_mutatie"
    __table_args__ = (
        Index("ix_mini_voorraad_mutatie_product", "product_id", "aangemaakt_op"),
        Index("ix_mini_voorraad_mutatie_document", "administratie_id", "document_id"),
        CheckConstraint(
            "soort IN ('instroom', 'storno', 'uitstroom', 'beschadiging')", name="ck_mini_voorraad_mutatie_soort"
        ),
        CheckConstraint(
            "soort <> 'beschadiging' OR project_id IS NOT NULL", name="ck_mini_voorraad_mutatie_beschadiging_project"
        ),
        CheckConstraint("aantal <> 0", name="ck_mini_voorraad_mutatie_aantal"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.mini_product.id"))
    soort: Mapped[str]
    aantal: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    datum: Mapped[date]
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.document.id"), default=None
    )
    regel_volgnummer: Mapped[int | None] = mapped_column(default=None)
    boek_cyclus: Mapped[int | None] = mapped_column(default=None)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    gemeld_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    toelichting: Mapped[str | None] = mapped_column(default=None)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
