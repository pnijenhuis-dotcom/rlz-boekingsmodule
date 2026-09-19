"""Projectverdeling × projectstatus (opdracht 19-09, nazorg rapport 2026-09-18-facturen-zonder-project beslispunt 3).

Drie dingen, alle deterministisch en zonder RLZ-calls:

1. **Herberekening bij afsluiten/heropenen** (`herbereken_na_projectstatus`): de omzetsleutel
(`omzet.omzet_per_project`)
   neemt sinds 19-09 uitsluitend projecten mét `is_actief` ÉN module-status ≠ afgesloten. Een VOORSTEL-verdeling wordt
   bij
   elke lezing al live herrekend, maar het opgeslagen snapshot (`verdeling`/`omzetstanden`) en de tijdlijn niet — dus
   ná de
   statuswissel (0160-flow, `app/projecten/status.py`) herrekent deze module de nog niet geboekte verdelingen die het
   project
   raken, schrijft het snapshot terug en zet één tijdlijnregel "verdeling herberekend: ‹project› afgesloten" + audit.
   Geboekte verdelingen blijven staan (boekstand — herverdelen is de bestaande tegenboek-route). Nooit blokkerend: een
   fout hier maakt het afsluiten niet ongedaan (logregel, de volgende lezing rekent tóch live).
2. **LET-OP "naam zegt afgesloten, status actief"** (`let_op_bevindingen`): een project waarvan de NAAM met "Afgesloten"
   begint maar dat actief staat, blijft in de sleutel (nooit stil uitsluiten op naam) en wordt in het reconciliatieblok
   `projecten` gemeld mét de actie "Projecten › afsluiten".
3. **Lees-only rapport** (`rapport_geboekt_op_afgesloten`, `rapport_overhead_via_sleutel`; CLI
   `projectverdeling-afgesloten-rapport`): geboekte verdelingsdelen op projecten die nú afgesloten/inactief zijn of
   "Afgesloten" heten, mét voorstel per rij (storno + herverdeling / laten staan) — niets uitvoeren; plus wat er via de
   sleutel loopt dat overhead is (4xxx zonder projectreferentie) en wat een OVH-project zou vangen (beslispunt Peter).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Grootboekrekening
from app.db.session import scoped_session
from app.documenten.models import Boekvoorstel, BoekvoorstelRegel, Document, DocumentGebeurtenis, DocumentStatus
from app.projectverdeling import data as pv
from app.projectverdeling.models import Projectverdeling
from app.projectverdeling.omzet import actieve_projecten_met_afgesloten_naam, naam_zegt_afgesloten
from app.sync.models import PROJECT_STATUS_AFGESLOTEN, ProjectCache, VendorCache

logger = logging.getLogger(__name__)

#: Bevindingssoort in het reconciliatieblok `projecten` (LET-OP, nooit een afwijking: de sleutel is niet fout, de status
#: is
#: nog niet gezet). Tekst: app/reconciliatie/teksten.py::_let_op; stand: soort_stand.REGISTRY (meten).
SOORT_NAAM_AFGESLOTEN = "project_naam_afgesloten_status_actief"
BLOK = "projecten"
_BEVROREN = frozenset({DocumentStatus.GEBOEKT, DocumentStatus.VERWIJDERD})


# --- 1. herberekening bij statuswissel
# -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class HerberekenUitkomst:
    project_id: uuid.UUID
    project_naam: str | None
    naar: str
    bekeken: int
    herberekend: int
    document_ids: list[uuid.UUID] = field(default_factory=list)


def _kandidaat_rijen(
    session: Session, *, administratie_id: uuid.UUID, project_id: uuid.UUID, naar: str
) -> list[Projectverdeling]:
    """Afsluiten: voorstel-rijen waarvan het snapshot het project draagt (verdeling of omzetstanden). Heropenen: álle
    pro-rato-voorstellen van de administratie — het project kan nu (weer) in de sleutel komen, dat zie je niet aan het
    oude snapshot."""
    q = select(Projectverdeling).where(
        Projectverdeling.administratie_id == administratie_id,
        Projectverdeling.status == pv.STATUS_VOORSTEL,
    )
    if naar == PROJECT_STATUS_AFGESLOTEN:
        sleutel = [{"project_id": str(project_id)}]
        q = q.where(or_(Projectverdeling.verdeling.contains(sleutel), Projectverdeling.omzetstanden.contains(sleutel)))
    else:
        q = q.where(Projectverdeling.pro_rato_periode.is_not(None))
    return list(session.scalars(q.order_by(Projectverdeling.aangemaakt_op)))


def herbereken_na_projectstatus(
    *,
    administratie_id: uuid.UUID,
    project_id: uuid.UUID,
    project_naam: str | None,
    naar: str,
    actor_id: uuid.UUID,
    vandaag: date | None = None,
) -> HerberekenUitkomst:
    """Ná de statuswissel van een project (afgesloten ↔ lopend): herreken de NOG NIET GEBOEKTE verdelingen die het
    project
    raken, schrijf het snapshot terug en zet per gewijzigd document één tijdlijnregel + audit. Geboekte verdelingen
    blijven
    (boekstand). Eigen transactie — de aanroeper (status._wissel) vangt élke fout: afsluiten mag hier nooit op
    stranden."""
    from app.projectverdeling import service

    label = "afgesloten" if naar == PROJECT_STATUS_AFGESLOTEN else "heropend"
    naam = project_naam or str(project_id)
    reden = f"verdeling herberekend: {naam} {label}"
    herberekend: list[uuid.UUID] = []
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rijen = _kandidaat_rijen(session, administratie_id=administratie_id, project_id=project_id, naar=naar)
        for row in rijen:
            document = session.get(Document, row.document_id)
            if document is None or document.status in _BEVROREN:
                continue
            regels = [
                (r.project_id, r.netto_bedrag)
                for r in session.scalars(
                    select(BoekvoorstelRegel).where(BoekvoorstelRegel.document_id == row.document_id)
                )
            ]
            live = service._live(
                session,
                administratie_id=administratie_id,
                regels=regels,
                vaste=pv.vaste_regels_uit_json(row.vaste_regels),
                periode=service._periode_van(row),
                status=pv.STATUS_VOORSTEL,
                opgeslagen=True,
                prefill=False,
                boek_cyclus=None,
                vandaag=vandaag,
            )
            nieuw = pv.delen_naar_json(live.delen)
            nieuwe_standen = pv.omzetstanden_naar_json(live.omzetstanden)
            if nieuw == row.verdeling and nieuwe_standen == row.omzetstanden:
                continue
            oud = row.verdeling
            row.verdeling = nieuw
            row.omzetstanden = nieuwe_standen
            row.pro_rato_bedrag = live.pro_rato_bedrag
            session.add(
                DocumentGebeurtenis(
                    document_id=row.document_id,
                    van_status=document.status,
                    naar_status=document.status,
                    actor_id=actor_id,
                    detail={
                        "projectverdeling_herberekend": {
                            "project_id": str(project_id),
                            "project_naam": project_naam,
                            "aanleiding": label,
                            "oude_verdeling": oud,
                            "nieuwe_verdeling": nieuw,
                        },
                        "reden": reden,
                    },
                )
            )
            record_audit_event(
                session,
                actor_id=actor_id,
                module="boekhouding",
                tabel="projectverdeling",
                record_id=row.document_id,
                actie="projectverdeling_herberekend",
                correlatie_id=uuid.uuid4(),
                oude_waarde={"verdeling": oud},
                nieuwe_waarde={"verdeling": nieuw, "reden": reden, "project_id": str(project_id)},
                administratie_id=administratie_id,
            )
            herberekend.append(row.document_id)
    return HerberekenUitkomst(
        project_id=project_id,
        project_naam=project_naam,
        naar=naar,
        bekeken=len(rijen),
        herberekend=len(herberekend),
        document_ids=herberekend,
    )


def herbereken_na_projectstatus_veilig(**kwargs) -> HerberekenUitkomst | None:  # noqa: ANN003
    """Wrapper voor de statuswissel: nooit blokkerend, fout = logregel (de volgende lezing rekent tóch live)."""
    try:
        return herbereken_na_projectstatus(**kwargs)
    except Exception:  # noqa: BLE001 — bewust: afsluiten mag hier niet op stranden
        logger.exception(
            "projectverdeling-herberekening ná projectstatus mislukt (project %s, administratie %s) — voorstel "
            "rekent bij "
            "de volgende lezing live",
            kwargs.get("project_id"),
            kwargs.get("administratie_id"),
        )
        return None


# --- 2. LET-OP "naam zegt afgesloten, status actief" ------------------------------------------------------------------


def let_op_bevindingen(session: Session, *, administratie_id: uuid.UUID, administratie_naam: str | None) -> list[dict]:
    """Per actief project mét een "Afgesloten"-naam één LET-OP-dict voor `Verzamelaar.bevinding` (blok `projecten`;
    vingerafdruk administratie + project, stabiel over runs). Actie: Projecten › afsluiten — dan valt het project uit de
    sleutel via de status, nooit via de naam."""
    uit: list[dict] = []
    for p in actieve_projecten_met_afgesloten_naam(session, administratie_id=administratie_id):
        tekst = (
            f"LET-OP  administratie={administratie_id} soort={SOORT_NAAM_AFGESLOTEN} project={p.id}: "
            f"naam zegt afgesloten, status actief — afsluiten? ({p.naam})"
        )
        uit.append(
            {
                "soort": "let_op",
                "administratie_id": administratie_id,
                "vingerafdruk": f"{BLOK}:{administratie_id}:naam_afgesloten:{p.id}",
                "tekst": tekst,
                "detail": {
                    "afwijking_soort": SOORT_NAAM_AFGESLOTEN,
                    "administratie_naam": administratie_naam,
                    "project_id": str(p.id),
                    "project_naam": p.naam,
                    "is_actief": p.is_actief,
                    "status": p.status,
                    "deeplink": f"/projecten/{administratie_id}/{p.id}",
                },
                "blok": BLOK,
            }
        )
    return uit


# --- 3. lees-only rapport
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class GeboektOpAfgeslotenRij:
    document_id: uuid.UUID
    boekstuk: str | None
    referentie: str | None
    leverancier: str | None
    factuurdatum: date | None
    geboekt_op: datetime | None
    project_id: uuid.UUID
    project_naam: str | None
    project_stand: str  # "afgesloten (module)" | "inactief in de bron" | "naam zegt afgesloten, actief"
    wijze: str
    bedrag: Decimal
    voorstel: str


def _project_stand(p: ProjectCache) -> str | None:
    if p.status == PROJECT_STATUS_AFGESLOTEN:
        return "afgesloten (module)"
    if p.is_actief is not True:
        return "inactief in de bron"
    if naam_zegt_afgesloten(p.naam):
        return "naam zegt afgesloten, actief"
    return None


def _voorstel(stand: str) -> str:
    if stand == "naam zegt afgesloten, actief":
        return (
            "laten staan tot het project is afgesloten (Projecten › afsluiten); daarna storno 19 + herverdeling — "
            "klikpunt Peter"
        )
    return (
        "storno 19 + herverdeling over de actieve projecten (aangiftepoort toetsen; tegenboek-pad bij ingediend) "
        "— klikpunt Peter"
    )


def rapport_geboekt_op_afgesloten(session: Session, *, administratie_id: uuid.UUID) -> list[GeboektOpAfgeslotenRij]:
    """Geboekte verdelingsdelen (snapshot `verdeling`) op projecten die nú afgesloten/inactief zijn of "Afgesloten"
    heten.
    Lees-only; het voorstel per rij is tekst, niets wordt uitgevoerd."""
    rijen = list(
        session.scalars(
            select(Projectverdeling)
            .where(
                Projectverdeling.administratie_id == administratie_id,
                Projectverdeling.status == pv.STATUS_GEBOEKT,
            )
            .order_by(Projectverdeling.geboekt_op)
        )
    )
    if not rijen:
        return []
    project_ids: set[uuid.UUID] = set()
    for row in rijen:
        for d in row.verdeling or []:
            try:
                project_ids.add(uuid.UUID(str(d.get("project_id"))))
            except (ValueError, AttributeError):
                continue
    projecten = (
        {
            p.id: p
            for p in session.scalars(
                select(ProjectCache).where(
                    ProjectCache.administratie_id == administratie_id, ProjectCache.id.in_(project_ids)
                )
            )
        }
        if project_ids
        else {}
    )
    koppen = {
        b.document_id: b
        for b in session.scalars(
            select(Boekvoorstel).where(Boekvoorstel.document_id.in_([r.document_id for r in rijen]))
        )
    }
    vendor_ids = {b.vendor_id for b in koppen.values() if b.vendor_id}
    vendors = (
        {
            v.id: v.naam
            for v in session.scalars(
                select(VendorCache).where(
                    VendorCache.administratie_id == administratie_id, VendorCache.id.in_(vendor_ids)
                )
            )
        }
        if vendor_ids
        else {}
    )
    uit: list[GeboektOpAfgeslotenRij] = []
    for row in rijen:
        kop = koppen.get(row.document_id)
        for d in row.verdeling or []:
            try:
                pid = uuid.UUID(str(d.get("project_id")))
            except (ValueError, AttributeError):
                continue
            p = projecten.get(pid)
            stand = _project_stand(p) if p is not None else "project onbekend in de cache"
            if stand is None:
                continue
            uit.append(
                GeboektOpAfgeslotenRij(
                    document_id=row.document_id,
                    boekstuk=kop.rlz_boekstuknummer if kop else None,
                    referentie=kop.referentie if kop else None,
                    leverancier=vendors.get(kop.vendor_id) if kop and kop.vendor_id else None,
                    factuurdatum=kop.factuurdatum if kop else None,
                    geboekt_op=row.geboekt_op,
                    project_id=pid,
                    project_naam=p.naam if p else None,
                    project_stand=stand,
                    wijze=str(d.get("wijze") or "?"),
                    bedrag=Decimal(str(d.get("bedrag") or "0")),
                    voorstel=_voorstel(stand),
                )
            )
    return uit


@dataclass(frozen=True)
class OverheadRij:
    document_id: uuid.UUID
    status: str  # geboekt | voorstel
    document_status: str
    boekstuk: str | None
    referentie: str | None
    leverancier: str | None
    factuurdatum: date | None
    pro_rato_bedrag: Decimal
    grootboek: list[str]  # "4499 Diverse kantoorkosten" per regel zonder project
    overhead: bool  # álle regels zonder project op 4xxx = overhead (algemene kosten)


@dataclass(frozen=True)
class OverheadRapport:
    rijen: list[OverheadRij]
    heeft_ovh_project: bool
    ovh_projecten: list[str]

    @property
    def geboekt_overhead(self) -> Decimal:
        return sum((r.pro_rato_bedrag for r in self.rijen if r.overhead and r.status == pv.STATUS_GEBOEKT), Decimal(0))

    @property
    def onderweg_overhead(self) -> Decimal:
        return sum((r.pro_rato_bedrag for r in self.rijen if r.overhead and r.status == pv.STATUS_VOORSTEL), Decimal(0))


def rapport_overhead_via_sleutel(session: Session, *, administratie_id: uuid.UUID) -> OverheadRapport:
    """Wat loopt er via de pro-rato-sleutel dat overhead is (regels zonder projectreferentie op 4xxx = algemene
    kosten) en
    wat zou een OVH-project vangen (Σ pro_rato_bedrag van die documenten, geboekt + onderweg)? Beslispunt Peter — niets
    wordt aangemaakt."""
    from app.projectverdeling.omzet import is_ovh_project

    rijen = list(
        session.scalars(
            select(Projectverdeling).where(
                Projectverdeling.administratie_id == administratie_id,
                Projectverdeling.status.in_([pv.STATUS_GEBOEKT, pv.STATUS_VOORSTEL]),
                Projectverdeling.pro_rato_periode.is_not(None),
            )
        )
    )
    uit: list[OverheadRij] = []
    if rijen:
        ids = [r.document_id for r in rijen]
        docs = {d.id: d for d in session.scalars(select(Document).where(Document.id.in_(ids)))}
        koppen = {
            b.document_id: b for b in session.scalars(select(Boekvoorstel).where(Boekvoorstel.document_id.in_(ids)))
        }
        regels: dict[uuid.UUID, list[BoekvoorstelRegel]] = {}
        for r in session.scalars(select(BoekvoorstelRegel).where(BoekvoorstelRegel.document_id.in_(ids))):
            regels.setdefault(r.document_id, []).append(r)
        ledger_ids = {r.ledger_id for rs in regels.values() for r in rs if r.ledger_id}
        gb = (
            {
                g.ledger_id: g
                for g in session.scalars(
                    select(Grootboekrekening).where(
                        Grootboekrekening.administratie_id == administratie_id,
                        Grootboekrekening.ledger_id.in_(ledger_ids),
                    )
                )
            }
            if ledger_ids
            else {}
        )
        vendor_ids = {b.vendor_id for b in koppen.values() if b.vendor_id}
        vendors = (
            {
                v.id: v.naam
                for v in session.scalars(
                    select(VendorCache).where(
                        VendorCache.administratie_id == administratie_id, VendorCache.id.in_(vendor_ids)
                    )
                )
            }
            if vendor_ids
            else {}
        )
        for row in rijen:
            doc = docs.get(row.document_id)
            if doc is None or doc.status == DocumentStatus.VERWIJDERD:
                continue
            kop = koppen.get(row.document_id)
            zonder = [r for r in regels.get(row.document_id, []) if r.project_id is None]
            labels: list[str] = []
            codes: list[str] = []
            for r in zonder:
                g = gb.get(r.ledger_id) if r.ledger_id else None
                code = (g.code or "") if g else ""
                codes.append(code)
                labels.append(f"{code or '?'} {(g.naam if g else '') or ''}".strip())
            overhead = bool(zonder) and all(c.startswith("4") for c in codes if c) and all(codes)
            uit.append(
                OverheadRij(
                    document_id=row.document_id,
                    status=row.status,
                    document_status=doc.status.value,
                    boekstuk=kop.rlz_boekstuknummer if kop else None,
                    referentie=kop.referentie if kop else None,
                    leverancier=vendors.get(kop.vendor_id) if kop and kop.vendor_id else None,
                    factuurdatum=kop.factuurdatum if kop else None,
                    pro_rato_bedrag=row.pro_rato_bedrag or Decimal(0),
                    grootboek=labels,
                    overhead=overhead,
                )
            )
    ovh = [
        p.naam or str(p.id)
        for p in session.scalars(
            select(ProjectCache).where(
                ProjectCache.administratie_id == administratie_id, ProjectCache.verdwenen_uit_bron_op.is_(None)
            )
        )
        if is_ovh_project(p.naam)
    ]
    return OverheadRapport(rijen=uit, heeft_ovh_project=bool(ovh), ovh_projecten=ovh)


def _euro(bedrag: Decimal | None) -> str:
    return f"€ {bedrag or Decimal(0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def rapportregels(
    *,
    administratie_naam: str | None,
    administratie_id: uuid.UUID,
    let_op: list[ProjectCache],
    geboekt: list[GeboektOpAfgeslotenRij],
    overhead: OverheadRapport,
) -> list[str]:
    r: list[str] = [f"== {administratie_naam or '?'} ({administratie_id}) =="]
    r.append(f"-- Actieve projecten mét een 'Afgesloten'-naam (LET-OP afsluiten?): {len(let_op)}")
    for p in let_op:
        r.append(f"   {p.id}  {p.naam}  (is_actief={p.is_actief}, status={p.status})")
    r.append(
        f"-- Geboekte verdelingsdelen op afgesloten/inactieve/'Afgesloten'-projecten: {len(geboekt)} rij(en), "
        f"{_euro(sum((x.bedrag for x in geboekt), Decimal(0)))}"
    )
    for x in geboekt:
        r.append(
            f"   {x.boekstuk or '?'}  ref {x.referentie or '?'}  {x.leverancier or '?'}  factuur "
            f"{x.factuurdatum or '?'}  "
            f"geboekt {x.geboekt_op.date() if x.geboekt_op else '?'}  → {x.project_naam or x.project_id}  "
            f"[{x.project_stand}]  "
            f"{x.wijze} {_euro(x.bedrag)}  voorstel: {x.voorstel}"
        )
    r.append(
        f"-- Overhead via de sleutel: {sum(1 for x in overhead.rijen if x.overhead)} van {len(overhead.rijen)} "
        f"pro-rato-"
        f"document(en) is overhead (regels zonder project op 4xxx); geboekt {_euro(overhead.geboekt_overhead)}, "
        f"onderweg "
        f"{_euro(overhead.onderweg_overhead)} — dat zou een OVH-project vangen. OVH-project aanwezig: "
        f"{'ja (' + ', '.join(overhead.ovh_projecten) + ')' if overhead.heeft_ovh_project else 'nee'}"
    )
    for x in overhead.rijen:
        r.append(
            f"   [{x.status}/{x.document_status}] {x.boekstuk or '-'}  ref {x.referentie or '?'}  "
            f"{x.leverancier or '?'}  "
            f"factuur {x.factuurdatum or '?'}  pro rato {_euro(x.pro_rato_bedrag)}  gb "
            f"{'; '.join(x.grootboek) or '?'}  "
            f"{'OVERHEAD' if x.overhead else 'projectkosten/onbepaald'}"
        )
    return r
