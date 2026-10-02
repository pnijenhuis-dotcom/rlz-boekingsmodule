"""Dagelijkse accordeur-herinnering (mockup-besluit: "dagelijkse push 09:00 alleen bij >0 open").

Job-logica (CLI `accordeur-herinneringen`, Cloud Scheduler 09:00 Europe/Amsterdam):
- Selectie: per administratie de open accorderingsrondes -> wie is aan de beurt
  (accordering.service.aantallen_aan_de_beurt — exact de wachtrij-definitie), geaggregeerd per
  accordeur. Alleen actieve klant-accordeurs; 0 open = níéts (geen bericht, geen rij).
- Idempotent per dag per accordeur via platform.accordeur_herinnering (unique gebruiker+datum):
  een herhaalde run stuurt nooit dubbel. Claim-vóór-verzenden: de rij gaat op 'bezig' en pas na
  geslaagde verzending op 'verzonden'; blijft 'bezig' hangen (crash mid-verzending) dan telt dat
  als fout in het rapport en wordt er NOOIT automatisch opnieuw gestuurd — zichtbaar via exit 1
  (F3.2-alert), nooit stil en nooit dubbel. 'mislukt' (aantoonbaar niet verzonden) wordt bij een
  herhaalde run wél opnieuw geprobeerd.
- Kanaal: PUSH-ONLY (besluit Peter 02-10 "zet die mail uit over hoeveel facturen er klaar staan …
  geen mails meer"; herziet de push-anders-mail-regel van 15-08): push naar álle actieve
  subscripties van de accordeur (apparaat niet ingetrokken); vervallen subscripties (404/410)
  worden gemarkeerd; geen subscriptie of geen enkele push gelukt = overslaan mét teller
  `overgeslagen_geen_push` in de joblog + één administratie-loos audit-event `accordeur_melding_run`
  per run (bron van de reconciliatie-dagteller "Accordeur-meldingen") — NOOIT e-mail. De
  handmatige herinnering per document (kantoorknop, app/accordering/herinnering.py) blijft
  push-anders-mail: dat is een bewuste mensactie.
- Volumerem (noodrem): max. settings.herinnering_max_berichten_per_run berichten per run —
  daarboven stopt de run zichtbaar (exit 1 via het rapport), nooit stil doorpompen.

HARD PRINCIPE (BESLISSINGEN "Accordeur-notificaties"): het bericht bevat aantal + deep-link
naar de PWA — nooit een goedkeuren-zonder-inloggen-mechanisme; de auth-cadans blijft de poort."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.accordering import service as accordering_service
from app.berichten import verzending
from app.berichten.models import AccordeurHerinnering, HerinneringKanaal, HerinneringStatus
from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import Administratie, Gebruiker, GebruikerRol, GebruikerStatus
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.tijd import vandaag_nl

TIJDZONE = ZoneInfo("Europe/Amsterdam")
logger = logging.getLogger("app.berichten")

#: Audit-actie van het run-event (één administratie-loze rij per job-run, systeem-actor) — gelezen door
#: `app/reconciliatie/automatiseringen.py` (teller ACCORDEUR_MELDINGEN). `soort` = 'dag_herinnering' | 'nieuwe_facturen'.
RUN_AUDIT_ACTIE = "accordeur_melding_run"


def schrijf_melding_run_audit(*, soort: str, tellers: dict) -> None:
    """Eén administratie-loos audit-event per run — de bron van de reconciliatie-dagteller (verwacht/gedaan/
    overgeslagen_geen_push). Mag de job nooit laten omvallen."""
    try:
        with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
            record_audit_event(
                session,
                actor_id=SYSTEEM_ACTOR_ID,
                module="boekhouding",
                tabel="accordeur_melding",
                record_id=SYSTEEM_ACTOR_ID,
                actie=RUN_AUDIT_ACTIE,
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde={"soort": soort, **tellers},
            )
    except Exception:  # noqa: BLE001 — de teller mag de job nooit laten omvallen
        logger.exception("audit %s (%s) mislukt", RUN_AUDIT_ACTIE, soort)


def log_overgeslagen_geen_push(*, soort: str, gebruiker_id: uuid.UUID, detail: dict | None) -> None:
    """Zichtbare joblog-regel per overgeslagen accordeur (alleen gebruikers-id, geen PII)."""
    uitleg = (detail or {}).get("uitleg") or (detail or {}).get("push_fouten") or ""
    logger.info("%s overgeslagen_geen_push gebruiker=%s %s", soort, gebruiker_id, uitleg)


@dataclass
class HerinneringRapport:
    """Job-uitkomst — elke teller is zichtbaar in de joblog; is_fout bepaalt de exit-code."""

    verzonden_push: int = 0
    al_verzonden: int = 0
    overgeslagen_geen_push: int = 0  # 02-10: geen push-inschrijving / push mislukt → overgeslagen, nooit mail
    geen_open_werk: int = 0
    mislukt: int = 0
    onafgemaakt: int = 0  # rijen die op 'bezig' bleven hangen — mens beoordeelt, nooit auto-dubbel
    subscripties_vervallen: int = 0
    volumerem_bereikt: bool = False
    fouten: list[str] = field(default_factory=list)

    @property
    def is_fout(self) -> bool:
        return bool(self.mislukt or self.onafgemaakt or self.volumerem_bereikt)

    def als_tellers(self) -> dict:
        return {
            "verzonden_push": self.verzonden_push,
            "al_verzonden": self.al_verzonden,
            "overgeslagen_geen_push": self.overgeslagen_geen_push,
            "geen_open_werk": self.geen_open_werk,
            "mislukt": self.mislukt,
            "onafgemaakt": self.onafgemaakt,
            "subscripties_vervallen": self.subscripties_vervallen,
            "volumerem_bereikt": self.volumerem_bereikt,
        }


def _vandaag() -> date:
    return vandaag_nl()


def bericht_teksten(aantal: int) -> tuple[str, str, str]:
    """(onderwerp, pushtekst, mailtekst) — de pushtekst is de exacte mockup-copy
    (mockup/accordeur.html #pushteller, incl. enkelvoud/meervoud). Onderwerp/mailtekst blijven als
    vorm bestaan (tests, consistentie) maar worden sinds 02-10 door deze job niet meer verzonden."""
    facturen = "1 factuur" if aantal == 1 else f"{aantal} facturen"
    wachten = "wacht" if aantal == 1 else "wachten"
    onderwerp = f"Goedkeuren: er {wachten} nog {facturen} op je akkoord"
    pushtekst = f"Goedemorgen! Er {wachten} nog {facturen} op je akkoord."
    link = f"{settings.app_basis_url.rstrip('/')}/accordeur"
    mailtekst = (
        f"Goedemorgen!\n\n"
        f"Er {wachten} nog {facturen} op je akkoord.\n\n"
        f"Open de app om te beoordelen:\n{link}\n\n"
        f"Deze link opent alleen de app — goedkeuren gebeurt altijd ín de app, na ontgrendelen.\n\n"
        f"Administratiekantoor Nijenhuis"
    )
    return onderwerp, pushtekst, mailtekst


def open_aantallen_per_accordeur() -> dict[uuid.UUID, int]:
    """Alle administraties langs (RLS: één scope per transactie) en de aan-de-beurt-tellingen
    per accordeur optellen."""
    with scoped_session(None) as session:
        administratie_ids = list(session.scalars(select(Administratie.id).where(Administratie.actief.is_(True))))
    totalen: dict[uuid.UUID, int] = {}
    for administratie_id in administratie_ids:
        for accordeur_id, aantal in accordering_service.aantallen_aan_de_beurt(
            administratie_id=administratie_id
        ).items():
            totalen[accordeur_id] = totalen.get(accordeur_id, 0) + aantal
    return totalen


def _actieve_accordeurs() -> list[Gebruiker]:
    with scoped_session(None) as session:
        rijen = session.scalars(
            select(Gebruiker).where(
                Gebruiker.rol == GebruikerRol.KLANT_ACCORDEUR,
                Gebruiker.status == GebruikerStatus.ACTIEF,
                Gebruiker.gepseudonimiseerd_op.is_(None),
            )
        ).all()
        session.expunge_all()
        return sorted(rijen, key=lambda g: str(g.id))


@dataclass(frozen=True)
class _Claim:
    herinnering_id: uuid.UUID | None
    uitkomst: str  # 'nieuw' | 'opnieuw' | 'al_verzonden' | 'onafgemaakt'


def _claim_dagrij(gebruiker_id: uuid.UUID, vandaag: date, aantal: int) -> _Claim:
    """Idempotentie-anker: claim (of hervind) de dagrij vóór er iets verstuurd wordt."""
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        bestaande = session.scalars(
            select(AccordeurHerinnering).where(
                AccordeurHerinnering.gebruiker_id == gebruiker_id,
                AccordeurHerinnering.datum == vandaag,
            )
        ).first()
        if bestaande is not None:
            if bestaande.status in (HerinneringStatus.VERZONDEN.value, HerinneringStatus.OVERGESLAGEN.value):
                return _Claim(None, "al_verzonden")
            if bestaande.status == HerinneringStatus.BEZIG.value:
                return _Claim(None, "onafgemaakt")
            # mislukt -> opnieuw proberen: rij terug naar bezig (claim), aantal verversen.
            bestaande.status = HerinneringStatus.BEZIG.value
            bestaande.aantal_open = aantal
            return _Claim(bestaande.id, "opnieuw")
        rij = AccordeurHerinnering(gebruiker_id=gebruiker_id, datum=vandaag, aantal_open=aantal)
        session.add(rij)
        try:
            session.flush()
        except IntegrityError:
            # Parallelle run won de race op de unique (gebruiker, datum) — dan is dit een
            # al-geclaimde dag: niet dubbel sturen.
            return _Claim(None, "al_verzonden")
        return _Claim(rij.id, "nieuw")


def _rond_dagrij_af(
    herinnering_id: uuid.UUID, *, status: HerinneringStatus, kanaal: HerinneringKanaal | None, detail: dict | None
) -> None:
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        rij = session.get(AccordeurHerinnering, herinnering_id)
        if rij is None:  # kan niet (we hebben 'm net geclaimd) — maar nooit stil crashen
            return
        rij.status = status.value
        rij.kanaal = kanaal.value if kanaal else None
        rij.detail = detail
        if status == HerinneringStatus.VERZONDEN:
            rij.verzonden_op = datetime.now(UTC)


def _verstuur_voor_accordeur(
    gebruiker: Gebruiker, aantal: int, rapport: HerinneringRapport
) -> tuple[HerinneringStatus, HerinneringKanaal | None, dict | None]:
    """Push-only (alle actieve subscripties) — besluit Peter 02-10; geen e-mail-terugval.
    Retourneert (status, kanaal, detail)."""
    _, pushtekst, _ = bericht_teksten(aantal)
    uitkomst = verzending.verstuur_push_only(
        gebruiker,
        pushtekst=pushtekst,
        url="/accordeur",
        extra_payload={"aantal": aantal, "badge": aantal},
    )
    rapport.subscripties_vervallen += uitkomst.subscripties_vervallen
    return uitkomst.status, uitkomst.kanaal, uitkomst.detail


def verstuur_dagelijkse_herinneringen(*, vandaag: date | None = None) -> HerinneringRapport:
    rapport = HerinneringRapport()
    vandaag = vandaag or _vandaag()
    totalen = open_aantallen_per_accordeur()
    accordeurs = _actieve_accordeurs()
    # Open werk toegewezen aan iemand die geen actieve accordeur (meer) is: geen bericht, maar
    # wél zichtbaar in de joblog — het document blijft anders geruisloos bij een geblokkeerd
    # account hangen (het staat óók gewoon "Bij klant" in de werkvoorraad, dit is een extra oog).
    actieve_ids = {g.id for g in accordeurs}
    for gebruiker_id, aantal in sorted(totalen.items(), key=lambda t: str(t[0])):
        if gebruiker_id not in actieve_ids:
            rapport.fouten.append(
                f"LET-OP: {aantal} open accordering(en) aan de beurt bij {gebruiker_id}, "
                f"maar die gebruiker is geen actieve klant-accordeur — geen herinnering verstuurd"
            )
    verzonden_deze_run = 0
    for gebruiker in accordeurs:
        aantal = totalen.get(gebruiker.id, 0)
        if aantal <= 0:
            rapport.geen_open_werk += 1
            continue
        if verzonden_deze_run >= settings.herinnering_max_berichten_per_run:
            rapport.volumerem_bereikt = True
            rapport.fouten.append(
                f"volumerem: max {settings.herinnering_max_berichten_per_run} berichten per run bereikt — "
                f"resterende accordeurs niet verstuurd (herhaalde run pakt ze op, nooit dubbel)"
            )
            break
        claim = _claim_dagrij(gebruiker.id, vandaag, aantal)
        if claim.uitkomst == "al_verzonden":
            rapport.al_verzonden += 1
            continue
        if claim.uitkomst == "onafgemaakt":
            rapport.onafgemaakt += 1
            rapport.fouten.append(
                f"herinnering voor {gebruiker.id} op {vandaag} bleef op 'bezig' staan "
                f"(gecrashte run?) — niet automatisch opnieuw verstuurd, handmatig beoordelen"
            )
            continue
        status, kanaal, detail = _verstuur_voor_accordeur(gebruiker, aantal, rapport)
        _rond_dagrij_af(claim.herinnering_id, status=status, kanaal=kanaal, detail=detail)
        if status == HerinneringStatus.VERZONDEN:
            verzonden_deze_run += 1
            rapport.verzonden_push += 1
        elif status == HerinneringStatus.OVERGESLAGEN:
            rapport.overgeslagen_geen_push += 1
            log_overgeslagen_geen_push(soort="dag_herinnering", gebruiker_id=gebruiker.id, detail=detail)
        else:
            rapport.mislukt += 1
            rapport.fouten.append(f"verzending mislukt voor {gebruiker.id}: {detail}")
    schrijf_melding_run_audit(soort="dag_herinnering", tellers={"datum": vandaag.isoformat(), **rapport.als_tellers()})
    return rapport
