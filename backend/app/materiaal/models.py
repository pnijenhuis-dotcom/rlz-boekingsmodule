"""Transportplanning + bestellingen + materiaalstand (steigerbouw-run blok D, besluiten Peter
24-08 — mockup planning-steigerbouw.html Transport-tab + bestelling-popup = norm; migratie 0074).

- Materiaalcatalogus per LEVERANCIER (eigen verhuurbedrijven zoals Universal Verhuur / Floor
  Liften): categorieën → producten mét verpakkingseenheid en m²-lengte (de m²-totaalformule uit
  Peters bestellijst: Σ(aantal × lengte) / 4,6 — `M2_DELER`). Seedbaar uit
  verkenning/voorbeelden/bestellijst-universal-voorbeeld.xlsx (app/materiaal/seed.py).
- Bestelling per project × leverancier: concept-regels (product → aantal; 0 = niet bestellen),
  gewenste leverdatum + tijd, leveradres (default projectadres); versturen = REVISIE (r1, r2 …)
  met snapshot van de regels, delta t.o.v. de vorige revisie, PDF-bon en mail — append-only.
- Transport-item = levering (▲) of retour (▼) per project per dag met regels, leverancier en
  status gepland → bevestigd → geleverd (kantoor-klikwerk; de koppeling met het verhuursysteem
  landt later op dezelfde seam `zet_transport_status`); geannuleerd = met reden.
- Materiaalstand per project = Σ geleverd − Σ retour per product (alleen status 'geleverd'
  telt), huurperiode per item; m² geleverd = toetsbron naast gebouwde m² uit de weekstaten.
- Materiaalmatch (D6): inkoopfacturen van gekoppelde verhuur-crediteuren (`vendor_id` op de
  leverancier) getoetst tegen geregistreerde leveringen/huurperiodes — zelfde vlag-patroon als
  de uren-factuurmatch (afwijking = signaal + boeken mét expliciete bevestiging).

Alles administratie-gebonden mét RLS (patroon 0056); GRANT zonder DELETE behalve op de
concept-regels (JSONB op de bestelling) — niets verdwijnt stil, élke mutatie geauditeerd."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, Numeric, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base

M2_DELER = Decimal("4.6")  # steigerbouw-vuistregel uit de bestellijst: Σ(aantal × lengte) / 4,6


class TransportSoort(enum.StrEnum):
    LEVERING = "levering"
    RETOUR = "retour"


class TransportStatus(enum.StrEnum):
    """Statusflow her-enum 31-08 (mockup planning-werkopdracht-transport, besluit Peter):
    GERESERVEERD (rood, ontstaat bij slepen uit het werkbakje) → BEVESTIGD (oranje, mét
    verplichte voertuigtoezegging + mail aan het transport-contact) → DEFINITIEF (groen,
    materiaallijst + transportplanner ingevuld, lijst per mail aan het materiaal-contact)
    → GELEVERD (grijs, terminaal). GEPLAND is de pre-0091-legacywaarde en gedraagt zich
    overal als GERESERVEERD (de CHECK laat 'm toe; omzetting = app-stap, migratie is DDL)."""

    GERESERVEERD = "gereserveerd"
    BEVESTIGD = "bevestigd"
    DEFINITIEF = "definitief"
    GELEVERD = "geleverd"
    GEANNULEERD = "geannuleerd"
    GEPLAND = "gepland"  # legacy (pre-0091) — alias van GERESERVEERD


class TransportVoertuig(enum.StrEnum):
    """Voertuigtoezegging van het transport-contact bij het bevestigen (besluit Peter 31-08)."""

    COMBI = "combi"
    VOORWAGEN = "voorwagen"


class BestellingStatus(enum.StrEnum):
    CONCEPT = "concept"
    VERSTUURD = "verstuurd"
    GEANNULEERD = "geannuleerd"


class MateriaalmatchUitkomst(enum.StrEnum):
    MATCH = "match"
    AFWIJKING = "afwijking"
    NIET_TOETSBAAR = "niet_toetsbaar"


def _sql(enum_cls: type[enum.StrEnum]) -> str:
    return ", ".join(f"'{e.value}'" for e in enum_cls)


class MateriaalLeverancier(Base):
    __tablename__ = "materiaal_leverancier"
    __table_args__ = (
        UniqueConstraint("administratie_id", "naam", name="uq_materiaal_leverancier_naam"),
        Index("ix_materiaal_leverancier_administratie_id", "administratie_id"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    naam: Mapped[str]
    bestel_email: Mapped[str | None] = mapped_column(default=None)
    telefoon: Mapped[str | None] = mapped_column(default=None)
    adres: Mapped[str | None] = mapped_column(default=None)
    # Koppeling met de RLZ-crediteur (D6 factuurcontrole) — bewust geen FK naar vendor_cache.
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    # Twee contactpersonen (31-08, migratie 0091): transport-contact krijgt de bevestig-mail
    # ("transport gaat definitief door"), materiaal-contact de materiaallijst + delta-mails.
    transport_contact_naam: Mapped[str | None] = mapped_column(default=None)
    transport_contact_email: Mapped[str | None] = mapped_column(default=None)
    materiaal_contact_naam: Mapped[str | None] = mapped_column(default=None)
    materiaal_contact_email: Mapped[str | None] = mapped_column(default=None)
    actief: Mapped[bool] = mapped_column(default=True)
    bijgewerkt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    bijgewerkt_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class MateriaalCategorie(Base):
    __tablename__ = "materiaal_categorie"
    __table_args__ = (
        UniqueConstraint("leverancier_id", "naam", name="uq_materiaal_categorie_naam"),
        Index("ix_materiaal_categorie_administratie_id", "administratie_id"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    leverancier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.materiaal_leverancier.id")
    )
    naam: Mapped[str]
    # Bundel (mockup popup: "1 · Vierkante meter (bundel)" = steigermateriaal, "2 · Trappentoren").
    bundel: Mapped[str] = mapped_column(default="steiger")
    volgorde: Mapped[int] = mapped_column(default=0)
    actief: Mapped[bool] = mapped_column(default=True)


class MateriaalProduct(Base):
    __tablename__ = "materiaal_product"
    __table_args__ = (
        UniqueConstraint("leverancier_id", "naam", name="uq_materiaal_product_naam"),
        CheckConstraint("m2_lengte IS NULL OR m2_lengte >= 0", name="ck_materiaal_product_m2_lengte"),
        Index("ix_materiaal_product_administratie_id", "administratie_id"),
        Index("ix_materiaal_product_leverancier", "leverancier_id", "categorie_id", "volgorde"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    leverancier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.materiaal_leverancier.id")
    )
    categorie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.materiaal_categorie.id")
    )
    naam: Mapped[str]
    verpakking: Mapped[str | None] = mapped_column(default=None)  # "100 st." / "rol" / "p. st."
    eenheid: Mapped[str] = mapped_column(default="stuks")  # stuks | rol | m1 | m2
    # Bijdrage aan de m²-bundelformule: lengte in meter (Σ aantal × lengte / M2_DELER); NULL = telt niet.
    m2_lengte: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), default=None)
    volgorde: Mapped[int] = mapped_column(default=0)
    actief: Mapped[bool] = mapped_column(default=True)


class MateriaalBestelling(Base):
    """Bestelling per project × leverancier. `regels` = de CONCEPT-regels {product_id: aantal}
    (0/afwezig = niet bestellen); `revisie` = aantal verstuurde revisies (0 = nog nooit
    verstuurd). De verstuurde stand per revisie staat append-only in materiaal_bestelling_revisie."""

    __tablename__ = "materiaal_bestelling"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "administratie_id"],
            ["boekhouding.project_cache.id", "boekhouding.project_cache.administratie_id"],
            name="fk_materiaal_bestelling_project_cache",
        ),
        UniqueConstraint("administratie_id", "volgnummer", name="uq_materiaal_bestelling_volgnummer"),
        CheckConstraint(f"status IN ({_sql(BestellingStatus)})", name="ck_materiaal_bestelling_status"),
        CheckConstraint("revisie >= 0", name="ck_materiaal_bestelling_revisie"),
        CheckConstraint(
            "status <> 'geannuleerd' OR (annulering_reden IS NOT NULL AND length(btrim(annulering_reden)) > 0)",
            name="ck_materiaal_bestelling_annulering",
        ),
        Index("ix_materiaal_bestelling_administratie_id", "administratie_id"),
        Index("ix_materiaal_bestelling_project", "administratie_id", "project_id"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    leverancier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.materiaal_leverancier.id")
    )
    volgnummer: Mapped[int]
    status: Mapped[str] = mapped_column(default=BestellingStatus.CONCEPT.value)
    revisie: Mapped[int] = mapped_column(default=0)
    regels: Mapped[dict] = mapped_column(JSONB, default=dict)
    gewenste_leverdatum: Mapped[date | None] = mapped_column(default=None)
    gewenste_levertijd: Mapped[time | None] = mapped_column(default=None)
    leveradres: Mapped[str | None] = mapped_column(default=None)
    contactpersoon: Mapped[str | None] = mapped_column(default=None)
    opmerking: Mapped[str | None] = mapped_column(default=None)
    annulering_reden: Mapped[str | None] = mapped_column(default=None)
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    bijgewerkt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    bijgewerkt_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class MateriaalBestellingRevisie(Base):
    """Append-only: één rij per verzonden revisie (r1, r2 …) — snapshot van de regels, m²-som,
    delta t.o.v. de vorige revisie (alleen gewijzigde regels oud → nieuw), PDF-bon en het
    mailresultaat. Nooit gewijzigd ná aanmaak."""

    __tablename__ = "materiaal_bestelling_revisie"
    __table_args__ = (
        UniqueConstraint("bestelling_id", "revisie", name="uq_materiaal_bestelling_revisie"),
        CheckConstraint("mail_status IN ('verzonden', 'mislukt')", name="ck_materiaal_bestelling_revisie_mail"),
        Index("ix_materiaal_bestelling_revisie_administratie_id", "administratie_id"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    bestelling_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.materiaal_bestelling.id")
    )
    revisie: Mapped[int]
    regels: Mapped[dict] = mapped_column(JSONB)
    m2_totaal: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    delta: Mapped[list | None] = mapped_column(JSONB, default=None)
    gewenste_leverdatum: Mapped[date | None] = mapped_column(default=None)
    gewenste_levertijd: Mapped[time | None] = mapped_column(default=None)
    leveradres: Mapped[str | None] = mapped_column(default=None)
    pdf_opslag_pad: Mapped[str]
    verzonden_naar: Mapped[str]
    mail_status: Mapped[str]
    mail_fout: Mapped[str | None] = mapped_column(default=None)
    verstuurd_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    verstuurd_op: Mapped[datetime] = mapped_column(server_default=func.now())


class MateriaalTransport(Base):
    """Levering (▲) of retour (▼) per project per dag — het transport-weekgrid."""

    __tablename__ = "materiaal_transport"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "administratie_id"],
            ["boekhouding.project_cache.id", "boekhouding.project_cache.administratie_id"],
            name="fk_materiaal_transport_project_cache",
        ),
        CheckConstraint(f"soort IN ({_sql(TransportSoort)})", name="ck_materiaal_transport_soort"),
        CheckConstraint(f"status IN ({_sql(TransportStatus)})", name="ck_materiaal_transport_status"),
        CheckConstraint(
            "status <> 'geannuleerd' OR (status_reden IS NOT NULL AND length(btrim(status_reden)) > 0)",
            name="ck_materiaal_transport_annulering",
        ),
        CheckConstraint(
            f"voertuig IS NULL OR voertuig IN ({_sql(TransportVoertuig)})",
            name="ck_materiaal_transport_voertuig",
        ),
        Index("ix_materiaal_transport_administratie_id", "administratie_id"),
        Index("ix_materiaal_transport_datum", "administratie_id", "datum"),
        Index("ix_materiaal_transport_project", "administratie_id", "project_id", "datum"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    leverancier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.materiaal_leverancier.id")
    )
    bestelling_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.materiaal_bestelling.id"), default=None
    )
    soort: Mapped[str]
    datum: Mapped[date]
    tijdstip: Mapped[time | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(default=TransportStatus.GERESERVEERD.value)
    status_bron: Mapped[str] = mapped_column(default="kantoor")  # kantoor | verhuursysteem (later)
    status_reden: Mapped[str | None] = mapped_column(default=None)
    # Voertuigtoezegging van het transport-contact bij bevestigen (combi | voorwagen, 0091);
    # dag verschuiven wist 'm — de toezegging moet opnieuw (besluit Peter 31-08).
    voertuig: Mapped[str | None] = mapped_column(default=None)
    # Transportplanner, ingevuld bij definitief maken (vrije tekst, mockup "planner: De Jong").
    transportplanner: Mapped[str | None] = mapped_column(default=None)
    status_gewijzigd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    status_gewijzigd_op: Mapped[datetime | None] = mapped_column(default=None)
    regels: Mapped[dict] = mapped_column(JSONB, default=dict)  # {product_id: aantal}
    omschrijving: Mapped[str | None] = mapped_column(default=None)
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    bijgewerkt_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Materiaalmatch(Base):
    """Eén materiaalmatch per inkoopfactuur-document van een gekoppelde verhuur-crediteur (D6):
    factuurregels (omschrijving + hoeveelheid uit het veldvoorstel) vs. verwacht = aantal ×
    huurperiode per item uit de geregistreerde leveringen. Zelfde vlag-patroon als factuurmatch
    (afwijking = signaal; boeken mét expliciete bevestiging, persistent op de rij)."""

    __tablename__ = "materiaalmatch"
    __table_args__ = (
        CheckConstraint(f"uitkomst IN ({_sql(MateriaalmatchUitkomst)})", name="ck_materiaalmatch_uitkomst"),
        CheckConstraint(
            "(afwijking_bevestigd_door IS NULL) = (afwijking_bevestigd_op IS NULL)",
            name="ck_materiaalmatch_bevestigd_samen",
        ),
        Index("ix_materiaalmatch_administratie_id", "administratie_id"),
        Index("ix_materiaalmatch_administratie_uitkomst", "administratie_id", "uitkomst"),
        {"schema": "boekhouding"},
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.document.id"), primary_key=True
    )
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    leverancier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.materiaal_leverancier.id")
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    uitkomst: Mapped[str]
    aantal_regels_getoetst: Mapped[int] = mapped_column(default=0)
    aantal_regels_afwijkend: Mapped[int] = mapped_column(default=0)
    aantal_regels_onbekend: Mapped[int] = mapped_column(default=0)
    details: Mapped[dict | None] = mapped_column(JSONB, default=None)
    berekend_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    afwijking_bevestigd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    afwijking_bevestigd_op: Mapped[datetime | None] = mapped_column(default=None)
