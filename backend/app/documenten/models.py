from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, func, text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class DocumentBron(enum.StrEnum):
    """Intake-kanaal. EMAIL is nog niet gebouwd (fase 3, e-mail-intake) maar hoort al in de
    statusmachine/het schema thuis — 'niet_toegewezen' (zie DocumentStatus) is primair voor die
    flow bedoeld."""

    UPLOAD = "upload"
    EMAIL = "email"


class DocumentSoort(enum.StrEnum):
    """Documentsoort-discriminator (migratie 0027): een kassarapport doorloopt dezelfde
    statusmachine en werkvoorraad als een inkoopfactuur, maar krijgt de rapport-extractie
    (app/extractie/rapport.py) en het omzetreview-scherm (mockup #omzetreview) i.p.v. de
    inkoopflow. In de DB TEXT + CHECK — geen PG-enum, zodat een later derde soort geen
    ALTER TYPE nodig heeft (zelfde overweging als vraag.status, migratie 0022)."""

    INKOOPFACTUUR = "inkoopfactuur"
    KASSARAPPORT = "kassarapport"
    # VASTLY-WAARBORG-bericht (§2d-waarborgroute v1.11, migratie 0039): geen factuurstuk maar
    # een klein deterministisch XML-bericht; boekt als ManualJournal op de balansrekening.
    WAARBORG = "waarborg"
    # §2d (koppelcontract): Vastly-verkoopfactuur uit de e-mail-intake (UBL-markering
    # VASTLY-VERKOOP) — de omzetkant boekt 'm als SalesInvoice (migratie 0028).
    VERKOOPFACTUUR = "verkoopfactuur"


class DocumentStatus(enum.StrEnum):
    """Hoofdpad: ontvangen -> extractie_bezig -> te_controleren -> klaar_om_te_boeken -> geboekt.
    Grote documenten (async extractie, migratie 0016): ontvangen -> extractie_wachtrij ->
    extractie_bezig -> ... — de wachtrij-status betekent "staat klaar voor de achtergrondworker",
    de upload-request keert dan direct terug.
    Zijtakken: vraag_open (blokkeert boeken), afgewezen (verplichte reden, blijft zichtbaar,
    heropenen herstelt de herkomst — zie Afwijzing),
    boeken_mislukt (RLZ-fout, retry mogelijk), niet_toegewezen (verzamelbak — geen administratie
    gekoppeld, zie Document.administratie_id), handmatig_afmaken (migratie 0015, waarborg
    projectadministratie: AI-extractie kreeg de regelset niet aantoonbaar compleet bij een
    administratie met projectplicht — er is bewust GEEN veldvoorstel opgeslagen, de controleur
    vult alles handmatig in of probeert de extractie opnieuw), verwijderd (soft-delete,
    design-pass taak 4: bewust géén harde delete — "niets verdwijnt stil" — bestand en record
    blijven bestaan, alleen geboekte documenten kunnen hier nooit naartoe vanwege de
    bewaarplicht). Toegestane overgangen: zie app/documenten/statusmachine.py — nooit hier of
    elders losse status-writes."""

    ONTVANGEN = "ontvangen"
    EXTRACTIE_WACHTRIJ = "extractie_wachtrij"
    EXTRACTIE_BEZIG = "extractie_bezig"
    TE_CONTROLEREN = "te_controleren"
    KLAAR_OM_TE_BOEKEN = "klaar_om_te_boeken"
    GEBOEKT = "geboekt"
    VRAAG_OPEN = "vraag_open"
    AFGEWEZEN = "afgewezen"
    BOEKEN_MISLUKT = "boeken_mislukt"
    NIET_TOEGEWEZEN = "niet_toegewezen"
    HANDMATIG_AFMAKEN = "handmatig_afmaken"
    # Vier-ogen-accordering van een afwijkend IBAN (migratie 0024, docs/ontwerp/
    # iban-wissel-accordering.md): boeken geblokkeerd tot een accordeur ≠ aanvrager besluit.
    WACHT_OP_IBAN_ACCORDERING = "wacht_op_iban_accordering"
    # Klant-accorderingsflow (migratie 0033, mockup #autorisatie): "Bij klant" — het document
    # wacht op één of meer accorderingslagen; ná het laatste akkoord boekt de motor automatisch
    # mét alle harde checks opnieuw (app/accordering/service.py).
    TER_ACCORDERING = "ter_accordering"
    VERWIJDERD = "verwijderd"
    # E-mail-intake (migratie 0028): terminale status van een bron-PDF waarvan de bevestigde
    # multi-factuur-splitsing kind-documenten heeft opgeleverd — het origineel blijft bestaan
    # en terugvindbaar, de kinderen doorlopen elk de normale flow.
    GESPLITST = "gesplitst"


def _enum_waarden(python_enum: type[enum.StrEnum]) -> list[str]:
    return [member.value for member in python_enum]


_DOCUMENT_BRON_ENUM = ENUM(
    DocumentBron, name="document_bron", schema="boekhouding", create_type=False, values_callable=_enum_waarden
)
_DOCUMENT_STATUS_ENUM = ENUM(
    DocumentStatus, name="document_status", schema="boekhouding", create_type=False, values_callable=_enum_waarden
)


class Document(Base):
    """Eén binnengekomen document (fundament van de werkvoorraad). `administratie_id` is NULL
    voor 'niet_toegewezen' documenten (verzamelbak, zie CLAUDE.md) — zelfde RLS-patroon als
    platform.audit_event: platformbrede rijen (NULL) zijn zichtbaar ongeacht scope, geen
    uitzondering op RLS zelf. `mogelijk_duplicaat_van_id` is een losse vlag, geen statusmachine-
    tak: het document doorloopt gewoon de normale flow, met dit signaal erbovenop voor de
    controleur (zie mockup: chip 'Mogelijk duplicaat van ... — beoordelen')."""

    __tablename__ = "document"
    __table_args__ = (
        Index("ix_document_administratie_id", "administratie_id"),
        Index("ix_document_administratie_hash", "administratie_id", "sha256_hash"),
        Index("ix_document_status", "status"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    administratie_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), default=None
    )
    bron: Mapped[DocumentBron] = mapped_column(_DOCUMENT_BRON_ENUM)
    # TEXT met CHECK (migratie 0027), waarden uit DocumentSoort — zie die docstring.
    soort: Mapped[str] = mapped_column(default=DocumentSoort.INKOOPFACTUUR.value)
    bestandsnaam: Mapped[str]
    sha256_hash: Mapped[str]
    status: Mapped[DocumentStatus] = mapped_column(_DOCUMENT_STATUS_ENUM, default=DocumentStatus.ONTVANGEN)
    toegewezen_aan: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    mogelijk_duplicaat_van_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.document.id"), default=None
    )
    opslag_pad: Mapped[str]
    # E-mail-intake-herkomst (migratie 0028): welk bericht, wie mailde (afzender = hint) en de
    # gelezen tenaamstelling (leidend voor toewijzing). De suggestie-velden dragen de beste
    # niet-eenduidige match voor de verzamelbak-UI — een suggestie, nooit een stille toewijzing.
    intake_bericht_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.intake_bericht.id"), default=None
    )
    afzender_hint: Mapped[str | None] = mapped_column(default=None)
    tenaamstelling: Mapped[str | None] = mapped_column(default=None)
    toewijzing_suggestie_administratie_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), default=None
    )
    toewijzing_suggestie_bron: Mapped[str | None] = mapped_column(default=None)
    # Splitsing-kind: verwijzing naar het bron-document (paginabereik in de tijdlijn).
    gesplitst_uit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.document.id"), default=None
    )
    # Origineel brondocument (migratie 0070, feedbackronde 25-08 deel 3 punt 2): een afbeelding
    # (JPEG/PNG/HEIC) wordt bij binnenkomst naar PDF omgezet — opslag_pad/bestandsnaam zijn dan
    # de PDF, deze drie kolommen het aangeleverde origineel. NULL = het bestand ís het origineel.
    bron_opslag_pad: Mapped[str | None] = mapped_column(default=None)
    bron_bestandsnaam: Mapped[str | None] = mapped_column(default=None)
    bron_content_type: Mapped[str | None] = mapped_column(default=None)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    laatst_gewijzigd_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class DocumentGebeurtenis(Base):
    """Append-only tijdlijn (voedt de mockup-tijdlijn: binnenkomst -> extractie -> vraag ->
    accordering -> boeking). `van_status` is NULL voor de allereerste gebeurtenis (aanmaak).
    `actor_id` is bewust verplicht: een menselijke handeling draagt de gebruiker, een
    achtergrondstap draagt de vaste systeem-actor (app/db/systeem_actor.py, migratie 0016) —
    nooit NULL, nooit de mens die de achtergrondtaak toevallig triggerde."""

    __tablename__ = "document_gebeurtenis"
    __table_args__ = (
        Index("ix_document_gebeurtenis_document_id", "document_id"),
        Index("ix_document_gebeurtenis_tijdstip", "tijdstip"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("boekhouding.document.id"))
    van_status: Mapped[DocumentStatus | None] = mapped_column(_DOCUMENT_STATUS_ENUM, default=None)
    naar_status: Mapped[DocumentStatus] = mapped_column(_DOCUMENT_STATUS_ENUM)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    detail: Mapped[dict | None] = mapped_column(JSONB, default=None)
    tijdstip: Mapped[datetime] = mapped_column(server_default=func.now())


class Boekvoorstel(Base):
    """Kopgegevens van het controlescherm-boekvoorstel (migratie 0008) — één per document. Alle
    velden zijn nullable in de DB (een half ingevuld voorstel mag bewaard worden terwijl de
    controleur nog aan het werk is); de harde checks (app/documenten/checks.py) bepalen of het
    voorstel al *boekbaar* is, niet het schema. `vendor_id`/`ledger_id`/`taxrate_id`/`project_id`
    zijn RLZ-GUID's (Vendor/Ledger/TaxRate/Project) — bewust geen FK naar de eigen caches (die
    zijn per-administratie samengestelde PK's en puur read-side, geen brondata om op te FK'en).
    `rlz_boekstuknummer` is RLZ's `ReceiptNumber` (geverifieerd: al gezet bij de PUT, niet pas na
    boeken — zie verkenning/api-verkenning.md), leeg totdat de eerste PUT gelukt is."""

    __tablename__ = "boekvoorstel"
    __table_args__ = {"schema": "boekhouding"}

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.document.id"), primary_key=True
    )
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    referentie: Mapped[str | None] = mapped_column(default=None)
    factuurdatum: Mapped[date | None] = mapped_column(default=None)
    # Vervaldatum (C1 26-08, migratie 0078): kopveld uit de scan (zelfde herkomst-chip), gaat als
    # `DueDate` mee naar RLZ (live bewezen — anders leidt RLZ 'm af uit Date + PaymentDueDays).
    vervaldatum: Mapped[date | None] = mapped_column(default=None)
    totaalbedrag: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    # Afdeling (migratie 0084, blok A 28-08): handmatige kantoorkeuze per document zodra de
    # administratie-toggle aan staat; stuurt de accorderingsroute en is de MI-dimensie voor later.
    afdeling_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.afdeling.id"), default=None
    )
    rlz_boekstuknummer: Mapped[str | None] = mapped_column(default=None)
    # Tegenboek-pad (migratie 0061): 0 = de oorspronkelijke boeking; elke "tegenboeken én
    # opnieuw boeken" verhoogt de cyclus. Bepaalt het RLZ-client-GUID van de (her)boeking
    # (rlz_ids.rlz_herboeking_id) — een herboeking mag NOOIT het GUID van het origineel
    # hergebruiken (her-PUT zou de DocumentLineList van het origineel vervangen).
    boek_cyclus: Mapped[int] = mapped_column(server_default=text("0"), default=0)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    bijgewerkt_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class BoekvoorstelRegel(Base):
    """Eén boekingsregel binnen een Boekvoorstel. `volgnummer` bepaalt de weergave-/PUT-volgorde
    (geen betekenis in RLZ zelf, puur voor een stabiele, voorspelbare regelvolgorde in het
    controlescherm en de RLZ-PUT)."""

    __tablename__ = "boekvoorstel_regel"
    __table_args__ = (
        Index("ix_boekvoorstel_regel_document_id", "document_id"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.boekvoorstel.document_id")
    )
    volgnummer: Mapped[int]
    ledger_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    taxrate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    netto_bedrag: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    btw_bedrag: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    omschrijving: Mapped[str | None] = mapped_column(default=None)


class LeverancierVoorkeur(Base):
    """Weergave-/boekvoorkeur per crediteur per administratie (migratie 0017, fix 3 2026-07-10):
    onthoudt of de controleur de factuurregels van deze leverancier samengevoegd (één
    boekingsregel) of gesplitst wil zien — mockup: "standaard aan · keuze wordt per leverancier
    onthouden". Bewust geen FK naar vendor_cache (de voorkeur overleeft een sync-verdwijning);
    bij projectplicht wordt deze voorkeur genegeerd én nooit op samenvoegen gezet
    (app/documenten/boekvoorstel.py — project per regel is daar hard)."""

    __tablename__ = "leverancier_voorkeur"
    __table_args__ = {"schema": "boekhouding"}

    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), primary_key=True
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    regels_samenvoegen: Mapped[bool]
    # Autoboeken-opt-in per leverancier (migratie 0036, CLAUDE.md-poort "vereist vóór het
    # eerste autoboeken van inkoopfacturen"): default UIT, alleen door een Beheerder te
    # wijzigen, elke wijziging in audit_event. De harde checks + failsafes blijven bij het
    # automatisch boeken onverkort blokkerend (app/documenten/autoboeken.py).
    autoboeken_ingeschakeld: Mapped[bool] = mapped_column(default=False)
    gewijzigd_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class LeverancierIbanBron(enum.StrEnum):
    """Hoe een IBAN in de vertrouwde set kwam (migratie 0019): RLZ_SEED = uit RLZ's
    Vendors/{id}/BankRelations; BASELINE = eerste factuur-IBAN van een crediteur zonder seed
    (vastgelegd, ter bevestiging getoond, niet blokkerend); BEVESTIGD = door een mens bevestigd
    na een wissel-blokkade (bevestigd_door verplicht)."""

    RLZ_SEED = "rlz_seed"
    BASELINE = "baseline"
    BEVESTIGD = "bevestigd"


class LeverancierIban(Base):
    """Vertrouwde IBAN's per crediteur per administratie (migratie 0019) — de vergelijkingsbasis
    van de IBAN-wissel-fraudecontrole (app/documenten/checks.py::check_iban_wissel). Meerwaardig
    per crediteur: meerdere bevestigde rekeningen (G-rekening/WKA) is de norm, geen
    wissel-signaal. Bewust geen FK naar vendor_cache (overleeft sync-verdwijning, zelfde
    overweging als LeverancierVoorkeur). Elke toevoeging krijgt een audit_event — zie
    app/documenten/leverancier_iban.py."""

    __tablename__ = "leverancier_iban"
    __table_args__ = {"schema": "boekhouding"}

    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), primary_key=True
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    iban: Mapped[str] = mapped_column(primary_key=True)
    bron: Mapped[str]
    bevestigd_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())


class CrediteurKenmerk(Base):
    """Btw-nummer (primair) + KvK-nummer (secundair) per crediteur per administratie (migratie 0082,
    opruimrun 28-08 punt 14). Gevuld uit de factuur-extractie zodra de controleur het boekvoorstel
    mét die crediteur opslaat (bron 'factuur'); KvK kan óók uit RLZ komen (vendor_cache.brondata
    `ChamberOfCommerceNumber`, bron 'rlz' — alleen als lees-fallback, niet gekopieerd). Bewust geen
    FK naar vendor_cache (overleeft sync-verdwijning, zelfde overweging als LeverancierIban). Voedt de
    nummer-eerst crediteur-match, de duplicaatcheck over crediteuren heen en de dubbel-signalering."""

    __tablename__ = "crediteur_kenmerk"
    __table_args__ = (
        Index("ix_crediteur_kenmerk_btw", "administratie_id", "btw_nummer"),
        Index("ix_crediteur_kenmerk_kvk", "administratie_id", "kvk_nummer"),
        CheckConstraint(
            "btw_nummer_bron IS NULL OR btw_nummer_bron IN ('factuur', 'handmatig')",
            name="ck_crediteur_kenmerk_btw_bron",
        ),
        CheckConstraint(
            "kvk_nummer_bron IS NULL OR kvk_nummer_bron IN ('factuur', 'rlz', 'handmatig')",
            name="ck_crediteur_kenmerk_kvk_bron",
        ),
        {"schema": "boekhouding"},
    )

    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), primary_key=True
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    btw_nummer: Mapped[str | None] = mapped_column(default=None)
    btw_nummer_geverifieerd: Mapped[bool | None] = mapped_column(default=None)
    btw_nummer_bron: Mapped[str | None] = mapped_column(default=None)
    kvk_nummer: Mapped[str | None] = mapped_column(default=None)
    kvk_nummer_bron: Mapped[str | None] = mapped_column(default=None)
    laatst_uit_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    bijgewerkt_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    bijgewerkt_op: Mapped[datetime] = mapped_column(server_default=func.now())


class VraagStatus(enum.StrEnum):
    """Levenscyclus van een vraag (migratie 0022): OPEN blokkeert het boeken van het document
    (DocumentStatus.VRAAG_OPEN); BEANTWOORD en INGETROKKEN zijn eindtoestanden — een vraag wordt
    nooit verwijderd, ook niet na boeken (historie, mockup #vragen: "Beantwoord & geboekt").
    INGETROKKEN (bewuste uitbreiding op de mockup, zie docs/BESLISSINGEN.md) voorkomt dat een per
    ongeluk gestelde vraag een pro-forma nep-antwoord afdwingt."""

    OPEN = "open"
    # LEGACY (vóór migratie 0064): het oude één-antwoord-model. Bestaande rijen blijven staan; de
    # servicelaag toont het oude antwoord als laatste bericht van de thread. Nieuwe vragen komen
    # hier nooit meer in.
    BEANTWOORD = "beantwoord"
    INGETROKKEN = "ingetrokken"
    # Eindstatus sinds de dialoog (besluit Peter 25-08, migratie 0064): alleen de oorspronkelijke
    # vraagsteller sluit de thread; pas dán gaat het document terug naar de herkomst-status.
    AFGEHANDELD = "afgehandeld"


class Vraag(Base):
    """Eén vraag over een document (vragenworkflow, mockup #vragen + #vraagmodal). Precies één
    open vraag per document tegelijk (partiële unique index, migratie 0022); eerdere beantwoorde
    of ingetrokken vragen blijven als historie staan. `toegewezen_aan` default naar de
    administratie-eigenaar (Administratie.eigenaar_gebruiker_id), overschrijfbaar binnen de scope
    van de administratie — zie app/documenten/vragen.py. `status_voor_vraag` is de document-
    status van vóór de vraag: beantwoorden/intrekken herstellen exact díé herkomst (nooit
    hardgecodeerd te_controleren). De antwoord- en intrek-velden zijn per CHECK-constraint
    gebonden aan de status."""

    __tablename__ = "vraag"
    __table_args__ = (
        Index(
            "vraag_een_open_per_document",
            "document_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("boekhouding.document.id"))
    gesteld_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    gesteld_op: Mapped[datetime] = mapped_column(server_default=func.now())
    vraag_tekst: Mapped[str]
    toegewezen_aan: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    # TEXT met CHECK, niet de document_status-PG-enum (zie migratie 0022 voor het waarom);
    # app/documenten/vragen.py vertaalt van/naar DocumentStatus.
    status_voor_vraag: Mapped[str]
    status: Mapped[str] = mapped_column(default=VraagStatus.OPEN.value)
    antwoord_tekst: Mapped[str | None] = mapped_column(default=None)
    beantwoord_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    beantwoord_op: Mapped[datetime | None] = mapped_column(default=None)
    ingetrokken_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    ingetrokken_op: Mapped[datetime | None] = mapped_column(default=None)
    ingetrokken_reden: Mapped[str | None] = mapped_column(default=None)
    # Dialoog (migratie 0064): wie er in de thread aan zet is — de bestaande melding
    # (Document.toegewezen_aan, werkvoorraad-kolom "Toegewezen") volgt dit veld. NULL op rijen
    # van vóór 0064 = toegewezen_aan (schema-only migratie; zie vragen.py::_aan_de_beurt).
    aan_de_beurt: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    afgehandeld_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    afgehandeld_op: Mapped[datetime | None] = mapped_column(default=None)
    # Vragen aan de klant-accordeur (blok B5 26-08, migratie 0079): wanneer de beurt voor het
    # laatst wisselde en tot welke beurt de accordeur gemeld is — samen de idempotentie van de
    # push-anders-mail-melding (stille uren: de 10-min-job vangt uitgestelde meldingen op).
    aan_de_beurt_sinds: Mapped[datetime | None] = mapped_column(default=None)
    accordeur_gemeld_op: Mapped[datetime | None] = mapped_column(default=None)


class VraagBericht(Base):
    """Eén bijdrage in de vraag-dialoog (migratie 0064, besluit Peter 25-08): append-only — de
    app-rol heeft alleen SELECT + INSERT, een bericht wordt nooit herschreven of verwijderd
    (kernprincipe 4). De openingsvraag zelf staat in Vraag.vraag_tekst; elk antwoord/vervolg is
    een rij hier, mét auteur en tijdstip."""

    __tablename__ = "vraag_bericht"
    __table_args__ = (
        Index("ix_vraag_bericht_vraag_id", "vraag_id"),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    vraag_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("boekhouding.vraag.id"))
    auteur_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    tekst: Mapped[str]
    geplaatst_op: Mapped[datetime] = mapped_column(server_default=func.now())


class AfwijzingStatus(enum.StrEnum):
    """Levenscyclus van een afwijzing (migratie 0023): OPEN hoort bij een document met
    DocumentStatus.AFGEWEZEN ("Afgewezen — ter controle", blijft zichtbaar in de werkvoorraad,
    boeken geblokkeerd); HEROPEND is de eindtoestand na de heropenen-actie — een afwijzing wordt
    nooit verwijderd, de historie blijft staan (zelfde principe als Vraag)."""

    OPEN = "open"
    HEROPEND = "heropend"


class Afwijzing(Base):
    """Eén afwijzing van een document (CLAUDE.md "Afwijzen = verplichte reden, blijft zichtbaar",
    mockup #afwijsmodal). Precies één open afwijzing per document tegelijk (partiële unique
    index, migratie 0023); eerdere heropende afwijzingen blijven als historie staan. `reden` is
    verplicht (ook op DB-niveau: CHECK niet-leeg). `toegewezen_aan` = "Ter controle naar" uit de
    mockup-modal, default de administratie-eigenaar — zelfde patroon en scope-afdwinging als
    Vraag (app/documenten/afwijzen.py). `status_voor_afwijzing` is de document-status van vóór
    de afwijzing: heropenen herstelt exact díé herkomst (zelfde status_voor_*-patroon als
    Vraag.status_voor_vraag)."""

    __tablename__ = "afwijzing"
    __table_args__ = (
        Index(
            "afwijzing_een_open_per_document",
            "document_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("boekhouding.document.id"))
    afgewezen_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    afgewezen_op: Mapped[datetime] = mapped_column(server_default=func.now())
    reden: Mapped[str]
    toegewezen_aan: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    # TEXT met CHECK, niet de document_status-PG-enum — zelfde overweging als Vraag (migratie
    # 0022); app/documenten/afwijzen.py vertaalt van/naar DocumentStatus.
    status_voor_afwijzing: Mapped[str]
    status: Mapped[str] = mapped_column(default=AfwijzingStatus.OPEN.value)
    heropend_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    heropend_op: Mapped[datetime | None] = mapped_column(default=None)


class IbanAccorderingStatus(enum.StrEnum):
    """Levenscyclus van een IBAN-accordering (migratie 0024): OPEN hoort bij een document op
    DocumentStatus.WACHT_OP_IBAN_ACCORDERING; GEACCORDEERD en AFGEWEZEN zijn eindtoestanden —
    een accordering wordt nooit verwijderd (append-only historie, zelfde principe als
    Vraag/Afwijzing). Na een afwijzing blijft het document geblokkeerd; een nieuwe aanvraag
    (nieuwe rij) is de enige weg vooruit."""

    OPEN = "open"
    GEACCORDEERD = "geaccordeerd"
    AFGEWEZEN = "afgewezen"


class IbanSoort(enum.StrEnum):
    """Aard van de aangeboden rekening, opgegeven door de aanvrager — context voor het
    vier-ogen-besluit (G-rekening/WKA is in de bouwketen de norm-casus). De bevestiging zelf
    maakt de rekening vertrouwd; de vertrouwde set kent geen aparte G-rekening-klasse."""

    REGULIER = "regulier"
    G_REKENING = "g_rekening"


class IbanAccordeur(Base):
    """Instelling per administratie "IBAN-wissel accorderen door" (docs/ontwerp/
    iban-wissel-accordering.md): de set medewerkers die een aangeboden IBAN-wissel mag
    accorderen of afwijzen. Lege set → actieve beheerders. Wijzigen is Beheerder-only
    (router-dependency) met audit_event."""

    __tablename__ = "iban_accordeur"
    __table_args__ = {"schema": "boekhouding"}

    administratie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), primary_key=True
    )
    gebruiker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), primary_key=True
    )
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())


class IbanAccordering(Base):
    """Eén vier-ogen-accordering van een afwijkend IBAN (migratie 0024). Precies één open
    accordering per document (partiële unique index); besliste accorderingen blijven als
    historie staan. `status_voor_accordering` is de document-status van vóór het aanbieden:
    accorderen herstelt exact díé herkomst (zelfde status_voor_*-patroon als
    Vraag/Afwijzing). Vier-ogen: besloten_door ≠ aangevraagd_door, server-side afgedwongen in
    app/documenten/iban_accordering.py én met een DB-CHECK."""

    __tablename__ = "iban_accordering"
    __table_args__ = (
        Index(
            "iban_accordering_een_open_per_document",
            "document_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("boekhouding.document.id"))
    nieuw_iban: Mapped[str]
    soort: Mapped[str]
    aangevraagd_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangevraagd_op: Mapped[datetime] = mapped_column(server_default=func.now())
    # TEXT met CHECK, niet de document_status-PG-enum — zelfde overweging als Vraag/Afwijzing
    # (migratie 0022: ALTER TYPE ... ADD VALUE-beperking).
    status_voor_accordering: Mapped[str]
    status: Mapped[str] = mapped_column(default=IbanAccorderingStatus.OPEN.value)
    besloten_door: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"), default=None
    )
    besloten_op: Mapped[datetime | None] = mapped_column(default=None)
    afwijs_reden: Mapped[str | None] = mapped_column(default=None)


class TegenboekingSoort(enum.StrEnum):
    """Mockup tegenboek-mockup.html (akkoord Peter 22-08): `volledig` = de boeking hoort er
    helemaal niet te zijn (saldo-effect nul, document blijft GEBOEKT mét chip TEGENGEBOEKT);
    `vervang` = tegenboeken én opnieuw boeken (document terug naar te_controleren, boek_cyclus
    +1 — de herboeking krijgt een eigen RLZ-GUID en een duplicaat-uitzondering)."""

    VOLLEDIG = "volledig"
    VERVANG = "vervang"


_TEGENBOEKING_SOORT_SQL = ", ".join(f"'{s.value}'" for s in TegenboekingSoort)


class Tegenboeking(Base):
    """Tegenboeking van een geboekte inkoopfactuur (migratie 0061, mockup tegenboek-mockup.html):
    een NIEUWE PurchaseInvoice in RLZ met gespiegelde negatieve regels op dezelfde Entity,
    boekdatum vandaag — de route wanneer storno door de aangifte-poort geblokkeerd is (STAP-0
    "Tegenboek-pad" 22-08: btw telt als negatieve voorbelasting mee in de eerstvolgende open
    aangifte; besluit Peter 22-08: géén suppletie-signaal). Eén rij per (document, boek_cyclus);
    append-only (geen UPDATE/DELETE-grant) — terugdraaien van een tegenboeking is een
    RLZ-UI-handeling (actie 19), nooit een app-mutatie."""

    __tablename__ = "tegenboeking"
    __table_args__ = (
        CheckConstraint(f"soort IN ({_TEGENBOEKING_SOORT_SQL})", name="ck_tegenboeking_soort"),
        CheckConstraint("length(btrim(reden)) >= 5", name="ck_tegenboeking_reden"),
        Index("ix_tegenboeking_administratie_id", "administratie_id"),
        {"schema": "boekhouding"},
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.document.id"), primary_key=True
    )
    # De boek_cyclus van het origineel dat deze rij tegenboekt (boekvoorstel.boek_cyclus op het
    # moment van tegenboeken) — de kruisverwijzing beide kanten: origineel → tegenboeking via
    # (document_id, cyclus == huidige boek_cyclus), tegenboeking → origineel via document_id.
    boek_cyclus: Mapped[int] = mapped_column(primary_key=True)
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    soort: Mapped[str]
    reden: Mapped[str]
    rlz_tegenboeking_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    rlz_boekstuknummer: Mapped[str | None] = mapped_column(default=None)
    # Betaalstatus van het origineel op het moment van tegenboeken (mockup-waarschuwing "open
    # creditpost"): puur informatief vastgelegd voor tijdlijn/audit, RLZ blijft de bron.
    origineel_betaald_bedrag: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())


class WebhookStatus(enum.StrEnum):
    """Afleverstatus van een outbox-rij (migratie 0025) — zichtbaar, nooit stil: `mislukt` is de
    dead-letter na max pogingen en vraagt om menselijke actie, geen stille eindtoestand."""

    OPENSTAAND = "openstaand"
    AFGELEVERD = "afgeleverd"
    MISLUKT = "mislukt"


class WebhookUitgaand(Base):
    """Outbox voor het "factuur geboekt"-webhook (migratie 0009 + 0025, koppelcontract §3).
    `payload` is de ONGETEKENDE envelope ({schema_version, event, data}) — timestamp/nonce/
    handtekening berekent de afleveraar per verzendpoging (app/documenten/webhook_afleveraar.py),
    anders wijst het ~5 min-replay-venster van de ontvanger elke uitgestelde aflevering af.
    `administratie_id` (migratie 0046): NULL = het event hoort bij de administratie van het
    document (inkoop/verkoop-pad); gevuld = de administratie waar het event over gaat terwijl
    `document_id` een document van een ándere administratie is — het doorbelasting-spiegelpad
    (document_id = bron-document, administratie_id = doel-administratie)."""

    __tablename__ = "webhook_uitgaand"
    __table_args__ = (
        Index("ix_webhook_uitgaand_document_id", "document_id"),
        Index("ix_webhook_uitgaand_administratie_id", "administratie_id"),
        Index(
            "ix_webhook_uitgaand_openstaand",
            "volgende_poging_op",
            postgresql_where=text("status = 'openstaand'"),
        ),
        {"schema": "boekhouding"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("boekhouding.document.id"))
    administratie_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.administratie.id"), default=None
    )
    event: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSONB)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    afgeleverd_op: Mapped[datetime | None] = mapped_column(default=None)
    # Afleverstatus (migratie 0025): tekst + DB-CHECK i.p.v. PG-enum, waarden uit WebhookStatus.
    status: Mapped[str] = mapped_column(default=WebhookStatus.OPENSTAAND.value)
    pogingen: Mapped[int] = mapped_column(default=0)
    laatste_poging_op: Mapped[datetime | None] = mapped_column(default=None)
    laatste_fout: Mapped[str | None] = mapped_column(default=None)
    volgende_poging_op: Mapped[datetime | None] = mapped_column(default=None)


# Metadata-registratie: Document.intake_bericht_id draagt een FK naar boekhouding.intake_bericht
# (migratie 0028) — die tabel moet in Base.metadata staan vóór SQLAlchemy de Document-mapper
# configureert, óók als de aanroeper alleen dit module importeert. Onderaan i.p.v. bovenaan om
# elke schijn van een importcyclus te vermijden (app/intake/models.py importeert alleen Base).
class DuplicaatSignaalUitkomst(enum.StrEnum):
    """Gecachete uitkomst van de RLZ-duplicaatquery (besluit Peter 25-08, feedbackronde deel 2
    punt 6): GEEN = geen andere factuur in RLZ met dezelfde crediteur+referentie+bedrag;
    MOGELIJK_DUPLICAAT = wél (chip in de werkvoorraad, teller per klant); NIET_TOETSBAAR = kop
    nog onvolledig (crediteur/referentie/bedrag ontbreekt); ONBEKEND = RLZ niet bereikbaar bij
    de laatste berekening. De cache is SIGNALERING: de live check op het boekmoment
    (checks.check_duplicaat) blijft de bindende poort — bij verschil wint de live check."""

    GEEN = "geen"
    MOGELIJK_DUPLICAAT = "mogelijk_duplicaat"
    NIET_TOETSBAAR = "niet_toetsbaar"
    ONBEKEND = "onbekend"


_DUPLICAAT_UITKOMST_SQL = ", ".join(f"'{u.value}'" for u in DuplicaatSignaalUitkomst)


class DuplicaatSignaal(Base):
    """Eén rij per inkoopfactuur-document met de laatst berekende duplicaat-uitkomst (migratie
    0066). Herberekend ná extractie én bij elke veldopslag (`sla_boekvoorstel_op`) zodat de
    werkvoorraad het signaal toont zónder live RLZ-call per lijstrij. Herberekenen = UPDATE
    (geen DELETE — het spoor van de laatste toetsing blijft; `berekend_op` toont de versheid).
    `treffers` = de RLZ-documenten (id + Reference + InvoiceNumber) waarop het signaal rust;
    `vendor_id`/`referentie`/`totaalbedrag` = de kopgegevens waarop getoetst is (herleidbaar
    waarom het signaal er staat, ook als het voorstel intussen gewijzigd is)."""

    __tablename__ = "duplicaat_signaal"
    __table_args__ = (
        CheckConstraint(f"uitkomst IN ({_DUPLICAAT_UITKOMST_SQL})", name="ck_duplicaat_signaal_uitkomst"),
        Index("ix_duplicaat_signaal_administratie_uitkomst", "administratie_id", "uitkomst"),
        {"schema": "boekhouding"},
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boekhouding.document.id"), primary_key=True
    )
    administratie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.administratie.id"))
    uitkomst: Mapped[str]
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    referentie: Mapped[str | None] = mapped_column(default=None)
    totaalbedrag: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    treffers: Mapped[list | None] = mapped_column(JSONB, default=None)
    melding: Mapped[str | None] = mapped_column(default=None)
    berekend_op: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


from app.intake import models as _intake_models  # noqa: E402, F401
