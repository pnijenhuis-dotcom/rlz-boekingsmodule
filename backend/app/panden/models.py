"""ORM-modellen pandenregister (migratie 0130, bundel 10-09 blok D2).

Een `Pand` is één dossier-adres binnen een administratie; `PandBoeking` koppelt een RLZ-boekstuk of module-document
aan een pand mét herkomst (voorstel|mens) en zekerheid. Niets wordt verwijderd (GRANT zonder DELETE): een fout
voorstel wordt `vervallen`, een pand dat er nooit was ook. Tekstkolommen = `sa.Text()` via de type_annotation_map."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class PandHerkomst(enum.StrEnum):
    AFGELEID = "afgeleid"
    MENS = "mens"


class PandStatus(enum.StrEnum):
    VOORSTEL = "voorstel"
    BEVESTIGD = "bevestigd"
    IN_HANDEL = "in_handel"
    VERKOCHT = "verkocht"
    VERVALLEN = "vervallen"


class PandBoekingSoort(enum.StrEnum):
    AANKOOP = "aankoop"
    VERKOOP = "verkoop"
    KOSTEN = "kosten"
    OVERHEAD = "overhead"


class PandBoekingHerkomst(enum.StrEnum):
    VOORSTEL = "voorstel"
    MENS = "mens"


class Zekerheid(enum.StrEnum):
    HOOG = "hoog"
    MIDDEN = "midden"
    LAAG = "laag"


class Pand(Base):
    """Eén pand = één dossier-adres. `code` is de genormaliseerde adres-sleutel (`afleiding.AdresVoorstel.code`) —
    uniek per administratie; `adres`/`plaats` zijn de leesbare vorm. Dossiernummers zijn een lijst (aankoop- én
    verkoopdossier)."""

    __tablename__ = "pand"
    __table_args__ = (
        CheckConstraint("herkomst IN ('afgeleid', 'mens')", name="ck_pand_herkomst"),
        CheckConstraint(
            "status IN ('voorstel', 'bevestigd', 'in_handel', 'verkocht', 'vervallen')", name="ck_pand_status"
        ),
        Index("ix_pand_administratie_id", "administratie_id"),
        Index("ux_pand_code", "administratie_id", "code", unique=True),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    code: Mapped[str]
    adres: Mapped[str]
    plaats: Mapped[str | None] = mapped_column(default=None)
    postcode: Mapped[str | None] = mapped_column(default=None)
    aankoopdatum: Mapped[date | None] = mapped_column(default=None)
    verkoopdatum: Mapped[date | None] = mapped_column(default=None)
    notaris_dossiernummers: Mapped[list] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb"), nullable=False
    )
    herkomst: Mapped[str] = mapped_column(default=PandHerkomst.AFGELEID.value)
    status: Mapped[str] = mapped_column(default=PandStatus.VOORSTEL.value)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    gewijzigd_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class PandBoeking(Base):
    """Koppeling boeking ↔ pand. Bron = RLZ-document (`rlz_document_id` + boekstuk + collectie) óf module-document
    (`document_id`); `bron_sleutel` ("rlz:<id>"/"doc:<id>") maakt de uniekheid (administratie, bron, pand) uitvoerbaar
    zonder expressie-index. `herkomst='mens'` wint altijd van een afleidingsrun (mens wint, nooit overschreven)."""

    __tablename__ = "pand_boeking"
    __table_args__ = (
        CheckConstraint("soort IN ('aankoop', 'verkoop', 'kosten', 'overhead')", name="ck_pand_boeking_soort"),
        CheckConstraint("herkomst IN ('voorstel', 'mens')", name="ck_pand_boeking_herkomst"),
        CheckConstraint("zekerheid IN ('hoog', 'midden', 'laag')", name="ck_pand_boeking_zekerheid"),
        CheckConstraint("rlz_document_id IS NOT NULL OR document_id IS NOT NULL", name="ck_pand_boeking_bron_aanwezig"),
        Index("ix_pand_boeking_administratie_id", "administratie_id"),
        Index("ix_pand_boeking_pand_id", "pand_id"),
        Index("ux_pand_boeking_bron_pand", "administratie_id", "bron_sleutel", "pand_id", unique=True),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    pand_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("boekhouding.pand.id"))
    rlz_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    rlz_boekstuknummer: Mapped[str | None] = mapped_column(default=None)
    rlz_collectie: Mapped[str | None] = mapped_column(default=None)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.document.id"), default=None
    )
    bron_sleutel: Mapped[str]
    soort: Mapped[str]
    herkomst: Mapped[str] = mapped_column(default=PandBoekingHerkomst.VOORSTEL.value)
    zekerheid: Mapped[str]
    reden: Mapped[str | None] = mapped_column(default=None)
    datum: Mapped[date | None] = mapped_column(default=None)
    bedrag: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    bevestigd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    bevestigd_op: Mapped[datetime | None] = mapped_column(default=None)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    gewijzigd_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


def bron_sleutel_voor(*, rlz_document_id: uuid.UUID | None, document_id: uuid.UUID | None) -> str:
    if rlz_document_id is not None:
        return f"rlz:{rlz_document_id}"
    if document_id is not None:
        return f"doc:{document_id}"
    raise ValueError("pand_boeking zonder bron: rlz_document_id óf document_id is verplicht")
