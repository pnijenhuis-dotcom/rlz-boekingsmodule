"""Voorraad-aansluiting (bouwrun 28-08 blok D, mockup voorraad-aansluiting.html; migratie 0086) —
eerste bewoner van het `mi`-schema. Controle-laag, géén tweede voorraadadministratie: instroom =
regel-niveau feiten uit AI-gescande inkoopfacturen (externe documenten), uitstroom = geregistreerde
verkoopfactuurregels; theoretische stand vs systeemstand = verschil-signaal. Nooit geboekt in RLZ."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base

SCHEMA = "mi"
# Vendor-sentinel voor normalisatieregels zonder herkende leverancier (unique-constraint kent
# geen NULL-gelijkheid).
ONBEKENDE_LEVERANCIER = uuid.UUID(int=0)


class Artikelgroep(Base):
    """Genormaliseerde artikelgroep ("Koppelingen 48mm") per administratie; tolerantie-% per groep
    (default 1 — mockup-beslispunt 4). Actief/inactief, nooit verwijderen."""

    __tablename__ = "artikelgroep"
    __table_args__ = (
        Index("ix_artikelgroep_administratie_id", "administratie_id"),
        # Gespiegeld uit migratie 0086: naam uniek (case-insensitief) onder actieve groepen.
        Index(
            "uq_artikelgroep_naam",
            "administratie_id",
            text("lower(naam)"),
            unique=True,
            postgresql_where=text("actief"),
        ),
        CheckConstraint("tolerantie_pct >= 0 AND tolerantie_pct <= 100", name="ck_artikelgroep_tolerantie"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    naam: Mapped[str]
    eenheid: Mapped[str] = mapped_column(default="st", server_default="st")
    tolerantie_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("1.00"), server_default="1.00")
    actief: Mapped[bool] = mapped_column(default=True, server_default="true")
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())


SOORTEN = ("artikel", "dienst", "transport")


class NormalisatieRegel(Base):
    """Deterministische normalisatieregel per (administratie, leverancier, genormaliseerde
    artikeltekst): → artikelgroep (soort 'artikel'), óf soort 'dienst'/'transport' (v2 30-08 — het
    soort-label vervángt het oude 'uitgesloten': dienstregels blijven bewaard als omzet-/dienstregel
    voor MI, tellen alleen niet in de voorraad-aansluiting). Bron 'regel' = de vaste dienst-/
    transportregel, 'ai' = eerste match (direct toegepast, zekerheid erbij), 'handmatig' = correctie
    door de mens (geldt vanaf dan voor álle regels met dezelfde tekst; historie herrekend). Daarna
    nooit meer een AI-call voor dezelfde tekst. `uitgesloten` (pre-0088) blijft in sync met soort ≠
    artikel tot de opruim-migratie ná de hernormalisatie op álle omgevingen."""

    __tablename__ = "normalisatie_regel"
    __table_args__ = (
        UniqueConstraint("administratie_id", "vendor_id", "artikeltekst_norm", name="uq_normalisatie_regel_tekst"),
        CheckConstraint("bron IN ('ai', 'handmatig', 'regel')", name="ck_normalisatie_regel_bron"),
        CheckConstraint("soort IN ('artikel', 'dienst', 'transport')", name="ck_normalisatie_regel_soort"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    artikeltekst_norm: Mapped[str]
    artikelgroep_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.artikelgroep.id"), default=None
    )
    uitgesloten: Mapped[bool] = mapped_column(default=False, server_default="false")
    soort: Mapped[str] = mapped_column(default="artikel", server_default="artikel")
    zekerheid: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), default=None)
    bron: Mapped[str]
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    bijgewerkt_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    bijgewerkt_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class ArtikelcodeKoppeling(Base):
    """Artikelcode als deterministische normalisatiesleutel (v2 30-08, blok C): per (administratie,
    RICHTING, leverancier, code) → artikelgroep óf soort dienst/transport. Inkoopcodes (leverancier)
    en verkoopcodes (eigen Description "(560140.4)") zijn verschillende sleutelruimtes — nooit aannemen
    dat ze gelijk zijn, daarom `richting` in de sleutel. Eerste keer per code = voorstel (bron 'ai',
    zekerheid erbij, zichtbaar in de codes-inzage), daarna deterministisch vóór de tekstregel en vóór
    de AI; 'handmatig' = correctie (wint, herrekent historie)."""

    __tablename__ = "artikelcode_koppeling"
    __table_args__ = (
        UniqueConstraint("administratie_id", "richting", "vendor_id", "code", name="uq_artikelcode_koppeling"),
        Index("ix_artikelcode_koppeling_administratie_id", "administratie_id"),
        CheckConstraint("richting IN ('in', 'uit')", name="ck_artikelcode_koppeling_richting"),
        CheckConstraint("soort IN ('artikel', 'dienst', 'transport')", name="ck_artikelcode_koppeling_soort"),
        CheckConstraint("bron IN ('ai', 'handmatig')", name="ck_artikelcode_koppeling_bron"),
        CheckConstraint(
            "(soort = 'artikel') OR artikelgroep_id IS NULL", name="ck_artikelcode_koppeling_groep_bij_artikel"
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    richting: Mapped[str]
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    code: Mapped[str]
    artikelgroep_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.artikelgroep.id"), default=None
    )
    soort: Mapped[str] = mapped_column(default="artikel", server_default="artikel")
    zekerheid: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), default=None)
    bron: Mapped[str]
    voorbeeld_tekst: Mapped[str | None] = mapped_column(default=None)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    bijgewerkt_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    bijgewerkt_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class VoorraadRegel(Base):
    """Eén feit op regelniveau: in (inkoopfactuur, extern document) of uit (verkoopfactuurregel),
    op DAGNIVEAU (`datum`), mét de normalisatie-uitkomst. Afgeleide, herrekenbare feitenlaag
    (upsert per (document, richting, regelvolgnummer); verwijderen = herrekenen, geen bron).

    Herkomst (migratie 0087): een lokaal document (`document_id`) ÓF een RLZ-verkoopfactuur
    (`rlz_document_id` + `rlz_referentie`, bron `rlz_verkoop` — de eigen RLZ-facturen van een
    voorraad-administratie, dagelijkse leesroute); precies één van beide (CHECK).

    v2 (migratie 0088): `soort` artikel/dienst/transport — dienst-/transportregels blijven bewaard
    (omzet-/dienstinformatie voor MI) en tellen alleen niet in de aansluiting; `normalisatie_status`
    is sindsdien puur de zekerheid (genormaliseerd/onzeker/niet_genormaliseerd — 'uitgesloten' = legacy
    pre-0088, omgezet door de hernormalisatie); `artikelcode` = de code uit de regeltekst/het
    veldvoorstel (normalisatiesleutel, zie ArtikelcodeKoppeling)."""

    __tablename__ = "voorraad_regel"
    __table_args__ = (
        UniqueConstraint("document_id", "richting", "regel_volgnummer", name="uq_voorraad_regel_document_regel"),
        Index("ix_voorraad_regel_administratie_datum", "administratie_id", "datum"),
        Index("ix_voorraad_regel_artikelgroep_id", "artikelgroep_id"),
        Index("ix_voorraad_regel_rlz_document_id", "rlz_document_id"),
        Index("ix_voorraad_regel_artikelcode", "administratie_id", "artikelcode"),
        Index(
            "uq_voorraad_regel_rlz_regel",
            "rlz_document_id",
            "richting",
            "regel_volgnummer",
            unique=True,
            postgresql_where=text("rlz_document_id IS NOT NULL"),
        ),
        CheckConstraint("richting IN ('in', 'uit')", name="ck_voorraad_regel_richting"),
        CheckConstraint(
            "(document_id IS NOT NULL) <> (rlz_document_id IS NOT NULL)", name="ck_voorraad_regel_herkomst"
        ),
        # 'uitgesloten' = legacy-representatie vóór 0088 (de code schrijft 'm niet meer; de app-
        # hernormalisatie zet 'm om naar soort dienst/transport). Opruimen = latere migratie.
        CheckConstraint(
            "normalisatie_status IN ('genormaliseerd', 'onzeker', 'uitgesloten', 'niet_genormaliseerd')",
            name="ck_voorraad_regel_status",
        ),
        CheckConstraint("soort IN ('artikel', 'dienst', 'transport')", name="ck_voorraad_regel_soort"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.document.id"), default=None
    )
    rlz_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    rlz_referentie: Mapped[str | None] = mapped_column(default=None)
    richting: Mapped[str]
    bron: Mapped[str]
    datum: Mapped[date]
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    relatie_naam: Mapped[str | None] = mapped_column(default=None)
    regel_volgnummer: Mapped[int]
    artikeltekst: Mapped[str]
    artikelcode: Mapped[str | None] = mapped_column(default=None)
    soort: Mapped[str] = mapped_column(default="artikel", server_default="artikel")
    aantal: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), default=None)
    eenheid: Mapped[str | None] = mapped_column(default=None)
    prijs: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), default=None)
    netto_bedrag: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    artikelgroep_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.artikelgroep.id"), default=None
    )
    normalisatie_status: Mapped[str]
    normalisatie_zekerheid: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), default=None)
    bijgewerkt_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class VoorraadTelling(Base):
    """Systeemstand fase 1: handmatige telling per artikelgroep per datum (later: Odoo-stand via de
    JSON-2-leesroute — zelfde tabelvorm, andere bron)."""

    __tablename__ = "voorraad_telling"
    __table_args__ = (
        UniqueConstraint("artikelgroep_id", "datum", name="uq_voorraad_telling_groep_datum"),
        Index("ix_voorraad_telling_administratie_id", "administratie_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    artikelgroep_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.artikelgroep.id"))
    datum: Mapped[date]
    aantal: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    opmerking: Mapped[str | None] = mapped_column(default=None)
    ingevoerd_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    ingevoerd_op: Mapped[datetime] = mapped_column(server_default=func.now())
