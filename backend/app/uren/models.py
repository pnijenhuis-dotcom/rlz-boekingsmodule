"""Uren & meerwerk — steigerbouw-tak (BOUW GO Peter 2026-08-21, migratie 0056).

Datamodel-besluiten (BESLISSINGEN "Ontwerpronde uren & uitvoerder + meerwerk-kantoor"):
- WEEKSTAAT PER PROJECT: één staat per persoon per project per ISO-week; zelfde dag op twee
  projecten = twee staten. Dagregels (uren + optionele m² + opmerking) hangen aan de staat;
  een dag zonder rij telt als 0 uur.
- KEURING OP WEEKNIVEAU: de uitvoerder keurt de week in zijn geheel — akkoord óf afkeuren met
  verplichte reden (hele week terug naar "corrigeren"). Geen dag-keuring in het datamodel.
- Goedgekeurd = de GETEKENDE urenstaat (basis voor de latere factuurmatch) — onmuteerbaar;
  wijzigen kan uitsluitend doordat de uitvoerder opnieuw afkeurt (reden verplicht).
- DETACHEERDER vult in namens gekoppelde ZZP'ers: elke dagregel draagt `ingevuld_door` en de
  staat draagt `ingediend_door` — wijkt die af van de ZZP'er zelf, dan is dat de zichtbare
  "ingevuld door X namens Y"-vastlegging (audit + keurscherm). De koppeltabel zelf
  (detacheerder↔zzp'er) leeft in platform (app/db/models.py::DetacheerderKoppeling).
- Meerwerk: gemeld → goedgekeurd (nog doorbelasten) → doorbelast / afgewezen (eigen rekening,
  verplichte reden). Contract-toets = VOORSTEL uit de offerte-staffel (project_staffel), de
  mens bevestigt de prijs — nooit auto-boeken.
- Alles administratie-gebonden mét RLS; de module is opt-in per administratie
  (platform.administratie.uren_meerwerk_ingeschakeld, alleen Universal initieel)."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    SmallInteger,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class WeekstaatStatus(enum.StrEnum):
    """CONCEPT = in bewerking (dagen muteerbaar); INGEDIEND = bevroren, wacht op de uitvoerder;
    GOEDGEKEURD = de getekende urenstaat (onmuteerbaar); CORRIGEREN = afgekeurd met verplichte
    reden — dagen weer muteerbaar, de ZZP'er dient de wéék opnieuw in."""

    CONCEPT = "concept"
    INGEDIEND = "ingediend"
    GOEDGEKEURD = "goedgekeurd"
    CORRIGEREN = "corrigeren"


class MeerwerkStatus(enum.StrEnum):
    """GEMELD = door de uitvoerder gemeld, te beoordelen door het kantoor; GOEDGEKEURD =
    goedgekeurd voor doorbelasting (prijs door een mens bevestigd), bewaakt tot het op een
    verkoopfactuur staat; DOORBELAST = op een verkoopfactuur gezet (referentie verplicht);
    AFGEWEZEN = eigen rekening, met verplichte reden — blijft zichtbaar in de lijst."""

    GEMELD = "gemeld"
    GOEDGEKEURD = "goedgekeurd"
    DOORBELAST = "doorbelast"
    AFGEWEZEN = "afgewezen"


class MeerwerkEenheid(enum.StrEnum):
    """Eenheden uit de praktijklessen (verkenning/12): m² / m¹ / stuks / manuren."""

    M2 = "m2"
    M1 = "m1"
    STUKS = "stuks"
    MANUREN = "manuren"


_WEEKSTAAT_STATUS_SQL = ", ".join(f"'{s.value}'" for s in WeekstaatStatus)
_MEERWERK_STATUS_SQL = ", ".join(f"'{s.value}'" for s in MeerwerkStatus)
_EENHEID_SQL = ", ".join(f"'{e.value}'" for e in MeerwerkEenheid)


class Weekstaat(Base):
    """Eén weekstaat per (administratie, ZZP'er, project, ISO-jaar, ISO-week) — het
    datamodel-besluit van 2026-08-21. De afkeur-velden houden de LAATSTE afkeuring vast
    (volledige historie staat in audit_event); bij een nieuwe goedkeuring worden ze niet
    gewist — de UI toont ze alleen in status `corrigeren`."""

    __tablename__ = "weekstaat"
    __table_args__ = (
        UniqueConstraint(
            "administratie_id", "gebruiker_id", "project_id", "jaar", "weeknummer",
            name="uq_weekstaat_persoon_project_week",
        ),
        ForeignKeyConstraint(
            ["project_id", "administratie_id"],
            ["boekhouding.project_cache.id", "boekhouding.project_cache.administratie_id"],
            name="fk_weekstaat_project_cache",
        ),
        CheckConstraint(f"status IN ({_WEEKSTAAT_STATUS_SQL})", name="ck_weekstaat_status"),
        CheckConstraint("weeknummer BETWEEN 1 AND 53", name="ck_weekstaat_weeknummer"),
        CheckConstraint(
            "status != 'goedgekeurd' OR (goedgekeurd_op IS NOT NULL AND goedgekeurd_door IS NOT NULL)",
            name="ck_weekstaat_goedgekeurd_velden",
        ),
        CheckConstraint(
            "status != 'corrigeren' OR afkeur_reden IS NOT NULL",
            name="ck_weekstaat_afkeur_reden",
        ),
        Index("ix_weekstaat_administratie_id", "administratie_id"),
        Index("ix_weekstaat_administratie_status", "administratie_id", "status"),
        Index("ix_weekstaat_gebruiker", "administratie_id", "gebruiker_id"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    # De ZZP'er van wie de staat is — óók wanneer een detacheerder invult (die staat dan in
    # ingediend_door / weekstaat_dag.ingevuld_door).
    gebruiker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    jaar: Mapped[int] = mapped_column(SmallInteger)
    weeknummer: Mapped[int] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(default=WeekstaatStatus.CONCEPT.value)
    ingediend_op: Mapped[datetime | None] = mapped_column(default=None)
    ingediend_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    goedgekeurd_op: Mapped[datetime | None] = mapped_column(default=None)
    goedgekeurd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    afgekeurd_op: Mapped[datetime | None] = mapped_column(default=None)
    afgekeurd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    afkeur_reden: Mapped[str | None] = mapped_column(default=None)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    bijgewerkt_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class WeekstaatDag(Base):
    """Dagregel binnen een weekstaat: uren verplicht, m² optioneel (aanname aanvaard 21-08).
    `ingevuld_door` ≠ de ZZP'er van de staat = ingevuld door een detacheerder namens hem —
    zichtbaar bij de keuring en in het audit-log. Muteerbaar uitsluitend in de staten
    concept/corrigeren (statusmachine, app/uren/service.py). Geen DELETE gegrant: een
    verkeerde dag wordt op 0 uur gezet, nooit stil verwijderd."""

    __tablename__ = "weekstaat_dag"
    __table_args__ = (
        UniqueConstraint("weekstaat_id", "datum", name="uq_weekstaat_dag_datum"),
        CheckConstraint("uren >= 0 AND uren <= 24", name="ck_weekstaat_dag_uren"),
        CheckConstraint("m2 IS NULL OR m2 >= 0", name="ck_weekstaat_dag_m2"),
        Index("ix_weekstaat_dag_administratie_id", "administratie_id"),
        Index("ix_weekstaat_dag_weekstaat_id", "weekstaat_id"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    weekstaat_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("boekhouding.weekstaat.id"))
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    datum: Mapped[date]
    uren: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    m2: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), default=None)
    opmerking: Mapped[str | None] = mapped_column(default=None)
    ingevuld_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    bijgewerkt_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Meerwerk(Base):
    """Meerwerkmelding door een uitvoerder (zonder prijzen — de kantoorkant prijst).
    Omschrijving altijd voluit tonen (mockup-norm, nooit afkappen). De vraag-velden dragen de
    lichte kantoor→uitvoerder-vraag uit het beoordeel-paneel ("Vraag aan uitvoerder") — de
    status blijft daarbij `gemeld`. `prijs_per_eenheid`/`bedrag` worden door een MENS bevestigd
    bij het goedkeuren (contract-toets is alleen een voorstel); `verkoopfactuur_referentie` is
    verplicht bij doorbelast. Het 2-weken-bewakingssignaal draait op status `goedgekeurd` +
    `beoordeeld_op` ouder dan 14 dagen."""

    __tablename__ = "meerwerk"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "administratie_id"],
            ["boekhouding.project_cache.id", "boekhouding.project_cache.administratie_id"],
            name="fk_meerwerk_project_cache",
        ),
        CheckConstraint(f"status IN ({_MEERWERK_STATUS_SQL})", name="ck_meerwerk_status"),
        CheckConstraint(f"eenheid IN ({_EENHEID_SQL})", name="ck_meerwerk_eenheid"),
        CheckConstraint("aantal > 0", name="ck_meerwerk_aantal"),
        CheckConstraint(
            "status != 'afgewezen' OR afwijs_reden IS NOT NULL",
            name="ck_meerwerk_afwijs_reden",
        ),
        CheckConstraint(
            "status NOT IN ('goedgekeurd', 'doorbelast') OR (prijs_per_eenheid IS NOT NULL AND bedrag IS NOT NULL)",
            name="ck_meerwerk_prijs_bevestigd",
        ),
        CheckConstraint(
            "status != 'doorbelast' OR verkoopfactuur_referentie IS NOT NULL",
            name="ck_meerwerk_doorbelast_referentie",
        ),
        Index("ix_meerwerk_administratie_id", "administratie_id"),
        Index("ix_meerwerk_administratie_status", "administratie_id", "status"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    omschrijving: Mapped[str]
    aantal: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    eenheid: Mapped[str]
    datum_uitgevoerd: Mapped[date]
    in_opdracht_van: Mapped[str | None] = mapped_column(default=None)
    # Foto via dezelfde DocumentOpslag-interface als document-PDF's (app/documenten/storage.py).
    foto_opslag_pad: Mapped[str | None] = mapped_column(default=None)
    foto_bestandsnaam: Mapped[str | None] = mapped_column(default=None)
    foto_content_type: Mapped[str | None] = mapped_column(default=None)
    gemeld_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    gemeld_op: Mapped[datetime] = mapped_column(server_default=func.now())
    status: Mapped[str] = mapped_column(default=MeerwerkStatus.GEMELD.value)
    prijs_per_eenheid: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    bedrag: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    facturatie_notitie: Mapped[str | None] = mapped_column(default=None)
    beoordeeld_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    beoordeeld_op: Mapped[datetime | None] = mapped_column(default=None)
    afwijs_reden: Mapped[str | None] = mapped_column(default=None)
    doorbelast_op: Mapped[datetime | None] = mapped_column(default=None)
    verkoopfactuur_referentie: Mapped[str | None] = mapped_column(default=None)
    vraag_tekst: Mapped[str | None] = mapped_column(default=None)
    vraag_gesteld_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    vraag_gesteld_op: Mapped[datetime | None] = mapped_column(default=None)
    vraag_antwoord: Mapped[str | None] = mapped_column(default=None)
    vraag_beantwoord_op: Mapped[datetime | None] = mapped_column(default=None)


class UrenProjectToewijzing(Base):
    """Kantoor-beheerde koppeling gebruiker↔project (Beheerder-only, geaudit): voor een ZZP'er
    = "op dit project schrijf je weekstaten", voor een uitvoerder = keurrecht + projectinhoud
    (specs/contract/meerwerk). De betekenis volgt uit Gebruiker.rol — bewust geen soort-kolom."""

    __tablename__ = "uren_project_toewijzing"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "administratie_id"],
            ["boekhouding.project_cache.id", "boekhouding.project_cache.administratie_id"],
            name="fk_uren_project_toewijzing_project_cache",
        ),
        Index("ix_uren_project_toewijzing_administratie_id", "administratie_id"),
        {"schema": "boekhouding"},
    )

    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), primary_key=True
    )
    gebruiker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), primary_key=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    toegevoegd_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())


class ProjectSpecificatie(Base):
    """Steigerbouw-projectgegevens voor het uitvoerder-projectdetail (mockup): opdrachtgever,
    werknummer, contract-m², looptijd, huurtijd. Gebouwde m² staan hier bewust NIET — die
    volgen als som uit de goedgekeurde weekstaten (voeding van de generieke projectenmodule).
    Kantoor-beheerd; alle velden optioneel (ontbrekend = nette lege staat in de app)."""

    __tablename__ = "project_specificatie"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "administratie_id"],
            ["boekhouding.project_cache.id", "boekhouding.project_cache.administratie_id"],
            name="fk_project_specificatie_project_cache",
        ),
        {"schema": "boekhouding"},
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), primary_key=True
    )
    opdrachtgever: Mapped[str | None] = mapped_column(default=None)
    werknummer_opdrachtgever: Mapped[str | None] = mapped_column(default=None)
    soort_werk: Mapped[str | None] = mapped_column(default=None)
    contract_m2: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    looptijd_van: Mapped[date | None] = mapped_column(default=None)
    looptijd_tot: Mapped[date | None] = mapped_column(default=None)
    huurtijd_omschrijving: Mapped[str | None] = mapped_column(default=None)
    doorlopende_huur_omschrijving: Mapped[str | None] = mapped_column(default=None)
    bijgewerkt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    bijgewerkt_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class ProjectDocument(Base):
    """Contract-/offerte-PDF per project, alleen-lezen voor de uitvoerder (mét prijzen —
    aanname aanvaard 21-08). Opslag via DocumentOpslag (zelfde interface als document-PDF's).
    Vervangen = nieuwe rij (versie_omschrijving), nooit verwijderen — geen DELETE gegrant."""

    __tablename__ = "project_document"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "administratie_id"],
            ["boekhouding.project_cache.id", "boekhouding.project_cache.administratie_id"],
            name="fk_project_document_project_cache",
        ),
        CheckConstraint("soort IN ('contract', 'offerte')", name="ck_project_document_soort"),
        Index("ix_project_document_administratie_id", "administratie_id"),
        Index("ix_project_document_project", "administratie_id", "project_id"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    soort: Mapped[str]
    titel: Mapped[str]
    versie_omschrijving: Mapped[str | None] = mapped_column(default=None)
    opslag_pad: Mapped[str]
    bestandsnaam: Mapped[str]
    geupload_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())


class ProjectStaffel(Base):
    """Offerte-staffel/verrekenprijzen per project — de bron voor de contract-toets in het
    kantoor-beoordeel-paneel (VOORSTEL: prijs uit de staffel bij dezelfde eenheid; de mens
    bevestigt of past aan, de app rekent nooit zelf door naar een boeking). Gevuld door het
    kantoor; t.z.t. voedt de offerte-ontleding van de generieke projectenmodule deze tabel."""

    __tablename__ = "project_staffel"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "administratie_id"],
            ["boekhouding.project_cache.id", "boekhouding.project_cache.administratie_id"],
            name="fk_project_staffel_project_cache",
        ),
        CheckConstraint(f"eenheid IN ({_EENHEID_SQL})", name="ck_project_staffel_eenheid"),
        CheckConstraint("prijs_per_eenheid >= 0", name="ck_project_staffel_prijs"),
        Index("ix_project_staffel_administratie_id", "administratie_id"),
        Index("ix_project_staffel_project", "administratie_id", "project_id"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    omschrijving: Mapped[str]
    eenheid: Mapped[str]
    prijs_per_eenheid: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    verrekenbaar: Mapped[bool] = mapped_column(default=True)
    bron: Mapped[str | None] = mapped_column(default=None)
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
