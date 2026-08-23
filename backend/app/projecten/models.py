from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, Numeric, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class ProjectAanvraagStatus(enum.StrEnum):
    AANGEMAAKT = "aangemaakt"
    BESTOND_AL = "bestond_al"


class ProjectAanvraag(Base):
    """Eén verwerkte projectaanvraag van vastgoed (route A, koppelcontract §5 v1.15; migratie
    0048). `bericht_id` is de idempotentiesleutel (UUIDv5 door vastgoed gegenereerd, PK): een
    herlevering van hetzelfde bericht vindt deze rij en krijgt exact hetzelfde synchrone
    antwoord terug, zonder tweede RLZ-call. `nonce` is DB-uniek als replay-verdediging bovenop
    het timestamp-venster: dezelfde nonce onder een ánder bericht wordt geweigerd. Rijen
    ontstaan alleen bij een geslaagde verwerking (append-only register — een RLZ-fout is een
    zichtbare 502 + audit_event, vastgoed herhaalt met hetzelfde bericht_id)."""

    __tablename__ = "projectaanvraag"
    __table_args__ = {"schema": "boekhouding"}

    bericht_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id")
    )
    nonce: Mapped[str] = mapped_column(unique=True)
    pand_referentie: Mapped[str] = mapped_column()
    naam_invoer: Mapped[str] = mapped_column()
    # De door ónze naamconventie-motor gevormde definitieve projectnaam — bij `bestond_al` de
    # werkelijke naam van het bestaande RLZ-project (RLZ-staat wint, nooit stil hernoemen).
    projectnaam: Mapped[str] = mapped_column()
    rlz_project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column()
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())


class ProjectRegelSoort(enum.StrEnum):
    """Kant van een RLZ-documentregel in de cijfer-cache: inkoop = kosten, verkoop = baten."""

    INKOOP = "inkoop"
    VERKOOP = "verkoop"


_REGEL_SOORT_SQL = ", ".join(f"'{s.value}'" for s in ProjectRegelSoort)


class ProjectRegelCache(Base):
    """Cache van RLZ-documentregels MÉT projectreferentie (projectenmodule, migratie 0062) —
    de rekenbron voor "resultaat per project" (mockup projecten-invoer.html views 3/4).
    Gevuld door de projectcijfers-sync (app/projecten/cijfers.py: PurchaseInvoices +
    SalesInvoices → /Lines?$expand=Account,Project — api-verkenning: "factuurregels dragen
    Project + GB aan béíde kanten"); RLZ blijft de bron van waarheid, dit is een leescache
    (kernprincipe 1). `id` = het RLZ-Line-GUID; regels van geboekte documenten (Status 2/3).
    Bedragen zoals RLZ ze geeft — creditregels zijn negatief, nooit hier omgerekend."""

    __tablename__ = "project_regel_cache"
    __table_args__ = (
        CheckConstraint(f"soort IN ({_REGEL_SOORT_SQL})", name="ck_project_regel_cache_soort"),
        Index("ix_project_regel_cache_administratie_id", "administratie_id"),
        Index("ix_project_regel_cache_project", "administratie_id", "project_id"),
        Index("ix_project_regel_cache_document", "administratie_id", "rlz_document_id"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), primary_key=True
    )
    rlz_document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    soort: Mapped[str]
    # RLZ-Project-GUID — bewust géén FK naar project_cache: een regel kan naar een intussen
    # gearchiveerd/verdwenen project wijzen; de rekenlaag joint zelf op de cache.
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    ledger_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    netto_bedrag: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    btw_bedrag: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    # Documentdatum (RLZ `Date`) — de week-toewijzing "anders factuurdatum" (mockup-notitie).
    datum: Mapped[date | None] = mapped_column(default=None)
    referentie: Mapped[str | None] = mapped_column(default=None)
    omschrijving: Mapped[str | None] = mapped_column(default=None)
    laatst_gesynchroniseerd: Mapped[datetime] = mapped_column(server_default=func.now())
    verdwenen_uit_bron_op: Mapped[datetime | None] = mapped_column(default=None)


class CijfersSyncRunStatus(enum.StrEnum):
    """Levensloop van één projectcijfers-syncrun: `wachtrij` (aangevraagd, wacht op de
    verwerker), `bezig` (geclaimd, heartbeat in laatst_actief_op), `klaar` of `fout`
    (fout_reden verplicht zichtbaar — nooit stil, kernprincipe 4)."""

    WACHTRIJ = "wachtrij"
    BEZIG = "bezig"
    KLAAR = "klaar"
    FOUT = "fout"


_SYNC_RUN_STATUS_SQL = ", ".join(f"'{s.value}'" for s in CijfersSyncRunStatus)


class ProjectCijfersSyncRun(Base):
    """Statusrij van één projectcijfers-syncrun (migratie 0063 — fix van de 504-crash 23-08:
    de knop start een ACHTERGRONDRUN i.p.v. de hele RLZ-ronde in één HTTP-request; de UI pollt
    deze rij via de status-leesroute). Cloud Run-voertuig = de on-demand job
    `rlz-projecten-cijfers` (wachtrij-patroon: de rij ís de opdracht, de job-args blijven
    leeg); dev-voertuig = een achtergrond-thread. `laatst_actief_op` is de heartbeat — een
    `bezig`-rij zonder verse heartbeat telt als afgebroken (zichtbaar fout, blokkeert geen
    nieuwe run). `leesfouten` = documenten waarvan RLZ de regels niet gaf (bv. 403-storm):
    hun cache-rijen worden dan bewust NIET als verdwenen gemarkeerd."""

    __tablename__ = "project_cijfers_sync_run"
    __table_args__ = (
        CheckConstraint(f"status IN ({_SYNC_RUN_STATUS_SQL})", name="ck_project_cijfers_sync_run_status"),
        Index("ix_project_cijfers_sync_run_administratie_id", "administratie_id"),
        Index("ix_project_cijfers_sync_run_status", "administratie_id", "status"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id")
    )
    status: Mapped[str] = mapped_column(default=CijfersSyncRunStatus.WACHTRIJ.value)
    # NULL = aangevraagd door het systeem (dagelijkse sync-job) i.p.v. de knop.
    aangevraagd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    aangevraagd_op: Mapped[datetime] = mapped_column(server_default=func.now())
    gestart_op: Mapped[datetime | None] = mapped_column(default=None)
    laatst_actief_op: Mapped[datetime | None] = mapped_column(default=None)
    beeindigd_op: Mapped[datetime | None] = mapped_column(default=None)
    documenten: Mapped[int | None] = mapped_column(default=None)
    regels: Mapped[int | None] = mapped_column(default=None)
    verdwenen: Mapped[int | None] = mapped_column(default=None)
    leesfouten: Mapped[int | None] = mapped_column(default=None)
    fout_reden: Mapped[str | None] = mapped_column(default=None)


class OntledingRegelStatus(enum.StrEnum):
    VOORSTEL = "voorstel"
    BEVESTIGD = "bevestigd"
    AFGEWEZEN = "afgewezen"


class OntledingRegelSoort(enum.StrEnum):
    """Wat een ontleed-voorstelregel bij bevestiging deterministisch voedt (mockup: bevestigen
    per regel, nooit automatisch overnemen)."""

    CONTRACT_M2 = "contract_m2"  # → project_specificatie.contract_m2
    LOOPTIJD = "looptijd"  # → looptijd_van/looptijd_tot
    HUURTIJD = "huurtijd"  # → huurtijd_omschrijving
    DOORLOPENDE_HUUR = "doorlopende_huur"  # → doorlopende_huur_omschrijving
    OPDRACHTGEVER = "opdrachtgever"  # → opdrachtgever
    WERKNUMMER = "werknummer"  # → werknummer_opdrachtgever
    STAFFEL = "staffel"  # → project_staffel-rij (mens kiest de eenheid uit de vaste vier)
    BOETE = "boete"  # vastgelegd als info/projectsignaal — geen spec-/staffelveld


_ONTLEDING_SOORT_SQL = ", ".join(f"'{s.value}'" for s in OntledingRegelSoort)
_ONTLEDING_STATUS_SQL = ", ".join(f"'{s.value}'" for s in OntledingRegelStatus)


class ProjectOntledingRegel(Base):
    """Eén regel van het contract-/offerte-ontleedvoorstel (AI — mockup projecten-invoer.html:
    "Ontleed-voorstel … bevestig per regel"; migratie 0062). De AI stelt VOOR, de mens
    bevestigt (✓) of wijst af (✗); bevestigen = deterministisch doorschrijven naar
    project_specificatie/project_staffel (app/projecten/ontleding.py) — er wordt nooit iets
    automatisch overgenomen. Een her-ontleding vervangt alleen de nog onbesliste
    voorstel-regels; besliste regels blijven als vastlegging staan."""

    __tablename__ = "project_ontleding_regel"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "administratie_id"],
            ["boekhouding.project_cache.id", "boekhouding.project_cache.administratie_id"],
            name="fk_project_ontleding_regel_project_cache",
        ),
        CheckConstraint(f"soort IN ({_ONTLEDING_SOORT_SQL})", name="ck_project_ontleding_regel_soort"),
        CheckConstraint(f"status IN ({_ONTLEDING_STATUS_SQL})", name="ck_project_ontleding_regel_status"),
        Index("ix_project_ontleding_regel_administratie_id", "administratie_id"),
        Index("ix_project_ontleding_regel_project", "administratie_id", "project_id"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    project_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.project_document.id")
    )
    soort: Mapped[str]
    omschrijving: Mapped[str]
    citaat: Mapped[str | None] = mapped_column(default=None)
    # Soort-afhankelijke voorstelwaarde ({"waarde": "4200"}, {"prijs": "9.20", "eenheid": …},
    # {"van": "2026-06-02", "tot": "2026-11-30"}, {"tekst": …}) — string-bedragen, geen floats.
    waarde: Mapped[dict | None] = mapped_column(JSONB, default=None)
    zekerheid: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), default=None)
    status: Mapped[str] = mapped_column(default=OntledingRegelStatus.VOORSTEL.value)
    beslist_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    beslist_op: Mapped[datetime | None] = mapped_column(default=None)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())


class LeverancierWerknummer(Base):
    """Leverancier-werknummer ↔ project-mapping (praktijkles verkenning/12: leveranciers
    hanteren eigen werknummers op hun facturen; eerste keer bevestigen, daarna automatisch;
    migratie 0062). `bron` = hoe de rij ontstond; `bevestigd` = mens heeft de koppeling
    bevestigd (mockup-badge). Voedt de factuur↔project-matching (t.z.t. de fuzzy match —
    de mapping-tabel is er nu, het automatisch leren uit facturen is een parkeerpost)."""

    __tablename__ = "leverancier_werknummer"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "administratie_id"],
            ["boekhouding.project_cache.id", "boekhouding.project_cache.administratie_id"],
            name="fk_leverancier_werknummer_project_cache",
        ),
        UniqueConstraint("administratie_id", "vendor_id", "werknummer", name="uq_leverancier_werknummer"),
        Index("ix_leverancier_werknummer_administratie_id", "administratie_id"),
        Index("ix_leverancier_werknummer_project", "administratie_id", "project_id"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))  # RLZ-Vendor-GUID, geen FK
    werknummer: Mapped[str]
    bron: Mapped[str] = mapped_column(default="handmatig")
    bevestigd: Mapped[bool] = mapped_column(default=False)
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    bevestigd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    bevestigd_op: Mapped[datetime | None] = mapped_column(default=None)
