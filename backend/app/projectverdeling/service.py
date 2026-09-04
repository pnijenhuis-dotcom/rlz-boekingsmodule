"""Servicelaag projectverdeling: voorstel/prefill lezen (live herrekend), opslaan (upsert, nooit DELETE),
bevriezen bij het boeken (①), per-leverancier-opt-in (④), Beheerder-instellingen, lijst-chipdata en
"Herverdelen…" (⑥ — de bestaande tegenboek-én-opnieuw-boeken-route, mens bevestigt).

Sessieregel: alle documentgebonden lezingen in `scoped_session(administratie_id, …)` (RLS); de
Administratie-instellingen in `scoped_session(None)` zoals app/beheer/service.py."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.documenten.checks import CheckResultaat
from app.documenten.models import Document, DocumentGebeurtenis, DocumentStatus, LeverancierVoorkeur
from app.projectverdeling import data as pv
from app.projectverdeling.models import Projectverdeling
from app.projectverdeling.omzet import omzet_per_project, projectnamen
from app.sync.models import ProjectCache, VendorCache

if TYPE_CHECKING:
    from app.documenten.boekvoorstel import BoekvoorstelData

CHECK_NAAM = "Projectverdeling"
_BEVROREN = frozenset({DocumentStatus.GEBOEKT, DocumentStatus.VERWIJDERD})


class ProjectverdelingServiceFout(Exception):
    """Domeinfout (422/409 in de router)."""


class HerverdelenGeblokkeerd(ProjectverdelingServiceFout):
    """Herverdelen kan niet via de tegenboek-route (aangifte-poort niet blokkerend, al tegengeboekt, …) — de
    melding legt uit wat wél de weg is (409)."""


# --- lezen ---------------------------------------------------------------------------------------------


def _row(session: Session, document_id: uuid.UUID) -> Projectverdeling | None:
    return session.scalar(select(Projectverdeling).where(Projectverdeling.document_id == document_id))


def _opt_in_pro_rato(session: Session, *, administratie_id: uuid.UUID, vendor_id: uuid.UUID | None) -> bool:
    if vendor_id is None:
        return False
    voorkeur = session.get(LeverancierVoorkeur, (administratie_id, vendor_id))
    return bool(voorkeur and voorkeur.projectverdeling_pro_rato)


def _heeft_actieve_projecten(session: Session, administratie_id: uuid.UUID) -> bool:
    return bool(
        session.scalar(
            select(func.count())
            .select_from(ProjectCache)
            .where(
                ProjectCache.administratie_id == administratie_id,
                ProjectCache.is_actief.is_(True),
                ProjectCache.verdwenen_uit_bron_op.is_(None),
            )
        )
    )


def is_beschikbaar(*, administratie_id: uuid.UUID) -> bool:
    """B1 (04-09): projectverdeling is op élk inkoopdocument beschikbaar in een administratie mét
    `project_verplicht` óf met actieve projecten — de per-leverancier-opt-in is sinds 04-09 uitsluitend een
    PREFILL-trigger (B2), geen poort. Zonder projecten heeft het blok geen zin (blijft het beslispunt 6 van 04-09)."""
    with scoped_session(administratie_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is not None and administratie.project_verplicht:
            return True
        return _heeft_actieve_projecten(session, administratie_id)


def _met_namen(
    session: Session,
    administratie_id: uuid.UUID,
    berekening: pv.Berekening,
    vaste: list[pv.VasteRegel],
    standen: list[pv.Omzetstand],
) -> tuple[list[pv.VerdeelDeel], list[pv.VasteRegel], list[pv.Omzetstand]]:
    ids = {d.project_id for d in berekening.delen} | {r.project_id for r in vaste} | {s.project_id for s in standen}
    namen = projectnamen(session, administratie_id=administratie_id, project_ids=ids)
    delen = [replace(d, project_naam=d.project_naam or namen.get(d.project_id)) for d in berekening.delen]
    vaste = [replace(r, project_naam=r.project_naam or namen.get(r.project_id)) for r in vaste]
    standen = [replace(s, project_naam=s.project_naam or namen.get(s.project_id)) for s in standen]
    return delen, vaste, standen


def _live(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    regels: list[tuple[uuid.UUID | None, Decimal | None]],
    vaste: list[pv.VasteRegel],
    periode: date | None,
    status: str,
    opgeslagen: bool,
    prefill: bool,
    boek_cyclus: int | None,
) -> pv.ProjectverdelingData:
    basis = pv.basisbedrag_van(regels)
    selectie = (
        omzet_per_project(session, administratie_id=administratie_id, periode=periode) if periode is not None else None
    )
    standen = selectie.standen if selectie else []
    berekening = pv.bereken(
        basisbedrag=basis,
        vaste_regels=vaste,
        pro_rato=periode is not None,
        periode=periode,
        omzetstanden=standen,
        omzet_cache_leeg=bool(selectie and selectie.cache_leeg),
    )
    delen, vaste, standen = _met_namen(session, administratie_id, berekening, vaste, standen)
    return pv.ProjectverdelingData(
        status=status,
        basisbedrag=basis,
        vaste_regels=vaste,
        pro_rato=periode is not None,
        pro_rato_periode=periode,
        pro_rato_bedrag=berekening.restant,
        delen=delen,
        omzetstanden=standen,
        compleet=berekening.compleet,
        blokkade=berekening.blokkade,
        opgeslagen=opgeslagen,
        prefill=prefill,
        boek_cyclus=boek_cyclus,
        omzet_cache_leeg=bool(selectie and selectie.cache_leeg),
        aantal_projecten_met_omzet=len(standen),
    )


def _bevroren(
    session: Session, *, administratie_id: uuid.UUID, row: Projectverdeling, drempel: Decimal
) -> pv.ProjectverdelingData:
    vaste = pv.vaste_regels_uit_json(row.vaste_regels)
    delen = pv.delen_uit_json(row.verdeling)
    standen = pv.omzetstanden_uit_json(row.omzetstanden)
    berekening = pv.Berekening(row.pro_rato_bedrag, delen, True, None)
    delen, vaste, standen = _met_namen(session, administratie_id, berekening, vaste, standen)
    hercontrole = None
    if row.hercontrole_op is not None:
        nieuwe = pv.delen_uit_json(row.hercontrole_verdeling) if row.hercontrole_verdeling else []
        namen = projectnamen(session, administratie_id=administratie_id, project_ids={d.project_id for d in nieuwe})
        hercontrole = pv.HercontroleInfo(
            op=row.hercontrole_op,
            afwijking_pct=row.hercontrole_afwijking_pct,
            drempel_pct=drempel,
            periode=row.pro_rato_periode,
            nieuwe_verdeling=[replace(d, project_naam=namen.get(d.project_id)) for d in nieuwe],
            signaal=row.hercontrole_verdeling is not None,
        )
    basis = sum((r.bedrag for r in vaste), Decimal(0)) + (row.pro_rato_bedrag or Decimal(0))
    return pv.ProjectverdelingData(
        status=pv.STATUS_GEBOEKT,
        basisbedrag=basis.quantize(pv.CENT),
        vaste_regels=vaste,
        pro_rato=row.pro_rato_periode is not None,
        pro_rato_periode=row.pro_rato_periode,
        pro_rato_bedrag=row.pro_rato_bedrag,
        delen=delen,
        omzetstanden=standen,
        compleet=True,
        blokkade=None,
        opgeslagen=True,
        boek_cyclus=row.boek_cyclus,
        hercontrole=hercontrole,
        aantal_projecten_met_omzet=len(standen),
    )


def lees(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    vendor_id: uuid.UUID | None,
    regels: list[tuple[uuid.UUID | None, Decimal | None]],
    project_verplicht: bool,
    boek_cyclus: int,
    drempel_pct: Decimal,
    vandaag: date | None = None,
) -> pv.ProjectverdelingData | None:
    """De verdeling zoals het boekvoorstel 'm draagt: bevroren (geboekt, zelfde boek_cyclus), live herrekend
    (voorstel — óók een bevroren rij van een vórige cyclus ná tegenboeken-én-opnieuw-boeken), de
    opt-in-prefill (④: alleen de restant-regel, niets opgeslagen) of None (geen verdeling van toepassing)."""
    vandaag = vandaag or date.today()
    row = _row(session, document_id)
    if row is None:
        if not _opt_in_pro_rato(session, administratie_id=administratie_id, vendor_id=vendor_id):
            return None
        if not (project_verplicht or _heeft_actieve_projecten(session, administratie_id)):
            return None
        return _live(
            session,
            administratie_id=administratie_id,
            regels=regels,
            vaste=[],
            periode=pv.default_periode(vandaag),
            status=pv.STATUS_VOORSTEL,
            opgeslagen=False,
            prefill=True,
            boek_cyclus=boek_cyclus,
        )
    if row.status == pv.STATUS_GEBOEKT and (row.boek_cyclus is None or row.boek_cyclus >= boek_cyclus):
        return _bevroren(session, administratie_id=administratie_id, row=row, drempel=drempel_pct)
    if row.status == pv.STATUS_VERVALLEN:
        return pv.ProjectverdelingData(
            status=pv.STATUS_VERVALLEN,
            basisbedrag=pv.basisbedrag_van(regels),
            vaste_regels=[],
            pro_rato=False,
            pro_rato_periode=None,
            pro_rato_bedrag=None,
            delen=[],
            omzetstanden=[],
            compleet=False,
            blokkade=None,
            opgeslagen=True,
            boek_cyclus=boek_cyclus,
        )
    return _live(
        session,
        administratie_id=administratie_id,
        regels=regels,
        vaste=pv.vaste_regels_uit_json(row.vaste_regels),
        periode=row.pro_rato_periode,
        status=pv.STATUS_VOORSTEL,
        opgeslagen=True,
        prefill=False,
        boek_cyclus=boek_cyclus,
    )


def drempel_voor(session: Session, administratie_id: uuid.UUID) -> Decimal:
    administratie = session.get(Administratie, administratie_id)
    return administratie.projectverdeling_drempel_pct if administratie else Decimal("5.00")


def verrijk_boekvoorstel(
    session: Session, *, administratie_id: uuid.UUID, data: BoekvoorstelData, project_verplicht: bool
) -> BoekvoorstelData:
    """Koppelpunt voor `boekvoorstel.haal_boekvoorstel_op`: zet `projectverdeling` op de (frozen) BoekvoorstelData.
    Een leesfout in deze laag mag het boekvoorstel nooit onbruikbaar maken (signalering + verdeling, geen kern)."""
    verdeling = lees(
        session,
        administratie_id=administratie_id,
        document_id=data.document_id,
        vendor_id=data.vendor_id,
        regels=[(r.project_id, r.netto_bedrag) for r in data.regels],
        project_verplicht=project_verplicht,
        boek_cyclus=data.boek_cyclus,
        drempel_pct=drempel_voor(session, administratie_id),
    )
    return replace(data, projectverdeling=verdeling)


def check(data: pv.ProjectverdelingData | None) -> CheckResultaat:
    """Aanvullende harde check (naast "Verplichte velden"): blokkeert zolang een actieve verdeling niet op
    exact 100 % sluit. Geen verdeling = niet van toepassing (ok)."""
    if data is None or not data.actief:
        return CheckResultaat(CHECK_NAAM, True, "Geen projectverdeling van toepassing")
    if not data.compleet:
        return CheckResultaat(CHECK_NAAM, False, data.blokkade or "De projectverdeling sluit niet op 100 %")
    projecten = len({d.project_id for d in data.delen})
    return CheckResultaat(
        CHECK_NAAM, True, f"Verdeeld over {projecten} project(en) — som exact € {data.basisbedrag:.2f}"
    )


# --- opslaan / vervallen ----------------------------------------------------------------------------------


def _laad_document(session: Session, administratie_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    from app.documenten.service import DocumentNietGevonden

    document = session.get(Document, document_id)
    if document is None or document.administratie_id != administratie_id:
        raise DocumentNietGevonden(f"Onbekend document: {document_id}")
    return document


def _valideer_projecten(session: Session, *, administratie_id: uuid.UUID, vaste: list[pv.VasteRegel]) -> None:
    if not vaste:
        return
    ids = {r.project_id for r in vaste}
    bekend = set(
        session.scalars(
            select(ProjectCache.id).where(
                ProjectCache.administratie_id == administratie_id,
                ProjectCache.id.in_(ids),
                ProjectCache.verdwenen_uit_bron_op.is_(None),
            )
        )
    )
    onbekend = ids - bekend
    if onbekend:
        raise ProjectverdelingServiceFout(
            "Een vaste regel wijst naar een project dat niet (meer) in deze administratie bestaat"
        )


def sla_op(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    vaste_regels: list[pv.VasteRegel],
    pro_rato_periode: date | None,
    vervallen: bool = False,
) -> pv.ProjectverdelingData | None:
    """Upsert van de verdeling op een NOG NIET geboekt inkoopdocument. `pro_rato_periode=None` = pro rato uit
    (alleen vaste regels); `vervallen=True` = de mens haalt de verdeling weg (status vervallen — de prefill komt
    dan niet terug; nooit een DELETE). Audit oud→nieuw op élke wijziging."""
    try:
        pv.valideer_vaste_regels(vaste_regels)
    except pv.ProjectverdelingFout as exc:
        raise ProjectverdelingServiceFout(str(exc)) from exc
    if pro_rato_periode is not None and pro_rato_periode.day != 1:
        raise ProjectverdelingServiceFout("De omzetmaand hoort de eerste dag van een kalendermaand te zijn")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = _laad_document(session, administratie_id, document_id)
        if document.soort != "inkoopfactuur":
            raise ProjectverdelingServiceFout("Projectverdeling is alleen voor inkoopfacturen")
        if document.status in _BEVROREN:
            raise ProjectverdelingServiceFout(
                f"Document staat op {document.status.value} — de verdeling is bevroren (herverdelen via tegenboeken)"
            )
        _valideer_projecten(session, administratie_id=administratie_id, vaste=vaste_regels)
        row = _row(session, document_id)
        oud = (
            {
                "status": row.status,
                "vaste_regels": row.vaste_regels,
                "pro_rato_periode": str(row.pro_rato_periode) if row.pro_rato_periode else None,
            }
            if row
            else None
        )
        if row is None:
            row = Projectverdeling(administratie_id=administratie_id, document_id=document_id)
            session.add(row)
        row.status = pv.STATUS_VERVALLEN if vervallen else pv.STATUS_VOORSTEL
        row.vaste_regels = [] if vervallen else pv.vaste_regels_naar_json(vaste_regels)
        row.pro_rato_periode = None if vervallen else pro_rato_periode
        row.boek_cyclus = None
        row.geboekt_op = None
        row.hercontrole_op = None
        row.hercontrole_afwijking_pct = None
        row.hercontrole_verdeling = None
        # Informatief snapshot van de berekening op dit moment (de bindende stand wordt bij het boeken bevroren).
        from app.documenten.models import BoekvoorstelRegel

        regels = [
            (r.project_id, r.netto_bedrag)
            for r in session.scalars(select(BoekvoorstelRegel).where(BoekvoorstelRegel.document_id == document_id))
        ]
        live = None
        if not vervallen:
            live = _live(
                session,
                administratie_id=administratie_id,
                regels=regels,
                vaste=vaste_regels,
                periode=pro_rato_periode,
                status=pv.STATUS_VOORSTEL,
                opgeslagen=True,
                prefill=False,
                boek_cyclus=None,
            )
            row.pro_rato_bedrag = live.pro_rato_bedrag
            row.verdeling = pv.delen_naar_json(live.delen)
            row.omzetstanden = pv.omzetstanden_naar_json(live.omzetstanden)
        else:
            row.pro_rato_bedrag = None
            row.verdeling = []
            row.omzetstanden = []
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="projectverdeling",
            record_id=document_id,
            actie="projectverdeling_vervallen" if vervallen else "projectverdeling_opgeslagen",
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde={
                "status": row.status,
                "vaste_regels": row.vaste_regels,
                "pro_rato_periode": str(row.pro_rato_periode) if row.pro_rato_periode else None,
                "pro_rato_bedrag": str(row.pro_rato_bedrag) if row.pro_rato_bedrag is not None else None,
                "compleet": bool(live and live.compleet),
            },
            administratie_id=administratie_id,
        )
    from app.documenten.boekvoorstel import haal_boekvoorstel_op

    return haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id).projectverdeling


def bevries_bij_boeking(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    data: pv.ProjectverdelingData | None,
    boek_cyclus: int,
    actor_id: uuid.UUID,
) -> None:
    """Ín de GEBOEKT-transactie (①): de gebruikte omzetstanden + berekende delen worden bevroren — status
    geboekt, boek_cyclus, audit. Zonder actieve verdeling gebeurt er niets."""
    if data is None or not data.actief or not data.compleet:
        return
    row = _row(session, document_id)
    if row is None:
        row = Projectverdeling(administratie_id=administratie_id, document_id=document_id)
        session.add(row)
    row.status = pv.STATUS_GEBOEKT
    row.vaste_regels = pv.vaste_regels_naar_json(data.vaste_regels)
    row.pro_rato_periode = data.pro_rato_periode
    row.pro_rato_bedrag = data.pro_rato_bedrag
    row.verdeling = pv.delen_naar_json(data.delen)
    row.omzetstanden = pv.omzetstanden_naar_json(data.omzetstanden)
    row.geboekt_op = datetime.now(UTC)
    row.boek_cyclus = boek_cyclus
    row.hercontrole_op = None
    row.hercontrole_afwijking_pct = None
    row.hercontrole_verdeling = None
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="projectverdeling",
        record_id=document_id,
        actie="projectverdeling_bevroren",
        correlatie_id=uuid.uuid4(),
        nieuwe_waarde={
            "boek_cyclus": boek_cyclus,
            "pro_rato_periode": str(data.pro_rato_periode) if data.pro_rato_periode else None,
            "pro_rato_bedrag": str(data.pro_rato_bedrag) if data.pro_rato_bedrag is not None else None,
            "verdeling": row.verdeling,
            "omzetstanden": row.omzetstanden,
        },
        administratie_id=administratie_id,
    )


# --- per-leverancier-opt-in (④) ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LeverancierProRato:
    vendor_id: uuid.UUID
    naam: str | None
    projectverdeling_pro_rato: bool


def lijst_leverancier_pro_rato(*, administratie_id: uuid.UUID) -> list[LeverancierProRato]:
    with scoped_session(administratie_id) as session:
        vendors = session.scalars(
            select(VendorCache)
            .where(VendorCache.administratie_id == administratie_id, VendorCache.verdwenen_uit_bron_op.is_(None))
            .order_by(VendorCache.naam)
        ).all()
        standen = {
            v.vendor_id: v.projectverdeling_pro_rato
            for v in session.scalars(
                select(LeverancierVoorkeur).where(LeverancierVoorkeur.administratie_id == administratie_id)
            )
        }
        return [
            LeverancierProRato(vendor_id=v.id, naam=v.naam, projectverdeling_pro_rato=standen.get(v.id, False))
            for v in vendors
        ]


def zet_leverancier_pro_rato(
    *, administratie_id: uuid.UUID, vendor_id: uuid.UUID, actor_id: uuid.UUID, ingeschakeld: bool
) -> bool:
    """Beheerder-only (router). AAN = élk document van deze crediteur krijgt automatisch een voorstel mét alleen
    de restant-regel (④). Audit oud→nieuw."""
    from app.backends.registry import standaard_regels_samenvoegen

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        voorkeur = session.get(LeverancierVoorkeur, (administratie_id, vendor_id))
        oud = voorkeur.projectverdeling_pro_rato if voorkeur else False
        if voorkeur is None:
            voorkeur = LeverancierVoorkeur(
                administratie_id=administratie_id,
                vendor_id=vendor_id,
                regels_samenvoegen=standaard_regels_samenvoegen(administratie_id),
                projectverdeling_pro_rato=ingeschakeld,
            )
            session.add(voorkeur)
        else:
            voorkeur.projectverdeling_pro_rato = ingeschakeld
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="leverancier_voorkeur",
            record_id=vendor_id,
            actie="leverancier_projectverdeling_pro_rato_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"projectverdeling_pro_rato": oud},
            nieuwe_waarde={"projectverdeling_pro_rato": ingeschakeld},
            administratie_id=administratie_id,
        )
    return ingeschakeld


# --- Beheerder-instellingen per administratie -------------------------------------------------------------


@dataclass(frozen=True)
class Instellingen:
    drempel_pct: Decimal
    wachtweken: int


def haal_instellingen(*, administratie_id: uuid.UUID) -> Instellingen:
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise ProjectverdelingServiceFout(f"Onbekende administratie: {administratie_id}")
        return Instellingen(
            drempel_pct=administratie.projectverdeling_drempel_pct,
            wachtweken=administratie.inkoop_zonder_omzet_wachtweken,
        )


def zet_instellingen(
    *, administratie_id: uuid.UUID, actor_id: uuid.UUID, drempel_pct: Decimal | None, wachtweken: int | None
) -> Instellingen:
    """Hercontrole-drempel (0 < pct ≤ 100) en wachtweken (0–52) — Beheerder-only, audit oud→nieuw."""
    if drempel_pct is not None and not (Decimal("0") < drempel_pct <= Decimal("100")):
        raise ProjectverdelingServiceFout("De hercontrole-drempel moet tussen 0 en 100 % liggen")
    if wachtweken is not None and not (0 <= wachtweken <= 52):
        raise ProjectverdelingServiceFout("De wachttijd moet tussen 0 en 52 weken liggen")
    with scoped_session(None, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise ProjectverdelingServiceFout(f"Onbekende administratie: {administratie_id}")
        oud = {
            "projectverdeling_drempel_pct": str(administratie.projectverdeling_drempel_pct),
            "inkoop_zonder_omzet_wachtweken": administratie.inkoop_zonder_omzet_wachtweken,
        }
        if drempel_pct is not None:
            administratie.projectverdeling_drempel_pct = drempel_pct
        if wachtweken is not None:
            administratie.inkoop_zonder_omzet_wachtweken = wachtweken
        nieuw = {
            "projectverdeling_drempel_pct": str(administratie.projectverdeling_drempel_pct),
            "inkoop_zonder_omzet_wachtweken": administratie.inkoop_zonder_omzet_wachtweken,
        }
        if nieuw != oud:
            record_audit_event(
                session,
                actor_id=actor_id,
                module="platform",
                tabel="administratie",
                record_id=administratie_id,
                actie="projectverdeling_instellingen_gewijzigd",
                correlatie_id=uuid.uuid4(),
                oude_waarde=oud,
                nieuwe_waarde=nieuw,
            )
        return Instellingen(
            drempel_pct=administratie.projectverdeling_drempel_pct,
            wachtweken=administratie.inkoop_zonder_omzet_wachtweken,
        )


# --- lijst-chipdata + kantoorbreed --------------------------------------------------------------------------


def afwijkingen_per_document(session: Session, document_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    """Bulk (geen N+1): geboekte verdelingen mét hercontrole-signaal → afwijking in % per document."""
    if not document_ids:
        return {}
    rijen = session.execute(
        select(Projectverdeling.document_id, Projectverdeling.hercontrole_afwijking_pct).where(
            Projectverdeling.document_id.in_(document_ids),
            Projectverdeling.status == pv.STATUS_GEBOEKT,
            Projectverdeling.hercontrole_verdeling.is_not(None),
        )
    ).all()
    return {doc_id: pct for doc_id, pct in rijen if pct is not None}


@dataclass(frozen=True)
class SignaalRij:
    administratie_id: uuid.UUID
    administratie_naam: str
    document_id: uuid.UUID
    bestandsnaam: str
    leverancier: str | None
    referentie: str | None
    pro_rato_periode: date | None
    pro_rato_bedrag: Decimal | None
    afwijking_pct: Decimal
    drempel_pct: Decimal
    hercontrole_op: datetime


@dataclass(frozen=True)
class SignaalLijst:
    rijen: list[SignaalRij]
    totaal: int
    pagina: int
    per_pagina: int
    administraties: int


PER_PAGINA = 25


def hercontrole_signalen(*, actor_id: uuid.UUID, rol, pagina: int = 1) -> SignaalLijst:
    """Kantoorbreed (principe 7 regel 1: administratie = filter, geen poort): alle geboekte pro-rato-verdelingen
    mét een hercontrole-signaal over de administraties in scope van de actor, urgentste (hoogste %) bovenaan,
    server-side gepagineerd. Per administratie gelezen in een gescoopte sessie (RLS blijft de scope-waarheid)."""
    from app.auth import service as auth_service
    from app.documenten.models import Boekvoorstel

    administraties = auth_service.mijn_administraties(actor_id=actor_id, rol=rol)
    rijen: list[SignaalRij] = []
    for administratie in administraties:
        with scoped_session(administratie.id, actor_id=actor_id) as session:
            resultaten = session.execute(
                select(Projectverdeling, Document, Boekvoorstel)
                .join(Document, Document.id == Projectverdeling.document_id)
                .outerjoin(Boekvoorstel, Boekvoorstel.document_id == Projectverdeling.document_id)
                .where(
                    Projectverdeling.administratie_id == administratie.id,
                    Projectverdeling.status == pv.STATUS_GEBOEKT,
                    Projectverdeling.hercontrole_verdeling.is_not(None),
                    Document.status == DocumentStatus.GEBOEKT,
                )
            ).all()
            vendor_ids = {b.vendor_id for _, _, b in resultaten if b is not None and b.vendor_id}
            namen = {}
            if vendor_ids:
                namen = dict(
                    session.execute(
                        select(VendorCache.id, VendorCache.naam).where(
                            VendorCache.administratie_id == administratie.id, VendorCache.id.in_(vendor_ids)
                        )
                    ).all()
                )
            for row, document, boekvoorstel in resultaten:
                rijen.append(
                    SignaalRij(
                        administratie_id=administratie.id,
                        administratie_naam=administratie.naam,
                        document_id=document.id,
                        bestandsnaam=document.bestandsnaam,
                        leverancier=namen.get(boekvoorstel.vendor_id)
                        if boekvoorstel and boekvoorstel.vendor_id
                        else None,
                        referentie=boekvoorstel.referentie if boekvoorstel else None,
                        pro_rato_periode=row.pro_rato_periode,
                        pro_rato_bedrag=row.pro_rato_bedrag,
                        afwijking_pct=row.hercontrole_afwijking_pct or Decimal("0"),
                        drempel_pct=administratie.projectverdeling_drempel_pct,
                        hercontrole_op=row.hercontrole_op or datetime.now(UTC),
                    )
                )
    rijen.sort(key=lambda r: (-r.afwijking_pct, r.administratie_naam, r.bestandsnaam))
    start = (pagina - 1) * PER_PAGINA
    return SignaalLijst(
        rijen=rijen[start : start + PER_PAGINA],
        totaal=len(rijen),
        pagina=pagina,
        per_pagina=PER_PAGINA,
        administraties=len({r.administratie_id for r in rijen}),
    )


# --- herverdelen (⑥) ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class HerverdeelResultaat:
    document_id: uuid.UUID
    status: DocumentStatus
    rlz_tegenboeking_id: uuid.UUID
    rlz_boekstuknummer: str | None


def herverdelen(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, reden: str
) -> HerverdeelResultaat:
    """ "Herverdelen…" = de BESTAANDE tegenboek-én-opnieuw-boeken-route (`tegenboeken.voer_tegenboeking_uit`,
    soort 'vervang'; aangifte-poort onverkort) — daarna staat de verdeling als VOORSTEL (zelfde vaste regels en
    omzetmaand, live herrekend op de actuele omzetstand) op de herboeking klaar; de mens boekt opnieuw. Nooit stil
    herboeken. Kan tegenboeken niet (storno niet door de aangifte geblokkeerd, al tegengeboekt, origineel niet meer
    geboekt), dan een leesbare HerverdelenGeblokkeerd (409)."""
    from app.documenten import tegenboeken

    with scoped_session(administratie_id) as session:
        row = _row(session, document_id)
        if row is None or row.status != pv.STATUS_GEBOEKT:
            raise ProjectverdelingServiceFout("Dit document heeft geen bevroren projectverdeling om te herverdelen")
        if row.hercontrole_verdeling is None:
            raise ProjectverdelingServiceFout(
                "Er is geen hercontrole-afwijking op deze verdeling — herverdelen is niet nodig"
            )
    try:
        uitkomst = tegenboeken.voer_tegenboeking_uit(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor_id,
            soort="vervang",
            reden=reden,
        )
    except tegenboeken.TegenboekenNietToegestaan as exc:
        raise HerverdelenGeblokkeerd(
            "Herverdelen via tegenboeken kan alleen als storno door een ingediende btw-aangifte geblokkeerd is. "
            "De periode staat nog open: corrigeer via stornering (actie 19) in Reeleezee en boek daarna opnieuw — "
            f"de nieuwe verdeling staat dan als voorstel klaar. ({exc})"
        ) from exc
    except (tegenboeken.TegenboekingBestaatAl, tegenboeken.OngeldigeTegenboeking) as exc:
        raise HerverdelenGeblokkeerd(str(exc)) from exc
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        row = _row(session, document_id)
        assert row is not None
        oud_verdeling = row.verdeling
        row.status = pv.STATUS_VOORSTEL
        row.verdeling = row.hercontrole_verdeling or []
        row.boek_cyclus = None
        row.geboekt_op = None
        row.hercontrole_op = None
        row.hercontrole_afwijking_pct = None
        row.hercontrole_verdeling = None
        document = session.get(Document, document_id)
        assert document is not None
        session.add(
            DocumentGebeurtenis(
                document_id=document_id,
                van_status=document.status,
                naar_status=document.status,
                actor_id=actor_id,
                detail={
                    "projectverdeling_herverdeeld": {
                        "oude_verdeling": oud_verdeling,
                        "nieuwe_verdeling": row.verdeling,
                    },
                    "reden": f"projectverdeling herverdeeld — {reden.strip()}",
                },
            )
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="projectverdeling",
            record_id=document_id,
            actie="projectverdeling_herverdeeld",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"verdeling": oud_verdeling},
            nieuwe_waarde={"verdeling": row.verdeling, "reden": reden.strip()},
            administratie_id=administratie_id,
        )
    return HerverdeelResultaat(
        document_id=document_id,
        status=uitkomst.status,
        rlz_tegenboeking_id=uitkomst.rlz_tegenboeking_id,
        rlz_boekstuknummer=uitkomst.rlz_boekstuknummer,
    )
