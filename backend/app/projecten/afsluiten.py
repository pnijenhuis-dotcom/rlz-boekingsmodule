"""Afsluit-kandidaten (opdracht Peter 19-09 — "welk project is afgesloten? dat onderscheid maken wij nu nog niet"): één
motor
voor de tab "Afsluiten? (N)" (per administratie én kantoorbreed), de chip op Inzicht › Projecten en de lees-only CLI
`projecten-afsluit-kandidaten`. HERZIET het 18-09-criterium "stil ≥ 90 dagen ÉN contract-m² bereikt" (te smal: zonder
contract-m²
nooit een kandidaat, terwijl bij Universal 8 projecten "Afgesloten …" heten en gewoon actief staan).

Kandidaat = een lopend, actief project mét één of meer REDENEN (deterministisch, geen AI):
- `stil`               — geen inkoop-/verkoopregel, weekstaat, planning of verplichting in de laatste N maanden
                          (N = `administratie.project_afsluit_stil_maanden`, default 6, instelbaar per administratie);
                          een project zonder énige activiteit telt NIET als stil (leeftijd onbekend — een nieuw project
                          mag nooit "afsluiten?" heten), de tekst zegt dat wel;
- `eindfactuur`        — de jongste VERKOOPregel van het project draagt "eindfactuur"/"eindafrekening"/"slotfactuur" in
                          omschrijving of referentie (de eindafrekening is geboekt);
- `naam_afgesloten`    — de naam begint met "Afgesloten" (`projectverdeling.omzet.naam_zegt_afgesloten`) terwijl het
project actief
                          staat — nooit stil uitsluiten op naam, wél aanbieden;
- `looptijd_verstreken`— `project_specificatie.looptijd_tot` ligt vóór vandaag.
Per rij: de LAATSTE ACTIVITEIT (soort, datum, bedrag, boekstuk) en de OPEN POSTEN als chip "let op" — inkoop nog niet
geboekt
(boekvoorstelregels op het project van niet-terminale, niet-geboekte documenten), verplichting open (goedgekeurd, niet vervallen,
verbruik < bedrag) en uren niet gekeurd (weekstaten ≠ goedgekeurd) — informatie, nooit een blokkade.

"Niet afsluiten" (mét VERPLICHTE reden, `ProjectAfsluitUitstel`, audit `project_afsluiten_uitgesteld`) haalt de rij uit
de kandidaten
tot er activiteit ná het snapshot `laatste_activiteit` bijkomt; uitgestelde rijen blijven zichtbaar onder "Toon
uitgesteld (N)" —
niets verdwijnt stil. Bulk-afsluiten loopt per project door de bestaande 0160-flow (`status.sluit_project_af`: bron eerst inactief,
terugleesverificatie, RLZ wint; audit + herberekening projectverdeling) mét uitkomst per rij — NOOIT automatisch, altijd
een mens
op de knop. Rol: lezen = kantoorrol + scope, handelen = Beheerder + Boekhouding+Projecten (`kantoor._vereis_schrijfrol`)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Administratie, GebruikerRol
from app.db.session import scoped_session
from app.documenten.models import Boekvoorstel, BoekvoorstelRegel, Document, DocumentStatus
from app.projecten.models import ProjectAfsluitUitstel, ProjectRegelCache, ProjectRegelSoort
from app.projectverdeling.omzet import naam_zegt_afgesloten
from app.sync.models import PROJECT_STATUS_AFGESLOTEN, ProjectCache
from app.tijd import vandaag_nl
from app.uren.models import PlanningToewijzing, ProjectSpecificatie, Weekstaat, WeekstaatStatus
from app.verplichting.match_pipeline import ONDERWEG_UITGESLOTEN_STATUSSEN
from app.verplichting.models import Verplichting

STIL_MAANDEN_DEFAULT = 6
STIL_MAANDEN_MIN = 1
STIL_MAANDEN_MAX = 36

REDENEN: tuple[str, ...] = ("stil", "eindfactuur", "naam_afgesloten", "looptijd_verstreken")
REDEN_LABEL: dict[str, str] = {
    "stil": "geen activiteit",
    "eindfactuur": "eindfactuur geboekt",
    "naam_afgesloten": "naam zegt afgesloten",
    "looptijd_verstreken": "looptijd verstreken",
}
_EINDFACTUUR = re.compile(r"eind\s*(factuur|afrekening)|slotfactuur", re.IGNORECASE)

UITKOMSTEN: tuple[str, ...] = ("gelukt", "bron_weigert", "al_afgesloten", "niet_gevonden", "geen_toegang")


class AfsluitenFout(Exception):
    """Basis (router: 422)."""


class RedenVerplicht(AfsluitenFout):
    """ "Niet afsluiten" zonder reden — niets verdwijnt stil (422)."""


class OngeldigStilVenster(AfsluitenFout):
    """Stil-venster buiten 1..36 maanden (422)."""


# --- dataclasses ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Activiteit:
    soort: str  # inkoop | verkoop | uren | planning | verplichting
    datum: date
    bedrag: Decimal | None = None
    boekstuk: str | None = None  # referentie/omschrijving (inkoop/verkoop), "wk 2026-36" (uren), None (planning)


@dataclass(frozen=True)
class OpenPosten:
    inkoop_niet_geboekt: int = 0
    inkoop_niet_geboekt_bedrag: Decimal = Decimal("0")
    verplichting_open: int = 0
    uren_niet_gekeurd: int = 0

    @property
    def let_op(self) -> bool:
        return bool(self.inkoop_niet_geboekt or self.verplichting_open or self.uren_niet_gekeurd)


@dataclass(frozen=True)
class Uitstel:
    reden: str
    door: uuid.UUID
    op: datetime
    laatste_activiteit: date | None


@dataclass(frozen=True)
class Kandidaat:
    administratie_id: uuid.UUID
    administratie_naam: str
    project_id: uuid.UUID
    naam: str | None
    redenen: tuple[str, ...]
    reden_tekst: str
    laatste_activiteit: Activiteit | None
    stil_dagen: int | None
    stil_maanden: int
    open_posten: OpenPosten
    looptijd_tot: date | None
    uitstel: Uitstel | None = None

    @property
    def kandidaat(self) -> bool:
        return bool(self.redenen) and self.uitstel is None

    @property
    def uitgesteld(self) -> bool:
        return bool(self.redenen) and self.uitstel is not None

    @property
    def zoektekst(self) -> str:
        return " ".join(x for x in (self.naam, self.administratie_naam, str(self.project_id)) if x).lower()


@dataclass(frozen=True)
class Tellers:
    kandidaten: int = 0
    uitgesteld: int = 0
    administraties: int = 0
    per_reden: dict[str, int] = field(default_factory=dict)
    let_op: int = 0


@dataclass(frozen=True)
class Lijst:
    rijen: list[Kandidaat]
    totaal: int
    pagina: int
    per_pagina: int
    tellers: Tellers
    stil_maanden: int | None  # alleen bij één administratie


@dataclass(frozen=True)
class BulkUitkomst:
    administratie_id: uuid.UUID
    project_id: uuid.UUID
    naam: str | None
    uitkomst: str  # UITKOMSTEN
    detail: str | None = None


PER_PAGINA = 50


# --- laatste activiteit per soort (set-based, per administratie) ----------------------------------------------------


def _maandag(jaar: int, week: int) -> date:
    try:
        return date.fromisocalendar(int(jaar), min(int(week), 52), 1)
    except ValueError:
        return date(int(jaar), 12, 28)


def _laatste_regel_per_project(
    session: Session, *, aid: uuid.UUID, ids: list[uuid.UUID], soort: ProjectRegelSoort
) -> dict[uuid.UUID, ProjectRegelCache]:
    """Jongste regel van de soort per project (datum desc; regels zonder datum tellen niet als activiteit).

    Meerdere regels op dezelfde jongste datum (een factuur mét meerdere regels) = deterministische keuze: een regel die
    de eindfactuur-tekst draagt wint (de reden `eindfactuur` mag niet afhangen van de rijvolgorde van de database —
    nameting 19-09), anders de eerste op (rlz_document_id, id)."""
    sub = (
        select(
            ProjectRegelCache.project_id.label("pid"),
            func.max(ProjectRegelCache.datum).label("d"),
        )
        .where(
            ProjectRegelCache.administratie_id == aid,
            ProjectRegelCache.project_id.in_(ids),
            ProjectRegelCache.soort == soort.value,
            ProjectRegelCache.verdwenen_uit_bron_op.is_(None),
            ProjectRegelCache.datum.is_not(None),
        )
        .group_by(ProjectRegelCache.project_id)
        .subquery()
    )
    uit: dict[uuid.UUID, ProjectRegelCache] = {}
    for regel in session.scalars(
        select(ProjectRegelCache)
        .join(sub, (sub.c.pid == ProjectRegelCache.project_id) & (sub.c.d == ProjectRegelCache.datum))
        .where(
            ProjectRegelCache.administratie_id == aid,
            ProjectRegelCache.soort == soort.value,
            ProjectRegelCache.verdwenen_uit_bron_op.is_(None),
        )
        .order_by(ProjectRegelCache.rlz_document_id, ProjectRegelCache.id)
    ):
        huidig = uit.get(regel.project_id)
        if huidig is None or (is_eindfactuur(regel) and not is_eindfactuur(huidig)):
            uit[regel.project_id] = regel
    return uit


def activiteit_per_project(
    session: Session, *, administratie_id: uuid.UUID, project_ids: set[uuid.UUID]
) -> tuple[dict[uuid.UUID, Activiteit], dict[uuid.UUID, ProjectRegelCache]]:
    """Laatste activiteit (max over inkoop, verkoop, uren, planning, verplichting) per project + de jongste verkoopregel
    (bron voor de eindfactuur-reden). Vijf set-based statements voor álle projecten van de administratie."""
    if not project_ids:
        return {}, {}
    ids = list(project_ids)
    laatste: dict[uuid.UUID, Activiteit] = {}

    def neem(a: Activiteit, pid: uuid.UUID) -> None:
        if pid not in laatste or a.datum > laatste[pid].datum:
            laatste[pid] = a

    inkoop = _laatste_regel_per_project(session, aid=administratie_id, ids=ids, soort=ProjectRegelSoort.INKOOP)
    verkoop = _laatste_regel_per_project(session, aid=administratie_id, ids=ids, soort=ProjectRegelSoort.VERKOOP)
    for soort, regels in (("inkoop", inkoop), ("verkoop", verkoop)):
        for pid, r in regels.items():
            if r.datum is not None:
                neem(Activiteit(soort, r.datum, r.netto_bedrag, r.referentie or r.omschrijving), pid)
    for pid, jaar, week in session.execute(
        select(Weekstaat.project_id, func.max(Weekstaat.jaar), func.max(Weekstaat.weeknummer))
        .where(Weekstaat.administratie_id == administratie_id, Weekstaat.project_id.in_(ids))
        .group_by(Weekstaat.project_id)
    ):
        neem(Activiteit("uren", _maandag(jaar, week), None, f"wk {int(jaar)}-{int(week):02d}"), pid)
    for pid, d in session.execute(
        select(PlanningToewijzing.project_id, func.max(PlanningToewijzing.datum))
        .where(PlanningToewijzing.administratie_id == administratie_id, PlanningToewijzing.project_id.in_(ids))
        .group_by(PlanningToewijzing.project_id)
    ):
        if d is not None:
            neem(Activiteit("planning", d), pid)
    for pid, d, aangemaakt, bedrag in session.execute(
        select(
            Verplichting.project_id,
            func.max(Verplichting.datum),
            func.max(Verplichting.aangemaakt_op),
            func.max(Verplichting.totaalbedrag_excl),
        )
        .where(Verplichting.administratie_id == administratie_id, Verplichting.project_id.in_(ids))
        .group_by(Verplichting.project_id)
    ):
        dag = d or (aangemaakt.date() if aangemaakt else None)
        if dag is not None:
            neem(Activiteit("verplichting", dag, bedrag), pid)
    return laatste, verkoop


def open_posten_per_project(
    session: Session, *, administratie_id: uuid.UUID, project_ids: set[uuid.UUID]
) -> dict[uuid.UUID, OpenPosten]:
    """Chip "let op" — informatie, nooit een blokkade. Drie set-based statements."""
    if not project_ids:
        return {}
    ids = list(project_ids)
    inkoop: dict[uuid.UUID, tuple[int, Decimal]] = {}
    for pid, n, bedrag in session.execute(
        select(
            BoekvoorstelRegel.project_id,
            func.count(func.distinct(Document.id)),
            func.coalesce(func.sum(BoekvoorstelRegel.netto_bedrag), 0),
        )
        .join(Boekvoorstel, Boekvoorstel.document_id == BoekvoorstelRegel.document_id)
        .join(Document, Document.id == Boekvoorstel.document_id)
        .where(
            Document.administratie_id == administratie_id,
            BoekvoorstelRegel.project_id.in_(ids),
            Document.status.notin_(ONDERWEG_UITGESLOTEN_STATUSSEN),
        )
        .group_by(BoekvoorstelRegel.project_id)
    ):
        inkoop[pid] = (int(n), Decimal(bedrag))
    verpl: dict[uuid.UUID, int] = {}
    for v in session.scalars(
        select(Verplichting)
        .join(Document, Document.id == Verplichting.document_id)
        .where(
            Verplichting.administratie_id == administratie_id,
            Verplichting.project_id.in_(ids),
            Document.status == DocumentStatus.GEACCORDEERD,
            Verplichting.vervallen_op.is_(None),
        )
    ):
        totaal = v.goedgekeurd_bedrag_excl if v.goedgekeurd_bedrag_excl is not None else v.totaalbedrag_excl
        if totaal is None or Decimal(v.verbruikt_bedrag_excl or 0) < totaal:
            verpl[v.project_id] = verpl.get(v.project_id, 0) + 1
    uren: dict[uuid.UUID, int] = {}
    for pid, n in session.execute(
        select(Weekstaat.project_id, func.count())
        .where(
            Weekstaat.administratie_id == administratie_id,
            Weekstaat.project_id.in_(ids),
            Weekstaat.status != WeekstaatStatus.GOEDGEKEURD.value,
        )
        .group_by(Weekstaat.project_id)
    ):
        uren[pid] = int(n)
    uit: dict[uuid.UUID, OpenPosten] = {}
    for pid in ids:
        n_ink, b_ink = inkoop.get(pid, (0, Decimal("0")))
        uit[pid] = OpenPosten(
            inkoop_niet_geboekt=n_ink,
            inkoop_niet_geboekt_bedrag=b_ink,
            verplichting_open=verpl.get(pid, 0),
            uren_niet_gekeurd=uren.get(pid, 0),
        )
    return uit


# --- redenen ----------------------------------------------------------------------------------------------------------


def _maanden_terug(d: date, maanden: int) -> date:
    m = d.month - maanden
    j = d.year
    while m <= 0:
        m += 12
        j -= 1
    dag = min(
        d.day,
        [31, 29 if j % 4 == 0 and (j % 100 != 0 or j % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][
            m - 1
        ],
    )
    return date(j, m, dag)


def is_eindfactuur(regel: ProjectRegelCache | None) -> bool:
    if regel is None:
        return False
    return bool(_EINDFACTUUR.search(regel.omschrijving or "") or _EINDFACTUUR.search(regel.referentie or ""))


def bepaal_redenen(
    *,
    naam: str | None,
    laatste: Activiteit | None,
    jongste_verkoop: ProjectRegelCache | None,
    looptijd_tot: date | None,
    vandaag: date,
    stil_maanden: int,
) -> tuple[tuple[str, ...], str]:
    """Puur: redenen + leesbare tekst. Volgorde vast (REDENEN)."""
    grens = _maanden_terug(vandaag, stil_maanden)
    redenen: list[str] = []
    teksten: list[str] = []
    if laatste is None:
        # Geen énkele activiteit bekend: de leeftijd van het project is niet betrouwbaar af te leiden (RLZ kent geen
        # aanmaakdatum in de cache) — een gisteren aangemaakt project mag nooit "afsluiten?" heten. Geen stil-reden;
        # de andere redenen (naam, looptijd) gelden wél. Zichtbaar in de tekst, nooit stil weggelaten.
        teksten.append("geen inkoop, verkoop, uren of planning bekend (leeftijd onbekend — telt niet als stil)")
    elif laatste.datum <= grens:
        redenen.append("stil")
        teksten.append(
            f"geen activiteit sinds {laatste.datum.isoformat()} "
            f"({(vandaag - laatste.datum).days} dagen, venster {stil_maanden} mnd)"
        )
    if is_eindfactuur(jongste_verkoop):
        redenen.append("eindfactuur")
        assert jongste_verkoop is not None
        teksten.append(
            f"eindfactuur geboekt ({(jongste_verkoop.referentie or jongste_verkoop.omschrijving or '').strip()[:60]})"
        )
    if naam_zegt_afgesloten(naam):
        redenen.append("naam_afgesloten")
        teksten.append("naam zegt afgesloten, status actief")
    if looptijd_tot is not None and looptijd_tot < vandaag:
        redenen.append("looptijd_verstreken")
        teksten.append(f"looptijd tot {looptijd_tot.isoformat()} verstreken")
    return tuple(redenen), " · ".join(teksten)


def kandidaten_voor_administratie(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    administratie_naam: str,
    vandaag: date | None = None,
    stil_maanden: int | None = None,
    project_ids: set[uuid.UUID] | None = None,
) -> list[Kandidaat]:
    """Alle lopende, actieve projecten van de administratie mét hun kandidaat-stand (redenen leeg = geen kandidaat).
    `project_ids` beperkt (chip op Inzicht › Projecten hergebruikt de al geladen set)."""
    vandaag = vandaag or vandaag_nl()
    administratie = session.get(Administratie, administratie_id)
    if administratie is None:
        return []
    maanden = stil_maanden or int(administratie.project_afsluit_stil_maanden or STIL_MAANDEN_DEFAULT)
    q = select(ProjectCache).where(
        ProjectCache.administratie_id == administratie_id,
        ProjectCache.verdwenen_uit_bron_op.is_(None),
        ProjectCache.is_actief.is_(True),
        ProjectCache.status != PROJECT_STATUS_AFGESLOTEN,
    )
    if project_ids is not None:
        if not project_ids:
            return []
        q = q.where(ProjectCache.id.in_(list(project_ids)))
    projecten = list(session.scalars(q.order_by(ProjectCache.naam)))
    if not projecten:
        return []
    ids = {p.id for p in projecten}
    laatste, verkoop = activiteit_per_project(session, administratie_id=administratie_id, project_ids=ids)
    open_posten = open_posten_per_project(session, administratie_id=administratie_id, project_ids=ids)
    specs = {
        s.project_id: s
        for s in session.scalars(
            select(ProjectSpecificatie).where(
                ProjectSpecificatie.administratie_id == administratie_id, ProjectSpecificatie.project_id.in_(list(ids))
            )
        )
    }
    uitstel = {
        u.project_id: u
        for u in session.scalars(
            select(ProjectAfsluitUitstel).where(
                ProjectAfsluitUitstel.administratie_id == administratie_id,
                ProjectAfsluitUitstel.project_id.in_(list(ids)),
            )
        )
    }
    uit: list[Kandidaat] = []
    for p in projecten:
        la = laatste.get(p.id)
        spec = specs.get(p.id)
        redenen, tekst = bepaal_redenen(
            naam=p.naam,
            laatste=la,
            jongste_verkoop=verkoop.get(p.id),
            looptijd_tot=spec.looptijd_tot if spec else None,
            vandaag=vandaag,
            stil_maanden=maanden,
        )
        u = uitstel.get(p.id)
        # Uitstel geldt zolang er geen activiteit ná het snapshot is: nieuwe activiteit → opnieuw kandidaat.
        geldig_uitstel: Uitstel | None = None
        if u is not None and redenen:
            nieuwer = la is not None and (u.laatste_activiteit is None or la.datum > u.laatste_activiteit)
            if not nieuwer:
                geldig_uitstel = Uitstel(reden=u.reden, door=u.door, op=u.op, laatste_activiteit=u.laatste_activiteit)
        uit.append(
            Kandidaat(
                administratie_id=administratie_id,
                administratie_naam=administratie_naam,
                project_id=p.id,
                naam=p.naam,
                redenen=redenen,
                reden_tekst=tekst,
                laatste_activiteit=la,
                stil_dagen=(vandaag - la.datum).days if la else None,
                stil_maanden=maanden,
                open_posten=open_posten.get(p.id, OpenPosten()),
                looptijd_tot=spec.looptijd_tot if spec else None,
                uitstel=geldig_uitstel,
            )
        )
    return uit


def _sorteer(rijen: list[Kandidaat]) -> list[Kandidaat]:
    # "Afgesloten …"-namen bovenaan (Peter: die twee eerst), dan meeste redenen, dan langst stil, dan naam.
    return sorted(
        rijen,
        key=lambda k: (
            "naam_afgesloten" not in k.redenen,
            -len(k.redenen),
            -(k.stil_dagen if k.stil_dagen is not None else 10**6),
            k.administratie_naam.lower(),
            (k.naam or "").lower(),
        ),
    )


def lijst(
    *,
    actor_id: uuid.UUID,
    rol: GebruikerRol,
    administratie_id: uuid.UUID | None = None,
    q: str = "",
    reden: str | None = None,
    toon_uitgesteld: bool = False,
    pagina: int = 1,
    vandaag: date | None = None,
) -> Lijst:
    """Tab "Afsluiten? (N)": kantoorbreed over de administraties in scope (administratie = filter, nooit poort) of één
    administratie (deeplink `?administratie=…&tab=afsluiten`). Alleen rijen mét redenen; uitgestelde apart (toggle)."""
    from app.auth import service as auth_service

    if reden is not None and reden not in REDENEN:
        raise AfsluitenFout(f"Onbekende reden: {reden}")
    vandaag = vandaag or vandaag_nl()
    administraties = [
        a
        for a in auth_service.mijn_administraties(actor_id=actor_id, rol=rol)
        if administratie_id is None or a.id == administratie_id
    ]
    alle: list[Kandidaat] = []
    stil_maanden: int | None = None
    for a in administraties:
        with scoped_session(a.id, actor_id=actor_id) as session:
            rijen = kandidaten_voor_administratie(
                session, administratie_id=a.id, administratie_naam=a.naam, vandaag=vandaag
            )
            if administratie_id is not None:
                adm = session.get(Administratie, a.id)
                stil_maanden = int(adm.project_afsluit_stil_maanden) if adm else STIL_MAANDEN_DEFAULT
        alle.extend(r for r in rijen if r.redenen)
    kandidaten = [r for r in alle if r.kandidaat]
    uitgesteld = [r for r in alle if r.uitgesteld]
    per_reden = {rd: sum(1 for r in kandidaten if rd in r.redenen) for rd in REDENEN}
    tellers = Tellers(
        kandidaten=len(kandidaten),
        uitgesteld=len(uitgesteld),
        administraties=len({r.administratie_id for r in kandidaten}),
        per_reden=per_reden,
        let_op=sum(1 for r in kandidaten if r.open_posten.let_op),
    )
    basis = uitgesteld if toon_uitgesteld else kandidaten
    term = q.strip().lower()
    selectie = _sorteer(
        [r for r in basis if (not term or term in r.zoektekst) and (reden is None or reden in r.redenen)]
    )
    start = (pagina - 1) * PER_PAGINA
    return Lijst(
        rijen=selectie[start : start + PER_PAGINA],
        totaal=len(selectie),
        pagina=pagina,
        per_pagina=PER_PAGINA,
        tellers=tellers,
        stil_maanden=stil_maanden,
    )


def aantal_kandidaten(*, actor_id: uuid.UUID, rol: GebruikerRol, administratie_id: uuid.UUID | None = None) -> int:
    return lijst(actor_id=actor_id, rol=rol, administratie_id=administratie_id).tellers.kandidaten


# --- handelingen ------------------------------------------------------------------------------------------------------


def stel_afsluiten_uit(
    *, administratie_id: uuid.UUID, project_id: uuid.UUID, actor_id: uuid.UUID, reden: str
) -> Uitstel:
    """ "Niet afsluiten" mét verplichte reden: upsert + snapshot van de laatste activiteit + audit. Rol
    Beheerder/B+P."""
    from app.projecten.kantoor import ProjectNietGevonden, _vereis_schrijfrol

    reden = (reden or "").strip()
    if not reden:
        raise RedenVerplicht("Een reden is verplicht bij 'Niet afsluiten' — niets verdwijnt stil")
    nu = datetime.now(UTC)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _vereis_schrijfrol(session, actor_id)
        project = session.get(ProjectCache, (project_id, administratie_id))
        if project is None or project.verdwenen_uit_bron_op is not None:
            raise ProjectNietGevonden(f"Onbekend project: {project_id}")
        laatste, _ = activiteit_per_project(session, administratie_id=administratie_id, project_ids={project_id})
        la = laatste.get(project_id)
        rij = session.get(ProjectAfsluitUitstel, (project_id, administratie_id))
        oud = (
            None
            if rij is None
            else {
                "reden": rij.reden,
                "laatste_activiteit": rij.laatste_activiteit.isoformat() if rij.laatste_activiteit else None,
            }
        )
        if rij is None:
            rij = ProjectAfsluitUitstel(
                project_id=project_id, administratie_id=administratie_id, reden=reden, door=actor_id
            )
            session.add(rij)
        rij.reden = reden
        rij.door = actor_id
        rij.op = nu
        rij.laatste_activiteit = la.datum if la else None
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="project_afsluit_uitstel",
            record_id=project_id,
            actie="project_afsluiten_uitgesteld",
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde={
                "reden": reden,
                "laatste_activiteit": la.datum.isoformat() if la else None,
                "project_naam": project.naam,
            },
            administratie_id=administratie_id,
        )
        return Uitstel(reden=reden, door=actor_id, op=nu, laatste_activiteit=la.datum if la else None)


def _bron_client(administratie_id: uuid.UUID) -> tuple[Any | None, str | None]:
    """Eén bron-client per administratie voor de bulk (RLZ of Odoo); geen credential = leesbare reden, geen exception."""
    from app.backends.port import Backend
    from app.backends.registry import backend_voor

    try:
        if backend_voor(administratie_id) is Backend.ODOO:
            from app.odoo.credentials import GeenOdooKoppeling, odoo_client_voor

            try:
                return odoo_client_voor(administratie_id), None
            except GeenOdooKoppeling as exc:
                return None, f"Geen Odoo-koppeling: {exc}"
        from app.rlz.credentials import GeenRlzCredentials, client_voor_rlz_admin_id, rlz_admin_id_voor

        try:
            rlz_admin_id = rlz_admin_id_voor(administratie_id)
            return client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id), None
        except GeenRlzCredentials as exc:
            return None, f"Geen RLZ-login voor deze administratie: {exc}"
    except Exception as exc:  # noqa: BLE001 — bulk mag nooit halverwege omvallen op één administratie
        return None, f"Bron niet bereikbaar: {exc}"


def sluit_kandidaten_af(
    *,
    actor_id: uuid.UUID,
    rol: GebruikerRol,
    items: list[tuple[uuid.UUID, uuid.UUID]],
    reden: str | None = None,
    datum: date | None = None,
    client_factory: Any | None = None,
) -> list[BulkUitkomst]:
    """Bulk "Afsluiten (N)": per project de bestaande 0160-flow, uitkomst per rij (gelukt / RLZ weigerde mét reden /
    al inactief / niet gevonden / geen toegang). Eén bron-client per administratie. Rolpoort (GeenSchrijfrecht)
    propageert
    als geheel — wie niet mag, sluit niets. `client_factory(administratie_id) -> (client, reden)` = testseam."""
    from app.auth import service as auth_service
    from app.projecten import status as status_service
    from app.projecten.kantoor import _SCHRIJF_ROLLEN, GeenSchrijfrecht, ProjectNietGevonden

    # Fail-closed vóór er iets gebeurt: wie geen schrijfrol heeft, sluit niets — ook niet als de bron toch al zou weigeren.
    if rol not in _SCHRIJF_ROLLEN:
        raise GeenSchrijfrecht("Projecten afsluiten is voorbehouden aan Beheerder en Boekhouding+Projecten")
    in_scope = {a.id for a in auth_service.mijn_administraties(actor_id=actor_id, rol=rol)}
    per_admin: dict[uuid.UUID, list[uuid.UUID]] = {}
    volgorde: list[tuple[uuid.UUID, uuid.UUID]] = []
    for aid, pid in items:
        if (aid, pid) in volgorde:
            continue
        volgorde.append((aid, pid))
        per_admin.setdefault(aid, []).append(pid)
    namen: dict[tuple[uuid.UUID, uuid.UUID], str | None] = {}
    uitkomsten: dict[tuple[uuid.UUID, uuid.UUID], BulkUitkomst] = {}
    factory = client_factory or _bron_client
    for aid, pids in per_admin.items():
        if aid not in in_scope:
            for pid in pids:
                uitkomsten[(aid, pid)] = BulkUitkomst(aid, pid, None, "geen_toegang", "Administratie buiten je scope")
            continue
        with scoped_session(aid, actor_id=actor_id) as session:
            for p in session.scalars(
                select(ProjectCache).where(ProjectCache.administratie_id == aid, ProjectCache.id.in_(pids))
            ):
                namen[(aid, p.id)] = p.naam
        client, client_reden = factory(aid)
        try:
            for pid in pids:
                naam = namen.get((aid, pid))
                if client is None:
                    uitkomsten[(aid, pid)] = BulkUitkomst(aid, pid, naam, "bron_weigert", client_reden)
                    continue
                try:
                    status_service.sluit_project_af(
                        administratie_id=aid, project_id=pid, actor_id=actor_id, reden=reden, datum=datum, client=client
                    )
                    uitkomsten[(aid, pid)] = BulkUitkomst(aid, pid, naam, "gelukt", None)
                except status_service.StatusOngewijzigd as exc:
                    uitkomsten[(aid, pid)] = BulkUitkomst(aid, pid, naam, "al_afgesloten", str(exc))
                except status_service.BronWeigert as exc:
                    uitkomsten[(aid, pid)] = BulkUitkomst(aid, pid, naam, "bron_weigert", str(exc))
                except ProjectNietGevonden as exc:
                    uitkomsten[(aid, pid)] = BulkUitkomst(aid, pid, naam, "niet_gevonden", str(exc))
        finally:
            if client is not None and client_factory is None and hasattr(client, "close"):
                client.close()
    return [uitkomsten[k] for k in volgorde]


def haal_stil_maanden(*, administratie_id: uuid.UUID) -> int:
    with scoped_session(administratie_id) as session:
        adm = session.get(Administratie, administratie_id)
        return int(adm.project_afsluit_stil_maanden) if adm else STIL_MAANDEN_DEFAULT


def zet_stil_maanden(*, administratie_id: uuid.UUID, actor_id: uuid.UUID, maanden: int) -> int:
    """Stil-venster per administratie (Beheerder + B+P via `_vereis_schrijfrol`), 1..36 maanden, audit oud→nieuw."""
    from app.projecten.kantoor import _vereis_schrijfrol

    if not isinstance(maanden, int) or maanden < STIL_MAANDEN_MIN or maanden > STIL_MAANDEN_MAX:
        raise OngeldigStilVenster(f"Stil-venster moet tussen {STIL_MAANDEN_MIN} en {STIL_MAANDEN_MAX} maanden liggen")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _vereis_schrijfrol(session, actor_id)
        adm = session.get(Administratie, administratie_id)
        if adm is None:
            raise AfsluitenFout(f"Onbekende administratie: {administratie_id}")
        oud = int(adm.project_afsluit_stil_maanden)
        adm.project_afsluit_stil_maanden = maanden
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="administratie",
            record_id=administratie_id,
            actie="project_afsluit_stil_maanden_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"project_afsluit_stil_maanden": oud},
            nieuwe_waarde={"project_afsluit_stil_maanden": maanden},
        )
        return maanden


# --- rapport (CLI) ----------------------------------------------------------------------------------------------------


def rapportregels(rijen: list[Kandidaat], *, alles: bool = False) -> list[str]:
    uit: list[str] = []
    for k in _sorteer(rijen):
        if not (k.redenen or alles):
            continue
        la = k.laatste_activiteit
        la_txt = (
            f"{la.soort} {la.datum.isoformat()}"
            + (f" € {la.bedrag}" if la.bedrag is not None else "")
            + (f" [{la.boekstuk}]" if la.boekstuk else "")
            if la
            else "geen activiteit bekend"
        )
        op = k.open_posten
        let_op = []
        if op.inkoop_niet_geboekt:
            let_op.append(f"{op.inkoop_niet_geboekt} inkoop niet geboekt (€ {op.inkoop_niet_geboekt_bedrag})")
        if op.verplichting_open:
            let_op.append(f"{op.verplichting_open} verplichting open")
        if op.uren_niet_gekeurd:
            let_op.append(f"{op.uren_niet_gekeurd} weekstaat niet gekeurd")
        stand = "UITGESTELD" if k.uitgesteld else ("KANDIDAAT " if k.redenen else "nee       ")
        uit.append(
            f"  {stand} {k.project_id}  {k.naam!r}  redenen={','.join(k.redenen) or '—'}  laatste={la_txt}"
            + (f"  LET OP: {'; '.join(let_op)}" if let_op else "")
            + (f"  uitstel: {k.uitstel.reden!r} ({k.uitstel.op.date().isoformat()})" if k.uitstel else "")
        )
    return uit
