from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, MetaData, SmallInteger, func
from sqlalchemy.dialects.postgresql import BYTEA, ENUM, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(schema="platform")


class GebruikerRol(enum.StrEnum):
    """Rolmodel (CLAUDE.md): Beheerder / Boekhouding+Projecten / Boekhouding / Klant-accordeur
    (scope: eigen administratie). Beheerder is platform-breed (geen scope nodig, zie
    gebruiker_administratie + platform.current_actor_is_beheerder())."""

    BEHEERDER = "beheerder"
    BOEKHOUDING_PROJECTEN = "boekhouding_projecten"
    BOEKHOUDING = "boekhouding"
    KLANT_ACCORDEUR = "klant_accordeur"


class GebruikerStatus(enum.StrEnum):
    """Statusmachine: uitgenodigd -> (wachtwoord gezet) -> wacht_op_totp -> (TOTP bevestigd) ->
    actief. geblokkeerd is een aparte eindstatus, door een Beheerder gezet (niet in deze fase
    geautomatiseerd)."""

    UITGENODIGD = "uitgenodigd"
    WACHT_OP_TOTP = "wacht_op_totp"
    ACTIEF = "actief"
    GEBLOKKEERD = "geblokkeerd"


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
    """RLZ-administratie (tenant-scope). Vastgoed- en kantoorklant-administraties gemengd."""

    __tablename__ = "administratie"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    naam: Mapped[str]
    rlz_admin_id: Mapped[str] = mapped_column(unique=True)
    actief: Mapped[bool] = mapped_column(default=True)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())


class Gebruiker(Base):
    """Platform-gebruiker. Bevat PII (naam, e-mail) — bewust gescheiden van financiële data,
    die uitsluitend in het `boekhouding`-schema leeft. AVG-verwijderverzoek = `gepseudonimiseerd_op`
    zetten (nooit hard verwijderen), pas na relatie-einde + 7 jaar fiscale bewaarplicht.
    """

    __tablename__ = "gebruiker"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    naam: Mapped[str]
    e_mail: Mapped[str] = mapped_column(unique=True)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    gepseudonimiseerd_op: Mapped[datetime | None] = mapped_column(default=None)

    # Auth (migratie 0002). wachtwoord_hash is NULL tot de accept-flow een wachtwoord zet.
    wachtwoord_hash: Mapped[str | None] = mapped_column(default=None)
    rol: Mapped[GebruikerRol] = mapped_column(_GEBRUIKER_ROL_ENUM)
    status: Mapped[GebruikerStatus] = mapped_column(_GEBRUIKER_STATUS_ENUM, default=GebruikerStatus.UITGENODIGD)


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


class Uitnodiging(Base):
    """Eenmalige uitnodigingslink (72u geldig). Alleen `token_hash` wordt opgeslagen — het
    plaintext-token gaat naar de gebruiker (e-mail, buiten scope van deze migratie) en is daarna
    nergens anders herleidbaar dan via de hash."""

    __tablename__ = "uitnodiging"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    gebruiker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    token_hash: Mapped[str] = mapped_column(unique=True)
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    verloopt_op: Mapped[datetime]
    gebruikt_op: Mapped[datetime | None] = mapped_column(default=None)


class RefreshToken(Base):
    """Server-side vastlegging van uitgegeven refresh-tokens (Auth-0010-b punt 1, Platform/
    OPEN_ITEMS.md) — maakt intrekken en hergebruik-detectie mogelijk, wat een stateless JWT niet
    kan. Alleen `token_hash` wordt opgeslagen (zelfde patroon als Uitnodiging.token_hash).
    `gebruikt_op` markeert een geroteerd (verbruikt) token; `ingetrokken_op` markeert expliciete
    intrekking (bv. hergebruik-detectie trekt alle actieve tokens van de gebruiker in).
    `voorganger_id` legt de rotatieketen vast voor traceerbaarheid, niet functioneel vereist voor
    de hergebruik-check zelf (die leunt op gebruikt_op/ingetrokken_op)."""

    __tablename__ = "refresh_token"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    gebruiker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    token_hash: Mapped[str] = mapped_column(unique=True)
    voorganger_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.refresh_token.id"), default=None
    )
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    verloopt_op: Mapped[datetime]
    gebruikt_op: Mapped[datetime | None] = mapped_column(default=None)
    ingetrokken_op: Mapped[datetime | None] = mapped_column(default=None)


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
    laatste_stap: Mapped[int | None] = mapped_column(default=None)
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


class AuditEvent(Base):
    """Uniform, append-only audit-schema (koppelcontract v1.5, platformbrede afspraken) —
    bron voor de WORM-export. UPDATE/DELETE zijn niet gegrant aan de app-rol (zie migratie 0001).
    """

    __tablename__ = "audit_event"

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
