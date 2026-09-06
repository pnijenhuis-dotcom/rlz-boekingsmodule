"""Reconciliatie-alles als VASTGELEGDE run mét samenvattingsmail (opdracht 06-09 — BESLISSINGEN
"RECONCILIATIE-MELDING + INZICHT").

Wat hier gebeurt — en wat bewust níét:
- De vier reconciliatie-blokken (bank, documenten, omzet, doorbelasting) draaien ONGEWIJZIGD via de
  bestaande CLI-functies in app/cli.py; die printen exact dezelfde regels als voorheen (Peter leest de
  CLI-uitvoer lokaal nog). Ze krijgen alleen een `Verzamelaar` mee die élke regel óók als bevinding
  registreert (blok, soort, administratie, vingerafdruk, tekst, detail).
- Ná afloop schrijft deze motor één `reconciliatie_run`-rij + de bevindingen, ongeacht de exit-code
  (ook een omgevallen blok wordt een bevinding soort 'fout' op blok=<naam>).
- Delta t.o.v. de vorige AFGERONDE run: nieuwe afwijkingen, nieuwe LET-OP-regels (vingerafdruk niet in
  de vorige run én niet "gezien"), nieuwe GEACCEPTEERD-regels, nieuwe fouten, blokken die omvielen én
  verdwenen afwijkingen (herstelmelding). Een ongewijzigde LET-OP-set = géén mail — anders krijg je
  elke dag dezelfde concepten in je postvak.
- Mail via het bestaande SMTP-kanaal (app/berichten/mail, zelfde als de bewaking) naar
  `settings.bewaking_alert_ontvanger`; hooguit één mail per run (`mail_status`); een mailfout maakt de
  job NIET rood (audit + `mail_status='mislukt'`, de bewaking pikt dat op als storing
  'reconciliatie_mail'). Exit 1 blijft exit 1 — de F3.2-policy blijft het vangnet voor "job draait
  niet / crasht".
- "Nu draaien" (Beheerder, Inzicht › Reconciliatie): wachtrij-rij bron 'handmatig' + voertuig
  (dev = thread, cloud = on-demand Cloud Run-job `settings.reconciliatie_job_resource`); de job-CLI
  claimt een wachtende rij als die er is, anders maakt hij zijn eigen rij (bron scheduler/cli).

Geen AI, geen RLZ-writes, geen nieuwe RLZ-leesroutes — alles wat RLZ raakt zit in de blokken zelf."""

from __future__ import annotations

import hashlib
import logging
import threading
import uuid
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.reconciliatie.models import (
    BevindingSoort,
    ReconciliatieBevinding,
    ReconciliatieGezien,
    ReconciliatieRun,
    ReconciliatieRunBron,
    ReconciliatieRunStatus,
)

logger = logging.getLogger(__name__)

_AMSTERDAM = ZoneInfo("Europe/Amsterdam")
BLOKKEN = ("bank", "documenten", "omzet", "doorbelasting")
_VINGERAFDRUK_LENGTE = 16
#: Een run mét live RLZ-controles over tientallen administraties duurt minuten; de job-timeout is 3600 s.
#: `laatst_actief_op` wordt per blok bijgewerkt — langer dan dit zonder teken van leven = afgebroken.
STALE_NA = timedelta(minutes=45)
AFGEBROKEN_REDEN = "Afgebroken — geen voortgang meer gezien (proces of container gestopt); start opnieuw"
_ACTIEF = (ReconciliatieRunStatus.WACHTEND.value, ReconciliatieRunStatus.BEZIG.value)


# ---- vingerafdrukken ---------------------------------------------------------------------------


def vingerafdruk_opruim(*, kant: str, concept_administratie_id: uuid.UUID, rlz_id: uuid.UUID) -> str:
    """Sleutel van een opruim-kandidaat: het RLZ-concept zelf (kant + administratie waar het staat +
    RLZ-GUID) — niet de boeking/run die ernaar wees (die zijn er meerdere per concept, blok D)."""
    ruw = f"{kant}|{concept_administratie_id}|{rlz_id}".encode()
    return hashlib.sha256(ruw).hexdigest()[:_VINGERAFDRUK_LENGTE]


def vingerafdruk_tekst(*, blok: str, soort: str, administratie_id: uuid.UUID | None, tekst: str) -> str:
    """Sleutel voor regels zonder eigen sleutel (administratie-fouten, opruimlijst-fouten, blokcrash)."""
    ruw = f"{blok}|{soort}|{administratie_id or ''}|{tekst}".encode()
    return hashlib.sha256(ruw).hexdigest()[:_VINGERAFDRUK_LENGTE]


# ---- verzamelaar -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Bevinding:
    blok: str
    soort: str  # BevindingSoort
    administratie_id: uuid.UUID | None
    vingerafdruk: str
    tekst: str
    detail: dict | None = None

    @property
    def sleutel(self) -> tuple[str, uuid.UUID | None, str]:
        return (self.soort, self.administratie_id, self.vingerafdruk)


@dataclass
class BlokStand:
    status: str = "ok"  # ok | actie | fout
    exit_code: int | None = None
    gecontroleerd: int = 0
    afwijkingen: int = 0
    geaccepteerd: int = 0
    uitgesloten: int = 0
    let_op: int = 0
    fouten: int = 0
    foutmelding: str | None = None


class Verzamelaar:
    """Registreert per blok de tellers en élke bevinding. De CLI-blokfuncties roepen alleen
    `gecontroleerd()` en `bevinding()` aan; de run-motor doet start/sluit."""

    def __init__(self) -> None:
        self.bevindingen: list[Bevinding] = []
        self.blokken: dict[str, BlokStand] = {}
        self._huidig: str | None = None
        self.gestart_op = datetime.now(UTC)

    def start_blok(self, naam: str) -> None:
        self._huidig = naam
        self.blokken.setdefault(naam, BlokStand())

    def gecontroleerd(self, aantal: int) -> None:
        if self._huidig is not None:
            self.blokken[self._huidig].gecontroleerd += int(aantal or 0)

    def bevinding(
        self,
        *,
        soort: str,
        administratie_id: uuid.UUID | None,
        tekst: str,
        vingerafdruk: str | None = None,
        detail: dict | None = None,
        blok: str | None = None,
    ) -> None:
        blok = blok or self._huidig or "run"
        stand = self.blokken.setdefault(blok, BlokStand())
        vaf = vingerafdruk or vingerafdruk_tekst(blok=blok, soort=soort, administratie_id=administratie_id, tekst=tekst)
        self.bevindingen.append(
            Bevinding(
                blok=blok, soort=soort, administratie_id=administratie_id, vingerafdruk=vaf, tekst=tekst, detail=detail
            )
        )
        if soort == BevindingSoort.AFWIJKING:
            stand.afwijkingen += 1
        elif soort == BevindingSoort.GEACCEPTEERD:
            stand.geaccepteerd += 1
        elif soort == BevindingSoort.UITGESLOTEN:
            stand.uitgesloten += 1
        elif soort == BevindingSoort.LET_OP:
            stand.let_op += 1
        elif soort == BevindingSoort.FOUT:
            stand.fouten += 1

    def sluit_blok(self, naam: str, exit_code: int) -> None:
        stand = self.blokken.setdefault(naam, BlokStand())
        stand.exit_code = exit_code
        if stand.status != "fout":
            stand.status = "ok" if exit_code == 0 else "actie"
        self._huidig = None

    def blok_omgevallen(self, naam: str, exc: BaseException) -> None:
        stand = self.blokken.setdefault(naam, BlokStand())
        stand.status = "fout"
        stand.exit_code = 1
        stand.foutmelding = f"{type(exc).__name__}: {exc}"[:1000]
        self.bevinding(
            soort=BevindingSoort.FOUT.value,
            administratie_id=None,
            tekst=f"FOUT       {naam}-reconciliatie viel om: {exc}",
            blok=naam,
        )
        self._huidig = None

    def samenvatting(self) -> dict[str, dict]:
        return {naam: asdict(stand) for naam, stand in self.blokken.items()}


# ---- delta + mail ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Delta:
    nieuwe_afwijkingen: list[Bevinding] = field(default_factory=list)
    nieuwe_let_op: list[Bevinding] = field(default_factory=list)
    nieuwe_geaccepteerd: list[Bevinding] = field(default_factory=list)
    nieuwe_fouten: list[Bevinding] = field(default_factory=list)
    verdwenen_afwijkingen: list[Bevinding] = field(default_factory=list)
    blokken_fout: list[str] = field(default_factory=list)

    @property
    def is_leeg(self) -> bool:
        return not (
            self.nieuwe_afwijkingen
            or self.nieuwe_let_op
            or self.nieuwe_geaccepteerd
            or self.nieuwe_fouten
            or self.verdwenen_afwijkingen
            or self.blokken_fout
        )

    @property
    def aantal_nieuwe_aandachtspunten(self) -> int:
        return (
            len(self.nieuwe_afwijkingen)
            + len(self.nieuwe_let_op)
            + len(self.nieuwe_geaccepteerd)
            + len(self.nieuwe_fouten)
            + len(self.blokken_fout)
        )


def bepaal_delta(
    *,
    huidig: Sequence[Bevinding],
    vorig: Sequence[Bevinding] | None,
    gezien: set[tuple[uuid.UUID | None, str]],
    samenvatting: dict[str, dict],
) -> Delta:
    """Pure vergelijking. `vorig is None` = er was nog nooit een afgeronde run → alles is nieuw
    (één keer). `gezien` = (administratie_id, vingerafdruk) van actieve "Gezien"-snoozes: die
    LET-OP-regels tellen niet als nieuw en komen niet in de mail."""
    vorig_sleutels = {b.sleutel for b in vorig} if vorig is not None else set()
    vorig_afwijkingen = (
        {(b.administratie_id, b.vingerafdruk): b for b in vorig if b.soort == BevindingSoort.AFWIJKING}
        if vorig is not None
        else {}
    )
    huidig_vafs = {(b.administratie_id, b.vingerafdruk) for b in huidig}

    def nieuw(soort: str) -> list[Bevinding]:
        return [b for b in huidig if b.soort == soort and b.sleutel not in vorig_sleutels]

    # Een LET-OP is óók nieuw als het concept met een ándere reden terugkomt (bv. gestorneerd →
    # gestorneerd+vervallen_run): de werkelijkheid veranderde, en een eerdere "Gezien" geldt dan niet meer.
    vorig_redenen = (
        {
            (b.administratie_id, b.vingerafdruk): (b.detail or {}).get("reden")
            for b in vorig
            if b.soort == BevindingSoort.LET_OP
        }
        if vorig is not None
        else {}
    )
    nieuwe_let_op = [
        b
        for b in huidig
        if b.soort == BevindingSoort.LET_OP
        and (b.administratie_id, b.vingerafdruk) not in gezien
        and (
            b.sleutel not in vorig_sleutels
            or vorig_redenen.get((b.administratie_id, b.vingerafdruk)) != (b.detail or {}).get("reden")
        )
    ]
    verdwenen = [b for sleutel, b in vorig_afwijkingen.items() if sleutel not in huidig_vafs]
    blokken_fout = [naam for naam, stand in samenvatting.items() if stand.get("status") == "fout"]
    return Delta(
        nieuwe_afwijkingen=nieuw(BevindingSoort.AFWIJKING),
        nieuwe_let_op=nieuwe_let_op,
        nieuwe_geaccepteerd=nieuw(BevindingSoort.GEACCEPTEERD),
        nieuwe_fouten=nieuw(BevindingSoort.FOUT),
        verdwenen_afwijkingen=verdwenen,
        blokken_fout=blokken_fout,
    )


_PERSPECTIEF_AFWIJKING = (
    "→ controleren in de app (Inzicht › Reconciliatie) of in Reeleezee; is de situatie beoordeeld en "
    "blijvend, dan 'Accepteren…' mét reden."
)
_PERSPECTIEF_HALF_GEBOEKT = (
    "→ half geboekt: herstel via de half-geboekt-route (make omzet-reconciliatie / doorbelasting-"
    "reconciliatie, BESLISSINGEN 'Omzetmodule' resp. 'KEMPEN-DOORBELASTING') — nooit stil laten staan."
)
_PERSPECTIEF_CONTROLE_MISLUKT = (
    "→ verbinding/credentials van deze administratie nagaan; de volgende run controleert opnieuw."
)
_PERSPECTIEF_LET_OP = (
    "→ achtergebleven Reeleezee-concept: opruimen is klikwerk in de RLZ-UI (de app verwijdert nooit); "
    "in de app 'Gezien' mét reden om 'm uit de teller te halen."
)
_PERSPECTIEF_GEACCEPTEERD = "→ ter kennisgeving (beoordeeld-en-blijvend); intrekken kan op Inzicht › Reconciliatie."
_PERSPECTIEF_FOUT = (
    "→ niet gecontroleerd: credentials of RLZ-bereikbaarheid nagaan; de volgende run controleert opnieuw."
)


def _perspectief_afwijking(b: Bevinding) -> str:
    soort = (b.detail or {}).get("afwijking_soort") or ""
    if soort == "half_geboekt":
        return _PERSPECTIEF_HALF_GEBOEKT
    if soort == "controle_mislukt":
        return _PERSPECTIEF_CONTROLE_MISLUKT
    return _PERSPECTIEF_AFWIJKING


def bouw_mail(
    *,
    run_id: uuid.UUID,
    bron: str,
    afgerond_op: datetime,
    exit_code: int,
    samenvatting: dict[str, dict],
    delta: Delta,
    open_afwijkingen: int,
    namen: dict[uuid.UUID, str],
) -> tuple[str, str]:
    """(onderwerp, platte tekst). Bevindingen letterlijk = de CLI-regel, mét administratienaam náást
    het GUID; per soort het handelingsperspectief in één zin."""
    datum = afgerond_op.astimezone(_AMSTERDAM).strftime("%d-%m-%Y")
    onderwerp = (
        f"RLZ reconciliatie {datum}: {open_afwijkingen} afwijking(en) · "
        f"{delta.aantal_nieuwe_aandachtspunten} nieuwe aandachtspunt(en)"
    )

    def naam(b: Bevinding) -> str:
        if b.administratie_id is None:
            return ""
        return f"[{namen.get(b.administratie_id, 'onbekende administratie')}] "

    regels: list[str] = [
        f"Reconciliatie-run {afgerond_op.astimezone(_AMSTERDAM):%d-%m-%Y %H:%M} (bron {bron}, exit {exit_code}).",
        "",
        "Per blok:",
    ]
    for blok in BLOKKEN:
        stand = samenvatting.get(blok)
        if stand is None:
            regels.append(f"  {blok:<14} niet gedraaid")
            continue
        status = {"ok": "OK   ", "actie": "ACTIE", "fout": "FOUT "}.get(stand.get("status", ""), stand.get("status"))
        regels.append(
            f"  {status} {blok:<14} {stand.get('gecontroleerd', 0)} gecontroleerd, "
            f"{stand.get('afwijkingen', 0)} afwijking(en), {stand.get('geaccepteerd', 0)} geaccepteerd, "
            f"{stand.get('let_op', 0)} let-op, {stand.get('fouten', 0)} fout(en)"
            + (f" — {stand['foutmelding']}" if stand.get("foutmelding") else "")
        )

    def sectie(kop: str, items: Sequence[Bevinding], perspectief: Callable[[Bevinding], str] | str) -> None:
        if not items:
            return
        regels.extend(["", f"{kop} ({len(items)}):"])
        for b in items:
            regels.append(f"  - {naam(b)}{b.tekst}")
            regels.append(f"    {perspectief(b) if callable(perspectief) else perspectief}")

    if delta.blokken_fout:
        regels.extend(["", f"Omgevallen blok(ken): {', '.join(delta.blokken_fout)} — zie de foutmelding hierboven."])
    sectie("Nieuwe afwijkingen", delta.nieuwe_afwijkingen, _perspectief_afwijking)
    sectie("Nieuwe fouten (niet gecontroleerd)", delta.nieuwe_fouten, _PERSPECTIEF_FOUT)
    sectie("Nieuwe aandachtspunten (LET-OP)", delta.nieuwe_let_op, _PERSPECTIEF_LET_OP)
    sectie("Nieuw geaccepteerd", delta.nieuwe_geaccepteerd, _PERSPECTIEF_GEACCEPTEERD)
    if delta.verdwenen_afwijkingen:
        regels.extend(
            ["", f"Hersteld — {len(delta.verdwenen_afwijkingen)} afwijking(en) uit de vorige run niet meer gezien:"]
        )
        for b in delta.verdwenen_afwijkingen:
            regels.append(f"  - {naam(b)}{b.tekst}")
    regels.extend(
        [
            "",
            f"Alle bevindingen mét handeling: {settings.app_basis_url.rstrip('/')}/reconciliatie",
            f"Run-id: {run_id}",
            "",
            "Administratiekantoor Nijenhuis — automatisch bericht (rlz-reconciliatie)",
        ]
    )
    return onderwerp, "\n".join(regels)


# ---- run-lifecycle -----------------------------------------------------------------------------


@dataclass(frozen=True)
class RunInfo:
    run_id: uuid.UUID
    status: str
    bron: str
    aangevraagd_op: datetime
    gestart_op: datetime | None
    afgerond_op: datetime | None
    exit_code: int | None
    samenvatting: dict | None
    fout_reden: str | None
    mail_status: str | None
    mail_detail: str | None


class RunStartFout(Exception):
    """Het achtergrond-voertuig kon niet gestart worden — de run staat zichtbaar op `fout`."""


class RunNietGevonden(Exception):
    pass


def _dto(rij: ReconciliatieRun) -> RunInfo:
    return RunInfo(
        run_id=rij.id,
        status=rij.status,
        bron=rij.bron,
        aangevraagd_op=rij.aangevraagd_op,
        gestart_op=rij.gestart_op,
        afgerond_op=rij.afgerond_op,
        exit_code=rij.exit_code,
        samenvatting=rij.samenvatting,
        fout_reden=rij.fout_reden,
        mail_status=rij.mail_status,
        mail_detail=rij.mail_detail,
    )


def als_dict(info: RunInfo) -> dict:
    return asdict(info)


def _markeer_stale(session, nu: datetime) -> None:
    for rij in session.scalars(select(ReconciliatieRun).where(ReconciliatieRun.status.in_(_ACTIEF))):
        laatst = rij.laatst_actief_op or rij.gestart_op or rij.aangevraagd_op
        if laatst < nu - STALE_NA:
            rij.status = ReconciliatieRunStatus.FOUT.value
            rij.fout_reden = AFGEBROKEN_REDEN
            rij.afgerond_op = nu


def bepaal_bron() -> str:
    """De job-CLI weet niet wie 'm start: onder ENVIRONMENT=production is dat de Cloud Scheduler
    (of een handmatige job-run in de console — óók 'scheduler'-klasse), lokaal is het `make`."""
    return (
        ReconciliatieRunBron.SCHEDULER.value if settings.environment == "production" else ReconciliatieRunBron.CLI.value
    )


def start_handmatig(*, actor_id: uuid.UUID) -> RunInfo:
    """ "Nu draaien" (Beheerder): hergebruik een actieve run, anders wachtrij-rij bron 'handmatig' +
    voertuig. Een voertuig-fout staat zichtbaar op de run (status fout + reden)."""
    nu = datetime.now(UTC)
    with scoped_session(None, actor_id=actor_id) as session:
        _markeer_stale(session, nu)
        actief = session.scalars(
            select(ReconciliatieRun)
            .where(ReconciliatieRun.status.in_(_ACTIEF))
            .order_by(ReconciliatieRun.aangevraagd_op.desc())
        ).first()
        if actief is not None:
            return _dto(actief)
        rij = ReconciliatieRun(bron=ReconciliatieRunBron.HANDMATIG.value, aangevraagd_door=actor_id)
        session.add(rij)
        session.flush()
        session.refresh(rij)
        info = _dto(rij)
    try:
        _start_voertuig()
    except Exception as exc:  # noqa: BLE001 — élke voertuig-fout moet zichtbaar op de run
        logger.exception("Reconciliatie 'Nu draaien': voertuig starten mislukt")
        with scoped_session(None, actor_id=actor_id) as session:
            rij = session.get(ReconciliatieRun, info.run_id)
            if rij is not None and rij.status == ReconciliatieRunStatus.WACHTEND.value:
                rij.status = ReconciliatieRunStatus.FOUT.value
                rij.fout_reden = f"Achtergrondrun starten mislukt: {exc}"
                rij.afgerond_op = datetime.now(UTC)
        raise RunStartFout(str(exc)) from exc
    return info


def _start_voertuig() -> None:
    if settings.reconciliatie_job_resource:
        from app.projecten.cijfers_run import _trigger_cloud_run_job

        _trigger_cloud_run_job(settings.reconciliatie_job_resource)
        return
    threading.Thread(target=_thread_verwerker, name="reconciliatie-alles", daemon=True).start()


def _thread_verwerker() -> None:
    """Dev-voertuig: dezelfde code als de job-CLI (`reconciliatie-alles`), in een daemon-thread."""
    try:
        from app import cli

        cli.main(["reconciliatie-alles"])
    except Exception:  # noqa: BLE001
        logger.exception("Reconciliatie 'Nu draaien': achtergrond-thread gecrasht")


def status_van(run_id: uuid.UUID) -> RunInfo:
    nu = datetime.now(UTC)
    with scoped_session(None) as session:
        _markeer_stale(session, nu)
        rij = session.get(ReconciliatieRun, run_id)
        if rij is None:
            raise RunNietGevonden(f"Reconciliatie-run {run_id} niet gevonden")
        return _dto(rij)


def laatste_run() -> RunInfo | None:
    nu = datetime.now(UTC)
    with scoped_session(None) as session:
        _markeer_stale(session, nu)
        rij = session.scalars(
            select(ReconciliatieRun).order_by(ReconciliatieRun.aangevraagd_op.desc()).limit(1)
        ).first()
        return _dto(rij) if rij is not None else None


def laatste_afgeronde_run(*, behalve: uuid.UUID | None = None) -> RunInfo | None:
    with scoped_session(None) as session:
        q = (
            select(ReconciliatieRun)
            .where(
                ReconciliatieRun.afgerond_op.is_not(None), ReconciliatieRun.status == ReconciliatieRunStatus.KLAAR.value
            )
            .order_by(ReconciliatieRun.afgerond_op.desc())
        )
        if behalve is not None:
            q = q.where(ReconciliatieRun.id != behalve)
        rij = session.scalars(q.limit(1)).first()
        return _dto(rij) if rij is not None else None


def _claim_of_maak_run(*, bron: str) -> tuple[uuid.UUID, str]:
    """Een wachtende 'Nu draaien'-rij claimen (FOR UPDATE SKIP LOCKED) — anders een eigen rij."""
    nu = datetime.now(UTC)
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        _markeer_stale(session, nu)
        rij = session.scalars(
            select(ReconciliatieRun)
            .where(ReconciliatieRun.status == ReconciliatieRunStatus.WACHTEND.value)
            .order_by(ReconciliatieRun.aangevraagd_op)
            .with_for_update(skip_locked=True)
            .limit(1)
        ).first()
        if rij is None:
            rij = ReconciliatieRun(bron=bron, aangevraagd_op=nu)
            session.add(rij)
        rij.status = ReconciliatieRunStatus.BEZIG.value
        rij.gestart_op = nu
        rij.laatst_actief_op = nu
        session.flush()
        return rij.id, rij.bron


def _teken_van_leven(run_id: uuid.UUID) -> None:
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        rij = session.get(ReconciliatieRun, run_id)
        if rij is not None:
            rij.laatst_actief_op = datetime.now(UTC)


def _administratie_ids() -> list[uuid.UUID]:
    with scoped_session(None) as session:
        return list(session.scalars(select(Administratie.id)))


def administratie_namen() -> dict[uuid.UUID, str]:
    with scoped_session(None) as session:
        return {rij.id: rij.naam for rij in session.execute(select(Administratie.id, Administratie.naam)).all()}


def lees_bevindingen(run_id: uuid.UUID, *, administratie_ids: Sequence[uuid.UUID] | None = None) -> list[Bevinding]:
    """Alle bevindingen van één run — per administratie gelezen in een gescoopte sessie (RLS), plus de
    administratie-loze rijen (blokcrash) in de scope-loze sessie."""
    uit: list[Bevinding] = []
    for aid in [None, *(administratie_ids if administratie_ids is not None else _administratie_ids())]:
        with scoped_session(aid, actor_id=SYSTEEM_ACTOR_ID) as session:
            q = select(ReconciliatieBevinding).where(ReconciliatieBevinding.run_id == run_id)
            q = (
                q.where(ReconciliatieBevinding.administratie_id.is_(None))
                if aid is None
                else q.where(ReconciliatieBevinding.administratie_id == aid)
            )
            for rij in session.scalars(q.order_by(ReconciliatieBevinding.aangemaakt_op)):
                uit.append(
                    Bevinding(
                        blok=rij.blok,
                        soort=rij.soort,
                        administratie_id=rij.administratie_id,
                        vingerafdruk=rij.vingerafdruk,
                        tekst=rij.tekst,
                        detail=rij.detail,
                    )
                )
    return uit


def gezien_dagen() -> int:
    """Beheerder-instelling: ná hoeveel dagen een "Gezien"-snooze vervalt (default 90). Wordt bij het
    LEZEN toegepast (gezien_op + dagen), zodat een gewijzigde instelling direct voor álle bestaande
    snoozes geldt; `vervalt_op` op de rij is de termijn zoals die bij het markeren gold (audit-spoor)."""
    from app.reconciliatie.models import ReconciliatieInstelling

    with scoped_session(None) as session:
        rij = session.get(ReconciliatieInstelling, True)
        return rij.gezien_dagen if rij is not None else 90


def gezien_vervalt_op(rij: ReconciliatieGezien, dagen: int) -> datetime:
    return rij.gezien_op + timedelta(days=dagen)


def actieve_gezien(
    *, administratie_ids: Sequence[uuid.UUID], nu: datetime, dagen: int | None = None
) -> dict[tuple[uuid.UUID, str], ReconciliatieGezien]:
    """(administratie_id, vingerafdruk) → actieve snooze (niet ingetrokken, niet vervallen)."""
    dagen = gezien_dagen() if dagen is None else dagen
    uit: dict[tuple[uuid.UUID, str], ReconciliatieGezien] = {}
    for aid in administratie_ids:
        with scoped_session(aid, actor_id=SYSTEEM_ACTOR_ID) as session:
            for rij in session.scalars(
                select(ReconciliatieGezien).where(
                    ReconciliatieGezien.administratie_id == aid,
                    ReconciliatieGezien.ingetrokken_op.is_(None),
                    ReconciliatieGezien.gezien_op > nu - timedelta(days=dagen),
                )
            ):
                session.expunge(rij)
                uit[(aid, rij.vingerafdruk)] = rij
    return uit


def _schrijf_bevindingen(run_id: uuid.UUID, bevindingen: Sequence[Bevinding]) -> None:
    per_administratie: dict[uuid.UUID | None, list[Bevinding]] = {}
    for b in bevindingen:
        per_administratie.setdefault(b.administratie_id, []).append(b)
    for aid, items in per_administratie.items():
        with scoped_session(aid, actor_id=SYSTEEM_ACTOR_ID) as session:
            for b in items:
                session.add(
                    ReconciliatieBevinding(
                        run_id=run_id,
                        blok=b.blok,
                        soort=b.soort,
                        administratie_id=b.administratie_id,
                        vingerafdruk=b.vingerafdruk,
                        tekst=b.tekst,
                        detail=_json_veilig(b.detail),
                    )
                )


def _json_veilig(detail: dict | None) -> dict | None:
    if detail is None:
        return None
    return {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in detail.items()}


def _verzend_mail(*, onderwerp: str, tekst: str) -> tuple[str, str | None]:
    """→ (mail_status, detail). Nooit raise-n: een mailfout mag de job niet rood maken."""
    from app.berichten import mail

    ontvanger = settings.bewaking_alert_ontvanger
    if not ontvanger:
        return "niet_geconfigureerd", "geen BEWAKING_ALERT_ONTVANGER"
    try:
        mail.verzend_mail(naar=ontvanger, onderwerp=onderwerp, tekst=tekst)
    except mail.MailNietGeconfigureerd as exc:
        return "niet_geconfigureerd", str(exc)[:500]
    except mail.MailFout as exc:
        logger.exception("Reconciliatie-samenvattingsmail kon niet worden verzonden")
        return "mislukt", str(exc)[:500]
    return "verzonden", None


def _gezien_sleutels(gezien: dict[tuple[uuid.UUID, str], ReconciliatieGezien], huidig: Sequence[Bevinding]) -> set:
    """Een snooze geldt alleen zolang de kandidaat dezelfde reden draagt (`reden_snapshot`); kreeg het
    concept een andere oorsprong (bv. gestorneerd → gestorneerd+vervallen_run), dan telt de regel weer."""
    redenen = {(b.administratie_id, b.vingerafdruk): (b.detail or {}).get("reden") for b in huidig}
    uit: set[tuple[uuid.UUID | None, str]] = set()
    for sleutel, rij in gezien.items():
        if rij.reden_snapshot is None or redenen.get(sleutel) in (None, rij.reden_snapshot):
            uit.add(sleutel)
    return uit


def rond_af(*, run_id: uuid.UUID, bron: str, exit_code: int, verzamelaar: Verzamelaar) -> RunInfo:
    """Ná de blokken: run-rij afronden, bevindingen schrijven, delta bepalen, mailen (hooguit één)."""
    nu = datetime.now(UTC)
    samenvatting = verzamelaar.samenvatting()
    _schrijf_bevindingen(run_id, verzamelaar.bevindingen)
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        rij = session.get(ReconciliatieRun, run_id)
        if rij is None:
            raise RunNietGevonden(str(run_id))
        rij.status = ReconciliatieRunStatus.KLAAR.value
        rij.afgerond_op = nu
        rij.laatst_actief_op = nu
        rij.exit_code = exit_code
        rij.samenvatting = samenvatting
        rij.fout_reden = (
            "; ".join(
                f"{naam}: {stand['foutmelding']}" for naam, stand in samenvatting.items() if stand.get("foutmelding")
            )
            or None
        )

    administratie_ids = _administratie_ids()
    vorige = laatste_afgeronde_run(behalve=run_id)
    vorig_bevindingen = lees_bevindingen(vorige.run_id, administratie_ids=administratie_ids) if vorige else None
    gezien = actieve_gezien(administratie_ids=administratie_ids, nu=nu)
    delta = bepaal_delta(
        huidig=verzamelaar.bevindingen,
        vorig=vorig_bevindingen,
        gezien=_gezien_sleutels(gezien, verzamelaar.bevindingen),
        samenvatting=samenvatting,
    )
    open_afwijkingen = sum(1 for b in verzamelaar.bevindingen if b.soort == BevindingSoort.AFWIJKING)

    mail_status, mail_detail = "niet_nodig", None
    if not delta.is_leeg:
        onderwerp, tekst = bouw_mail(
            run_id=run_id,
            bron=bron,
            afgerond_op=nu,
            exit_code=exit_code,
            samenvatting=samenvatting,
            delta=delta,
            open_afwijkingen=open_afwijkingen,
            namen=administratie_namen(),
        )
        mail_status, mail_detail = _verzend_mail(onderwerp=onderwerp, tekst=tekst)

    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        rij = session.get(ReconciliatieRun, run_id)
        assert rij is not None
        rij.mail_status = mail_status
        rij.mail_detail = mail_detail
        if mail_status == "verzonden":
            rij.mail_verzonden_op = datetime.now(UTC)
        if mail_status == "mislukt":
            record_audit_event(
                session,
                actor_id=SYSTEEM_ACTOR_ID,
                module="boekhouding",
                tabel="reconciliatie_run",
                record_id=run_id,
                actie="reconciliatie_mail_mislukt",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde={"detail": mail_detail, "nieuwe_aandachtspunten": delta.aantal_nieuwe_aandachtspunten},
            )
        session.flush()
        session.refresh(rij)
        return _dto(rij)


def voer_uit(
    *,
    blokken: Sequence[tuple[str, Callable[..., int]]],
    args,  # noqa: ANN001 — argparse.Namespace, doorgegeven aan de blokfuncties
    bron: str | None = None,
    stdout: Callable[[str], None] = print,
    stderr: Callable[[str], None] | None = None,
) -> int:
    """Het hart van `reconciliatie-alles`: draai de blokken (nooit vroegtijdig stoppen; exit 1 zodra
    één blok afwijkingen/fouten meldt), leg de run vast en mail de delta. De CLI-regels zijn identiek
    aan vóór 06-09; er komt alleen een slotregel "run … vastgelegd" bij. Een fout in het vastleggen/
    mailen verandert de exit-code niet (zichtbaar in de uitvoer + log)."""
    import sys

    stderr = stderr or (lambda tekst: print(tekst, file=sys.stderr))
    bron = bron or bepaal_bron()
    run_id: uuid.UUID | None = None
    try:
        run_id, bron = _claim_of_maak_run(bron=bron)
    except Exception as exc:  # noqa: BLE001 — geen run-rij = tóch reconcilieren, dat is de vangrail
        logger.exception("Reconciliatie-run kon niet geregistreerd worden")
        stderr(f"FOUT       reconciliatie-run niet geregistreerd ({exc}) — blokken draaien zonder vastlegging")

    verzamelaar = Verzamelaar()
    exitcodes: dict[str, int] = {}
    for naam, functie in blokken:
        stdout(f"\n=== {naam}-reconciliatie ===")
        verzamelaar.start_blok(naam)
        try:
            exitcodes[naam] = functie(args, verzamelaar=verzamelaar)
            verzamelaar.sluit_blok(naam, exitcodes[naam])
        except Exception as exc:  # noqa: BLE001 — een omgevallen blok mag de rest nooit stoppen
            stderr(f"FOUT       {naam}-reconciliatie viel om: {exc}")
            exitcodes[naam] = 1
            verzamelaar.blok_omgevallen(naam, exc)
        if run_id is not None:
            try:
                _teken_van_leven(run_id)
            except Exception:  # noqa: BLE001
                logger.exception("teken van leven mislukt")

    stdout("\n=== samenvatting ===")
    for naam, code in exitcodes.items():
        stdout(f"{'OK       ' if code == 0 else 'ACTIE    '} {naam}-reconciliatie (exit {code})")
    exit_code = 1 if any(exitcodes.values()) else 0

    if run_id is not None:
        try:
            info = rond_af(run_id=run_id, bron=bron, exit_code=exit_code, verzamelaar=verzamelaar)
            stdout(
                f"RUN        {info.run_id} vastgelegd ({len(verzamelaar.bevindingen)} bevinding(en); "
                f"mail: {info.mail_status}{f' — {info.mail_detail}' if info.mail_detail else ''})"
            )
        except Exception as exc:  # noqa: BLE001 — vastleggen/mailen maakt de job nooit rood
            logger.exception("Reconciliatie-run afronden mislukt")
            stderr(f"FOUT       reconciliatie-run {run_id} niet afgerond: {exc}")
            try:
                with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
                    rij = session.get(ReconciliatieRun, run_id)
                    if rij is not None and rij.status != ReconciliatieRunStatus.KLAAR.value:
                        rij.status = ReconciliatieRunStatus.FOUT.value
                        rij.fout_reden = f"afronden mislukt: {exc}"[:1000]
                        rij.afgerond_op = datetime.now(UTC)
                        rij.exit_code = exit_code
            except Exception:  # noqa: BLE001
                logger.exception("Reconciliatie-run foutstatus zetten mislukt")
    return exit_code
