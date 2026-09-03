from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import BYTEA, ENUM, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(schema="platform")

    # Representatie-drift-fix (hygiëne-run 2026-08-16): de migraties schrijven TEXT en
    # timestamptz, maar kale Mapped[str]/Mapped[datetime] leidde tot VARCHAR/TIMESTAMP-zonder-
    # tijdzone in Base.metadata — waardoor `alembic check`/autogenerate op élke kolom aansloeg
    # en geen signaalwaarde had (GCP_UITROL "LES metadata-guard"). Deze map maakt de modellen
    # de DDL-representatie ín, zonder één functionele schemawijziging.
    type_annotation_map = {
        str: Text(),
        datetime: DateTime(timezone=True),
    }


class GebruikerRol(enum.StrEnum):
    """Rolmodel (CLAUDE.md): Beheerder / Boekhouding+Projecten / Boekhouding / Klant-accordeur
    (scope: eigen administratie). Beheerder is platform-breed (geen scope nodig, zie
    gebruiker_administratie + platform.current_actor_is_beheerder()).

    Veldrollen uren & meerwerk (migratie 0056, BOUW GO Peter 2026-08-21): ZZP'er / uitvoerder /
    detacheerder — externe app-rollen op de 0040-lijn (zelfde passkey-auth en 7-dagen-cadans
    als de klant-accordeur, zie app/auth/rollen.py). De detacheerder vult weekstaten in namens
    de ZZP'ers die het kantoor aan hem koppelt (DetacheerderKoppeling)."""

    BEHEERDER = "beheerder"
    BOEKHOUDING_PROJECTEN = "boekhouding_projecten"
    BOEKHOUDING = "boekhouding"
    KLANT_ACCORDEUR = "klant_accordeur"
    ZZPER = "zzper"
    UITVOERDER = "uitvoerder"
    DETACHEERDER = "detacheerder"


class GebruikerStatus(enum.StrEnum):
    """Statusmachine: uitgenodigd -> (wachtwoord gezet) -> wacht_op_totp -> (TOTP bevestigd) ->
    actief. geblokkeerd is een aparte eindstatus, door een Beheerder gezet (niet in deze fase
    geautomatiseerd). wacht_op_passkey (migratie 0040) is de accordeur-variant van
    wacht_op_totp: de accordeur-activeringsflow vervangt de TOTP-stap door passkey-registratie
    (de passkey ís de tweede factor op het apparaat — besluit auth-cadans 2026-08-11).
    gearchiveerd (migratie 0075, feedbackronde 26-08 punt 1) is de tweede beheer-eindstatus
    naast geblokkeerd: uit alle default-lijsten, toegang dicht, niets verwijderd — dearchiveren
    zet de status van vóór archivering terug."""

    UITGENODIGD = "uitgenodigd"
    WACHT_OP_TOTP = "wacht_op_totp"
    WACHT_OP_PASSKEY = "wacht_op_passkey"
    ACTIEF = "actief"
    GEBLOKKEERD = "geblokkeerd"
    GEARCHIVEERD = "gearchiveerd"


def _enum_values(python_enum: type[enum.StrEnum]) -> list[str]:
    return [member.value for member in python_enum]


_GEBRUIKER_ROL_ENUM = ENUM(
    GebruikerRol,
    name="gebruiker_rol",
    schema="platform",
    create_type=False,
    values_callable=_enum_values,
)
_GEBRUIKER_STATUS_ENUM = ENUM(
    GebruikerStatus,
    name="gebruiker_status",
    schema="platform",
    create_type=False,
    values_callable=_enum_values,
)


class Administratie(Base):
    """RLZ-administratie (tenant-scope). Vastgoed- en kantoorklant-administraties gemengd.
    `boeken_ingeschakeld` is de per-administratie boeken-failsafe (migratie 0008, CLAUDE.md
    "Automatisch boeken = opt-in"): default UIT, alleen een Beheerder kan 'm aanzetten. Boeken
    is bovendien ook nog onderhevig aan de globale kill switch (zie BoekenInstelling).
    `project_verplicht` (migratie 0010) bepaalt of de Project-kolom in het controlescherm
    zichtbaar én verplicht/blokkerend is — default UIT.
    `ai_extractie_ingeschakeld` (migratie 0014) is de AVG-gate voor AI-extractie: alleen bij AAN
    gaan PDF's van deze administratie naar de Claude API — default UIT; tot de AVG-volgorde rond
    is (DPA + EU-verwerking + verwerkersregister, docs/BOUWPLAN.md) alleen aan voor de
    test-administratie/eigen facturen.
    `is_vastgoed` (migratie 0018) markeert een vastgoed-administratie: alleen díé krijgen bij
    "geboekt" een webhook-outbox-rij (koppelcontract §3) — default UIT, expliciet zetten.
    `eigenaar_gebruiker_id` (migratie 0021, mockup Instellingen "Eigenaar (krijgt vragen)") is de
    default-toewijzing voor nieuwe vragen over documenten van deze administratie — nullable: geen
    eigenaar betekent dat vraag stellen een expliciete toewijzing vereist (zichtbare fout, geen
    stille default)."""

    __tablename__ = "administratie"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    naam: Mapped[str]
    rlz_admin_id: Mapped[str] = mapped_column(unique=True)
    # `actief` = niet gearchiveerd (v2 30-08): archiveren zet 'm op false; álle RLZ-rakende jobs en de
    # UI-lijsten filteren erop. Archiveringsspoor (0089, 0075-patroon) hieronder.
    actief: Mapped[bool] = mapped_column(default=True)
    gearchiveerd_op: Mapped[datetime | None] = mapped_column(default=None)
    gearchiveerd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    # Defaults voor NIEUWE administraties (besluit Peter 29-08, mockup instellingen-administraties-v2):
    # boeken + AI-extractie AAN — bestaande rijen behouden hun waarde (geen DB-default, geen backfill).
    boeken_ingeschakeld: Mapped[bool] = mapped_column(default=True)
    # Terugkerende-facturen-signaal (0090): drempel prijsstijging in %, default 10 (Beheerder-instelbaar).
    terugkerend_prijsstijging_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("10.00"), server_default="10.00"
    )
    project_verplicht: Mapped[bool] = mapped_column(default=False)
    ai_extractie_ingeschakeld: Mapped[bool] = mapped_column(default=True)
    is_vastgoed: Mapped[bool] = mapped_column(default=False)
    # Opt-in voor de volautomatische bankstappen (migratie 0026): vaste regels automatisch
    # direct-op-grootboek boeken tijdens de bank-sync — default UIT, werkt bovenop de
    # boeken-failsafes (boeken_ingeschakeld + globale kill switch, die blijven onverkort gelden).
    bank_autoboeken_ingeschakeld: Mapped[bool] = mapped_column(default=False)
    # Autoboek-opt-in voor VASTLY-VERKOOP-documenten (migratie 0051, besluit Peter 2026-08-15,
    # automatisering-first): ná intake + deterministische verwerking boekt een verkoopfactuur
    # automatisch, uitsluitend wanneer álles groen is (app/verkoop/autoboeken.py). Default UIT;
    # aanzetten kan alleen voor is_vastgoed-administraties (beheer-service dwingt dat af) en de
    # boeken-failsafes (boeken_ingeschakeld + globale kill switch + volumerem) gelden onverkort.
    verkoop_autoboeken_ingeschakeld: Mapped[bool] = mapped_column(default=False)
    # Omzet-autoboeken (GO Peter 01-09, migratie 0096): kassarapporten automatisch boeken als álles
    # groen is — opt-in per administratie, default UIT, Beheerder-only (app/omzet/autoboeken.py).
    omzet_autoboeken_ingeschakeld: Mapped[bool] = mapped_column(default=False, server_default="false")
    # Klant-accorderingsflow (migratie 0033, mockup #autorisatie): optioneel per administratie,
    # default UIT. Aan = de boekknop wordt "Ter accordering" en direct boeken is server-side
    # geblokkeerd tot alle vereiste lagen akkoord zijn (app/accordering/service.py).
    accordering_ingeschakeld: Mapped[bool] = mapped_column(default=False)
    # Tier-vlag (migratie 0037, platformbesluit 0018 + koppelcontract §3 v1.11): het
    # `factuur_afgeletterd`-event wordt uitsluitend aangemaakt voor administraties met deze
    # vlag (tier-model optie 2: Vastly + boekingsmodule) — aparte kolom naast is_vastgoed,
    # default UIT; activatie wacht op vastgoeds verwerker.
    afgeletterd_event_ingeschakeld: Mapped[bool] = mapped_column(default=False)
    # Doorbelasting-toggle (migratie 0044, besluit Peter 2026-08-13): de actie "Doorbelasten…"
    # bestaat alleen op BRON-administraties met deze vlag aan (default UIT; in de praktijk
    # alleen Kempen Facilities). De doel-kant heeft geen vlag nodig: doorbelasten náár een
    # administratie wordt afgedwongen via de mapping-whitelist (doorbelasting_mapping).
    doorbelasting_ingeschakeld: Mapped[bool] = mapped_column(default=False)
    # Uren & meerwerk (migratie 0056, BOUW GO Peter 2026-08-21): steigerbouw-specifieke tak,
    # opt-in per administratie — alleen Universal initieel. Uit = geen weekstaten/meerwerk voor
    # deze administratie (server-side afgedwongen in app/uren/service.py), default UIT.
    uren_meerwerk_ingeschakeld: Mapped[bool] = mapped_column(default=False)
    # Afdelingen (migratie 0084, bouwrun 28-08 blok A, project_verplicht-patroon): AAN = afdeling
    # verplicht op élk inkoopdocument (blokkerende check) + accorderingsroute per afdeling; UIT =
    # veld onzichtbaar. Beheerder-only; aanzetten maakt de terugval-afdeling "Algemeen" aan.
    afdelingen_ingeschakeld: Mapped[bool] = mapped_column(default=False, server_default="false")
    # Facturatiemodule niet afgenomen (migratie 0093, spoedopdracht 01-09 blok A, casus A.Y.
    # Holding 2 + Abbegaa): sommige RLZ-administraties hebben de facturatie-/verkoopmodule niet —
    # SalesInvoices geeft dan 403 ongeacht de rechten. De rechten-probe zet/wist dit kenmerk
    # (uitsluitend op SalesInvoices "403"/"ok", credentialstore.sla_probe_op, audit oud→nieuw);
    # verkoop-rakende LEESroutes (voorraad-RLZ-uitstroom, SalesInvoices in de projectcijfers-sync)
    # slaan de administratie zichtbaar over — nooit stil op de 403 laten stuklopen.
    verkoopmodule_afwezig: Mapped[bool] = mapped_column(default=False, server_default="false")
    # Boekhoud-backend (migratie 0101, Platform-besluit 0016, Odoo-adapter fase 1 03-09): 'rlz' | 'odoo'.
    # UITSLUITEND de routeringssleutel voor de adapter-registry (app/backends/registry.py) — het
    # domein vertakt hier nooit op (guardrail 0016). Default 'rlz'; bestaande rijen ongemoeid. Een
    # Odoo-administratie draagt in `rlz_admin_id` een sentinel (app/odoo/ids.py::odoo_admin_sentinel)
    # zodat élke RLZ-client-resolutie er fail-loud op stukloopt (app/rlz/credentials.py).
    boekhoud_backend: Mapped[str] = mapped_column(String(16), default="rlz", server_default="rlz")
    # Voorraad bijhouden (migratie 0086, bouwrun 28-08 blok D): opt-in voor de voorraad-aansluiting
    # (controle-laag in het mi-schema; nooit RLZ-writes). Beheerder-only, default UIT — aan voor
    # Universal Verkoop pas op Peters klik.
    voorraad_ingeschakeld: Mapped[bool] = mapped_column(default=False, server_default="false")
    # Signaal >N uur per dag (steigerbouw-run blok A6, migratie 0072): som van de ingediende uren
    # per persoon per kalenderdag over álle weekstaten heen boven deze drempel = oranje vlag bij
    # de keuring + zichtbaar voor kantoor. Geen blokkade. Default 12, per administratie instelbaar.
    uren_dagmax_uren: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=Decimal("12"), server_default="12")
    eigenaar_gebruiker_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    # Reconciliatie-uitsluiting (migratie 0043, besluit Peter 2026-08-12): deze administratie
    # telt niet mee in de EXIT-CODE van de dagelijkse reconciliaties. Bewust géén filter op het
    # rapport zelf — de bevindingen blijven zichtbaar onder de markering UITGESLOTEN, anders
    # wordt een echte fout in bv. de test-administratie (waar schrijftests op draaien) onzichtbaar.
    # Reden is verplicht zodra de vlag aan staat (DB-CHECK), mét actor en moment.
    reconciliatie_uitgesloten: Mapped[bool] = mapped_column(default=False)
    reconciliatie_uitsluiting_reden: Mapped[str | None] = mapped_column(default=None)
    reconciliatie_uitgesloten_op: Mapped[datetime | None] = mapped_column(default=None)
    reconciliatie_uitgesloten_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())


class Gebruiker(Base):
    """Platform-gebruiker. Bevat PII (naam, e-mail) — bewust gescheiden van financiële data,
    die uitsluitend in het `boekhouding`-schema leeft. AVG-verwijderverzoek = `gepseudonimiseerd_op`
    zetten (nooit hard verwijderen), pas na relatie-einde + 7 jaar fiscale bewaarplicht.
    """

    __tablename__ = "gebruiker"
    # E-mail altijd in de genormaliseerde (lowercase) vorm — migratie 0049. De CHECK maakt de
    # bestaande unique-index dé index op de genormaliseerde vorm en laat een schrijfpad dat
    # app.auth.normalisatie vergeet hard falen i.p.v. stil een case-gevoelig account maken.
    __table_args__ = (
        CheckConstraint("e_mail = lower(e_mail)", name="ck_gebruiker_e_mail_lowercase"),
        {
            "comment": "PII van platformgebruikers. Bevat nooit financiële velden — die leven "
            "uitsluitend in het boekhouding-schema."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    naam: Mapped[str]
    e_mail: Mapped[str] = mapped_column(unique=True)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    gepseudonimiseerd_op: Mapped[datetime | None] = mapped_column(default=None)

    # Auth (migratie 0002). wachtwoord_hash is NULL tot de accept-flow een wachtwoord zet.
    wachtwoord_hash: Mapped[str | None] = mapped_column(default=None)
    rol: Mapped[GebruikerRol] = mapped_column(_GEBRUIKER_ROL_ENUM)
    status: Mapped[GebruikerStatus] = mapped_column(_GEBRUIKER_STATUS_ENUM, default=GebruikerStatus.UITGENODIGD)

    # Blokkade (migratie 0052, beheer-mini 2026-08-16). status_voor_blokkade bewaart de status
    # van vóór de blokkade zodat heractiveren een half-geactiveerde gebruiker exact daarheen
    # terugzet — nooit naar 'actief' zonder credentials.
    geblokkeerd_op: Mapped[datetime | None] = mapped_column(default=None)
    geblokkeerd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    status_voor_blokkade: Mapped[str | None] = mapped_column(default=None)

    # Archivering (migratie 0075, feedbackronde 26-08 punt 1) — spiegel van de blokkade:
    # status_voor_archivering bewaart de status van vóór archivering (óók 'geblokkeerd').
    gearchiveerd_op: Mapped[datetime | None] = mapped_column(default=None)
    gearchiveerd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    status_voor_archivering: Mapped[str | None] = mapped_column(default=None)
    # Maandagochtend-digest kantoor (D2, 01-09, migratie 0097): opt-out per gebruiker (default mee).
    digest_opt_out: Mapped[bool] = mapped_column(default=False, server_default="false")


class GebruikerAdministratie(Base):
    """Scope-koppeltabel (CLAUDE.md, hard): klanten-scope per medewerker. Administratie-gebonden
    tabel — RLS verplicht (registers/conventies.md, geen uitzonderingen), zie migratie 0002.
    Elke insert/delete wordt automatisch geaudit door een DB-trigger (platform.current_actor_id()
    moet gezet zijn — anders faalt de trigger hard, zie migratie 0002)."""

    __tablename__ = "gebruiker_administratie"

    gebruiker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), primary_key=True
    )
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), primary_key=True
    )
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())


class GebruikerModuleRol(Base):
    """Rol per gebruiker per module (platformbesluit 0019 "Identiteit gedeeld, autorisatie per
    module", migratie 0034). Rol is TEXT met een CHECK per module — bewust géén gedeelde enum;
    module 'vastgoed' kent superadmin/eigenaar/kantoor. RLZ's eigen `Gebruiker.rol`-enum blijft
    staan tot de convergentie (besluit 0019 punt 4). Mutaties: RLS dwingt op DB-niveau af dat
    alleen een module-beheerder schrijft en nooit op zijn eigen gebruiker_id; audit-trigger op
    elke mutatie (hard falen zonder actor). Bootstrap van de eerste module-beheerder loopt via
    de migratie-eigenaar (RLS ENABLE, niet FORCE — zie migratie 0034)."""

    __tablename__ = "gebruiker_module_rol"

    gebruiker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), primary_key=True
    )
    module: Mapped[str] = mapped_column(primary_key=True)
    rol: Mapped[str]
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())


class GebruikerEntiteit(Base):
    """Scope-koppeltabel vastgoed-eigendom (besluit 0019, migratie 0034) — analoog aan
    GebruikerAdministratie. `entiteit_id` bewust zonder FK: vastgoed-entiteiten leven in de
    vastgoed-database, niet in het platform-schema. RLS: eigen rijen lezen of
    vastgoed-module-beheerder; muteren alleen module-beheerder en nooit de eigen scope."""

    __tablename__ = "gebruiker_entiteit"
    __table_args__ = (Index("ix_gebruiker_entiteit_entiteit_id", "entiteit_id"),)

    gebruiker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), primary_key=True
    )
    entiteit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())


class DetacheerderKoppeling(Base):
    """Koppeltabel detacheerder↔ZZP'er (migratie 0056, besluit Peter 2026-08-21): de
    detacheerder vult weekstaten in NAMENS de hieraan gekoppelde ZZP'ers — exact dezelfde
    schermen en velden als de ZZP'er zelf, elke invoer vastgelegd als "ingevuld door X namens
    Y". Persoonsniveau (niet administratie-gebonden) — analoog aan GebruikerEntiteit in het
    platform-schema. RLS: de detacheerder leest zijn eigen rijen, muteren is Beheerder-only
    (0019-lijn); elke mutatie via de service in het audit_event.

    `uurtarief` (migratie 0057, besluit Peter 2026-08-21): het bureau-tarief voor déze ZZP'er —
    het HOOFDMECHANISME van de bureaufactuurmatch (bureaus factureren per ZZP'er verschillende
    tarieven; bedragcontrole = som over de goedgekeurde staten van uren × dit tarief). NULL =
    "geen tarief bekend": de match valt terug op alleen uren (oranje, geen blokkade)."""

    __tablename__ = "detacheerder_koppeling"
    __table_args__ = (
        CheckConstraint("uurtarief IS NULL OR uurtarief >= 0", name="ck_detacheerder_koppeling_uurtarief"),
        Index("ix_detacheerder_koppeling_zzper", "zzper_gebruiker_id"),
    )

    detacheerder_gebruiker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), primary_key=True
    )
    zzper_gebruiker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), primary_key=True
    )
    uurtarief: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), default=None)
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())


class UitnodigingSoort(enum.StrEnum):
    """`uitnodiging` = activatielink voor een nieuw account (wachtwoord + tweede factor
    inrichten); `wachtwoord_herstel` (migratie 0068, feedbackronde 25-08 punt 7) = eenmalige
    herstel-link voor een al geactiveerde EXTERNE gebruiker (accordeur/veldwerker) die zijn
    wachtwoord kwijt is: nieuw wachtwoord zetten + direct door naar apparaat-registratie, status
    en bestaande passkeys blijven staan. Tekstkolom + CHECK, geen PG-enum (zelfde
    soort-patroon als elders in het platform)."""

    UITNODIGING = "uitnodiging"
    WACHTWOORD_HERSTEL = "wachtwoord_herstel"


class Uitnodiging(Base):
    """Eenmalige uitnodigings- óf herstel-link (72u geldig, `soort`). Alleen `token_hash` wordt
    opgeslagen — het plaintext-token gaat naar de gebruiker (e-mail) en is daarna nergens anders
    herleidbaar dan via de hash."""

    __tablename__ = "uitnodiging"
    __table_args__ = (
        Index("ix_uitnodiging_gebruiker_id", "gebruiker_id"),
        CheckConstraint("soort IN ('uitnodiging', 'wachtwoord_herstel')", name="ck_uitnodiging_soort"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    gebruiker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    token_hash: Mapped[str] = mapped_column(unique=True)
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    verloopt_op: Mapped[datetime]
    gebruikt_op: Mapped[datetime | None] = mapped_column(default=None)
    soort: Mapped[str] = mapped_column(
        Text, default=UitnodigingSoort.UITNODIGING.value, server_default=UitnodigingSoort.UITNODIGING.value
    )
    # Atomaire activatie externe rollen (migratie 0083, besluit 28-08): de wachtwoordstap parkeert
    # de hash hier; pas de geslaagde passkey-registratie zet 'm op de gebruiker en verbruikt de
    # link. Kantoor-rollen gebruiken dit veld niet.
    wachtwoord_hash_in_wacht: Mapped[str | None] = mapped_column(Text, default=None)


class RefreshToken(Base):
    """Server-side vastlegging van uitgegeven refresh-tokens (Auth-0010-b punt 1, Platform/
    OPEN_ITEMS.md) — maakt intrekken en hergebruik-detectie mogelijk, wat een stateless JWT niet
    kan. Alleen `token_hash` wordt opgeslagen (zelfde patroon als Uitnodiging.token_hash).
    `gebruikt_op` markeert een geroteerd (verbruikt) token; `ingetrokken_op` markeert expliciete
    intrekking (bv. hergebruik-detectie trekt alle actieve tokens van de gebruiker in).
    `voorganger_id` legt de rotatieketen vast voor traceerbaarheid, niet functioneel vereist voor
    de hergebruik-check zelf (die leunt op gebruikt_op/ingetrokken_op)."""

    __tablename__ = "refresh_token"
    __table_args__ = (
        Index("ix_refresh_token_gebruiker_id", "gebruiker_id"),
        Index("ix_refresh_token_apparaat_id", "apparaat_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    gebruiker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    token_hash: Mapped[str] = mapped_column(unique=True)
    voorganger_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.refresh_token.id"), default=None
    )
    # Device-binding (migratie 0040, accordeur-cadans): sessie hoort bij dit geregistreerde
    # apparaat; de kill-switch trekt credential + alle gebonden tokens in. NULL = geen
    # apparaatbinding (kantoor-login met TOTP).
    apparaat_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.webauthn_credential.id"), default=None
    )
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    verloopt_op: Mapped[datetime]
    gebruikt_op: Mapped[datetime | None] = mapped_column(default=None)
    ingetrokken_op: Mapped[datetime | None] = mapped_column(default=None)


class WebauthnCredential(Base):
    """Passkey per GEBRUIKER+APPARAAT (migratie 0040, besluit auth-cadans 2026-08-11): de
    publieke sleutel van een geregistreerd apparaat. Draagt de nieuw/onbekend-apparaat-detectie
    (geen actieve credential = volledige login + registratie) én de kantoor-kill-switch
    (`ingetrokken_op` — trekt samen met de gebonden refresh-tokens de toegang van precies dit
    apparaat in). `is_dev_stub` markeert de expliciete dev-fallback (auth_biometrie_dev_stub,
    alleen buiten productie — WebAuthn vereist https/localhost, dus een LAN-IP-kliktest kan
    geen echte passkey registreren)."""

    __tablename__ = "webauthn_credential"
    __table_args__ = (Index("ix_webauthn_credential_gebruiker_id", "gebruiker_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    gebruiker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    credential_id: Mapped[bytes] = mapped_column(BYTEA, unique=True)
    public_key: Mapped[bytes] = mapped_column(BYTEA)
    sign_count: Mapped[int] = mapped_column(BigInteger, default=0)
    aaguid: Mapped[str | None] = mapped_column(default=None)
    transports: Mapped[dict | list | None] = mapped_column(JSONB, default=None)
    apparaat_naam: Mapped[str | None] = mapped_column(default=None)
    is_dev_stub: Mapped[bool] = mapped_column(default=False)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    laatst_gebruikt_op: Mapped[datetime | None] = mapped_column(default=None)
    ingetrokken_op: Mapped[datetime | None] = mapped_column(default=None)
    ingetrokken_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )


class WebauthnChallenge(Base):
    """Eénmalige server-side WebAuthn-challenge (registratie of assertie) — de client krijgt de
    challenge in de options en moet 'm ondertekend terugbrengen; na gebruik wordt de rij
    verbrand (`gebruikt_op`), nooit hergebruikt (replay-bescherming)."""

    __tablename__ = "webauthn_challenge"
    __table_args__ = (Index("ix_webauthn_challenge_gebruiker_id", "gebruiker_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    gebruiker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    soort: Mapped[str]
    challenge: Mapped[bytes] = mapped_column(BYTEA)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    verloopt_op: Mapped[datetime]
    gebruikt_op: Mapped[datetime | None] = mapped_column(default=None)


class AccordeurAkkoord(Base):
    """Vastlegging voorwaarden + privacyverklaring-akkoord in de accordeur-activeringsflow
    (docs/avg/05-activatie-checklist.md bijlage A — informatielaag, géén AVG-vervanging).
    Append-only: wie/wanneer/tekstversie; een nieuwe tekstversie vraagt een nieuw akkoord.
    Zonder akkoord op de actuele tekstversie geen toegang tot de accordeer-wachtrij
    (server-side afgedwongen in app/accordering/router.py)."""

    __tablename__ = "accordeur_akkoord"
    __table_args__ = (UniqueConstraint("gebruiker_id", "tekst_versie", name="uq_accordeur_akkoord_versie"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    gebruiker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    tekst_versie: Mapped[str]
    akkoord_op: Mapped[datetime] = mapped_column(server_default=func.now())


class TotpSecret(Base):
    """TOTP-secret, versleuteld at rest (envelope encryption — zie app/security/envelope.py).
    `bevestigd_op` is NULL tot de eerste succesvolle verificatie (activatie-gate); daarna gezet
    en nooit meer teruggezet. `laatste_stap` is het TOTP-tijdvenster van de laatst geaccepteerde
    code — replay-bescherming (zie app/security/totp.py)."""

    __tablename__ = "totp_secret"

    gebruiker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), primary_key=True
    )
    secret_ciphertext: Mapped[bytes] = mapped_column(BYTEA)
    wrapped_data_key: Mapped[bytes] = mapped_column(BYTEA)
    laatste_stap: Mapped[int | None] = mapped_column(BigInteger, default=None)
    bevestigd_op: Mapped[datetime | None] = mapped_column(default=None)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())


class Grootboekrekening(Base):
    """Gedeelde platform-tabel (koppelcontract §2c, v1.8): RLZ-sync is de enige schrijver, vastgoed
    leest read-only (GRANT SELECT + RLS, geen eigen Reeleezee-scope/tweede client — zie migratie
    0005). `soort` is Reeleezee's AccountType ONVERTAALD doorgezet (1=opbrengsten, 2=kosten,
    3=activa, 4=passiva — geverifieerd tegen de officiële AccountTypeEnum-documentatie, zie
    Platform/contracten/KOPPELCONTRACT_RLZ_VASTGOED.md §2c). `verdwenen_uit_bron_op` is GEEN
    RLZ-brongegeven maar een sync-afleiding: de nachtelijke/on-demand sync zet dit op een rij
    zodra hij niet meer in de meest recente `GET Ledgers`-respons voorkomt (nooit hard
    verwijderen; komt hij terug, gaat de kolom terug naar NULL)."""

    __tablename__ = "grootboekrekening"
    __table_args__ = (Index("ix_grootboekrekening_administratie_id", "administratie_id"),)

    ledger_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), primary_key=True
    )
    code: Mapped[str]
    naam: Mapped[str]
    soort: Mapped[int] = mapped_column(SmallInteger)
    is_totaalrekening: Mapped[bool]
    laatst_gesynchroniseerd: Mapped[datetime] = mapped_column(server_default=func.now())
    verdwenen_uit_bron_op: Mapped[datetime | None] = mapped_column(default=None)


class RlzCredential(Base):
    """Credential-store voor RLZ-webservice-logins per administratie (besluit 0001: credential-
    store is gedeeld platform-fundament). Wachtwoord versleuteld at rest via hetzelfde envelope-
    patroon als TotpSecret (app/security/envelope.py) — geen tweede encryptie-implementatie.
    Schrijf-only vanaf de API-kant: het wachtwoord komt nooit terug in een response of log
    (besluit 0012) — deze kolommen worden uitsluitend intern uitgepakt om een RlzClient te
    bouwen. Eén credential-set per administratie (administratie_id is de PK, geen los id)."""

    __tablename__ = "rlz_credential"

    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), primary_key=True
    )
    webservice_username: Mapped[str]
    wachtwoord_ciphertext: Mapped[bytes] = mapped_column(BYTEA)
    wrapped_data_key: Mapped[bytes] = mapped_column(BYTEA)
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    bijgewerkt_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class RlzRechtenProbe(Base):
    """Laatste rechten-probe-resultaat per administratie (koppel-flow onboarding): welke
    read-only endpoints een webservice-login daadwerkelijk mag aanspreken. Overschrijft bij elke
    nieuwe probe (geen historie hier — die staat al in audit_event via de actie
    'rechten_probe_uitgevoerd'). `rapport` is endpoint -> 'ok' | HTTP-statuscode-string."""

    __tablename__ = "rlz_rechten_probe"

    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), primary_key=True
    )
    rapport: Mapped[dict] = mapped_column(JSONB)
    uitgevoerd_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    uitgevoerd_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class BoekenInstelling(Base):
    """Globale boeken-kill switch (migratie 0008, CLAUDE.md-failsafe (a)): Beheerder-only,
    singleton (precies één rij, afgedwongen door de CHECK op `singleton`). Werkt AANVULLEND op
    Administratie.boeken_ingeschakeld — boeken kan alleen als BEIDE aan staan; deze schakelaar is
    de snelle, platformbrede noodstop die niet per administratie afzonderlijk omgezet hoeft te
    worden."""

    __tablename__ = "boeken_instelling"

    singleton: Mapped[bool] = mapped_column(primary_key=True, default=True)
    globaal_ingeschakeld: Mapped[bool] = mapped_column(default=True)
    gewijzigd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    gewijzigd_op: Mapped[datetime] = mapped_column(server_default=func.now())


class WebhookInstelling(Base):
    """Webhook-aflevering-toggle (migratie 0025): Beheerder-only singleton, parallel aan
    BoekenInstelling maar met default UIT — de vastgoed-ontvanger bestaat nog niet, dus
    outbox-rijen blijven openstaand totdat aflevering expliciet aangezet wordt. Werkt AANVULLEND
    op de config-failsafe (geen doel-URL/secret = geen aflevering, geen fout)."""

    __tablename__ = "webhook_instelling"

    singleton: Mapped[bool] = mapped_column(primary_key=True, default=True)
    aflevering_ingeschakeld: Mapped[bool] = mapped_column(default=False)
    gewijzigd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    gewijzigd_op: Mapped[datetime] = mapped_column(server_default=func.now())


class IntakeInstelling(Base):
    """Intake-AI-toggle (migratie 0029): Beheerder-only singleton, zelfde patroon als
    WebhookInstelling — default UIT (AVG-gate: zonder opt-in gaat er geen intake-byte naar de
    Claude API). De env-setting `intake_ai_ingeschakeld` is uitsluitend fallback als deze rij
    ontbreekt (zie beheer/service.py::intake_ai_effectief_ingeschakeld)."""

    __tablename__ = "intake_instelling"

    singleton: Mapped[bool] = mapped_column(primary_key=True, default=True)
    ai_ingeschakeld: Mapped[bool] = mapped_column(default=False)
    gewijzigd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    gewijzigd_op: Mapped[datetime] = mapped_column(server_default=func.now())


class AiGebruik(Base):
    """AI-kostenmeter (besluit Peter 2026-08-14, migratie 0047): append-only log van élke
    Anthropic-aanroep, met de wérkelijke token-usage uit de API-response (input/output/cache) en
    de in code berekende kosten (gepinde prijstabel × gepinde USD→EUR-koers — "code voor cijfers",
    geen schattingen). UPDATE/DELETE zijn niet gegrant aan de app-rol (zelfde patroon als
    audit_event).

    `maand` = eerste dag van de kalendermaand in Europe/Amsterdam, in code bepaald bij het
    schrijven (app/aikosten/service.py) — de maandcumulatie en de harde poort draaien op deze
    kolom, nooit op een timezone-berekening in SQL. `document_id`/`intake_bericht_id` zijn bewust
    FK-loze referenties: platform (fundament) wijst niet hard naar de boekhouding-laag."""

    __tablename__ = "ai_gebruik"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tijdstip: Mapped[datetime] = mapped_column(server_default=func.now())
    maand: Mapped[date] = mapped_column(index=True)
    # Bewust String (VARCHAR): zo staan ze in migratie 0047 — de enige twee niet-TEXT
    # tekstkolommen; expliciet gepind zodat de type_annotation_map (str -> Text) ze niet raakt.
    model: Mapped[str] = mapped_column(String())
    bron: Mapped[str] = mapped_column(String())
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    intake_bericht_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    input_tokens: Mapped[int] = mapped_column(BigInteger)
    output_tokens: Mapped[int] = mapped_column(BigInteger)
    cache_schrijf_tokens: Mapped[int] = mapped_column(BigInteger)
    cache_lees_tokens: Mapped[int] = mapped_column(BigInteger)
    kosten_eur: Mapped[Decimal] = mapped_column(Numeric(12, 6))


class AiKostenInstelling(Base):
    """Maandlimiet AI-kosten (migratie 0047): Beheerder-only singleton, zelfde patroon als
    IntakeInstelling. Default € 100/kalendermaand (besluit Peter 2026-08-14); de env-setting
    `ai_kosten_maandlimiet_eur` is uitsluitend fallback als deze rij ontbreekt."""

    __tablename__ = "ai_kosten_instelling"

    singleton: Mapped[bool] = mapped_column(primary_key=True, default=True)
    maandlimiet_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("100"))
    gewijzigd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    gewijzigd_op: Mapped[datetime] = mapped_column(server_default=func.now())


class AiKostenMaandstatus(Base):
    """Eenmaligheid van de kostenmeldingen per kalendermaand (migratie 0047): de 80%-waarschuwing
    en de limiet-bereikt-melding worden elk hoogstens één keer per maand gezet (tijdstip = wanneer
    de drempel voor het eerst werd geraakt); een nieuwe maand begint blanco."""

    __tablename__ = "ai_kosten_maandstatus"

    maand: Mapped[date] = mapped_column(primary_key=True)
    waarschuwing_80_op: Mapped[datetime | None] = mapped_column(default=None)
    limiet_bereikt_op: Mapped[datetime | None] = mapped_column(default=None)


class AuditEvent(Base):
    """Uniform, append-only audit-schema (koppelcontract v1.5, platformbrede afspraken) —
    bron voor de WORM-export. UPDATE/DELETE zijn niet gegrant aan de app-rol (zie migratie 0001).
    """

    __tablename__ = "audit_event"
    __table_args__ = (
        Index("ix_audit_event_administratie_id", "administratie_id"),
        Index("ix_audit_event_tabel_record", "tabel", "record_id"),
        Index("ix_audit_event_correlatie_id", "correlatie_id"),
        Index("ix_audit_event_tijdstip", "tijdstip"),
        {
            "comment": "Append-only audit-log (bron voor de WORM-export). UPDATE/DELETE zijn niet "
            "gegrant aan de app-rol — zie GRANTs onderaan deze migratie."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tijdstip: Mapped[datetime] = mapped_column(server_default=func.now())
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    module: Mapped[str]
    tabel: Mapped[str]
    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    actie: Mapped[str]
    oude_waarde: Mapped[dict | None] = mapped_column(JSONB, default=None)
    nieuwe_waarde: Mapped[dict | None] = mapped_column(JSONB, default=None)
    correlatie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    administratie_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), default=None
    )
