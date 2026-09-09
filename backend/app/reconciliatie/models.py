from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class ReconciliatieBron(enum.StrEnum):
    """Welke van de drie reconciliaties de afwijking meldde. Bewust een eigen discriminator en
    geen documentsoort: de bank-reconciliatie kent helemaal geen document, de omzet-variant
    rapporteert per boeking."""

    DOCUMENTEN = "documenten"
    BANK = "bank"
    OMZET = "omzet"
    DOORBELASTING = "doorbelasting"


class ReconciliatieAcceptatie(Base):
    """Eén beoordeelde-en-bewust-blijvende afwijking (migratie 0042).

    Waarom dit bestaat: een afwijking die terecht is maar niet meer opgelost gaat worden — het
    klassieke geval is een testboeking die een mens ná een storno in de RLZ-UI heeft opgeruimd,
    waardoor ons lokale GEBOEKT-document elke ochtend opnieuw als `ontbreekt_in_rlz` binnenkomt.
    Zonder acceptatie blijft die ruis staan, went het kantoor eraan en sterft de vangrail.

    Drie harde eigenschappen, in lijn met "niets verdwijnt stil":
    1. **Acceptatie onderdrukt niets.** De afwijking blijft in elk rapport zichtbaar, alleen met
       de markering GEACCEPTEERD; ze telt niet mee in de exit-code.
    2. **Acceptatie is zo smal als de afwijking zelf.** `vingerafdruk` is een hash over
       (bron, soort, detail): verandert het detail — ander bedrag, andere RLZ-status, ineens een
       500 i.p.v. een 404 — dan matcht de acceptatie niet meer en staat het signaal er gewoon
       weer. Fail-loud is hier de veilige richting.
    3. **Acceptatie is nooit een delete.** Intrekken zet `ingetrokken_op/-door`; de rij blijft
       staan (append-only-gedachte, GRANT zonder DELETE).

    Reden is verplicht en gaat mét actor in het audit_event — zelfde discipline als afwijzen
    met verplichte reden in de werkvoorraad."""

    __tablename__ = "reconciliatie_acceptatie"
    __table_args__ = (
        Index(
            "reconciliatie_acceptatie_actief_uniek",
            "administratie_id",
            "bron",
            "vingerafdruk",
            unique=True,
            postgresql_where=text("ingetrokken_op IS NULL"),
        ),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    bron: Mapped[str] = mapped_column()
    # Het record waar de meldende reconciliatie over sprak: document_id (documenten),
    # bankboeking-/afletteropdracht-id (bank) of omzetboeking-id (omzet). Bewust géén FK — de
    # drie bronnen wijzen naar drie verschillende tabellen.
    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    soort: Mapped[str] = mapped_column()
    vingerafdruk: Mapped[str] = mapped_column()
    # De detailtekst zoals hij op het moment van accepteren luidde — puur voor leesbaarheid in
    # rapport en audit; de vingerafdruk is de sleutel.
    detail: Mapped[str] = mapped_column()
    reden: Mapped[str] = mapped_column()
    geaccepteerd_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    geaccepteerd_op: Mapped[datetime] = mapped_column(server_default=func.now())
    ingetrokken_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    ingetrokken_op: Mapped[datetime | None] = mapped_column(default=None)


# --- Reconciliatie-melding + Inzicht (opdracht 06-09, migratie 0114) ---------------------------------
#
# Aanleiding: de Cloud Run-job `rlz-reconciliatie` draait dagelijks, maar alles wat exit 0 oplevert
# en tóch aandacht vraagt (LET-OP-regels over achtergebleven RLZ-concepten, nieuwe GEACCEPTEERD-regels,
# blokken die op een RLZ-leesfout deels overgeslagen zijn) was onzichtbaar; de F3.2-failure-mail zegt
# alleen "job failed". Daarom bewaart élke run zijn uitkomst (run-rij + bevindingen), bepaalt de
# motor de delta t.o.v. de vorige afgeronde run en mailt alleen als er iets te melden is; de kantoor-UI
# (Inzicht › Reconciliatie) toont de bevindingen mét handeling. De reconciliatie-blokken zelf zijn
# ongewijzigd — dit is uitsluitend vastleggen, vergelijken en melden.


class ReconciliatieRunStatus(enum.StrEnum):
    WACHTEND = "wachtend"  # "Nu draaien" gezet, voertuig nog niet begonnen
    BEZIG = "bezig"
    KLAAR = "klaar"  # alle blokken gedraaid (exit 0 óf 1 — de exit-code staat apart)
    FOUT = "fout"  # de run zelf kon niet (af)draaien


class ReconciliatieRunBron(enum.StrEnum):
    SCHEDULER = "scheduler"  # Cloud Run-job onder ENVIRONMENT=production
    CLI = "cli"  # lokale `make reconciliatie-alles`
    HANDMATIG = "handmatig"  # knop "Nu draaien" (Beheerder) op Inzicht › Reconciliatie


class BevindingSoort(enum.StrEnum):
    AFWIJKING = "afwijking"  # open afwijking — telt mee in de exit-code
    LET_OP = "let_op"  # informatief: opruim-kandidaat (achtergebleven RLZ-concept) of opruimlijst-fout
    GEACCEPTEERD = "geaccepteerd"  # beoordeeld-en-blijvend (reconciliatie_acceptatie)
    UITGESLOTEN = "uitgesloten"  # bevinding op een van de exit-code uitgesloten administratie
    FOUT = "fout"  # administratie/blok kon niet gecontroleerd worden (credentials, RLZ-leesfout, crash)


class ReconciliatieRun(Base):
    """Eén reconciliatie-alles-run (append-only: rijen verdwijnen nooit; alleen de status-/afrondings-
    kolommen van een lopende run worden bijgewerkt — het bank_sync_run-patroon). PLATFORMBREED (geen
    administratie_id, geen RLS — 0099-lijn): de run gaat over álle administraties, de per-administratie-
    scope zit op de bevindingen. `samenvatting` = per blok {status, gecontroleerd, afwijkingen,
    geaccepteerd, uitgesloten, let_op, fouten, exit_code, foutmelding}. `mail_status` draagt de
    idempotentie van de mail (hooguit één per kanaal per run) — sinds bundel 09-09 blok 1 een samengestelde
    tekst "actie=<s>;systeem=<s>" (kanaal actie = kantoor, systeem = beheer; s ∈ niet_nodig | verzonden |
    mislukt | niet_geconfigureerd; runs van vóór 09-09 dragen één kale status = kanaal actie), te lezen via
    `run.mail_statussen()`; élk kanaal op 'mislukt' pikt de bewaking op als storing 'reconciliatie_mail'."""

    __tablename__ = "reconciliatie_run"
    __table_args__ = (
        Index("ix_reconciliatie_run_status", "status"),
        Index("ix_reconciliatie_run_aangevraagd_op", "aangevraagd_op"),
        CheckConstraint("status IN ('wachtend', 'bezig', 'klaar', 'fout')", name="ck_reconciliatie_run_status"),
        CheckConstraint("bron IN ('scheduler', 'cli', 'handmatig')", name="ck_reconciliatie_run_bron"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(default=ReconciliatieRunStatus.WACHTEND.value, server_default="wachtend")
    bron: Mapped[str] = mapped_column(default=ReconciliatieRunBron.CLI.value, server_default="cli")
    aangevraagd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    aangevraagd_op: Mapped[datetime] = mapped_column(server_default=func.now())
    gestart_op: Mapped[datetime | None] = mapped_column(default=None)
    laatst_actief_op: Mapped[datetime | None] = mapped_column(default=None)
    afgerond_op: Mapped[datetime | None] = mapped_column(default=None)
    exit_code: Mapped[int | None] = mapped_column(default=None)
    samenvatting: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), default=None)
    fout_reden: Mapped[str | None] = mapped_column(default=None)
    mail_status: Mapped[str | None] = mapped_column(default=None)
    mail_detail: Mapped[str | None] = mapped_column(default=None)
    mail_verzonden_op: Mapped[datetime | None] = mapped_column(default=None)


class ReconciliatieBevinding(Base):
    """Eén regel uit één run — dezelfde tekst als de CLI-regel, mét administratie en vingerafdruk.
    De vingerafdruk is de sleutel voor "nieuw sinds de vorige run": voor afwijkingen de bestaande
    acceptatie-vingerafdruk (bron|soort|detail), voor opruim-kandidaten sha(kant|concept_administratie|
    rlz_id), voor fouten sha(blok|administratie|tekst). RLS op administratie_id (0004-vorm: NULL =
    administratie-loze blokfout, zichtbaar in élke scope). `detail` = de machineleesbare kern
    (bron/record_id/afwijking_soort/detail voor accepteren; kant/rlz_id/document_id voor de deeplink)."""

    __tablename__ = "reconciliatie_bevinding"
    __table_args__ = (
        Index("ix_reconciliatie_bevinding_run_id", "run_id"),
        Index("ix_reconciliatie_bevinding_vingerafdruk", "vingerafdruk"),
        Index("ix_reconciliatie_bevinding_administratie_id", "administratie_id"),
        CheckConstraint(
            "soort IN ('afwijking', 'let_op', 'geaccepteerd', 'uitgesloten', 'fout')",
            name="ck_reconciliatie_bevinding_soort",
        ),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("boekhouding.reconciliatie_run.id"))
    blok: Mapped[str] = mapped_column()  # bank | documenten | omzet | doorbelasting | run
    soort: Mapped[str] = mapped_column()
    administratie_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), default=None
    )
    vingerafdruk: Mapped[str] = mapped_column()
    tekst: Mapped[str] = mapped_column()
    detail: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), default=None)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())


class ReconciliatieGezien(Base):
    """ "Gezien" op een LET-OP-bevinding (opruim-kandidaat): snooze mét verplichte reden. De bevinding
    verdwijnt uit de KPI-teller en uit de mail, blijft onder het facet "gezien" zichtbaar en komt terug
    zodra (a) `gezien_op` + de Beheerder-instelling `gezien_dagen` (default 90) voorbij is — bij het LEZEN
    getoetst, zodat een gewijzigde instelling direct geldt; `vervalt_op` = de termijn zoals gezet bij het
    markeren (audit-spoor) — of (b) de
    kandidaat met een ándere reden terugkomt (`reden_snapshot` ≠ actuele reden — het concept kreeg een
    andere status/oorsprong). Nooit een delete: intrekken zet `ingetrokken_op/-door`. RLS op
    administratie_id (bron-administratie van de doorbelasting)."""

    __tablename__ = "reconciliatie_gezien"
    __table_args__ = (
        Index(
            "reconciliatie_gezien_actief_uniek",
            "administratie_id",
            "vingerafdruk",
            unique=True,
            postgresql_where=text("ingetrokken_op IS NULL"),
        ),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    blok: Mapped[str] = mapped_column()
    vingerafdruk: Mapped[str] = mapped_column()
    reden_snapshot: Mapped[str | None] = mapped_column(default=None)
    reden: Mapped[str] = mapped_column()
    gezien_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    gezien_op: Mapped[datetime] = mapped_column(server_default=func.now())
    vervalt_op: Mapped[datetime] = mapped_column()
    ingetrokken_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    ingetrokken_op: Mapped[datetime | None] = mapped_column(default=None)


class ReconciliatieInstelling(Base):
    """Beheerder-instelling van de reconciliatie-melding (singleton, BoekenInstelling-patroon maar in
    het module-schema): `gezien_dagen` = na hoeveel dagen een "Gezien"-snooze vervalt (default 90)."""

    __tablename__ = "reconciliatie_instelling"
    __table_args__ = (
        CheckConstraint("singleton", name="reconciliatie_instelling_singleton"),
        CheckConstraint("gezien_dagen BETWEEN 1 AND 3650", name="ck_reconciliatie_instelling_gezien_dagen"),
        {"schema": "boekhouding"},
    )

    singleton: Mapped[bool] = mapped_column(primary_key=True, default=True)
    gezien_dagen: Mapped[int] = mapped_column(default=90, server_default="90")
    gewijzigd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    gewijzigd_op: Mapped[datetime] = mapped_column(server_default=func.now())
