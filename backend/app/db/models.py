from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, MetaData, func
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
