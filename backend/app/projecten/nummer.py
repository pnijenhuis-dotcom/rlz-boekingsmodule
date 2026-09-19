"""Projectnummer uniek (blok B opdracht 18-09, Peter: "per abuis 2× hetzelfde projectnummer aangemaakt — moet
geblokkeerd worden"). Het nummer is de cijfer-prefix van de projectnaam (RLZ heeft géén codeveld — STAP-0 16-09); uniek
BINNEN de
administratie over álle projecten (lopend + afgesloten, actief + inactief), getoetst op de cache én live in RLZ
(`startswith(Name,'26127 ') or startswith(Name,'Afgesloten 26127 ')` — opdracht 19-09: het afsluitwoord van
Universal vóór de naam telt niet als naam, het nummer erachter bezet het nummer óók). Bestaat het nummer →
`ProjectnummerBestaatAl` (router: 409 mét het bestaande project),
nooit
stil een tweede aanmaken. Daarnaast: het lees-only rapport "dubbele nummers" (Peter's casus, klikpunt samenvoegen) en de
reconciliatie-soort `project_nummer_dubbel` (stand `meten`) voor dubbelen die buiten de module om in RLZ ontstaan.
Puur code — geen AI, geen writes."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.projectverdeling.omzet import naam_zegt_afgesloten
from app.sync.models import PROJECT_STATUS_AFGESLOTEN, ProjectCache

#: Cijfer-prefix volgens de naamconventie "26127 Tilburg (Heijmans)" — drie tot zes cijfers, gevolgd door het einde óf
#: een niet-cijfer (zodat "261270 …" geen treffer voor 26127 is).
_NUMMER_PREFIX = re.compile(r"^\s*(\d{3,6})(?!\d)")

#: Bijvangst nameting 19-09: Universal zet het woord "Afgesloten" VÓÓR de naam als afsluitmarkering ("Afgesloten 26064
#: Apeldoorn (Ben Kuijer)", 94 van 170 projecten) — het nummer staat dan op de tweede positie. Eén afsluitwoord, alleen
#: als eerste woord (`omzet.naam_zegt_afgesloten`, hoofdletterongevoelig); daarna wordt de rest als gewone naam gelezen.
AFGESLOTEN_VOORVOEGSEL = "Afgesloten "

#: Reconciliatie-blok + soort (registry in app/reconciliatie/soort_stand.py — start in `meten`).
BLOK = "projecten"
SOORT = "project_nummer_dubbel"


def zonder_afgesloten_voorvoegsel(naam: str | None) -> str:
    """ "Afgesloten 26064 Apeldoorn (Ben Kuijer)" → "26064 Apeldoorn (Ben Kuijer)"; een naam zonder het afsluitwoord als
    eerste woord blijft ongewijzigd. Alleen het EERSTE woord telt (patroon `naam_zegt_afgesloten`): "Project afgesloten
    26064" is géén afsluitmarkering en levert dus geen nummer."""
    if not naam:
        return ""
    if not naam_zegt_afgesloten(naam):
        return naam
    delen = naam.strip().split(maxsplit=1)
    return delen[1] if len(delen) == 2 else ""


def cijfer_prefix(naam: str | None) -> str | None:
    """ "26127 Tilburg (Heijmans)" → "26127"; "Afgesloten 26064 Apeldoorn" → "26064" (opdracht 19-09: de
    afsluitmarkering van Universal telt niet als naam); geen cijfer-prefix → None (nooit raden). Eén functie voor de
    409-poort, `project_nummer_dubbel`, `projecten-dubbele-nummers` én `volgende_projectnummer`."""
    if not naam:
        return None
    m = _NUMMER_PREFIX.match(zonder_afgesloten_voorvoegsel(naam))
    return m.group(1) if m else None


def rlz_prefixen(nummer: str) -> tuple[str, str]:
    """De twee RLZ-`startswith`-vormen waarin een nummer als naam-prefix kan staan: "26064 " en "Afgesloten 26064 " (de
    spatie erachter zorgt dat 261270 geen treffer voor 26127 is)."""
    return (f"{nummer} ", f"{AFGESLOTEN_VOORVOEGSEL}{nummer} ")


@dataclass(frozen=True)
class NummerTreffer:
    project_id: uuid.UUID
    naam: str
    status: str  # lopend | afgesloten
    is_actief: bool | None
    bron: str  # 'cache' | 'rlz'


class ProjectnummerBestaatAl(Exception):
    """Het nummer bestaat al in deze administratie — de router maakt er een 409 van mét het bestaande project."""

    def __init__(self, nummer: str, treffer: NummerTreffer) -> None:
        status = "afgesloten" if treffer.status == PROJECT_STATUS_AFGESLOTEN or treffer.is_actief is False else "lopend"
        super().__init__(f"{nummer} bestaat al: {treffer.naam}, {status} — openen?")
        self.nummer = nummer
        self.treffer = treffer
        self.status_label = status

    def als_detail(self) -> dict[str, Any]:
        return {
            "code": "projectnummer_bestaat_al",
            "melding": str(self),
            "nummer": self.nummer,
            "bestaand_project_id": str(self.treffer.project_id),
            "bestaand_naam": self.treffer.naam,
            "status": self.status_label,
            "bron": self.treffer.bron,
        }


def treffers_in_cache(session: Session, *, administratie_id: uuid.UUID, nummer: str) -> list[NummerTreffer]:
    """Alle niet-verdwenen cache-projecten van de administratie mét exact dit nummer als cijfer-prefix (status maakt
    niet uit: een afgesloten of inactief project bezet het nummer óók)."""
    # Voorselectie ruim (nummer aan het begin óf ná het afsluitwoord, hoofdletterongevoelig via ilike); de exacte toets
    # is `cijfer_prefix` — dat is de ene bron van waarheid, ook voor "Afgesloten 26064 …" (opdracht 19-09).
    rijen = session.scalars(
        select(ProjectCache).where(
            ProjectCache.administratie_id == administratie_id,
            ProjectCache.verdwenen_uit_bron_op.is_(None),
            or_(ProjectCache.naam.like(f"{nummer}%"), ProjectCache.naam.ilike("afgesloten%")),
        )
    )
    return [
        NummerTreffer(project_id=r.id, naam=r.naam or "", status=r.status, is_actief=r.is_actief, bron="cache")
        for r in rijen
        if cijfer_prefix(r.naam) == nummer
    ]


def treffers_in_rlz(client: Any, *, nummer: str) -> list[NummerTreffer]:
    """Live RLZ-lookup (klanten kunnen buiten de module om projecten maken): één GET `startswith(Name,'<nummer> ') or
    startswith(Name,'Afgesloten <nummer> ')` (STAP-0 19-09: de OData-`or` werkt op Projects) — zo telt ook een project
    dat Universal al met het afsluitwoord heeft gemarkeerd als bezet. Een client mét alleen de oudere enkelvoudige
    methode krijgt twee GET's; een client zonder beide (oudere fakes) telt als "geen extra treffers"; een RLZ-fout laat
    de aanroeper beslissen."""
    prefixen = rlz_prefixen(nummer)
    zoek_meer = getattr(client, "find_projects_by_name_prefixes", None)
    if zoek_meer is not None:
        ruw = list(zoek_meer(prefixes=prefixen))
    else:
        zoek = getattr(client, "find_projects_by_name_prefix", None)
        if zoek is None:
            return []
        ruw = [p for prefix in prefixen for p in zoek(prefix=prefix)]
    uit: list[NummerTreffer] = []
    gezien: set[uuid.UUID] = set()
    for p in ruw:
        naam = str(p.get("Name") or "")
        if cijfer_prefix(naam) != nummer:
            continue
        try:
            pid = uuid.UUID(str(p.get("id")))
        except ValueError:
            continue
        if pid in gezien:
            continue
        gezien.add(pid)
        uit.append(NummerTreffer(project_id=pid, naam=naam, status="lopend", is_actief=p.get("IsActive"), bron="rlz"))
    return uit


def vereis_nummer_vrij(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    nummer: str,
    client: Any | None,
    toegestaan_id: uuid.UUID | None = None,
    toegestane_naam: str | None = None,
) -> None:
    """Poort vóór het aanmaken: bestaat het nummer al (cache óf RLZ) op een ander project, of op hetzelfde
    deterministische
    GUID maar met een ándere naam (Peter's casus: zelfde nummer, andere plaats) → `ProjectnummerBestaatAl`. Alleen exact
    dezelfde naam op `toegestaan_id` mag door (dat is de idempotente herhaal-klik, geen tweede project)."""
    treffers = treffers_in_cache(session, administratie_id=administratie_id, nummer=nummer)
    if client is not None:
        bekend = {t.project_id for t in treffers}
        treffers += [t for t in treffers_in_rlz(client, nummer=nummer) if t.project_id not in bekend]
    for t in treffers:
        if toegestaan_id is not None and t.project_id == toegestaan_id and t.naam == (toegestane_naam or ""):
            continue
        raise ProjectnummerBestaatAl(nummer, t)


# --- dubbele nummers (rapport + reconciliatie) -----------------------------------------------------------------------


@dataclass(frozen=True)
class DubbelNummer:
    nummer: str
    projecten: tuple[NummerTreffer, ...]
    #: per project_id: aantal factuurregels (project_regel_cache), weekstaten, planningregels — de "wat
    #: verhuist"-kolommen
    tellers: dict[uuid.UUID, dict[str, int]] = field(default_factory=dict)


def dubbele_nummers(session: Session, *, administratie_id: uuid.UUID) -> list[DubbelNummer]:
    """Alle nummers die in de cache van deze administratie op ≥ 2 niet-verdwenen projecten staan, mét per kant de
    tellers facturen/uren/planning (lees-only; bron voor het klikpunt "samenvoegen" — nooit automatisch)."""
    from app.projecten.models import ProjectRegelCache
    from app.uren.models import PlanningToewijzing, Weekstaat

    per_nummer: dict[str, list[NummerTreffer]] = {}
    for r in session.scalars(
        select(ProjectCache).where(
            ProjectCache.administratie_id == administratie_id, ProjectCache.verdwenen_uit_bron_op.is_(None)
        )
    ):
        nr = cijfer_prefix(r.naam)
        if nr is None:
            continue
        per_nummer.setdefault(nr, []).append(
            NummerTreffer(project_id=r.id, naam=r.naam or "", status=r.status, is_actief=r.is_actief, bron="cache")
        )
    dubbel = {nr: ts for nr, ts in per_nummer.items() if len(ts) >= 2}
    if not dubbel:
        return []
    ids = [t.project_id for ts in dubbel.values() for t in ts]

    def tel(kolom, model, extra_where=()) -> dict[uuid.UUID, int]:  # noqa: ANN001
        return dict(
            session.execute(
                select(kolom, func.count())
                .where(model.administratie_id == administratie_id, kolom.in_(ids), *extra_where)
                .group_by(kolom)
            ).all()
        )

    facturen = tel(
        ProjectRegelCache.project_id, ProjectRegelCache, (ProjectRegelCache.verdwenen_uit_bron_op.is_(None),)
    )
    uren = tel(Weekstaat.project_id, Weekstaat)
    planning = tel(PlanningToewijzing.project_id, PlanningToewijzing)
    uit: list[DubbelNummer] = []
    for nr in sorted(dubbel):
        ts = tuple(sorted(dubbel[nr], key=lambda t: t.naam))
        uit.append(
            DubbelNummer(
                nummer=nr,
                projecten=ts,
                tellers={
                    t.project_id: {
                        "facturen": facturen.get(t.project_id, 0),
                        "weekstaten": uren.get(t.project_id, 0),
                        "planning": planning.get(t.project_id, 0),
                    }
                    for t in ts
                },
            )
        )
    return uit


def rapportregels(dubbel: Iterable[DubbelNummer]) -> list[str]:
    """Leesbare regels voor het lees-only CLI-rapport `projecten-dubbele-nummers` (klikpunt Peter: welke blijft, wat
    verhuist — voorstel: het project mét de meeste facturen/uren blijft; de verliezer gaat ná verhuizing op
    IsActive=false,
    nooit verwijderen)."""
    uit: list[str] = []
    for d in dubbel:
        kant = max(d.projecten, key=lambda t: sum(d.tellers.get(t.project_id, {}).values()))
        uit.append(f"  nummer {d.nummer} — {len(d.projecten)} projecten:")
        for t in d.projecten:
            tl = d.tellers.get(t.project_id, {})
            blijft = "  ← voorstel: blijft" if t.project_id == kant.project_id else ""
            uit.append(
                f"    {t.project_id}  {t.naam!r}  status={t.status} actief={t.is_actief}  "
                f"facturen={tl.get('facturen', 0)} "
                f"weekstaten={tl.get('weekstaten', 0)} planning={tl.get('planning', 0)}{blijft}"
            )
    return uit


def cli_blok(args, verzamelaar=None, *, stdout: Callable[[str], None] = print) -> int:  # noqa: ANN001
    """Blokfunctie `projecten` voor `reconciliatie-alles` (contract als `rlz_dubbel.cli_blok`): per actieve
    administratie
    één afwijking `project_nummer_dubbel` per dubbel nummer (vingerafdruk = administratie + nummer, stabiel over runs).
    Soort start in stand `meten` (registry) — telt, vraagt nog geen handeling. Exit 1 zodra er een dubbel is."""
    from app.db.models import Administratie
    from app.db.session import scoped_session
    from app.projectverdeling import afgesloten
    from app.reconciliatie.models import BevindingSoort

    with scoped_session(None) as session:
        administraties = session.execute(
            select(Administratie.id, Administratie.naam)
            .where(Administratie.actief.is_(True))
            .order_by(Administratie.naam)
        ).all()
    exit_code = 0
    totaal = 0
    let_op_totaal = 0
    for aid, naam in administraties:
        with scoped_session(aid) as session:
            dubbel = dubbele_nummers(session, administratie_id=aid)
            # Opdracht 19-09: actief project mét een "Afgesloten"-naam = LET-OP "afsluiten?" (geen filter in de sleutel).
            let_ops = afgesloten.let_op_bevindingen(session, administratie_id=aid, administratie_naam=naam)
        if verzamelaar is not None:
            verzamelaar.gecontroleerd(1)
        for lo in let_ops:
            let_op_totaal += 1
            stdout(f"{lo['tekst']}  [{naam}]")
            if verzamelaar is not None:
                verzamelaar.bevinding(**lo)
        for d in dubbel:
            totaal += 1
            exit_code = 1
            namen = " | ".join(f"{t.naam} ({t.status})" for t in d.projecten)
            tekst = (
                f"AFWIJKING  administratie={aid} soort={SOORT} nummer={d.nummer}: "
                f"{len(d.projecten)} projecten — {namen}"
            )
            stdout(f"{tekst}  [{naam}]")
            if verzamelaar is not None:
                verzamelaar.bevinding(
                    soort=BevindingSoort.AFWIJKING.value,
                    administratie_id=aid,
                    vingerafdruk=f"{BLOK}:{aid}:{d.nummer}",
                    tekst=tekst,
                    detail={
                        "afwijking_soort": SOORT,
                        "administratie_naam": naam,
                        "nummer": d.nummer,
                        "projecten": [
                            {
                                "project_id": str(t.project_id),
                                "naam": t.naam,
                                "status": t.status,
                                **d.tellers.get(t.project_id, {}),
                            }
                            for t in d.projecten
                        ],
                    },
                    blok=BLOK,
                )
    stdout(
        f"projecten-reconciliatie: {len(administraties)} administraties, {totaal} dubbel(e) projectnummer(s), "
        f"{let_op_totaal} actief project(en) mét 'Afgesloten'-naam (LET-OP)"
    )
    return exit_code
