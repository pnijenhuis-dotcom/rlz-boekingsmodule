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
- Mail via het bestaande SMTP-kanaal (app/berichten/mail, zelfde als de bewaking) — sinds bundel 09-09
  blok 1 (feedback Peter "hier doe ik niks mee, veel te veel input") in TWEE kanalen, elk hooguit één
  mail per run (`mail_status` = samengestelde tekst "actie=…;systeem=…", geen migratie):
  * ACTIEMAIL aan het kantoor (`settings.bewaking_alert_ontvanger`): alleen als de delta bevindingen
    mét handeling voor het kantoor draagt — één kopregel, per bevinding één regel in mensentaal
    (`bouw_actiemail`), één link naar /reconciliatie. Geen tellers, geen blok-namen, geen run-id.
  * SYSTEEMMAIL aan het beheer (`settings.reconciliatie_beheer_ontvangers`): de volledige technische
    samenvatting (`bouw_mail`, onderwerp "[systeem] …") bij dezelfde delta-drempel én altijd bij exit ≠ 0.
  Een mailfout op één kanaal maakt de job NIET rood en houdt het andere kanaal niet tegen (audit
  `reconciliatie_mail_mislukt` mét kanaal; de bewaking pikt élk kanaal op 'mislukt' op als storing
  'reconciliatie_mail'). Exit 1 blijft exit 1 — de F3.2-policy blijft het vangnet voor "job draait
  niet / crasht".
- Regressie-LET-OP's (automatiseringen.REGRESSIE_CATEGORIEEN, "mag sinds … niet meer voorkomen") zijn
  bug-signalen: audit-event `automatisering_regressie` (administratie-loos, idempotent per run +
  vingerafdruk) waarop de bewaking alarmeert; nooit in de actiemail.
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
#: Blok 6 (08-09): `rlz_dubbel` = periodieke toets "mogelijk dubbel geboekt in RLZ" (app/reconciliatie/rlz_dubbel.py) —
#: een eigen blok zodat Peter 'm kan schrappen door één tuple-regel (hier + cli._reconciliatie_alles) weg te halen.
BLOKKEN = ("bank", "documenten", "omzet", "doorbelasting", "rlz_dubbel")
#: Sleutel in `samenvatting` voor de tellers per automatisering (géén blokstand — de bevindingen ervan
#: staan onder blok `automatisering`, enkelvoud).
AUTOMATISERINGEN_SLEUTEL = "automatiseringen"
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
        #: Tellers per automatisering (herstelrun 07-09 blok C, `app/reconciliatie/automatiseringen.py`) —
        #: landt in `samenvatting["automatiseringen"]`, naast de blokstanden (geen migratie, 0114-JSONB).
        self.automatiseringen: dict | None = None

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
        uit: dict[str, dict] = {naam: asdict(stand) for naam, stand in self.blokken.items()}
        if self.automatiseringen is not None:
            uit[AUTOMATISERINGEN_SLEUTEL] = self.automatiseringen
        return uit


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


# ---- twee mailkanalen (bundel 09-09 blok 1) ------------------------------------------------------

#: Kanaal 'actie' = het kantoor (bewaking_alert_ontvanger), 'systeem' = het beheer (reconciliatie_beheer_ontvangers).
KANALEN = ("actie", "systeem")
MAIL_STATUSSEN = ("niet_nodig", "verzonden", "mislukt", "niet_geconfigureerd")
#: Eén actiemail-regel blijft leesbaar op een telefoon: harde bovengrens, daarna afkappen met "…".
MAX_ACTIE_REGEL = 140
#: Meer bevindingen dan dit = "en N andere" mét dezelfde link (de lijst staat op /reconciliatie).
MAX_ACTIE_REGELS = 10


def mail_status_samenstellen(statussen: dict[str, str]) -> str:
    """{'actie': 'verzonden', 'systeem': 'niet_nodig'} → 'actie=verzonden;systeem=niet_nodig' (vaste volgorde)."""
    return ";".join(f"{k}={statussen.get(k, 'niet_nodig')}" for k in KANALEN)


def mail_statussen(waarde: str | None) -> dict[str, str]:
    """De samengestelde kolomwaarde terug naar {kanaal: status}. Een run van vóór 09-09 draagt één kale status —
    die telt als het (toen enige) kanaal 'actie'. None = nog niet afgerond → leeg."""
    if not waarde:
        return {}
    if "=" not in waarde:
        return {"actie": waarde}
    uit: dict[str, str] = {}
    for deel in waarde.split(";"):
        k, _, v = deel.partition("=")
        if k and v:
            uit[k] = v
    return uit


def is_regressie(b: Bevinding) -> bool:
    """LET-OP op blok `automatisering` met een regressie-categorie (bv. `geen_eigenaar` ná 0121): bug-signaal."""
    from app.reconciliatie import automatiseringen

    return (
        b.blok == automatiseringen.BLOK
        and b.soort == BevindingSoort.LET_OP
        and str((b.detail or {}).get("reden") or "") in automatiseringen.REGRESSIE_CATEGORIEEN
    )


def is_beheer_signaal(b: Bevinding) -> bool:
    """Bevinding waarvan de handeling bij het beheer ligt, niet bij het kantoor: een omgevallen blok of een andere
    administratie-loze fout (tellers niet bepaald), een LET-OP over Cloud Run/IAM/jobs of zeven dagen stil, en
    élke regressie. Die gaan uitsluitend in de systeemmail."""
    from app.reconciliatie import automatiseringen

    if is_regressie(b):
        return True
    if b.soort == BevindingSoort.FOUT and b.administratie_id is None:
        return True
    return (
        b.blok == automatiseringen.BLOK
        and b.soort == BevindingSoort.LET_OP
        and str((b.detail or {}).get("reden") or "") in automatiseringen.BEHEER_CATEGORIEEN
    )


def actie_bevindingen(delta: Delta) -> list[Bevinding]:
    """Wat het kantoor uit de delta te DOEN heeft: nieuwe afwijkingen, nieuwe fouten per administratie en nieuwe
    LET-OP's mét handeling — in urgentievolgorde. Geaccepteerd, hersteld, omgevallen blokken en beheer-/regressie-
    signalen horen in de systeemmail."""
    return [
        b
        for b in (*delta.nieuwe_afwijkingen, *delta.nieuwe_fouten, *delta.nieuwe_let_op)
        if not is_beheer_signaal(b)
    ]


def actie_regel(b: Bevinding, administratie_naam: str | None) -> str:
    """'<administratie> — <onderwerp> — <wat wijkt af>' uit de leesbare titel (teksten.py, één bron met de UI):
    de titel is 'kop — onderwerp'; hier gedraaid zodat de administratie vooraan staat en de afwijking achteraan.
    Nooit GUID's/vingerafdrukken (die staan alleen in `details`); ≤ MAX_ACTIE_REGEL tekens."""
    from app.reconciliatie import teksten

    lees = teksten.leesbaar(b, administratie_naam=administratie_naam)
    kop, _, onderwerp = lees.titel.partition(" — ")
    onderwerp = onderwerp.strip()
    if administratie_naam and onderwerp == administratie_naam:
        onderwerp = ""  # 'Administratie niet gecontroleerd — <naam>': de naam staat al vooraan
    regel = " — ".join(x for x in (administratie_naam, onderwerp, kop.strip()) if x)
    if len(regel) > MAX_ACTIE_REGEL:
        regel = regel[: MAX_ACTIE_REGEL - 1].rstrip(" —-(·") + "…"
    return regel


def bouw_actiemail(
    *, bevindingen: Sequence[Bevinding], namen: dict[uuid.UUID, str], alles_gelopen: bool = True
) -> tuple[str, str] | None:
    """(onderwerp, platte tekst) van de ACTIEMAIL aan het kantoor, of None als er niets te doen is.
    Kopregel 'N zaken vragen je aandacht', per bevinding één regel in mensentaal, hooguit MAX_ACTIE_REGELS
    (daarna 'en N andere'), één link naar /reconciliatie, slotregel. Geen tellers, blok-namen, run-id of
    vingerafdruk — de guard-test (tests/reconciliatie/test_actiemail_guard.py) bewaakt dat."""
    if not bevindingen:
        return None
    n = len(bevindingen)
    kop = "1 zaak vraagt je aandacht" if n == 1 else f"{n} zaken vragen je aandacht"
    link = f"{settings.app_basis_url.rstrip('/')}/reconciliatie"
    regels = [f"{kop}.", ""]
    for b in bevindingen[:MAX_ACTIE_REGELS]:
        naam = namen.get(b.administratie_id, "onbekende administratie") if b.administratie_id else None
        regels.append(f"- {actie_regel(b, naam)}")
    rest = n - MAX_ACTIE_REGELS
    if rest > 0:
        regels.append(f"- en {rest} andere")
    regels.extend(
        [
            "",
            f"Bekijken en afhandelen: {link}",
            "",
            "Verder liep alles."
            if alles_gelopen
            else "Een deel van de controles is vandaag niet gelopen; het beheer is daarvan op de hoogte.",
            "",
            "Administratiekantoor Nijenhuis — automatisch bericht",
        ]
    )
    return f"Boekhouding: {kop}", "\n".join(regels)


def _perspectief_afwijking(b: Bevinding, administratie_naam: str | None = None) -> str:
    """Handelingsperspectief = de 'doe'-zin van de leesbare tekst (sinds 07-09 blok A8 één bron voor UI en mail)."""
    from app.reconciliatie import teksten

    return teksten.leesbaar(b, administratie_naam=administratie_naam).doe


def automatiseringen_mailregels(samenvatting_automatiseringen: dict) -> list[str]:
    """Blok 5 (08-09): de mail draagt het volledige blok "Automatiseringen (laatste 24 u):" ALLEEN als er iets afwijkt —
    ≥ 1 LET-OP (ontbrekende harde voorwaarde in het etmaal, óf zeven dagen stil; ook op een uit-teller). Anders één regel
    "Automatiseringen: alles gelopen (N aan)" — N = automatiseringen die niet uit staan. Sleutel-agnostisch: leest de
    opgeslagen JSON terug via `uit_samenvatting` (een nieuwe teller-sleutel zoals `bank_sync` hoeft hier niets)."""
    from app.reconciliatie import automatiseringen

    tellers = automatiseringen.uit_samenvatting(samenvatting_automatiseringen)
    aan = [t for t in tellers if not t.is_uit]
    # Óók een uit-teller kan een LET-OP dragen (07-09-uitzondering: noodrem UIT + gesignaleerde duplicaten in het etmaal) —
    # een signaal mét handeling gaat nooit stil weg, dus over álle tellers toetsen.
    afwijkend = [t for t in tellers if t.stil or t.harde_voorwaarden]
    if afwijkend:
        return automatiseringen.regels(tellers)
    return [f"Automatiseringen: alles gelopen ({len(aan)} aan)"]


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
    """SYSTEEMMAIL (beheer) — (onderwerp, platte tekst). Sinds bundel 09-09 blok 1 de volledige technische
    samenvatting voor `settings.reconciliatie_beheer_ontvangers`, onderwerp "[systeem] …"; het kantoor krijgt de
    actiemail (`bouw_actiemail`). Per bevinding DEZELFDE leesbare tekst als in de UI (blok A8, 07-09):
    "[administratie] titel — wat" + "doe" als hoofdregels; de vingerafdruk (sleutel voor de CLI-acceptatie)
    en de ruwe CLI-regel staan als technische regel eronder — nooit meer een kale GUID-regel bovenaan."""
    from app.reconciliatie import teksten

    datum = afgerond_op.astimezone(_AMSTERDAM).strftime("%d-%m-%Y")
    onderwerp = (
        f"[systeem] RLZ reconciliatie {datum}: {open_afwijkingen} afwijking(en) · "
        f"{delta.aantal_nieuwe_aandachtspunten} nieuwe aandachtspunt(en)"
    )

    def adm_naam(b: Bevinding) -> str | None:
        if b.administratie_id is None:
            return None
        return namen.get(b.administratie_id, "onbekende administratie")

    def naam(b: Bevinding) -> str:
        n = adm_naam(b)
        return f"[{n}] " if n else ""

    def leesbare_regels(b: Bevinding) -> list[str]:
        lees = teksten.leesbaar(b, administratie_naam=adm_naam(b))
        return [
            f"  - {naam(b)}{lees.titel} — {lees.wat}",
            f"    → {lees.doe}",
            f"    technisch: vaf:{b.vingerafdruk} · {b.tekst}",
        ]

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
    # Herstelrun 07-09 blok C: het vangnet op "geen stille no-op". Blok 5 (08-09, feedback Peter "wat moet ik
    # hiermee"): het volledige blok staat alleen nog in de mail als er iets AFWIJKT; anders één regel. De CLI-uitvoer
    # blijft volledig (`automatiseringen.regels`), de mail-drempel (geen delta = geen mail) is ongewijzigd.
    if samenvatting.get(AUTOMATISERINGEN_SLEUTEL):
        regels.extend(["", *automatiseringen_mailregels(samenvatting[AUTOMATISERINGEN_SLEUTEL])])

    def sectie(kop: str, items: Sequence[Bevinding]) -> None:
        if not items:
            return
        regels.extend(["", f"{kop} ({len(items)}):"])
        for b in items:
            regels.extend(leesbare_regels(b))

    if delta.blokken_fout:
        regels.extend(["", f"Omgevallen blok(ken): {', '.join(delta.blokken_fout)} — zie de foutmelding hierboven."])
    sectie("Nieuwe afwijkingen", delta.nieuwe_afwijkingen)
    sectie("Nieuwe fouten (niet gecontroleerd)", delta.nieuwe_fouten)
    sectie("Nieuwe aandachtspunten (LET-OP)", delta.nieuwe_let_op)
    sectie("Nieuw geaccepteerd", delta.nieuwe_geaccepteerd)
    if delta.verdwenen_afwijkingen:
        regels.extend(
            ["", f"Hersteld — {len(delta.verdwenen_afwijkingen)} afwijking(en) uit de vorige run niet meer gezien:"]
        )
        for b in delta.verdwenen_afwijkingen:
            lees = teksten.leesbaar(b, administratie_naam=adm_naam(b))
            regels.append(f"  - {naam(b)}{lees.titel} — {lees.wat}")
            regels.append(f"    technisch: vaf:{b.vingerafdruk} · {b.tekst}")
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


def _ontvangers(kanaal: str) -> tuple[str | None, str]:
    """(adres(sen) als één To-header, naam van de instelling) per kanaal. Komma-gescheiden = meerdere."""
    if kanaal == "systeem":
        ruw, naam = settings.reconciliatie_beheer_ontvangers, "RECONCILIATIE_BEHEER_ONTVANGERS"
    else:
        ruw, naam = settings.bewaking_alert_ontvanger, "BEWAKING_ALERT_ONTVANGER"
    adressen = [a.strip() for a in (ruw or "").split(",") if a.strip()]
    return (", ".join(adressen) if adressen else None), naam


def _verzend_mail(*, onderwerp: str, tekst: str, kanaal: str = "actie") -> tuple[str, str | None]:
    """→ (mail_status, detail) voor één kanaal. Nooit raise-n: een mailfout mag de job niet rood maken en houdt
    het andere kanaal niet tegen."""
    from app.berichten import mail

    ontvanger, instelling = _ontvangers(kanaal)
    if not ontvanger:
        return "niet_geconfigureerd", f"geen {instelling}"
    try:
        mail.verzend_mail(naar=ontvanger, onderwerp=onderwerp, tekst=tekst)
    except mail.MailNietGeconfigureerd as exc:
        return "niet_geconfigureerd", str(exc)[:500]
    except mail.MailFout as exc:
        logger.exception("Reconciliatie-%smail kon niet worden verzonden", kanaal)
        return "mislukt", str(exc)[:500]
    return "verzonden", None


def _registreer_regressies(session, run_id: uuid.UUID, bevindingen: Sequence[Bevinding]) -> int:  # noqa: ANN001
    """Bundel 09-09 blok 1: élke regressie-LET-OP wordt een audit-event `automatisering_regressie` (administratie-
    loos; detail = automatisering + categorie + aantal + run-id + vingerafdruk), idempotent per run + vingerafdruk.
    De bewaking (`_probe_automatisering_regressie`) alarmeert erop. Geeft het aantal nieuw geschreven events terug."""
    from app.db.models import AuditEvent

    regressies = [b for b in bevindingen if is_regressie(b)]
    if not regressies:
        return 0
    al_gemeld = {
        (nw or {}).get("vingerafdruk")
        for (nw,) in session.execute(
            select(AuditEvent.nieuwe_waarde).where(
                AuditEvent.actie == "automatisering_regressie", AuditEvent.record_id == run_id
            )
        ).all()
    }
    geschreven = 0
    for b in regressies:
        if b.vingerafdruk in al_gemeld:
            continue
        d = b.detail or {}
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="boekhouding",
            tabel="reconciliatie_run",
            record_id=run_id,
            actie="automatisering_regressie",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "automatisering": d.get("automatisering"),
                "categorie": d.get("reden"),
                "aantal": d.get("aantal"),
                "administratie_id": str(b.administratie_id) if b.administratie_id else None,
                "run_id": str(run_id),
                "vingerafdruk": b.vingerafdruk,
            },
        )
        al_gemeld.add(b.vingerafdruk)
        geschreven += 1
    return geschreven


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

    # Twee kanalen (bundel 09-09 blok 1), onafhankelijk van elkaar: een fout op het ene houdt het andere niet tegen.
    namen = administratie_namen()
    statussen: dict[str, str] = {k: "niet_nodig" for k in KANALEN}
    details: dict[str, str | None] = {k: None for k in KANALEN}

    # ACTIEMAIL (kantoor): alleen bevindingen mét handeling voor het kantoor; geen bevindingen = geen mail.
    actie = actie_bevindingen(delta)
    actiemail = bouw_actiemail(bevindingen=actie, namen=namen, alles_gelopen=not delta.blokken_fout)
    if actiemail is not None:
        statussen["actie"], details["actie"] = _verzend_mail(onderwerp=actiemail[0], tekst=actiemail[1], kanaal="actie")

    # SYSTEEMMAIL (beheer): de volledige samenvatting bij dezelfde delta-drempel, én altijd bij exit ≠ 0.
    if not delta.is_leeg or exit_code != 0:
        onderwerp, tekst = bouw_mail(
            run_id=run_id,
            bron=bron,
            afgerond_op=nu,
            exit_code=exit_code,
            samenvatting=samenvatting,
            delta=delta,
            open_afwijkingen=open_afwijkingen,
            namen=namen,
        )
        statussen["systeem"], details["systeem"] = _verzend_mail(onderwerp=onderwerp, tekst=tekst, kanaal="systeem")

    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        rij = session.get(ReconciliatieRun, run_id)
        assert rij is not None
        rij.mail_status = mail_status_samenstellen(statussen)
        rij.mail_detail = "; ".join(f"{k}: {details[k]}" for k in KANALEN if details[k]) or None
        if "verzonden" in statussen.values():
            rij.mail_verzonden_op = datetime.now(UTC)
        for kanaal in KANALEN:
            if statussen[kanaal] == "mislukt":
                record_audit_event(
                    session,
                    actor_id=SYSTEEM_ACTOR_ID,
                    module="boekhouding",
                    tabel="reconciliatie_run",
                    record_id=run_id,
                    actie="reconciliatie_mail_mislukt",
                    correlatie_id=uuid.uuid4(),
                    nieuwe_waarde={
                        "kanaal": kanaal,
                        "detail": details[kanaal],
                        "nieuwe_aandachtspunten": delta.aantal_nieuwe_aandachtspunten,
                    },
                )
        # Regressie-LET-OP's = bug-signalen: audit-event waarop de bewaking alarmeert (nooit in de actiemail).
        _registreer_regressies(session, run_id, verzamelaar.bevindingen)
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

    # Herstelrun 07-09 blok C: tellers per automatisering (vangnet, geen poort) — LET-OP-bevindingen op blok
    # `automatisering`, tellers in de samenvatting. Een fout hier verandert exit-code noch blokuitkomst.
    stdout("\n=== automatiseringen ===")
    try:
        from app.reconciliatie import automatiseringen

        verzamelaar.automatiseringen = automatiseringen.registreer(verzamelaar, stdout=stdout)
    except Exception as exc:  # noqa: BLE001 — het vangnet mag de reconciliatie nooit laten omvallen
        logger.exception("Tellers per automatisering mislukt")
        stderr(f"FOUT       tellers per automatisering niet bepaald: {exc}")
        verzamelaar.bevinding(
            soort=BevindingSoort.FOUT.value,
            administratie_id=None,
            tekst=f"FOUT       tellers per automatisering niet bepaald: {exc}",
            blok="automatisering",
        )

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
