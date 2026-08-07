from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class IntakeBericht(Base):
    """Eén binnengekomen e-mail uit het centrale postvak of een geüploade .eml (migratie 0028).
    `message_id` (RFC 5322 Message-ID) is uniek → hetzelfde bericht wordt nooit twee keer
    verwerkt. `detail` bevat het verwerkingsresultaat per bijlage — óók wat géén
    werkvoorraad-document werd (VGB-genegeerd, niet-verwerkbaar type): "niets verdwijnt stil"."""

    __tablename__ = "intake_bericht"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[str | None] = mapped_column(default=None)
    afzender: Mapped[str | None] = mapped_column(default=None)
    onderwerp: Mapped[str | None] = mapped_column(default=None)
    bron: Mapped[str] = mapped_column(default="eml_upload")
    ontvangen_op: Mapped[datetime | None] = mapped_column(default=None)
    verwerkt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    verwerkt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    detail: Mapped[dict] = mapped_column(JSONB)


class ToewijzingRegelSoort(enum.StrEnum):
    """Tenaamstelling is leidend; afzender is een hint die alléén auto-toewijst als er geen
    tegenstrijdig tenaamstelling-signaal is (CLAUDE.md-verzamelbakbesluit)."""

    TENAAMSTELLING = "tenaamstelling"
    AFZENDER = "afzender"


class ToewijzingRegel(Base):
    """Het toewijzings-geheugen (mockup: "elke handmatige toewijzing wordt onthouden"): een
    genormaliseerde sleutel → administratie. Gevoed door handmatige toewijzingen in de
    verzamelbak; deactiveren i.p.v. verwijderen (historie blijft)."""

    __tablename__ = "toewijzing_regel"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    soort: Mapped[str]
    sleutel: Mapped[str]
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id")
    )
    actief: Mapped[bool] = mapped_column(default=True)
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    gedeactiveerd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    gedeactiveerd_op: Mapped[datetime | None] = mapped_column(default=None)


class IntakeSplitsingStatus(enum.StrEnum):
    VOORGESTELD = "voorgesteld"
    BEVESTIGD = "bevestigd"
    AFGEWEZEN = "afgewezen"


class IntakeSplitsing(Base):
    """Multi-factuur-splitsingsvoorstel per bron-document (migratie 0028): de AI stelt
    factuurgrenzen voor, een mens bevestigt (evt. met aangepaste paginabereiken) of wijst af —
    ALTIJD eerst ter controle, nooit stil auto-splitsen (mockup). `voorstel` = lijst van
    {start_pagina, eind_pagina, tenaamstelling, leverancier, factuurnummer, zekerheid}."""

    __tablename__ = "intake_splitsing"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bron_document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("boekhouding.document.id"))
    voorstel: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(default=IntakeSplitsingStatus.VOORGESTELD.value)
    voorgesteld_op: Mapped[datetime] = mapped_column(server_default=func.now())
    besloten_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    besloten_op: Mapped[datetime | None] = mapped_column(default=None)
    besluit_detail: Mapped[dict | None] = mapped_column(JSONB, default=None)
