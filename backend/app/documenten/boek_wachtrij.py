"""Achtergrond-schrijver voor "Boeken in RLZ" (opdracht Peter 18-09 "Boeken sneller", stap 2).

Peter: "Als ik daarna druk op Boeken in RLZ duurt het weer 4 à 5 seconden voordat ik bij de volgende boeking terecht
kom. Vooral deze stap moet sneller: meteen weg (backend draait rustig door) en mij de volgende boeking binnen een
seconde geven."

Regel (`docs/regels/werkvoorraad-controlescherm.md`, BESLISSINGEN "BOEKEN SNELLER — CHECKS-CACHE + ACHTERGROND-
SCHRIJVER"):
- **Synchroon deel (< 500 ms, DB-only)** = `dien_boeking_in`: scope/rol (router), statusmachine, klant-accorderings-
  poort, factuurmatch-/materiaalmatch-bevestiging (409's blijven synchroon — die vragen een menselijke keuze), de
  harde checks mét het EXTERNE rapport uit de cache (geen geldig rapport → deze ene keer wél synchroon extern, nooit
  stil overslaan), boeken-toggle en volumerem. Groen → status `wordt_geboekt` (tijdlijn + audit) + antwoord 202 mét
  `{document_id, status, volgende_document_id}` — de server kiest het volgende document met exact de
  `kiesVolgendDocument`-regels van de frontend (positie in de getoonde lijstvolgorde, cyclisch, alleen verwerkbare
  statussen), zodat de frontend geen lijst hoeft op te halen.
- **Achtergrond-schrijver** = `verwerk_boek_taak`: exact het bestaande `boek_document` (client-GUID + eigen duplicaat-
  query vóór de PUT, PUT + Upload + actie 17 + GET + de DB-afwikkeling in één transactie + post-commit stappen) plus
  de klaargezette doorbelasting en de webhook — via `orkestratie.boek_document_met_doorbelasting`, mét de bij het
  indienen vastgelegde actor en bevestigingsvlaggen. ELKE mislukking = zichtbare status `boeken_mislukt` mét reden
  (bestaand principe 4: rode rij in de lijst + toast, geen pop-up meer) en "Opnieuw".
- **Idempotency-key** `boek-{document_id}-{boek_cyclus}` (`boekhouding.boek_wachtrij_claim`): twee verwerkers (on-
  demand job + scheduler-vangnet) pakken nooit dezelfde boeking; de RLZ-adapter hervat idempotent (GET op het GUID:
  al geboekt = niets opnieuw schrijven). Een claim zonder afronding > `settings.boek_wachtrij_herstel_minuten` =
  gestrande verwerker → herstel-vangnet claimt opnieuw (startup + job/scheduler); de reconciliatie telt zo'n
  document als bevinding `wordt_geboekt_verouderd` (start in `meten`) mét actie "Opnieuw proberen".
- **Cloud**: het bestaande job-triggerpatroon (`CloudRunJobBoekWachtrij` → on-demand job `rlz-boek-wachtrij`, CLI
  `boek-wachtrij-verwerken`) mét scheduler-vangnet elke 2 min. Cloud Tasks is NIET gekozen: dat vergt een nieuwe
  dependency, een queue + IAM (`cloudtasks.enqueuer`, OIDC-SA) en een interne route die in deze run niet live te
  bewijzen zijn — het job-patroon werkt aantoonbaar sinds 26-08 (extractie-wachtrij) en heeft dezelfde latency-
  klasse (executie < 1 s ná de trigger). Dev/tests = in-process thread (`InProcessBoekWachtrij`).
- **Autoboek-pad en accordering-staande-goedkeuring** gebruiken dezelfde schrijfroute (`boek_document`, één motor)
  zonder de 202-shortcut — zij draaien al in een achtergrondproces (extractie-job / accorderingsflow) en hebben
  geen wachtende mens.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import select

from app.config import settings
from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import boeken as boeken_service
from app.documenten import checks_extern
from app.documenten.boekvoorstel import haal_boekvoorstel_op, voer_checks_uit
from app.documenten.models import (
    BoekWachtrijClaim,
    Document,
    DocumentGebeurtenis,
    DocumentStatus,
)
from app.documenten.service import _schrijf_overgang

logger = logging.getLogger(__name__)

#: Audit-acties (gelezen door de tellers per automatisering in de reconciliatiemail, `automatiseringen.py`).
AUDIT_INGEDIEND = "boek_wachtrij_ingediend"
AUDIT_AFGEROND = "boek_wachtrij_afgerond"
AUDIT_TRIGGER = "boek_wachtrij_trigger"
#: 21-09: een mens (of de reconciliatie-actie) diende een hangende boeking opnieuw in — zelfde sleutel, nieuwe trigger.
AUDIT_OPNIEUW = "boek_wachtrij_opnieuw_ingediend"
#:  Reconciliatie-bevindingssoort. Tot 21-09 een `afwijking` in `meten` (blok documenten); sinds 21-09 (BUG
#: rlz-boek-wachtrij
#:  zonder `--command python`: drie dagen "Wordt geboekt…" zonder één signaal) is een boeking > herstelgrens op
#: wordt_geboekt
#:  een REGRESSIE-LET-OP op blok automatisering (`automatiseringen.boek_wachtrij_gestrand_bevindingen` → systeemmail +
#: audit  `automatisering_regressie` + bewakingsprobe) én een kwartier-probe `boek_wachtrij_gestrand` (app/bewaking). De
#: soortnaam reist mee in `detail.afwijking_soort` zodat de rij op /reconciliatie de actie "Opnieuw indienen" draagt.
BEVINDING_VEROUDERD = "wordt_geboekt_verouderd"

#: Statussen waarin een document "te verwerken" is voor de doorloop — spiegel van
#: `frontend/src/werkvoorraad/volgendDocument.ts::VERWERKBARE_STATUSSEN` (guard-test houdt beide gelijk).
VERWERKBARE_STATUSSEN: frozenset[DocumentStatus] = frozenset(
    {
        DocumentStatus.TE_CONTROLEREN,
        DocumentStatus.KLAAR_OM_TE_BOEKEN,
        DocumentStatus.HANDMATIG_AFMAKEN,
        DocumentStatus.BOEKEN_MISLUKT,
    }
)


def _utc(t: datetime) -> datetime:
    """Postgres geeft timestamptz terug in de sessie-tijdzone: altijd naar UTC vergelijken, nooit `replace(tzinfo=…)`."""
    return t.astimezone(UTC) if t.tzinfo else t.replace(tzinfo=UTC)


def sleutel(document_id: uuid.UUID, boek_cyclus: int) -> str:
    return f"boek-{document_id}-{boek_cyclus}"


# --- wachtrij-implementaties (contract: enqueue(administratie_id, document_id)) ------------------------------------

BoekTaak = Callable[..., None]


class BoekWachtrij(Protocol):
    def enqueue(self, *, administratie_id: uuid.UUID, document_id: uuid.UUID) -> str | None:
        """Plant de boeking in. Geeft de trigger-FOUT terug als het starten van de verwerker mislukte (Cloud), anders
        None — zodat "Opnieuw indienen" de uitkomst direct aan de mens kan tonen (21-09, nooit stil)."""
        ...


class InProcessBoekWachtrij:
    """Dev-wachtrij: één worker-thread (boekingen op één administratie nooit door elkaar). `wacht_tot_leeg()` voor
    tests en een nette shutdown."""

    def __init__(self, *, taak: BoekTaak, max_workers: int = 1) -> None:
        self._taak = taak
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="boek-worker")
        self._lock = threading.Lock()
        self._futures: list[Future[None]] = []

    def enqueue(self, *, administratie_id: uuid.UUID, document_id: uuid.UUID) -> str | None:
        with self._lock:
            self._futures = [f for f in self._futures if not f.done()]
            self._futures.append(
                self._executor.submit(self._veilig, administratie_id=administratie_id, document_id=document_id)
            )
        return None

    def _veilig(self, *, administratie_id: uuid.UUID, document_id: uuid.UUID) -> None:
        try:
            self._taak(administratie_id=administratie_id, document_id=document_id)
        except Exception:  # noqa: BLE001 — vangnet: een worker-crash mag de pool nooit stil leegtrekken
            logger.exception("Boek-wachtrijtaak faalde onverwacht voor document %s", document_id)

    def wacht_tot_leeg(self, timeout: float = 60.0) -> None:
        with self._lock:
            futures = list(self._futures)
        wait(futures, timeout=timeout)


class DirecteBoekWachtrij:
    """Synchroon (job/CLI/tests): enqueue voert de taak meteen uit in de aanroepende thread."""

    def __init__(self, *, taak: BoekTaak) -> None:
        self._taak = taak
        self.verwerkt: list[uuid.UUID] = []

    def enqueue(self, *, administratie_id: uuid.UUID, document_id: uuid.UUID) -> str | None:
        try:
            self._taak(administratie_id=administratie_id, document_id=document_id)
        except Exception:  # noqa: BLE001
            logger.exception("Boek-wachtrijtaak faalde onverwacht voor document %s", document_id)
        self.verwerkt.append(document_id)
        return None


class CloudRunJobBoekWachtrij:
    """Cloud: elke enqueue triggert één uitvoering van de on-demand job `rlz-boek-wachtrij` (zelfde metadata-server-
    patroon als de extractie-wachtrij). De statusrij + claimtabel zíjn de opdracht: geen payload nodig, `run.invoker`
    volstaat. Faalt de trigger → het document blijft zichtbaar op "Wordt geboekt…" en het scheduler-vangnet (2 min)
    pakt het op; de uitkomst van élke trigger gaat als audit-rij naar de tellers (nooit stil)."""

    def __init__(self, *, job_resource: str, trigger: Callable[[str], None] | None = None) -> None:
        self._job_resource = job_resource
        self._trigger = trigger

    def enqueue(self, *, administratie_id: uuid.UUID, document_id: uuid.UUID) -> str | None:
        fout: str | None = None
        try:
            if self._trigger is not None:
                self._trigger(self._job_resource)
            else:
                from app.projecten.cijfers_run import _trigger_cloud_run_job

                _trigger_cloud_run_job(self._job_resource)
        except Exception as exc:  # noqa: BLE001 — de boeking is ingediend; vangnet = scheduler
            fout = f"{type(exc).__name__}: {exc}"[:500]
            logger.exception(
                "Boek-wachtrij: Cloud Run-job %s triggeren mislukt voor document %s — het scheduler-vangnet pakt 'm op",
                self._job_resource,
                document_id,
            )
        job = self._job_resource.rsplit("/", 1)[-1]
        _audit_stil(
            administratie_id,
            document_id, AUDIT_TRIGGER,
            {"uitkomst": "mislukt" if fout else "geslaagd", "job": job, "fout": fout},
        )
        if fout:
            # 21-09 (kernprincipe 4): de mislukte start stond alleen in het audit — de tijdlijn van het document zei
            # "de boeking loopt op de achtergrond" en daarna niets. Nu één zichtbare systeemregel op de tijdlijn.
            _tijdlijn_stil(
                administratie_id,
                document_id, {
                    "boek_wachtrij_trigger": {"uitkomst": "mislukt", "job": job, "fout": fout},
                    "reden": (
                        f"achtergrond-schrijver starten mislukt (job {job}): {fout} — het scheduler-vangnet (elke "
                        f"2 min) pakt de boeking op; blijft de rij op 'Wordt geboekt…' staan, kies 'Opnieuw indienen'"
                    ),
                },
            )
        return fout


_wachtrij: BoekWachtrij | None = None


def _standaard_wachtrij() -> BoekWachtrij:
    global _wachtrij
    if _wachtrij is None:
        if settings.boek_wachtrij_job_resource:
            _wachtrij = CloudRunJobBoekWachtrij(job_resource=settings.boek_wachtrij_job_resource)
        else:
            _wachtrij = InProcessBoekWachtrij(taak=verwerk_boek_taak)
    return _wachtrij


def _audit_stil(administratie_id: uuid.UUID, document_id: uuid.UUID, actie: str, nieuwe_waarde: dict) -> None:
    try:
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            record_audit_event(
                session,
                actor_id=SYSTEEM_ACTOR_ID,
                module="boekhouding",
                tabel="document",
                record_id=document_id,
                actie=actie,
                correlatie_id=document_id,
                nieuwe_waarde=nieuwe_waarde,
                administratie_id=administratie_id,
            )
    except Exception:  # noqa: BLE001
        logger.exception("Boek-wachtrij: audit %s niet geschreven voor document %s", actie, document_id)


def _tijdlijn_stil(administratie_id: uuid.UUID, document_id: uuid.UUID, detail: dict) -> None:
    """Eén systeemregel op de tijdlijn (van = naar = wordt_geboekt, geen statusovergang) — alleen als het document nog
    op wordt_geboekt staat; een fout hier mag de indiening nooit breken."""
    try:
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            document = session.get(Document, document_id)
            if document is None or document.status != DocumentStatus.WORDT_GEBOEKT:
                return
            session.add(
                DocumentGebeurtenis(
                    id=uuid.uuid4(),
                    document_id=document_id,
                    van_status=DocumentStatus.WORDT_GEBOEKT,
                    naar_status=DocumentStatus.WORDT_GEBOEKT,
                    actor_id=SYSTEEM_ACTOR_ID,
                    detail=detail,
                )
            )
    except Exception:  # noqa: BLE001
        logger.exception("Boek-wachtrij: tijdlijnregel niet geschreven voor document %s", document_id)


def laatste_trigger(administratie_id: uuid.UUID, document_id: uuid.UUID) -> dict | None:
    """De jongste `boek_wachtrij_trigger`-audit van dit document: {uitkomst, job, fout, tijdstip} of None (geen
    job-resource: lokaal/thread)."""
    from app.db.models import AuditEvent

    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        rij = session.execute(
            select(AuditEvent.nieuwe_waarde, AuditEvent.tijdstip)
            .where(AuditEvent.actie == AUDIT_TRIGGER, AuditEvent.record_id == document_id)
            .order_by(AuditEvent.tijdstip.desc())
            .limit(1)
        ).first()
    if rij is None:
        return None
    nw = dict(rij[0] or {})
    nw["tijdstip"] = _utc(rij[1]).isoformat()
    return nw


# --- synchroon deel: indienen -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BoekIngediend:
    document_id: uuid.UUID
    status: DocumentStatus
    volgende_document_id: uuid.UUID | None
    sleutel: str
    boek_cyclus: int
    #: soort van het volgende document (de frontend kiest er de route mee: inkoop/verkoop/omzet/…)
    volgende_document_soort: str | None = None


def kies_volgend_document(
    *, administratie_id: uuid.UUID, huidig_id: uuid.UUID, volgorde: list[uuid.UUID] | None
) -> tuple[uuid.UUID, str] | None:
    """Spiegel van `kiesVolgendDocument` (frontend, besluit Peter 07-09: positie in de GETOONDE lijstvolgorde wint):
    het eerstvolgende VERWERKBARE document ná het huidige in `volgorde` (de id's zoals de lijst ze toonde), daarna
    cyclisch vanaf de bovenkant, het huidige zelf uitgesloten — statussen VERS uit de database (de eigen boeking is
    net van status veranderd). Zonder `volgorde`: de backend-lijstvolgorde (nieuwste eerst), exact wat de
    documentenlijst zonder filter toont."""
    with scoped_session(administratie_id) as session:
        if volgorde:
            rijen = session.execute(
                select(Document.id, Document.status, Document.soort).where(
                    Document.administratie_id == administratie_id, Document.id.in_(volgorde)
                )
            ).all()
            per_id = {rij.id: (rij.status, rij.soort) for rij in rijen}
            ids = [d for d in volgorde if d in per_id]
        else:
            rijen = session.execute(
                select(Document.id, Document.status, Document.soort)
                .where(Document.administratie_id == administratie_id)
                .order_by(Document.aangemaakt_op.desc())
            ).all()
            per_id = {rij.id: (rij.status, rij.soort) for rij in rijen}
            ids = [rij.id for rij in rijen]
    n = len(ids)
    if n == 0:
        return None
    start = ids.index(huidig_id) if huidig_id in ids else n - 1
    for offset in range(1, n + 1):
        kandidaat = ids[(start + offset) % n]
        if kandidaat != huidig_id and per_id.get(kandidaat, (None, None))[0] in VERWERKBARE_STATUSSEN:
            return kandidaat, str(per_id[kandidaat][1])
    return None


def dien_boeking_in(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    match_afwijking_bevestigd: bool = False,
    materiaal_afwijking_bevestigd: bool = False,
    lijst_volgorde: list[uuid.UUID] | None = None,
    wachtrij: BoekWachtrij | None = None,
    timing: checks_extern.StapTiming | None = None,
) -> BoekIngediend:
    """Het synchrone deel van "Boeken in RLZ" — zie de moduledocstring. Raise-t exact de bestaande boek-fouten
    (statusmachine, accordering, match/materiaal 409, checks, toggle, volumerem) zodat de router ze ongewijzigd
    vertaalt; groen = `wordt_geboekt` + enqueue + het volgende document."""
    timing = timing or checks_extern.StapTiming()
    _, _, status_bij_start = boeken_service.toets_poorten_voor_boekpoging(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        match_afwijking_bevestigd=match_afwijking_bevestigd,
        materiaal_afwijking_bevestigd=materiaal_afwijking_bevestigd,
    )
    if status_bij_start == DocumentStatus.WORDT_GEBOEKT:
        raise boeken_service.OngeldigeBoekpoging("Deze boeking is al ingediend en wordt op de achtergrond geboekt")
    extern = boeken_service.extern_checks_modus(status_bij_start=status_bij_start, extra_overgang_detail=None)

    # Harde checks: lokaal direct, extern uit de cache als de vingerafdruk gelijk is en ≤ 15 min — anders (retry, of
    # geen geldig rapport) deze ene keer wél synchroon extern. Nooit stil overslaan.
    rapport = voer_checks_uit(administratie_id=administratie_id, document_id=document_id, extern=extern, timing=timing)
    if rapport.geblokkeerd:
        raise boeken_service.BoekenGeblokkeerdDoorChecks(rapport)

    t_db = time.perf_counter()
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        assert document is not None
        boeken_service._zorg_voor_klaar_om_te_boeken(session, document=document, actor_id=actor_id)

    with scoped_session(administratie_id) as session:
        if not boeken_service._is_boeken_toegestaan(session, administratie_id=administratie_id):
            raise boeken_service.BoekenUitgeschakeld(
                "Boeken staat uit voor deze administratie of via de globale kill switch"
            )
        boeken_service.toets_volumerem(
            session, administratie_id=administratie_id, document_id=document_id, actor_id=actor_id
        )

    voorstel = haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
    key = sleutel(document_id, voorstel.boek_cyclus)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        assert document is not None
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.WORDT_GEBOEKT,
            actor_id=actor_id,
            detail={
                "reden": "Boeken in RLZ ingediend — de boeking loopt op de achtergrond",
                "boek_wachtrij": {
                    "sleutel": key,
                    "actor_id": str(actor_id),
                    "match_afwijking_bevestigd": match_afwijking_bevestigd,
                    "materiaal_afwijking_bevestigd": materiaal_afwijking_bevestigd,
                    "extern_checks": extern,
                    "checks_extern_uit_cache": rapport.extern_uit_cache,
                },
            },
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="document",
            record_id=document_id,
            actie=AUDIT_INGEDIEND,
            correlatie_id=document_id,
            nieuwe_waarde={"sleutel": key, "boek_cyclus": voorstel.boek_cyclus, "extern_checks": extern},
            administratie_id=administratie_id,
        )
    timing.tel("boek.db", (time.perf_counter() - t_db) * 1000)

    (wachtrij or _standaard_wachtrij()).enqueue(administratie_id=administratie_id, document_id=document_id)
    with timing.met("boek.volgende"):
        volgende = kies_volgend_document(
            administratie_id=administratie_id, huidig_id=document_id, volgorde=lijst_volgorde
        )
    return BoekIngediend(
        document_id=document_id,
        status=DocumentStatus.WORDT_GEBOEKT,
        volgende_document_id=volgende[0] if volgende else None,
        volgende_document_soort=volgende[1] if volgende else None,
        sleutel=key,
        boek_cyclus=voorstel.boek_cyclus,
    )


# --- worker -----------------------------------------------------------------------------------------------------------


def _wachtrij_detail(session, document_id: uuid.UUID) -> dict:  # noqa: ANN001
    """Het `boek_wachtrij`-detail van de jongste ÉCHTE overgang naar wordt_geboekt (actor + bevestigingsvlaggen). De
    tijdlijnregels van 21-09 (trigger mislukt, opnieuw ingediend) hebben van = naar = wordt_geboekt en tellen niet —
    anders verloor de verwerker de actor en de bevestigingsvlaggen van de indiening."""
    gebeurtenis = session.scalar(
        select(DocumentGebeurtenis)
        .where(
            DocumentGebeurtenis.document_id == document_id,
            DocumentGebeurtenis.naar_status == DocumentStatus.WORDT_GEBOEKT,
            DocumentGebeurtenis.van_status != DocumentStatus.WORDT_GEBOEKT,
        )
        .order_by(DocumentGebeurtenis.tijdstip.desc())
        .limit(1)
    )
    return dict((gebeurtenis.detail or {}).get("boek_wachtrij") or {}) if gebeurtenis is not None else {}


def _claim(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, boek_cyclus: int, verwerker: str
) -> BoekWachtrijClaim | None:
    """INSERT = claim. Bestaat de sleutel al: alleen overnemen als de vorige verwerker gestrand is (geen afronding en
    ouder dan de herstelgrens) — anders None (een ander is bezig of klaar)."""
    key = sleutel(document_id, boek_cyclus)
    nu = datetime.now(UTC)
    grens = nu - timedelta(minutes=settings.boek_wachtrij_herstel_minuten)
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        bestaand = session.get(BoekWachtrijClaim, key)
        if bestaand is None:
            claim = BoekWachtrijClaim(
                sleutel=key,
                document_id=document_id,
                administratie_id=administratie_id,
                boek_cyclus=boek_cyclus,
                geclaimd_op=nu,
                verwerker=verwerker,
            )
            session.add(claim)
            session.flush()
            session.expunge(claim)
            return claim
        gestrand = bestaand.afgerond_op is None and _utc(bestaand.geclaimd_op) <= grens
        # Een afgeronde claim mét uitkomst 'mislukt' blokkeert een "Opnieuw" (zelfde boek_cyclus, zelfde sleutel) niet:
        # de retry is een nieuwe poging op dezelfde idempotency-key — 'geboekt' blijft wél definitief geblokkeerd.
        retry = bestaand.afgerond_op is not None and bestaand.uitkomst == "mislukt"
        if gestrand or retry:
            bestaand.geclaimd_op = nu
            bestaand.verwerker = f"{verwerker} ({'hervat' if gestrand else 'opnieuw'})"
            bestaand.afgerond_op = None
            bestaand.uitkomst = None
            session.flush()
            session.expunge(bestaand)
            return bestaand
        return None


def _rond_claim_af(*, administratie_id: uuid.UUID, key: str, uitkomst: str) -> None:
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        claim = session.get(BoekWachtrijClaim, key)
        if claim is not None:
            claim.afgerond_op = datetime.now(UTC)
            claim.uitkomst = uitkomst


def verwerk_boek_taak(*, administratie_id: uuid.UUID, document_id: uuid.UUID, verwerker: str = "thread") -> str:
    """De worker: één ingediende boeking afronden. Uitkomst 'geboekt' | 'mislukt' | 'overgeslagen' (niet meer op
    wordt_geboekt, of al door een andere verwerker geclaimd). Elke fout wordt een zichtbare `boeken_mislukt` mét
    reden; niets blijft stil op wordt_geboekt staan."""
    t0 = time.perf_counter()
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        document = session.get(Document, document_id)
        if document is None or document.status != DocumentStatus.WORDT_GEBOEKT:
            logger.info("Boek-wachtrij: document %s staat niet (meer) op wordt_geboekt — overgeslagen", document_id)
            return "overgeslagen"
        detail = _wachtrij_detail(session, document_id)
    voorstel = haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
    claim = _claim(
        administratie_id=administratie_id, document_id=document_id, boek_cyclus=voorstel.boek_cyclus, verwerker=verwerker
    )
    if claim is None:
        logger.info("Boek-wachtrij: %s al geclaimd door een andere verwerker — overgeslagen", document_id)
        return "overgeslagen"

    actor_id = uuid.UUID(detail["actor_id"]) if detail.get("actor_id") else SYSTEEM_ACTOR_ID
    timing = checks_extern.StapTiming()
    from app.doorbelasting import orkestratie  # lokaal: geen kring (orkestratie → boeken)

    uitkomst = "geboekt"
    fout: str | None = None
    try:
        gecombineerd = orkestratie.boek_document_met_doorbelasting(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor_id,
            extra_overgang_detail={"via_boek_wachtrij": claim.sleutel},
            match_afwijking_bevestigd=bool(detail.get("match_afwijking_bevestigd")),
            materiaal_afwijking_bevestigd=bool(detail.get("materiaal_afwijking_bevestigd")),
            extern_checks=detail.get("extern_checks") or checks_extern.AUTO,
            timing=timing,
        )
        if gecombineerd.doorbelasting_fout:
            fout = f"inkoop geboekt; doorbelasting (deels) mislukt: {gecombineerd.doorbelasting_fout}"
    except boeken_service.RlzBoekingMislukt as exc:
        # boek_document heeft het document al op boeken_mislukt gezet (mét reden).
        uitkomst, fout = "mislukt", str(exc)
    except boeken_service.BoekenGeblokkeerdDoorChecks as exc:
        uitkomst = "mislukt"
        fout = "harde checks blokkeren bij het boeken: " + "; ".join(
            f"{r.naam}: {r.melding}" for r in exc.rapport.resultaten if not r.ok
        )
        _zet_mislukt_stil(administratie_id, document_id, actor_id, fout)
    except Exception as exc:  # noqa: BLE001 — élke andere fout: zichtbaar mislukt, nooit limbo
        uitkomst, fout = "mislukt", f"{type(exc).__name__}: {exc}"
        logger.exception("Boek-wachtrij: boeken van %s mislukt", document_id)
        _zet_mislukt_stil(administratie_id, document_id, actor_id, str(exc))

    _rond_claim_af(administratie_id=administratie_id, key=claim.sleutel, uitkomst=uitkomst)
    duur_ms = round((time.perf_counter() - t0) * 1000, 1)
    _audit_stil(
        administratie_id,
        document_id,
        AUDIT_AFGEROND,
        {
            "sleutel": claim.sleutel,
            "uitkomst": uitkomst,
            "fout": (fout or "")[:500] or None,
            "duur_ms": duur_ms,
            "verwerker": verwerker,
            "stappen_ms": timing.als_dict(),
        },
    )
    logger.info(
        "boek_wachtrij_afgerond",
        extra={"document_id": str(document_id), "uitkomst": uitkomst, "duur_ms": duur_ms, "stappen": timing.als_dict()},
    )
    return uitkomst


def _zet_mislukt_stil(administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, reden: str) -> None:
    """Alleen als het document nog op wordt_geboekt staat (boek_document zet 'm zelf al bij een RLZ-fout)."""
    try:
        with scoped_session(administratie_id, actor_id=actor_id) as session:
            document = session.get(Document, document_id)
            if document is not None and document.status == DocumentStatus.WORDT_GEBOEKT:
                _schrijf_overgang(
                    session,
                    document=document,
                    naar=DocumentStatus.BOEKEN_MISLUKT,
                    actor_id=actor_id,
                    detail={"fout": reden, "reden": f"boeken mislukt: {reden}"},
                )
    except Exception:  # noqa: BLE001
        logger.exception("Boek-wachtrij: boeken_mislukt niet gezet voor document %s", document_id)


# --- job / vangnetten -------------------------------------------------------------------------------------------------


def _wordt_geboekt_documenten(*, ouder_dan: timedelta | None = None) -> list[tuple[uuid.UUID, uuid.UUID, datetime]]:
    """(administratie_id, document_id, sinds) van élk document op wordt_geboekt, oudste eerst; `ouder_dan` filtert op
    het moment van indienen (jongste overgang naar wordt_geboekt)."""
    from app.db.models import Administratie

    with scoped_session(None) as session:
        administratie_ids = [rij.id for rij in session.scalars(select(Administratie))]
    grens = datetime.now(UTC) - ouder_dan if ouder_dan else None
    uit: list[tuple[uuid.UUID, uuid.UUID, datetime]] = []
    for administratie_id in administratie_ids:
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            for document in session.scalars(
                select(Document).where(
                    Document.administratie_id == administratie_id, Document.status == DocumentStatus.WORDT_GEBOEKT
                )
            ):
                # `sinds` = de échte indiening (van ≠ wordt_geboekt): de tijdlijnregels "trigger mislukt"/"opnieuw
                # ingediend" (van = naar = wordt_geboekt, 21-09) verschuiven het indienmoment niet.
                sinds = session.scalar(
                    select(DocumentGebeurtenis.tijdstip)
                    .where(
                        DocumentGebeurtenis.document_id == document.id,
                        DocumentGebeurtenis.naar_status == DocumentStatus.WORDT_GEBOEKT,
                        DocumentGebeurtenis.van_status != DocumentStatus.WORDT_GEBOEKT,
                    )
                    .order_by(DocumentGebeurtenis.tijdstip.desc())
                    .limit(1)
                ) or datetime.now(UTC)
                sinds = _utc(sinds)
                if grens is None or sinds <= grens:
                    uit.append((administratie_id, document.id, sinds))
    uit.sort(key=lambda t: t[2])
    return uit


def verwerk_boek_wachtrij(*, verwerker: str = "job") -> int:
    """Job-/CLI-entrypoint (`boek-wachtrij-verwerken`): álle documenten op wordt_geboekt synchroon afronden, oudste
    eerst; de claim per sleutel maakt overlap met een tweede uitvoering (trigger + scheduler) veilig. Retourneert het
    aantal daadwerkelijk verwerkte (geboekt of mislukt) documenten."""
    verwerkt = 0
    for administratie_id, document_id, _ in _wordt_geboekt_documenten():
        if verwerk_boek_taak(administratie_id=administratie_id, document_id=document_id, verwerker=verwerker) != (
            "overgeslagen"
        ):
            verwerkt += 1
    return verwerkt


def herstel_achtergebleven_boekingen(*, wachtrij: BoekWachtrij | None = None) -> int:
    """Startup-vangnet (dev: de in-process wachtrij overleeft een herstart niet) en scheduler-vangnet: élk document dat
    langer dan `settings.boek_wachtrij_herstel_minuten` op wordt_geboekt staat wordt opnieuw ge-enqueued (de claim
    wordt bij het verwerken hervat als de vorige verwerker gestrand is). Retourneert het aantal."""
    hersteld = 0
    for administratie_id, document_id, sinds in _wordt_geboekt_documenten(
        ouder_dan=timedelta(minutes=settings.boek_wachtrij_herstel_minuten)
    ):
        logger.info("Boek-wachtrij herstel: document %s staat sinds %s op wordt_geboekt — opnieuw ingepland", document_id, sinds)
        (wachtrij or _standaard_wachtrij()).enqueue(administratie_id=administratie_id, document_id=document_id)
        hersteld += 1
    return hersteld


def verouderde_boekingen(*, nu: datetime | None = None) -> list[tuple[uuid.UUID, uuid.UUID, datetime]]:
    """Documenten die langer dan de herstelgrens (`BOEK_WACHTRIJ_HERSTEL_MINUTEN`, 10) op wordt_geboekt staan — de bron
    voor de regressie-LET-OP `boek_wachtrij_gestrand` (reconciliatie) en de kwartier-probe (bewaking)."""
    del nu
    return _wordt_geboekt_documenten(ouder_dan=timedelta(minutes=settings.boek_wachtrij_herstel_minuten))


@dataclass(frozen=True)
class GestrandeBoeking:
    administratie_id: uuid.UUID
    document_id: uuid.UUID
    sinds: datetime
    minuten: int
    #: jongste trigger-audit: 'geslaagd' | 'mislukt' | None (geen job-resource / geen spoor)
    trigger_uitkomst: str | None
    trigger_fout: str | None
    trigger_op: str | None


def gestrande_boekingen(*, nu: datetime | None = None) -> list[GestrandeBoeking]:
    """`verouderde_boekingen` verrijkt mét de reden uit het jongste `boek_wachtrij_trigger`-audit ("trigger mislukt:
    <fout>") — dát is wat de LET-OP, de probe en de tijdlijn aan de mens laten zien (21-09)."""
    nu = nu or datetime.now(UTC)
    uit: list[GestrandeBoeking] = []
    for administratie_id, document_id, sinds in verouderde_boekingen():
        trigger = laatste_trigger(administratie_id, document_id) or {}
        uit.append(
            GestrandeBoeking(
                administratie_id=administratie_id,
                document_id=document_id,
                sinds=sinds, minuten=max(0, int((nu - sinds).total_seconds() // 60)),
                trigger_uitkomst=trigger.get("uitkomst"),
                trigger_fout=trigger.get("fout"),
                trigger_op=trigger.get("tijdstip"),
            )
        )
    return uit


@dataclass(frozen=True)
class OpnieuwIngediend:
    document_id: uuid.UUID
    status: DocumentStatus
    sleutel: str | None
    #: 'geslaagd' (job gestart) | 'mislukt' (trigger-fout, vangnet volgt) | 'lokaal' (in-process/directe wachtrij)
    trigger_uitkomst: str
    trigger_fout: str | None


def dien_opnieuw_in(
    *, administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    wachtrij: BoekWachtrij | None = None,
) -> OpnieuwIngediend:
    """"Opnieuw indienen" op een boeking die op wordt_geboekt blijft hangen (21-09; rij op /reconciliatie, balk op het
    document, lijstlabel "loopt vast"): géén nieuwe boeking en geen statuswissel — de bestaande sleutel/claim blijft
    (idempotent: een gestrande claim wordt door de verwerker hervat), alleen de verwerker wordt opnieuw gestart.
    Tijdlijnregel + audit `boek_wachtrij_opnieuw_ingediend`; de trigger-uitkomst gaat direct terug naar de mens.
    Niet op wordt_geboekt = `OngeldigeBoekpoging` (409 in de router) — een boeking die intussen geboekt of mislukt is,
    wordt nooit stil opnieuw ingediend."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise boeken_service.OngeldigeBoekpoging("Document niet gevonden")
        if document.status != DocumentStatus.WORDT_GEBOEKT:
            raise boeken_service.OngeldigeBoekpoging(
                f"Opnieuw indienen kan alleen bij 'Wordt geboekt…' — dit document staat op {document.status.value}"
            )
        sleutel_ = (_wachtrij_detail(session, document_id) or {}).get("sleutel")
        session.add(
            DocumentGebeurtenis(
                id=uuid.uuid4(),
                document_id=document_id,
                van_status=DocumentStatus.WORDT_GEBOEKT,
                naar_status=DocumentStatus.WORDT_GEBOEKT,
                actor_id=actor_id,
                detail={
                    "boek_wachtrij_opnieuw": {"sleutel": sleutel_},
                    "reden": "Opnieuw ingediend — de achtergrond-schrijver wordt opnieuw gestart (zelfde boeking, zelfde "
                    "sleutel; niets wordt dubbel geboekt)",
                },
            )
        )
        record_audit_event(
            session, actor_id=actor_id,
            module="boekhouding",
            tabel="document",
            record_id=document_id,
            actie=AUDIT_OPNIEUW,
            correlatie_id=document_id,
            nieuwe_waarde={"sleutel": sleutel_},
            administratie_id=administratie_id,
        )
    gekozen = wachtrij or _standaard_wachtrij()
    fout = gekozen.enqueue(administratie_id=administratie_id, document_id=document_id)
    uitkomst = ("mislukt" if fout else "geslaagd") if isinstance(gekozen, CloudRunJobBoekWachtrij) else "lokaal"
    return OpnieuwIngediend(
        document_id=document_id,
        status=DocumentStatus.WORDT_GEBOEKT,
        sleutel=sleutel_,
        trigger_uitkomst=uitkomst,
        trigger_fout=fout,
    )
