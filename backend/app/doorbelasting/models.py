"""Datamodel Kempen-doorbelasting (besluit Peter 2026-08-13, canoniek patroon
verkenning/16_DOORBELASTING_KEMPEN.md §4 + goedgekeurde mockup #verdeelmodal/#centraleinkoopmodal).

Opzet: `DoorbelastingMapping` = de server-side afgedwongen whitelist doelentiteit ↔
Customer-GUID-in-bron (geseed uit verkenning §1, beheerbaar in Instellingen);
`DoorbelastingInstelling` = config per BRON-administratie (provisie-% default 5, vlak
btw-tarief, omzet-GB — nooit hardcoded, §2); `DoorbelastingRun` + `DoorbelastingRegel` = het
bevestigde verdeelvoorstel per geboekte bron-inkoopfactuur; `DoorbelastingBoeking` = de
uitgevoerde tweezijdige boeking per doelentiteit (verkoop in bron + spiegel-inkoop in doel),
met het half-geboekt-patroon van de omzetmotor en `spiegel_open` als bewuste open taak
wanneer de doel-administratie nog niet onboarded is (nooit stil half)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class DoorbelastingBoekingStatus(enum.StrEnum):
    GEBOEKT = "geboekt"  # beide kanten definitief in RLZ
    SPIEGEL_OPEN = "spiegel_open"  # bron-kant geboekt; doel niet onboarded → zichtbare open taak
    HALF_GEBOEKT = "half_geboekt"  # spiegel gefaald én storno bron gefaald — reconciliatie-signaal
    GESTORNEERD = "gestorneerd"  # actie 19 beide kanten (of alleen bron bij spiegel_open)


class DoorbelastingRunStatus(enum.StrEnum):
    CONCEPT = "concept"  # review open / (deels) nog niet geboekt
    GEBOEKT = "geboekt"  # elke doelentiteit heeft een niet-gestorneerde boeking
    GESTORNEERD = "gestorneerd"  # alle boekingen teruggedraaid


class DoorbelastingMapping(Base):
    """Whitelist-rij doelentiteit ↔ Customer-GUID binnen de bron-administratie (verkenning §1).
    `doel_administratie_id` is NULL zolang de doelentiteit niet onboarded is (geen
    webservice-login in de credential-store) — de motor boekt dan alleen de bron-kant en zet
    een open spiegel-taak. `intercompany` stuurt de RC-consequentie (blok 2): per rij
    instelbaar, want de Rubicon-verificatie (§2c) bewees dat RC-afhandeling per doelentiteit
    verschilt. `provisie_kosten_ledger_id` is de vaste provisie-GB in de DOEL-administratie
    (mockup: verplicht vóór de spiegel geboekt kan worden; Rubicon: eigen rekening 4808).
    `laatste_kosten_ledger_id` is het geheugen-voorstel voor de doel-kosten-GB (v1: laatst
    gebruikt per doelentiteit; het regel-niveau kiest de mens per verdeelregel)."""

    __tablename__ = "doorbelasting_mapping"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id")
    )
    doelentiteit_naam: Mapped[str]
    doel_customer_guid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    doel_administratie_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), default=None
    )
    intercompany: Mapped[bool] = mapped_column(default=True)
    provisie_kosten_ledger_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    laatste_kosten_ledger_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    actief: Mapped[bool] = mapped_column(default=True)
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id")
    )
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    gewijzigd_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class DoorbelastingInstelling(Base):
    """Config per BRON-administratie (mockup #centraleinkoopmodal; §2: provisie-% en btw-tarief
    zijn config, nooit hardcoded — huidige praktijk 5% en vlak 21% hoog).
    `btw_taxrate_id` wordt aan BEIDE kanten gebruikt: TaxRate-GUID's zijn administratie-
    overstijgend identiek (geverifieerd §2c + STAP-0 2026-08-13). `provisie_omzet_ledger_id`
    NULL = provisieregel op dezelfde omzet-GB als de kostenregels (huidige praktijk)."""

    __tablename__ = "doorbelasting_instelling"
    __table_args__ = {"schema": "boekhouding"}

    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), primary_key=True
    )
    provisie_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("5.00"))
    btw_taxrate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    omzet_ledger_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    provisie_omzet_ledger_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    gewijzigd_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class IntercompanyTegenpartij(Base):
    """Entity-GUID's die in déze administratie als intercompany gelden (migratie 0045, blok 2
    RC-consequentie): hun open posten worden uitgesloten van afletter-voorstellen en matches —
    IC loopt via de rekening-courant, nooit via aflettering (verkenning/16 §2b). Eigen tabel
    per scope (en geen directe mapping-join) omdat RLS de doel-administratie geen zicht geeft
    op de mapping-rijen van de bron-administratie; de doorbelasting-service onderhoudt per
    kant een rij: bron-kant = doel_customer_guid, doel-kant = de crediteur-GUID zodra die bij
    de eerste spiegel-boeking bekend is. `actief=False` i.p.v. delete (niets verdwijnt stil;
    de vlag volgt mapping.intercompany/actief)."""

    __tablename__ = "intercompany_tegenpartij"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id")
    )
    entity_guid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    naam: Mapped[str]
    bron: Mapped[str] = mapped_column(default="doorbelasting_mapping")
    mapping_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    actief: Mapped[bool] = mapped_column(default=True)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    gewijzigd_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class DoorbelastingRun(Base):
    """Het verdeelvoorstel voor één geboekte bron-inkoopfactuur (actie "Doorbelasten…").
    Hooguit één niet-gestorneerde run per document (partial unique index in migratie 0044) —
    de duplicaatbewaking op run-niveau. `laatste_fout` draagt per mapping-id de laatste
    boekfout (zichtbaar per deelboeking, mockup: "nooit een halve doorbelasting zonder
    spoor"); een geslaagde (deel)boeking wist zijn eigen ingang."""

    __tablename__ = "doorbelasting_run"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id")
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.document.id")
    )
    status: Mapped[str] = mapped_column(default=DoorbelastingRunStatus.CONCEPT.value)
    laatste_fout: Mapped[dict | None] = mapped_column(JSONB, default=None)
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id")
    )
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    geboekt_op: Mapped[datetime | None] = mapped_column(default=None)


class DoorbelastingRegel(Base):
    """Eén verdeelregel: (bron-boekvoorstelregel × doelentiteit × percentage). `netto_deel`
    is het grootste-rest-verdeelde centenbedrag (geld.verdeel_grootste_rest) — vastgelegd op
    bevestigingsmoment zodat de geboekte werkelijkheid nooit stil verschuift met een latere
    herberekening. `doel_kosten_ledger_id` = de GB in de DOEL-administratie voor dít deel
    (mockup: per verdeelregel kiesbaar, ook balans-GB's voor activeren; NULL zolang het doel
    niet onboarded is — mens kiest vóór de spiegel geboekt wordt)."""

    __tablename__ = "doorbelasting_regel"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.doorbelasting_run.id")
    )
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id")
    )
    bron_regel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.boekvoorstel_regel.id")
    )
    mapping_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.doorbelasting_mapping.id")
    )
    percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    netto_deel: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    doel_kosten_ledger_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)


class DoorbelastingBoeking(Base):
    """De uitgevoerde tweezijdige boeking per (bron-document, doelentiteit). `document_id`
    staat er gedenormaliseerd op voor de DB-unieke duplicaatbewaking per
    bron-factuur+doelentiteit (partial unique, gestorneerd uitgezonderd — opdracht blok 1d).
    De RLZ-GUID's zijn deterministisch (rlz_ids) en staan hier als vastlegging van wat er
    daadwerkelijk geraakt is, niet als tweede bron van waarheid. `half_geboekt_detail` volgt
    het omzetmotor-patroon (fouten + hersteladvies, JSONB)."""

    __tablename__ = "doorbelasting_boeking"
    __table_args__ = {"schema": "boekhouding"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.doorbelasting_run.id")
    )
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id")
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.document.id")
    )
    mapping_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.doorbelasting_mapping.id")
    )
    doel_administratie_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), default=None
    )
    status: Mapped[str] = mapped_column(default=DoorbelastingBoekingStatus.GEBOEKT.value)
    netto_totaal: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    provisie_bedrag: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    btw_bedrag: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    verkoop_rlz_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    verkoop_referentie: Mapped[str | None] = mapped_column(default=None)
    verkoop_invoice_number: Mapped[int | None] = mapped_column(default=None)
    spiegel_rlz_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    spiegel_geboekt_op: Mapped[datetime | None] = mapped_column(default=None)
    half_geboekt_detail: Mapped[dict | None] = mapped_column(JSONB, default=None)
    storno_reden: Mapped[str | None] = mapped_column(default=None)
    geboekt_door: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id")
    )
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    gewijzigd_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
