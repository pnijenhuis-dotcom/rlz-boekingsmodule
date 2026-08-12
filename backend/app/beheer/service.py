from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import (
    Administratie,
    BoekenInstelling,
    Gebruiker,
    GebruikerAdministratie,
    GebruikerRol,
    GebruikerStatus,
    IntakeInstelling,
    WebhookInstelling,
)
from app.db.session import scoped_session


class BeheerFout(Exception):
    """Domeinfout in de beheer-servicelaag (bv. onbekende administratie)."""


# platform.boeken_instelling en platform.webhook_instelling zijn singletons (PK is een boolean,
# geen UUID) — audit_event vereist wél een record_id; de nil-UUID is hier een vaste, herkenbare
# placeholder voor "de ene globale instelling-rij", nooit een echte entiteit.
_BOEKEN_INSTELLING_RECORD_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")
_WEBHOOK_INSTELLING_RECORD_ID = _BOEKEN_INSTELLING_RECORD_ID


def haal_boeken_ingeschakeld_op(*, administratie_id: uuid.UUID) -> bool:
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        return administratie.boeken_ingeschakeld


def zet_boeken_ingeschakeld(*, actor_id: uuid.UUID, administratie_id: uuid.UUID, ingeschakeld: bool) -> bool:
    """Boeken-failsafe (a), per-administratie deel (CLAUDE.md-taak 2.4) — Beheerder-only,
    afgedwongen door de router-dependency, niet hier. Elke wijziging in het audit_event, ook als
    de nieuwe waarde toevallig gelijk is aan de oude (geen stille no-op-detectie: een Beheerder
    die 'm bewust opnieuw bevestigt, mag daarvan ook een spoor verwachten). Sessie gescoped op
    None (platformbreed) — dit is een Beheerder-only beheerhandeling, geen document-/administratie-
    gescopede actie; audit_event.administratie_id blijft daarom bewust NULL (zelfde patroon als
    credentialstore/service.py::zet_credential — de RLS WITH CHECK op audit_event kent geen
    beheerder-bypass, alleen `administratie_id IS NULL OR administratie_id = current_administratie_id()`)."""
    with scoped_session(None, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        oud = administratie.boeken_ingeschakeld
        administratie.boeken_ingeschakeld = ingeschakeld
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="administratie",
            record_id=administratie_id,
            actie="boeken_ingeschakeld_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"boeken_ingeschakeld": oud},
            nieuwe_waarde={"boeken_ingeschakeld": ingeschakeld},
        )
        return ingeschakeld


def zet_reconciliatie_uitgesloten(
    *, actor_id: uuid.UUID, administratie_id: uuid.UUID, uitgesloten: bool, reden: str | None
) -> bool:
    """Sluit een administratie uit van de EXIT-CODE van de dagelijkse reconciliaties (migratie
    0043, besluit Peter 2026-08-12 — bedoeld voor de test-administratie, die permanent
    testboekingen draagt die een mens in de RLZ-UI opruimt).

    Wat het NIET doet: de administratie uit het rapport filteren. De reconciliatie draait
    gewoon en toont de bevindingen onder de markering UITGESLOTEN. Dat is het verschil tussen
    "ik weet dat hier ruis zit" en "ik kijk hier niet meer" — het tweede zou een echte fout in
    precies de administratie waarop schrijftests draaien onzichtbaar maken.

    Reden verplicht bij aanzetten (ook als DB-CHECK), audit altijd. Beheerder-only: de CLI
    levert de actor, de router-dependency doet de rolcheck zoals bij de andere toggles."""
    if uitgesloten and len((reden or "").strip()) < 5:
        raise BeheerFout("Uitsluiten van een administratie vereist een inhoudelijke reden")
    with scoped_session(None, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        oud = administratie.reconciliatie_uitgesloten
        oude_reden = administratie.reconciliatie_uitsluiting_reden
        administratie.reconciliatie_uitgesloten = uitgesloten
        administratie.reconciliatie_uitsluiting_reden = reden.strip() if (uitgesloten and reden) else None
        administratie.reconciliatie_uitgesloten_op = datetime.now(UTC) if uitgesloten else None
        administratie.reconciliatie_uitgesloten_door = actor_id if uitgesloten else None
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="administratie",
            record_id=administratie_id,
            actie="reconciliatie_uitsluiting_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"reconciliatie_uitgesloten": oud, "reden": oude_reden},
            nieuwe_waarde={
                "reconciliatie_uitgesloten": uitgesloten,
                "reden": administratie.reconciliatie_uitsluiting_reden,
            },
        )
        return uitgesloten


@dataclass(frozen=True)
class AdministratieBoekenStatus:
    administratie_id: uuid.UUID
    naam: str
    boeken_ingeschakeld: bool


def overzicht_boeken_status() -> list[AdministratieBoekenStatus]:
    """Voor `make boeken-status` (CLI-overzicht, geen endpoint — dit is een beheerhandeling
    zonder ingelogde gebruiker) — de globale kill switch zelf haalt de aanroeper apart op via
    haal_globale_kill_switch_op(), 'effectief aan' is beide tegelijk."""
    with scoped_session(None) as session:
        rijen = session.scalars(select(Administratie).order_by(Administratie.naam))
        return [
            AdministratieBoekenStatus(administratie_id=r.id, naam=r.naam, boeken_ingeschakeld=r.boeken_ingeschakeld)
            for r in rijen
        ]


@dataclass(frozen=True)
class AdministratieInstellingen:
    administratie_id: uuid.UUID
    naam: str
    boeken_ingeschakeld: bool
    project_verplicht: bool
    ai_extractie_ingeschakeld: bool
    eigenaar_gebruiker_id: uuid.UUID | None


def overzicht_administratie_instellingen() -> list[AdministratieInstellingen]:
    """Voor het instellingen-scherm (design-pass taak 3): beide schakelaars per administratie in
    één keer, i.p.v. de losse per-administratie GET-endpoints hierboven N keer aan te roepen.
    Los van `overzicht_boeken_status()` (CLI, alleen boeken_ingeschakeld) gehouden — dat commando
    hoeft niet mee te veranderen als deze lijst een derde kolom krijgt."""
    with scoped_session(None) as session:
        rijen = session.scalars(select(Administratie).order_by(Administratie.naam))
        return [
            AdministratieInstellingen(
                administratie_id=r.id,
                naam=r.naam,
                boeken_ingeschakeld=r.boeken_ingeschakeld,
                project_verplicht=r.project_verplicht,
                ai_extractie_ingeschakeld=r.ai_extractie_ingeschakeld,
                eigenaar_gebruiker_id=r.eigenaar_gebruiker_id,
            )
            for r in rijen
        ]


def haal_project_verplicht_op(*, administratie_id: uuid.UUID) -> bool:
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        return administratie.project_verplicht


def zet_project_verplicht(*, actor_id: uuid.UUID, administratie_id: uuid.UUID, verplicht: bool) -> bool:
    """Design-pass taak 4: bepaalt of de Project-kolom in het controlescherm zichtbaar/verplicht
    is voor deze administratie — Beheerder-only (router), audit als bij boeken_ingeschakeld."""
    with scoped_session(None, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        oud = administratie.project_verplicht
        administratie.project_verplicht = verplicht
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="administratie",
            record_id=administratie_id,
            actie="project_verplicht_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"project_verplicht": oud},
            nieuwe_waarde={"project_verplicht": verplicht},
        )
        return verplicht


def haal_ai_extractie_ingeschakeld_op(*, administratie_id: uuid.UUID) -> bool:
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        return administratie.ai_extractie_ingeschakeld


def zet_ai_extractie_ingeschakeld(*, actor_id: uuid.UUID, administratie_id: uuid.UUID, ingeschakeld: bool) -> bool:
    """AVG-gate voor AI-extractie (migratie 0014): alleen bij AAN gaan PDF's van deze
    administratie naar de Claude API — default UIT, Beheerder-only (router), audit als bij
    boeken_ingeschakeld. Echte klantfacturen pas ná DPA + EU-verwerking-bevestiging +
    verwerkersregister (docs/BOUWPLAN.md, AVG-volgorde)."""
    with scoped_session(None, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        oud = administratie.ai_extractie_ingeschakeld
        administratie.ai_extractie_ingeschakeld = ingeschakeld
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="administratie",
            record_id=administratie_id,
            actie="ai_extractie_ingeschakeld_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"ai_extractie_ingeschakeld": oud},
            nieuwe_waarde={"ai_extractie_ingeschakeld": ingeschakeld},
        )
        return ingeschakeld


def haal_bank_autoboeken_ingeschakeld_op(*, administratie_id: uuid.UUID) -> bool:
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        return administratie.bank_autoboeken_ingeschakeld


def zet_afgeletterd_event_ingeschakeld(
    *, actor_id: uuid.UUID, administratie_id: uuid.UUID, ingeschakeld: bool
) -> bool:
    """Tier-vlag voor het factuur_afgeletterd-event (migratie 0037, koppelcontract §3 v1.11
    punt 5 + besluit 0018): het event wordt uitsluitend aangemaakt voor administraties met
    deze vlag. Default UIT — activatie wacht op vastgoeds verwerker; de aflevering zelf staat
    daarnaast achter platform.webhook_instelling (default UIT)."""
    with scoped_session(None, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        oud = administratie.afgeletterd_event_ingeschakeld
        administratie.afgeletterd_event_ingeschakeld = ingeschakeld
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="administratie",
            record_id=administratie_id,
            actie="afgeletterd_event_ingeschakeld_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"afgeletterd_event_ingeschakeld": oud},
            nieuwe_waarde={"afgeletterd_event_ingeschakeld": ingeschakeld},
        )
        return ingeschakeld


def haal_doorbelasting_ingeschakeld_op(*, administratie_id: uuid.UUID) -> bool:
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        return administratie.doorbelasting_ingeschakeld


def zet_doorbelasting_ingeschakeld(
    *, actor_id: uuid.UUID, administratie_id: uuid.UUID, ingeschakeld: bool
) -> bool:
    """Toggle voor de actie "Doorbelasten…" op geboekte inkoopfacturen van deze
    BRON-administratie (migratie 0044, besluit Peter 2026-08-13). Default UIT; in de praktijk
    alleen Kempen Facilities aan. Beheerder-only (router/CLI), audit als bij de andere
    toggles; de doel-kant heeft geen eigen vlag — die wordt afgedwongen via de
    mapping-whitelist."""
    with scoped_session(None, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        oud = administratie.doorbelasting_ingeschakeld
        administratie.doorbelasting_ingeschakeld = ingeschakeld
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="administratie",
            record_id=administratie_id,
            actie="doorbelasting_ingeschakeld_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"doorbelasting_ingeschakeld": oud},
            nieuwe_waarde={"doorbelasting_ingeschakeld": ingeschakeld},
        )
        return ingeschakeld


def zet_bank_autoboeken_ingeschakeld(
    *, actor_id: uuid.UUID, administratie_id: uuid.UUID, ingeschakeld: bool
) -> bool:
    """Opt-in voor de volautomatische bankstappen (migratie 0026): vaste regels automatisch
    direct-op-grootboek boeken tijdens de bank-sync. Default UIT; werkt bovenop de bestaande
    boeken-failsafes (toggle per administratie + globale kill switch — die gelden onverkort in
    app/bank/boeken.py). Beheerder-only (router/CLI), audit als bij de andere toggles."""
    with scoped_session(None, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        oud = administratie.bank_autoboeken_ingeschakeld
        administratie.bank_autoboeken_ingeschakeld = ingeschakeld
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="administratie",
            record_id=administratie_id,
            actie="bank_autoboeken_ingeschakeld_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"bank_autoboeken_ingeschakeld": oud},
            nieuwe_waarde={"bank_autoboeken_ingeschakeld": ingeschakeld},
        )
        return ingeschakeld


@dataclass(frozen=True)
class Medewerker:
    id: uuid.UUID
    naam: str


def lijst_medewerkers(*, administratie_id: uuid.UUID) -> list[Medewerker]:
    """Actieve gebruikers die op deze administratie toegewezen kunnen worden (vraagmodal
    "Toewijzen aan", PART B): scope-gebruikers via de koppeltabel + alle actieve Beheerders
    (platform-breed, zelfde bypass als overal). Sessie gescoped op de administratie: de RLS op
    gebruiker_administratie geeft buiten die scope geen rijen — het lek-risico zit dus niet in
    deze query maar wordt op DB-niveau afgevangen; de router doet daarbovenop de
    vereis_administratie_scope-check op de aanroeper. Alleen id + naam — geen e-mail/rol/status
    naar de UI (dataminimalisatie)."""
    with scoped_session(administratie_id) as session:
        gescoopt = session.execute(
            select(Gebruiker.id, Gebruiker.naam)
            .join(GebruikerAdministratie, GebruikerAdministratie.gebruiker_id == Gebruiker.id)
            .where(
                GebruikerAdministratie.administratie_id == administratie_id,
                Gebruiker.status == GebruikerStatus.ACTIEF,
            )
        ).all()
        beheerders = session.execute(
            select(Gebruiker.id, Gebruiker.naam).where(
                Gebruiker.rol == GebruikerRol.BEHEERDER, Gebruiker.status == GebruikerStatus.ACTIEF
            )
        ).all()
    uniek = {rij.id: rij.naam for rij in [*gescoopt, *beheerders]}
    return sorted((Medewerker(id=gid, naam=naam) for gid, naam in uniek.items()), key=lambda m: m.naam.lower())


class OngeldigeEigenaar(BeheerFout):
    """De beoogde eigenaar is geen actieve gebruiker met toegang tot deze administratie."""


def haal_eigenaar_op(*, administratie_id: uuid.UUID) -> uuid.UUID | None:
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        return administratie.eigenaar_gebruiker_id


def zet_eigenaar(
    *, actor_id: uuid.UUID, administratie_id: uuid.UUID, eigenaar_gebruiker_id: uuid.UUID | None
) -> uuid.UUID | None:
    """Eigenaar per administratie (mockup Instellingen "Eigenaar (krijgt vragen)") — de
    default-toewijzing voor nieuwe vragen; Beheerder-only (router), audit als bij de andere
    administratie-instellingen. None = eigenaar weghalen (vragen vereisen dan een expliciete
    toewijzing). De eigenaar moet actief zijn en — tenzij Beheerder (platform-breed) — scope op
    déze administratie hebben; daarom is de sessie hier, anders dan bij de boolean-toggles,
    gescoped op de administratie (de gebruiker_administratie-RLS geeft buiten die scope nooit
    een rij terug) en draagt het audit_event de administratie_id."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        if eigenaar_gebruiker_id is not None:
            gebruiker = session.get(Gebruiker, eigenaar_gebruiker_id)
            if gebruiker is None or gebruiker.status != GebruikerStatus.ACTIEF:
                raise OngeldigeEigenaar(f"Eigenaar is geen actieve gebruiker: {eigenaar_gebruiker_id}")
            if (
                gebruiker.rol != GebruikerRol.BEHEERDER
                and session.get(GebruikerAdministratie, (eigenaar_gebruiker_id, administratie_id)) is None
            ):
                raise OngeldigeEigenaar("Eigenaar heeft geen toegang tot deze administratie")
        oud = administratie.eigenaar_gebruiker_id
        administratie.eigenaar_gebruiker_id = eigenaar_gebruiker_id
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="administratie",
            record_id=administratie_id,
            actie="eigenaar_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"eigenaar_gebruiker_id": str(oud) if oud else None},
            nieuwe_waarde={"eigenaar_gebruiker_id": str(eigenaar_gebruiker_id) if eigenaar_gebruiker_id else None},
            administratie_id=administratie_id,
        )
        return eigenaar_gebruiker_id


def haal_webhook_aflevering_ingeschakeld_op() -> bool:
    with scoped_session(None) as session:
        instelling = session.get(WebhookInstelling, True)
        return instelling is not None and instelling.aflevering_ingeschakeld


def zet_webhook_aflevering_ingeschakeld(*, actor_id: uuid.UUID, ingeschakeld: bool) -> bool:
    """Webhook-aflevering-toggle (migratie 0025) — Beheerder-only (router), zelfde patroon als
    de globale boeken-kill-switch. Default UIT: aanzetten is een bewuste actie zodra vastgoed's
    ontvanger bestaat; naast deze toggle geldt óók de config-failsafe (doel-URL + secret)."""
    with scoped_session(None, actor_id=actor_id) as session:
        instelling = session.get(WebhookInstelling, True)
        if instelling is None:
            raise BeheerFout("platform.webhook_instelling heeft geen rij — migratie 0025 niet toegepast?")
        oud = instelling.aflevering_ingeschakeld
        instelling.aflevering_ingeschakeld = ingeschakeld
        instelling.gewijzigd_door = actor_id
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="webhook_instelling",
            record_id=_WEBHOOK_INSTELLING_RECORD_ID,
            actie="webhook_aflevering_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"aflevering_ingeschakeld": oud},
            nieuwe_waarde={"aflevering_ingeschakeld": ingeschakeld},
        )
        return ingeschakeld


def haal_intake_ai_ingeschakeld_op() -> bool:
    """De opgeslagen instelling (zonder env-fallback) — voor het Beheerder-scherm/CLI: wat daar
    staat is wat een Beheerder heeft gezet, niet het effectieve resultaat van een deploy-config."""
    with scoped_session(None) as session:
        instelling = session.get(IntakeInstelling, True)
        if instelling is None:
            raise BeheerFout("platform.intake_instelling heeft geen rij — migratie 0029 niet toegepast?")
        return instelling.ai_ingeschakeld


def intake_ai_effectief_ingeschakeld() -> bool:
    """De AVG-gate die de intake-verwerking raadpleegt: DB-instelling leidend; de env-setting
    `intake_ai_ingeschakeld` is uitsluitend FALLBACK als de rij ontbreekt (migratie 0029 nog
    niet toegepast — bv. een los script tegen een oude database). Default dus UIT."""
    with scoped_session(None) as session:
        instelling = session.get(IntakeInstelling, True)
        if instelling is None:
            return settings.intake_ai_ingeschakeld
        return instelling.ai_ingeschakeld


def zet_intake_ai_ingeschakeld(*, actor_id: uuid.UUID, ingeschakeld: bool) -> bool:
    """Intake-AI-toggle (migratie 0029) — Beheerder-only (router/CLI), zelfde patroon als de
    webhook-aflevering-toggle. Default UIT: aanzetten is de bewuste AVG-opt-in waarmee
    nog-niet-toegewezen intake-PDF's (tenaamstelling + splitsingsdetectie) naar de Claude API
    mogen; de per-administratie-gate blijft daarnaast onverkort gelden ná toewijzing."""
    with scoped_session(None, actor_id=actor_id) as session:
        instelling = session.get(IntakeInstelling, True)
        if instelling is None:
            raise BeheerFout("platform.intake_instelling heeft geen rij — migratie 0029 niet toegepast?")
        oud = instelling.ai_ingeschakeld
        instelling.ai_ingeschakeld = ingeschakeld
        instelling.gewijzigd_door = actor_id
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="intake_instelling",
            record_id=_BOEKEN_INSTELLING_RECORD_ID,
            actie="intake_ai_ingeschakeld_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"ai_ingeschakeld": oud},
            nieuwe_waarde={"ai_ingeschakeld": ingeschakeld},
        )
        return ingeschakeld


def haal_globale_kill_switch_op() -> bool:
    with scoped_session(None) as session:
        instelling = session.get(BoekenInstelling, True)
        return instelling is not None and instelling.globaal_ingeschakeld


def zet_globale_kill_switch(*, actor_id: uuid.UUID, ingeschakeld: bool) -> bool:
    """Boeken-failsafe (a), globale deel — de platformbrede noodstop. Beheerder-only (router)."""
    with scoped_session(None, actor_id=actor_id) as session:
        instelling = session.get(BoekenInstelling, True)
        if instelling is None:
            raise BeheerFout("platform.boeken_instelling heeft geen rij — migratie 0008 niet toegepast?")
        oud = instelling.globaal_ingeschakeld
        instelling.globaal_ingeschakeld = ingeschakeld
        instelling.gewijzigd_door = actor_id
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="boeken_instelling",
            record_id=_BOEKEN_INSTELLING_RECORD_ID,
            actie="globale_kill_switch_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"globaal_ingeschakeld": oud},
            nieuwe_waarde={"globaal_ingeschakeld": ingeschakeld},
        )
        return ingeschakeld
