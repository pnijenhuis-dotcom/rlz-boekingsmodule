from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select

from app.auth.rollen import is_kantoorrol
from app.beheer.eerste_sync import EersteSyncRunInfo
from app.config import settings
from app.credentialstore import service as credentialstore_service
from app.db.audit import record_audit_event
from app.db.models import (
    Administratie,
    AiKostenInstelling,
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
    # Verkoop-autoboeken (migratie 0051): de kolom is alleen bedienbaar voor
    # is_vastgoed-administraties — de UI heeft beide velden nodig om dat te tonen.
    is_vastgoed: bool = False
    verkoop_autoboeken_ingeschakeld: bool = False
    # Uren & meerwerk (migratie 0056): steigerbouw-tak, opt-in per administratie.
    uren_meerwerk_ingeschakeld: bool = False
    uren_dagmax_uren: Decimal = Decimal("12")
    afdelingen_ingeschakeld: bool = False
    voorraad_ingeschakeld: bool = False
    rlz_admin_id: str | None = None
    webservice_username: str | None = None
    probe_groen: bool | None = None
    # Eerste-sync-stand (wizard-nazorg 27-08, casus Bouwadvies Oost Nederland): de laatste run
    # zoals de wizard 'm toont (status + onderdelen + foutreden) — de UI toont 'm op de rij zolang
    # de run niet volledig groen is, mét herstartknop op hetzelfde endpoint. None = nog nooit.
    eerste_sync: EersteSyncRunInfo | None = None
    # v2 30-08 (mockup instellingen-administraties-v2): compacte tabel mét meta-regel, chips en
    # sync-kolom — daarom hier óók eigenaar-naam, IBAN-accordeur-telling, de overige module-vlaggen,
    # de jongste sync-tijd (max laatst_gesynchroniseerd over de gesyncte caches) en het archiefspoor.
    eigenaar_naam: str | None = None
    iban_accordeurs_aantal: int = 0
    afgeletterd_event_ingeschakeld: bool = False
    doorbelasting_ingeschakeld: bool = False
    bank_autoboeken_ingeschakeld: bool = False
    accordering_ingeschakeld: bool = False
    laatste_sync_op: datetime | None = None
    gearchiveerd_op: datetime | None = None
    gearchiveerd_door_naam: str | None = None


def administratie_bestaat(administratie_id: uuid.UUID) -> bool:
    with scoped_session(None) as session:
        return session.get(Administratie, administratie_id) is not None


def _laatste_sync(session, administratie_id: uuid.UUID) -> datetime | None:
    """Jongste `laatst_gesynchroniseerd` over de gesyncte RLZ-caches (grootboek, btw, crediteuren) —
    de sync-kolom "✓ 06:14" van de v2-tabel. Geen eigen logtabel: de caches zijn het spoor. De caches
    zijn RLS-tabellen: altijd aanroepen binnen `scoped_session(administratie_id)` (RLS-les 25-08)."""
    from app.db.models import Grootboekrekening
    from app.sync.models import TaxRateCache, VendorCache

    jongste: datetime | None = None
    for model in (Grootboekrekening, TaxRateCache, VendorCache):
        moment = session.scalar(
            select(func.max(model.laatst_gesynchroniseerd)).where(model.administratie_id == administratie_id)
        )
        if moment is not None and (jongste is None or moment > jongste):
            jongste = moment
    return jongste


def overzicht_administratie_instellingen(*, inclusief_gearchiveerd: bool = False) -> list[AdministratieInstellingen]:
    """Voor het instellingen-scherm (design-pass taak 3): beide schakelaars per administratie in
    één keer, i.p.v. de losse per-administratie GET-endpoints hierboven N keer aan te roepen.
    Los van `overzicht_boeken_status()` (CLI, alleen boeken_ingeschakeld) gehouden — dat commando
    hoeft niet mee te veranderen als deze lijst een derde kolom krijgt. Gearchiveerde administraties
    (v2 30-08) alleen op expliciet verzoek — het scherm toont ze achter "gearchiveerd (N)"."""
    from app.beheer.eerste_sync import laatste_run
    from app.beheer.onboarding import koppelstand
    from app.documenten.models import IbanAccordeur

    with scoped_session(None) as session:
        q = select(Administratie).order_by(Administratie.naam)
        if not inclusief_gearchiveerd:
            q = q.where(Administratie.gearchiveerd_op.is_(None))
        rijen = list(session.scalars(q))
        ids = [r.id for r in rijen]
        gebruiker_ids = {r.eigenaar_gebruiker_id for r in rijen if r.eigenaar_gebruiker_id} | {
            r.gearchiveerd_door for r in rijen if r.gearchiveerd_door
        }
        namen = (
            dict(
                session.execute(select(Gebruiker.id, Gebruiker.naam).where(Gebruiker.id.in_(list(gebruiker_ids)))).all()
            )
            if gebruiker_ids
            else {}
        )
        session.expunge_all()
    # IBAN-accordeurs en de sync-caches zijn RLS-tabellen: per administratie gescoopt lezen.
    iban_tellingen: dict[uuid.UUID, int] = {}
    laatste_sync: dict[uuid.UUID, datetime | None] = {}
    for aid in ids:
        with scoped_session(aid) as session:
            iban_tellingen[aid] = int(
                session.scalar(
                    select(func.count()).select_from(IbanAccordeur).where(IbanAccordeur.administratie_id == aid)
                )
                or 0
            )
            laatste_sync[aid] = _laatste_sync(session, aid)
    stand = koppelstand(ids)
    # Per administratie (RLS-gescoopte tabel, zelfde stale-markering als de status-route) — één
    # korte query per rij is prima voor het Beheerder-scherm.
    syncs = {r.id: laatste_run(r.id) for r in rijen}
    return [
        AdministratieInstellingen(
            administratie_id=r.id,
            naam=r.naam,
            boeken_ingeschakeld=r.boeken_ingeschakeld,
            project_verplicht=r.project_verplicht,
            ai_extractie_ingeschakeld=r.ai_extractie_ingeschakeld,
            eigenaar_gebruiker_id=r.eigenaar_gebruiker_id,
            is_vastgoed=r.is_vastgoed,
            verkoop_autoboeken_ingeschakeld=r.verkoop_autoboeken_ingeschakeld,
            uren_meerwerk_ingeschakeld=r.uren_meerwerk_ingeschakeld,
            uren_dagmax_uren=r.uren_dagmax_uren,
            afdelingen_ingeschakeld=r.afdelingen_ingeschakeld,
            voorraad_ingeschakeld=r.voorraad_ingeschakeld,
            rlz_admin_id=r.rlz_admin_id,
            webservice_username=stand.get(r.id, (None, None))[0],
            probe_groen=stand.get(r.id, (None, None))[1],
            eerste_sync=None if syncs[r.id].status == "geen" else syncs[r.id],
            eigenaar_naam=namen.get(r.eigenaar_gebruiker_id) if r.eigenaar_gebruiker_id else None,
            iban_accordeurs_aantal=iban_tellingen.get(r.id, 0),
            afgeletterd_event_ingeschakeld=r.afgeletterd_event_ingeschakeld,
            doorbelasting_ingeschakeld=r.doorbelasting_ingeschakeld,
            bank_autoboeken_ingeschakeld=r.bank_autoboeken_ingeschakeld,
            accordering_ingeschakeld=r.accordering_ingeschakeld,
            laatste_sync_op=laatste_sync.get(r.id),
            gearchiveerd_op=r.gearchiveerd_op,
            gearchiveerd_door_naam=namen.get(r.gearchiveerd_door) if r.gearchiveerd_door else None,
        )
        for r in rijen
    ]


# --- Archiveren / dearchiveren (v2 30-08, mockup instellingen-administraties-v2, 0075-patroon) ---------


class AdministratieGearchiveerd(BeheerFout):
    pass


@dataclass(frozen=True)
class ArchiveringResultaat:
    gearchiveerd_op: datetime
    credential_ingetrokken: bool
    open_documenten: int


def archiveer_administratie(*, actor_id: uuid.UUID, administratie_id: uuid.UUID) -> ArchiveringResultaat:
    """Archiveren (🗑, nooit verwijderen): `actief` → false + archiefspoor; de webservice-login gaat uit
    de credential-store (syncs/jobs stoppen — ze filteren op `actief` én hebben geen login meer);
    documenten, boekingen, historie en audit blijven staan; registersync levert de rij niet meer
    (verdwenen-semantiek §8). Open werk is een waarschuwing in het resultaat, geen blokkade (zelfde
    lijn als gebruiker-archiveren). Beheerder-only (router)."""
    from app.documenten.models import Document, DocumentStatus

    with scoped_session(None, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        if administratie.gearchiveerd_op is not None:
            raise AdministratieGearchiveerd("Administratie is al gearchiveerd")
        nu = datetime.now(UTC)
        administratie.actief = False
        administratie.gearchiveerd_op = nu
        administratie.gearchiveerd_door = actor_id
        naam = administratie.naam
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="administratie",
            record_id=administratie_id,
            actie="administratie_gearchiveerd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"actief": True, "gearchiveerd_op": None},
            nieuwe_waarde={"actief": False, "gearchiveerd_op": nu.isoformat(), "naam": naam},
        )
    ingetrokken = credentialstore_service.trek_credential_in(actor_id=actor_id, administratie_id=administratie_id)
    with scoped_session(administratie_id) as session:
        open_documenten = int(
            session.scalar(
                select(func.count()).where(
                    Document.administratie_id == administratie_id,
                    Document.status.notin_(
                        [DocumentStatus.GEBOEKT, DocumentStatus.VERWIJDERD, DocumentStatus.GESPLITST]
                    ),
                )
            )
            or 0
        )
    return ArchiveringResultaat(gearchiveerd_op=nu, credential_ingetrokken=ingetrokken, open_documenten=open_documenten)


def dearchiveer_administratie(
    *, actor_id: uuid.UUID, administratie_id: uuid.UUID, webservice_username: str, wachtwoord: str, client=None
) -> dict[str, str]:
    """Terugzetten kan alleen mét een nieuwe webservice-login: admin-pin + rechten-probe groen (zelfde
    poort als de wizard), dan credential opslaan, `actief` terug en archiefspoor gewist. Niets van de
    tussenliggende historie wordt geraakt. Geeft het probe-rapport terug."""
    from app.beheer import onboarding

    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        if administratie.gearchiveerd_op is None:
            raise BeheerFout("Administratie is niet gearchiveerd")
        rlz_admin_id, naam = administratie.rlz_admin_id, administratie.naam
    rapport = onboarding.probe_nieuwe_login(
        rlz_admin_id=rlz_admin_id,
        naam=naam,
        webservice_username=webservice_username,
        wachtwoord=wachtwoord,
        client=client,
    )
    credentialstore_service.zet_credential(
        actor_id=actor_id,
        administratie_id=administratie_id,
        webservice_username=webservice_username,
        wachtwoord=wachtwoord,
    )
    with scoped_session(None, actor_id=actor_id) as session:
        credentialstore_service.sla_probe_op(
            session, administratie_id=administratie_id, rapport=rapport, actor_id=actor_id
        )
        administratie = session.get(Administratie, administratie_id)
        assert administratie is not None
        oud = administratie.gearchiveerd_op
        administratie.actief = True
        administratie.gearchiveerd_op = None
        administratie.gearchiveerd_door = None
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="administratie",
            record_id=administratie_id,
            actie="administratie_gedearchiveerd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"actief": False, "gearchiveerd_op": oud.isoformat() if oud else None},
            nieuwe_waarde={"actief": True, "gearchiveerd_op": None},
        )
    return rapport


def zet_voorraad_ingeschakeld(*, actor_id: uuid.UUID, administratie_id: uuid.UUID, ingeschakeld: bool) -> bool:
    """Opt-in "Voorraad bijhouden" (migratie 0086, blok D 28-08) — Beheerder-only (router), audit als
    de andere toggles. Aanzetten herrekent de feitenlaag voor de bestaande documenten op de
    achtergrond van de eerste "Verversen" (geen stille backfill hier)."""
    with scoped_session(None, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        oud = administratie.voorraad_ingeschakeld
        administratie.voorraad_ingeschakeld = ingeschakeld
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="administratie",
            record_id=administratie_id,
            actie="voorraad_ingeschakeld_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"voorraad_ingeschakeld": oud},
            nieuwe_waarde={"voorraad_ingeschakeld": ingeschakeld},
        )
        return ingeschakeld


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


def zet_afgeletterd_event_ingeschakeld(*, actor_id: uuid.UUID, administratie_id: uuid.UUID, ingeschakeld: bool) -> bool:
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


def zet_doorbelasting_ingeschakeld(*, actor_id: uuid.UUID, administratie_id: uuid.UUID, ingeschakeld: bool) -> bool:
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


def zet_bank_autoboeken_ingeschakeld(*, actor_id: uuid.UUID, administratie_id: uuid.UUID, ingeschakeld: bool) -> bool:
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


def haal_uren_meerwerk_ingeschakeld_op(*, administratie_id: uuid.UUID) -> bool:
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        return administratie.uren_meerwerk_ingeschakeld


def zet_uren_meerwerk_ingeschakeld(*, actor_id: uuid.UUID, administratie_id: uuid.UUID, ingeschakeld: bool) -> bool:
    """Opt-in uren & meerwerk (migratie 0056, BOUW GO Peter 2026-08-21): steigerbouw-
    specifieke tak, alleen Universal initieel. Default UIT; Beheerder-only (router/CLI).
    Uit = de module bestaat niet voor deze administratie (veld-API en kantoor-endpoints
    weigeren server-side; bestaande weekstaten/meerwerk blijven staan — niets verdwijnt)."""
    with scoped_session(None, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        oud = administratie.uren_meerwerk_ingeschakeld
        administratie.uren_meerwerk_ingeschakeld = ingeschakeld
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="administratie",
            record_id=administratie_id,
            actie="uren_meerwerk_ingeschakeld_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"uren_meerwerk_ingeschakeld": oud},
            nieuwe_waarde={"uren_meerwerk_ingeschakeld": ingeschakeld},
        )
        return ingeschakeld


def haal_verkoop_autoboeken_ingeschakeld_op(*, administratie_id: uuid.UUID) -> bool:
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        return administratie.verkoop_autoboeken_ingeschakeld


def zet_verkoop_autoboeken_ingeschakeld(
    *, actor_id: uuid.UUID, administratie_id: uuid.UUID, ingeschakeld: bool
) -> bool:
    """Autoboek-opt-in voor VASTLY-VERKOOP-documenten (migratie 0051, besluit Peter 2026-08-15,
    automatisering-first). Default UIT; Beheerder-only (router/CLI). Aanzetten kan uitsluitend
    voor is_vastgoed-administraties — alleen dáár bestaan VASTLY-VERKOOP-documenten, en een
    opt-in op een gewone administratie zou een slapende vlag zonder betekenis zijn (uitzetten
    kan altijd, ook als is_vastgoed intussen is teruggedraaid). De boeken-failsafes (toggle per
    administratie + globale kill switch + volumerem) gelden onverkort in de verkoop-boekmotor."""
    with scoped_session(None, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        # v2 30-08 (besluit Peter 29-08): de losse vlag volgt is_vastgoed — aan = aan, uit = uit. De
        # kolom blijft als spiegel bestaan (rapportage/audit); afwijkend zetten is vervallen.
        if ingeschakeld != administratie.is_vastgoed:
            raise BeheerFout(
                "Verkoop-autoboeken volgt sinds 30-08 de vastgoed-koppeling (is_vastgoed): aan = aan, uit = uit — "
                "zet de vastgoed-koppeling om, de losse instelling is vervallen"
            )
        oud = administratie.verkoop_autoboeken_ingeschakeld
        administratie.verkoop_autoboeken_ingeschakeld = ingeschakeld
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="administratie",
            record_id=administratie_id,
            actie="verkoop_autoboeken_ingeschakeld_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"verkoop_autoboeken_ingeschakeld": oud},
            nieuwe_waarde={"verkoop_autoboeken_ingeschakeld": ingeschakeld},
        )
        return ingeschakeld


@dataclass(frozen=True)
class IsVastgoedResultaat:
    """Uitkomst van `zet_is_vastgoed`: de nieuwe vlag + wat er aan opt-ins mee uitging."""

    is_vastgoed: bool
    verkoop_autoboeken_ingeschakeld: bool
    verkoop_autoboeken_uitgezet: bool


def haal_is_vastgoed_op(*, administratie_id: uuid.UUID) -> bool:
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        return administratie.is_vastgoed


def zet_is_vastgoed(*, actor_id: uuid.UUID, administratie_id: uuid.UUID, is_vastgoed: bool) -> IsVastgoedResultaat:
    """Vastgoed-koppeling per administratie (avondrun 26-08, S2-draaiboek R1 — tot dan alleen via
    de DB gezet). Beheerder-only (router/CLI). De vlag stuurt uitsluitend BESTAANDE poorten: de
    outbox-rijen `factuur_geboekt`/`factuur_gestorneerd` ontstaan alleen bij is_vastgoed
    (documenten/boeken.py, verkoop/boeken.py, doorbelasting-spiegel), de afleveraar assert het
    nogmaals, route A (projectaanvragen) is er hard op gescoped en het VASTLY-VERKOOP-boekpad
    vuurt zijn webhook alleen dan. Geen andere semantiek; de tier-vlag
    `afgeletterd_event_ingeschakeld` blijft onaangeroerd (besluit 0018 — aparte kolom).

    UIT zetten neemt `verkoop_autoboeken_ingeschakeld` mee UIT (de 409-regel: die opt-in kan
    alleen bestaan bij is_vastgoed — een slapende opt-in zou anders bij een latere her-activering
    stil weer gaan boeken). Dat gebeurt ZICHTBAAR: eigen audit_event + in het resultaat, nooit
    stil. Élke aanroep wordt geauditeerd (oud→nieuw), ook een no-op — zelfde lijn als de andere
    toggles (test_elke_wijziging_wordt_geaudit)."""
    with scoped_session(None, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        oud = administratie.is_vastgoed
        administratie.is_vastgoed = is_vastgoed
        correlatie_id = uuid.uuid4()
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="administratie",
            record_id=administratie_id,
            actie="is_vastgoed_gewijzigd",
            correlatie_id=correlatie_id,
            oude_waarde={"is_vastgoed": oud},
            nieuwe_waarde={"is_vastgoed": is_vastgoed},
        )
        # v2 30-08: verkoop-autoboeken volgt is_vastgoed (aan = aan, uit = uit) — de spiegelkolom gaat
        # zichtbaar mee (eigen audit_event), de boekmotor toetst zelf op is_vastgoed.
        verkoop_uitgezet = False
        if administratie.verkoop_autoboeken_ingeschakeld != is_vastgoed:
            oud_vlag = administratie.verkoop_autoboeken_ingeschakeld
            administratie.verkoop_autoboeken_ingeschakeld = is_vastgoed
            verkoop_uitgezet = not is_vastgoed
            record_audit_event(
                session,
                actor_id=actor_id,
                module="platform",
                tabel="administratie",
                record_id=administratie_id,
                actie="verkoop_autoboeken_ingeschakeld_gewijzigd",
                correlatie_id=correlatie_id,
                oude_waarde={"verkoop_autoboeken_ingeschakeld": oud_vlag},
                nieuwe_waarde={
                    "verkoop_autoboeken_ingeschakeld": is_vastgoed,
                    "reden": "volgt is_vastgoed (v2 30-08)",
                },
            )
        return IsVastgoedResultaat(
            is_vastgoed=is_vastgoed,
            verkoop_autoboeken_ingeschakeld=administratie.verkoop_autoboeken_ingeschakeld,
            verkoop_autoboeken_uitgezet=verkoop_uitgezet,
        )


@dataclass(frozen=True)
class Medewerker:
    id: uuid.UUID
    naam: str
    # Blok B5 (26-08): een klant-accordeur is óók toewijsbaar (vraag aan de klant) — de UI groepeert
    # en toont "bij de klant"; verder geen rol/e-mail (dataminimalisatie blijft).
    is_klant_accordeur: bool = False


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
            select(Gebruiker.id, Gebruiker.naam, Gebruiker.rol)
            .join(GebruikerAdministratie, GebruikerAdministratie.gebruiker_id == Gebruiker.id)
            .where(
                GebruikerAdministratie.administratie_id == administratie_id,
                Gebruiker.status == GebruikerStatus.ACTIEF,
            )
        ).all()
        beheerders = session.execute(
            select(Gebruiker.id, Gebruiker.naam, Gebruiker.rol).where(
                Gebruiker.rol == GebruikerRol.BEHEERDER, Gebruiker.status == GebruikerStatus.ACTIEF
            )
        ).all()
    uniek = {rij.id: (rij.naam, rij.rol) for rij in [*gescoopt, *beheerders]}
    # Veldrollen (zzp'er/uitvoerder/detacheerder) hebben scope-rijen maar zijn geen gesprekspartner
    # voor een factuurvraag — alleen kantoorrollen + klant-accordeurs zijn toewijsbaar.
    return sorted(
        (
            Medewerker(id=gid, naam=naam, is_klant_accordeur=rol == GebruikerRol.KLANT_ACCORDEUR)
            for gid, (naam, rol) in uniek.items()
            if is_kantoorrol(rol) or rol == GebruikerRol.KLANT_ACCORDEUR
        ),
        key=lambda m: (m.is_klant_accordeur, m.naam.lower()),
    )


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


def zet_ai_kosten_maandlimiet(*, actor_id: uuid.UUID, maandlimiet_eur: Decimal) -> Decimal:
    """AI-kosten-maandlimiet (migratie 0047, besluit Peter 2026-08-14) — Beheerder-only
    (router), zelfde patroon als de intake-AI-toggle: wijziging in het audit_event. De harde
    poort (app/aikosten/service.py) leest deze instelling bij élke AI-call."""
    with scoped_session(None, actor_id=actor_id) as session:
        instelling = session.get(AiKostenInstelling, True)
        if instelling is None:
            raise BeheerFout("platform.ai_kosten_instelling heeft geen rij — migratie 0047 niet toegepast?")
        oud = instelling.maandlimiet_eur
        instelling.maandlimiet_eur = maandlimiet_eur
        instelling.gewijzigd_door = actor_id
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="ai_kosten_instelling",
            record_id=_BOEKEN_INSTELLING_RECORD_ID,
            actie="ai_kosten_maandlimiet_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"maandlimiet_eur": str(oud)},
            nieuwe_waarde={"maandlimiet_eur": str(maandlimiet_eur)},
        )
        return maandlimiet_eur


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


def haal_uren_dagmax_op(*, administratie_id: uuid.UUID) -> Decimal:
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        return administratie.uren_dagmax_uren


def zet_uren_dagmax(*, actor_id: uuid.UUID, administratie_id: uuid.UUID, dagmax_uren: Decimal) -> Decimal:
    """Drempel voor het >N-uur-per-dag-signaal (steigerbouw-run A6, migratie 0072): som van de
    ingediende uren per persoon per kalenderdag over álle weekstaten heen boven N = oranje vlag
    bij de keuring + zichtbaar voor kantoor. Signaal, geen blokkade. Beheerder-only, geaudit."""
    if not (Decimal("0") < dagmax_uren <= Decimal("24")):
        raise BeheerFout("De dagdrempel moet tussen 0 en 24 uur liggen")
    with scoped_session(None, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        oud = administratie.uren_dagmax_uren
        administratie.uren_dagmax_uren = dagmax_uren
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="administratie",
            record_id=administratie_id,
            actie="uren_dagmax_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"uren_dagmax_uren": str(oud)},
            nieuwe_waarde={"uren_dagmax_uren": str(dagmax_uren)},
        )
        return dagmax_uren
