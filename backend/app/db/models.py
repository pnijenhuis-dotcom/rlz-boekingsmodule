from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, MetaData, SmallInteger, func
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
    geautomatiseerd). wacht_op_passkey (migratie 0040) is de accordeur-variant van
    wacht_op_totp: de accordeur-activeringsflow vervangt de TOTP-stap door passkey-registratie
    (de passkey ís de tweede factor op het apparaat — besluit auth-cadans 2026-08-11)."""

    UITGENODIGD = "uitgenodigd"
    WACHT_OP_TOTP = "wacht_op_totp"
    WACHT_OP_PASSKEY = "wacht_op_passkey"
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
    actief: Mapped[bool] = mapped_column(default=True)
    boeken_ingeschakeld: Mapped[bool] = mapped_column(default=False)
    project_verplicht: Mapped[bool] = mapped_column(default=False)
    ai_extractie_ingeschakeld: Mapped[bool] = mapped_column(default=False)
    is_vastgoed: Mapped[bool] = mapped_column(default=False)
    # Opt-in voor de volautomatische bankstappen (migratie 0026): vaste regels automatisch
    # direct-op-grootboek boeken tijdens de bank-sync — default UIT, werkt bovenop de
    # boeken-failsafes (boeken_ingeschakeld + globale kill switch, die blijven onverkort gelden).
    bank_autoboeken_ingeschakeld: Mapped[bool] = mapped_column(default=False)
    # Klant-accorderingsflow (migratie 0033, mockup #autorisatie): optioneel per administratie,
    # default UIT. Aan = de boekknop wordt "Ter accordering" en direct boeken is server-side
    # geblokkeerd tot alle vereiste lagen akkoord zijn (app/accordering/service.py).
    accordering_ingeschakeld: Mapped[bool] = mapped_column(default=False)
    # Tier-vlag (migratie 0037, platformbesluit 0018 + koppelcontract §3 v1.11): het
    # `factuur_afgeletterd`-event wordt uitsluitend aangemaakt voor administraties met deze
    # vlag (tier-model optie 2: Vastly + boekingsmodule) — aparte kolom naast is_vastgoed,
    # default UIT; activatie wacht op vastgoeds verwerker.
    afgeletterd_event_ingeschakeld: Mapped[bool] = mapped_column(default=False)
    eigenaar_gebruiker_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
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

    gebruiker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), primary_key=True
    )
    entiteit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
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
