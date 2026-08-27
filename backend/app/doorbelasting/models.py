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

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class DoorbelastingBoekingStatus(enum.StrEnum):
    GEBOEKT = "geboekt"  # beide kanten definitief in RLZ
    SPIEGEL_OPEN = "spiegel_open"  # bron-kant geboekt; doel niet onboarded → zichtbare open taak
    HALF_GEBOEKT = "half_geboekt"  # spiegel gefaald én storno bron gefaald — reconciliatie-signaal
    GESTORNEERD = "gestorneerd"  # actie 19 beide kanten (of alleen bron bij spiegel_open)


class DoorbelastingRunStatus(enum.StrEnum):
    """KLAARGEZET (migratie 0065, besluit Peter 25-08): verdeling opgeslagen aan een nog NIET
    geboekt document — "Boeken + doorbelasten" zet 'm ná de inkoopboeking om naar CONCEPT en
    draait de motor. VERVALLEN: vinkje vóór het boeken weer uit (nooit een delete, spoor blijft).
    Beide inactieve statussen (GESTORNEERD, VERVALLEN) tellen niet in de één-actieve-run-index."""

    KLAARGEZET = "klaargezet"  # verdeling aan een nog niet geboekt document (besluit 25-08)
    CONCEPT = "concept"  # review open / (deels) nog niet geboekt
    GEBOEKT = "geboekt"  # elke doelentiteit heeft een niet-gestorneerde boeking
    GESTORNEERD = "gestorneerd"  # alle boekingen teruggedraaid
    VERVALLEN = "vervallen"  # vinkje vóór het boeken weer uit — spoor blijft, nooit een delete


INACTIEVE_RUN_STATUSSEN: tuple[str, ...] = ("gestorneerd", "vervallen")


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
    __table_args__ = (
        UniqueConstraint("administratie_id", "doel_customer_guid", name="doorbelasting_mapping_doel_uniek"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    doelentiteit_naam: Mapped[str]
    doel_customer_guid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    doel_administratie_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), default=None
    )
    intercompany: Mapped[bool] = mapped_column(default=True)
    provisie_kosten_ledger_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    laatste_kosten_ledger_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    actief: Mapped[bool] = mapped_column(default=True)
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
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
    __table_args__ = (
        UniqueConstraint("administratie_id", "entity_guid", name="intercompany_tegenpartij_uniek"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
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
    __table_args__ = (
        Index(
            "doorbelasting_run_document_actief_uniek",
            "document_id",
            unique=True,
            postgresql_where=text("status NOT IN ('gestorneerd', 'vervallen')"),
        ),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("boekhouding.document.id"))
    status: Mapped[str] = mapped_column(default=DoorbelastingRunStatus.CONCEPT.value)
    laatste_fout: Mapped[dict | None] = mapped_column(JSONB, default=None)
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    geboekt_op: Mapped[datetime | None] = mapped_column(default=None)
    # Verdeelsleutel-herleidbaarheid (25-08, deel 2 punt 2c): welke sleutel(versie) is op deze run
    # toegepast — blijft staan óók als de mens de verdeling daarna nog aanpaste (het audit-spoor
    # `doorbelasting_verdeling_opgeslagen` toont die aanpassing).
    verdeelsleutel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.doorbelasting_verdeelsleutel.id"), default=None
    )
    verdeelsleutel_toegepast_op: Mapped[datetime | None] = mapped_column(default=None)


class DoorbelastingRegel(Base):
    """Eén verdeelregel: (bron-boekvoorstelregel × doelentiteit × percentage). `netto_deel`
    is het grootste-rest-verdeelde centenbedrag (geld.verdeel_grootste_rest) — vastgelegd op
    bevestigingsmoment zodat de geboekte werkelijkheid nooit stil verschuift met een latere
    herberekening. `doel_kosten_ledger_id` = de GB in de DOEL-administratie voor dít deel
    (mockup: per verdeelregel kiesbaar, ook balans-GB's voor activeren; NULL zolang het doel
    niet onboarded is — mens kiest vóór de spiegel geboekt wordt)."""

    __tablename__ = "doorbelasting_regel"
    __table_args__ = (
        # Multi-project (25-08, deel 2 punt 2b): één rij per project binnen een doelentiteit;
        # NULLS NOT DISTINCT houdt de rij-zonder-project even hard uniek als voorheen.
        UniqueConstraint(
            "run_id",
            "bron_regel_id",
            "mapping_id",
            "project_id",
            name="doorbelasting_regel_uniek",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("verdeelbasis IS NULL OR verdeelbasis IN ('m2', 'gelijk')", name="doorbelasting_regel_verdeelbasis"),
        CheckConstraint(
            "project_aandeel IS NULL OR (project_aandeel > 0 AND project_aandeel <= 1)",
            name="doorbelasting_regel_project_aandeel",
        ),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("boekhouding.doorbelasting_run.id"))
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    bron_regel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.boekvoorstel_regel.id")
    )
    mapping_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.doorbelasting_mapping.id")
    )
    percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    netto_deel: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    doel_kosten_ledger_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    # Doorbelasting × projecten (besluit Peter 25-08 "optie 2", migratie 0067): het project in de
    # DOEL-administratie (RLZ-project-GUID uit haar project_cache) waarop de spiegel-regel boekt.
    # `percentage` blijft het doelentiteit-aandeel van de bron-regel (identiek op alle project-
    # rijen van dezelfde doelentiteit); `project_aandeel` = de fractie van dát deel voor dit
    # project (som 1 per bron-regel × doelentiteit), `verdeelbasis` = 'm2' | 'gelijk' bij een
    # multi-project-verdeling (NULL bij één of geen project), `m2` = de contract-m² waarop
    # verdeeld is — herleidbaar waarom dit deel dit bedrag kreeg.
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    project_aandeel: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), default=None)
    verdeelbasis: Mapped[str | None] = mapped_column(default=None)
    m2: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)


class DoorbelastingVerdeelsleutel(Base):
    """Herbruikbare verdeelsleutel per bron-administratie (besluit Peter 25-08, deel 2 punt 2c):
    doelen + projecten + verdeelbasis als JSON-definitie, append-only per versie — opnieuw
    opslaan onder dezelfde naam maakt versie n+1 en zet de vorige inactief (nooit een delete:
    een run verwijst naar de exacte versie die toegepast is, QoE-eis).

    `definitie` = {"doelen": [{"mapping_id", "percentage", "doel_kosten_ledger_id"|null,
    "projecten": [project_id, ...] | "alle_actief" | [], "verdeelbasis": "m2"|"gelijk"|null}]};
    "alle_actief" wordt bij toepassen gematerialiseerd naar de dan actieve projecten van de
    doel-administratie (de run draagt de concrete lijst)."""

    __tablename__ = "doorbelasting_verdeelsleutel"
    __table_args__ = (
        UniqueConstraint("administratie_id", "naam", "versie", name="doorbelasting_verdeelsleutel_naam_versie"),
        CheckConstraint("versie >= 1", name="doorbelasting_verdeelsleutel_versie"),
        Index("ix_doorbelasting_verdeelsleutel_administratie_id", "administratie_id"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    naam: Mapped[str]
    versie: Mapped[int]
    actief: Mapped[bool] = mapped_column(server_default=text("true"), default=True)
    definitie: Mapped[dict] = mapped_column(JSONB)
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())


class DoorbelastingBoeking(Base):
    """De uitgevoerde tweezijdige boeking per (bron-document, doelentiteit). `document_id`
    staat er gedenormaliseerd op voor de DB-unieke duplicaatbewaking per
    bron-factuur+doelentiteit (partial unique, gestorneerd uitgezonderd — opdracht blok 1d).
    De RLZ-GUID's zijn deterministisch (rlz_ids) en staan hier als vastlegging van wat er
    daadwerkelijk geraakt is, niet als tweede bron van waarheid. `half_geboekt_detail` volgt
    het omzetmotor-patroon (fouten + hersteladvies, JSONB)."""

    __tablename__ = "doorbelasting_boeking"
    __table_args__ = (
        Index(
            "doorbelasting_boeking_doc_doel_uniek",
            "document_id",
            "mapping_id",
            unique=True,
            postgresql_where=text("status != 'gestorneerd'"),
        ),
        CheckConstraint(
            "factuur_pdf_status IS NULL OR factuur_pdf_status IN ('aanwezig', 'ontbreekt')",
            name="doorbelasting_boeking_factuur_pdf_status",
        ),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("boekhouding.doorbelasting_run.id"))
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("boekhouding.document.id"))
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
    geboekt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    gewijzigd_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    # Rechtsgeldige factuur-PDF (blok A 26-08, migratie 0077): RLZ's eigen gerenderde
    # verkoopfactuur als bijlage op beide kanten. `factuur_pdf_status` = 'aanwezig' |
    # 'ontbreekt' (NULL = boeking van vóór 26-08, nog nooit geprobeerd — herstel-commando);
    # `factuur_pdf_reden` = waarom hij ontbreekt (zichtbaar op de run, nooit stil);
    # `factuur_pdf_opslag_pad` = onze bewaarkopie (7 jaar, downloadbaar in de UI).
    # Expliciet String() (niet de type_annotation_map str -> Text): migratie 0077 legde deze vier
    # kolommen als VARCHAR aan; zonder deze pin meldde `alembic check` een schijn-drift
    # (VARCHAR vs Text) en was het signaal onbruikbaar (werkstroom-run 27/28-08, punt 6b — zelfde
    # patroon als AiKostenLog.model/bron in app/db/models.py). Geen migratie: type-neutraal in Postgres.
    factuur_pdf_status: Mapped[str | None] = mapped_column(String(), default=None)
    factuur_pdf_reden: Mapped[str | None] = mapped_column(String(), default=None)
    factuur_pdf_bestandsnaam: Mapped[str | None] = mapped_column(String(), default=None)
    factuur_pdf_opslag_pad: Mapped[str | None] = mapped_column(String(), default=None)
    factuur_pdf_op: Mapped[datetime | None] = mapped_column(default=None)
