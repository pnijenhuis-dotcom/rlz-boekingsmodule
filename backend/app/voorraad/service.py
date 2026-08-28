"""Voorraad-aansluiting fase 1 — Universal Verkoop (bouwrun 28-08 blok D; mockup
voorraad-aansluiting.html §1 = bouwnorm). Controle-laag: instroom = regel-niveau feiten uit het
inkoop-veldvoorstel (extern document), uitstroom = verkoopfactuurregels (fase 1: de in de app
geboekte verkoopdocumenten mét UBL-hoeveelheden; RLZ-SalesInvoice-Lines/Odoo = seam-parkeerpost),
systeemstand = handmatige telling per datum. Mutaties op DAGNIVEAU; verschil buiten de tolerantie =
vlag, puur MI — nooit een boeking, nooit RLZ-writes. Code voor cijfers: alle telling deterministisch."""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.models import Boekvoorstel, Document, DocumentGebeurtenis, DocumentSoort, DocumentStatus
from app.sync.models import VendorCache
from app.voorraad import normalisatie
from app.voorraad.models import ONBEKENDE_LEVERANCIER, Artikelgroep, NormalisatieRegel, VoorraadRegel, VoorraadTelling

logger = logging.getLogger(__name__)

_HONDERDSTE = Decimal("0.01")
_DUIZENDSTE = Decimal("0.001")


class VoorraadFout(Exception):
    pass


class VoorraadUitgeschakeld(VoorraadFout):
    pass


class OngeldigeInvoer(VoorraadFout):
    pass


def is_ingeschakeld(session: Session, administratie_id: uuid.UUID) -> bool:
    administratie = session.get(Administratie, administratie_id)
    return administratie is not None and administratie.voorraad_ingeschakeld


def _vereis_ingeschakeld(administratie_id: uuid.UUID) -> None:
    with scoped_session(None) as session:
        if not is_ingeschakeld(session, administratie_id):
            raise VoorraadUitgeschakeld("Voorraad bijhouden staat uit voor deze administratie")


def _als_decimal(waarde: object) -> Decimal | None:
    if isinstance(waarde, int | float):
        return Decimal(str(waarde))
    if not isinstance(waarde, str) or not waarde.strip():
        return None
    schoon = waarde.strip().replace(" ", "")
    # "1.234,50" → NL-notatie; "1234.50" → punt-decimaal; "12" → 12.
    if "," in schoon and "." in schoon:
        schoon = schoon.replace(".", "").replace(",", ".")
    elif "," in schoon:
        schoon = schoon.replace(",", ".")
    try:
        return Decimal(schoon)
    except InvalidOperation:
        return None


def _als_datum(waarde: object) -> date | None:
    if not isinstance(waarde, str) or not waarde:
        return None
    try:
        return date.fromisoformat(waarde[:10])
    except ValueError:
        return None


def _laatste_veldvoorstel(session: Session, document_id: uuid.UUID) -> dict | None:
    gebeurtenissen = session.scalars(
        select(DocumentGebeurtenis)
        .where(DocumentGebeurtenis.document_id == document_id)
        .order_by(DocumentGebeurtenis.tijdstip.desc())
    )
    for g in gebeurtenissen:
        if g.detail and "veldvoorstel" in g.detail:
            return g.detail["veldvoorstel"]
    return None


def _vervang_regels(session: Session, *, document_id: uuid.UUID, richting: str, nieuwe: list[VoorraadRegel]) -> None:
    """Afgeleide feitenlaag: alle regels van dit document+richting vervangen (herrekenbaar)."""
    session.execute(
        delete(VoorraadRegel).where(VoorraadRegel.document_id == document_id, VoorraadRegel.richting == richting)
    )
    for r in nieuwe:
        session.add(r)


# --- instroom: inkoopfactuur (veldvoorstel) --------------------------------------------------------


def registreer_inkoopregels(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> int:
    """Post-extractie (en bij herrekenen): regel-niveau feiten uit het laatste veldvoorstel van een
    inkoopfactuur → mi.voorraad_regel richting 'in', mét volautomatische normalisatie. Toggle uit =
    niets (stil, zoals elke opt-in). Geeft het aantal regels terug."""
    with scoped_session(None) as session:
        if not is_ingeschakeld(session, administratie_id):
            return 0
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        document = session.get(Document, document_id)
        if document is None or document.soort != DocumentSoort.INKOOPFACTUUR.value:
            return 0
        veldvoorstel = _laatste_veldvoorstel(session, document_id) or {}
        voorstel = session.get(Boekvoorstel, document_id)
        vendor_id = voorstel.vendor_id if voorstel is not None and voorstel.vendor_id else None
        if vendor_id is None:
            suggestie = veldvoorstel.get("vendor_suggestie")
            if isinstance(suggestie, dict) and suggestie.get("vendor_id"):
                try:
                    vendor_id = uuid.UUID(str(suggestie["vendor_id"]))
                except ValueError:
                    vendor_id = None
        leverancier = None
        if vendor_id is not None:
            vendor = session.get(VendorCache, (vendor_id, administratie_id))
            leverancier = vendor.naam if vendor else None
        leverancier = leverancier or veldvoorstel.get("leverancier_naam")
        datum = (
            (voorstel.factuurdatum if voorstel is not None else None)
            or _als_datum(veldvoorstel.get("factuurdatum"))
            or document.aangemaakt_op.date()
        )
        regels = [r for r in (veldvoorstel.get("regels") or []) if isinstance(r, dict) and r.get("omschrijving")]
        normalisaties = normalisatie.normaliseer_regels(
            session,
            administratie_id=administratie_id,
            document_id=document_id,
            regels=[(str(r["omschrijving"]), vendor_id, leverancier) for r in regels],
        )
        nieuwe: list[VoorraadRegel] = []
        for i, (r, n) in enumerate(zip(regels, normalisaties, strict=True), start=1):
            aantal = _als_decimal(r.get("hoeveelheid"))
            netto = _als_decimal(r.get("netto_bedrag"))
            prijs = _als_decimal(r.get("stuksprijs"))
            if prijs is None and aantal and netto is not None and aantal != 0:
                prijs = (netto / aantal).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            nieuwe.append(
                VoorraadRegel(
                    administratie_id=administratie_id,
                    document_id=document_id,
                    richting="in",
                    bron="inkoop_veldvoorstel",
                    datum=datum,
                    vendor_id=vendor_id,
                    relatie_naam=leverancier,
                    regel_volgnummer=i,
                    artikeltekst=str(r["omschrijving"])[:500],
                    aantal=aantal,
                    eenheid=(str(r["eenheid"])[:16] if r.get("eenheid") else None),
                    prijs=prijs,
                    netto_bedrag=netto,
                    artikelgroep_id=n.artikelgroep_id,
                    normalisatie_status=n.status,
                    normalisatie_zekerheid=n.zekerheid,
                )
            )
        _vervang_regels(session, document_id=document_id, richting="in", nieuwe=nieuwe)
        return len(nieuwe)


# --- uitstroom: verkoopfactuurregels (fase 1: geboekte verkoopdocumenten in de app) ------------------


def registreer_verkoopregels(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> int:
    """Ná de verkoopboeking: regels van het verkoopdocument → richting 'uit'. Hoeveelheden komen
    deterministisch uit de UBL (cbc:InvoicedQuantity/@unitCode, cac:Price) via het veldvoorstel
    (`ubl_regels`); een creditnota (381) telt als negatieve uitstroom (retour). Normalisatie via
    dezelfde motor, leverancier-sentinel = onbekend (het is onze verkoop)."""
    from app.verkoop.models import VerkoopVoorstel, VerkoopVoorstelRegel

    with scoped_session(None) as session:
        if not is_ingeschakeld(session, administratie_id):
            return 0
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        document = session.get(Document, document_id)
        if document is None or document.soort != DocumentSoort.VERKOOPFACTUUR.value:
            return 0
        if document.status != DocumentStatus.GEBOEKT:
            return 0
        kop = session.get(VerkoopVoorstel, document_id)
        veldvoorstel = _laatste_veldvoorstel(session, document_id) or {}
        ubl_per_nr: dict[int, dict] = {}
        for i, u in enumerate(veldvoorstel.get("ubl_regels") or [], start=1):
            if isinstance(u, dict):
                ubl_per_nr[int(u.get("volgnummer") or i)] = u
        regels_orm = list(
            session.scalars(
                select(VerkoopVoorstelRegel)
                .where(VerkoopVoorstelRegel.document_id == document_id)
                .order_by(VerkoopVoorstelRegel.volgnummer)
            )
        )
        teken = Decimal("-1") if (kop is not None and kop.is_creditnota) else Decimal("1")
        datum = (kop.factuurdatum if kop is not None and kop.factuurdatum else None) or document.aangemaakt_op.date()
        bruikbaar = [r for r in regels_orm if r.omschrijving]
        normalisaties = normalisatie.normaliseer_regels(
            session,
            administratie_id=administratie_id,
            document_id=document_id,
            regels=[(str(r.omschrijving), None, None) for r in bruikbaar],
        )
        nieuwe: list[VoorraadRegel] = []
        for r, n in zip(bruikbaar, normalisaties, strict=True):
            ubl = ubl_per_nr.get(r.volgnummer, {})
            aantal = _als_decimal(ubl.get("aantal"))
            nieuwe.append(
                VoorraadRegel(
                    administratie_id=administratie_id,
                    document_id=document_id,
                    richting="uit",
                    bron="verkoop_regel",
                    datum=datum,
                    vendor_id=None,
                    relatie_naam=kop.debiteur_naam if kop is not None else None,
                    regel_volgnummer=r.volgnummer,
                    artikeltekst=str(r.omschrijving)[:500],
                    aantal=(aantal * teken) if aantal is not None else None,
                    eenheid=(str(ubl["eenheid"])[:16] if ubl.get("eenheid") else None),
                    prijs=_als_decimal(ubl.get("prijs")),
                    netto_bedrag=(r.netto_bedrag * teken) if r.netto_bedrag is not None else None,
                    artikelgroep_id=n.artikelgroep_id,
                    normalisatie_status=n.status,
                    normalisatie_zekerheid=n.zekerheid,
                )
            )
        _vervang_regels(session, document_id=document_id, richting="uit", nieuwe=nieuwe)
        return len(nieuwe)


def herreken_administratie(*, administratie_id: uuid.UUID, actor_id: uuid.UUID) -> dict[str, int]:
    """ "⟳ Verversen" / ná een correctie: alle inkoopdocumenten mét veldvoorstel en alle geboekte
    verkoopdocumenten opnieuw door de feitenlaag (bestaande normalisatieregels = deterministisch,
    dus geen nieuwe AI-calls voor bekende teksten). Audit per run."""
    _vereis_ingeschakeld(administratie_id)
    with scoped_session(administratie_id) as session:
        inkoop = list(
            session.scalars(
                select(Document.id).where(
                    Document.administratie_id == administratie_id,
                    Document.soort == DocumentSoort.INKOOPFACTUUR.value,
                    Document.status != DocumentStatus.VERWIJDERD,
                )
            )
        )
        verkoop = list(
            session.scalars(
                select(Document.id).where(
                    Document.administratie_id == administratie_id,
                    Document.soort == DocumentSoort.VERKOOPFACTUUR.value,
                    Document.status == DocumentStatus.GEBOEKT,
                )
            )
        )
    telling = {"inkoop_documenten": 0, "inkoop_regels": 0, "verkoop_documenten": 0, "verkoop_regels": 0}
    for d in inkoop:
        n = registreer_inkoopregels(administratie_id=administratie_id, document_id=d)
        if n:
            telling["inkoop_documenten"] += 1
            telling["inkoop_regels"] += n
    for d in verkoop:
        n = registreer_verkoopregels(administratie_id=administratie_id, document_id=d)
        if n:
            telling["verkoop_documenten"] += 1
            telling["verkoop_regels"] += n
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        record_audit_event(
            session,
            actor_id=actor_id,
            module="mi",
            tabel="voorraad_regel",
            record_id=administratie_id,
            actie="voorraad_herrekend",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde=telling,
            administratie_id=administratie_id,
        )
    return telling


# --- aansluiting ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class GroepAansluiting:
    artikelgroep_id: uuid.UUID
    naam: str
    eenheid: str
    tolerantie_pct: Decimal
    begin: Decimal
    inkoop: Decimal
    verkoop: Decimal
    theoretisch: Decimal
    systeemstand: Decimal | None
    telling_datum: date | None
    verschil: Decimal | None
    verschil_pct: Decimal | None
    signaal: str  # binnen_tolerantie | onderzoeken | geen_telling
    # Aandeel onzeker-genormaliseerde regels (op aantal regels) in de periode — bij élk signaal.
    onzeker_pct: Decimal
    regels_in: int
    regels_uit: int


@dataclass(frozen=True)
class Aansluiting:
    administratie_id: uuid.UUID
    van: date
    tot: date
    groepen: list[GroepAansluiting]
    niet_genormaliseerd_in: int
    niet_genormaliseerd_uit: int
    onzeker_totaal: int
    regels_totaal: int
    bronnen: dict[str, str] = field(
        default_factory=lambda: {
            "inkoop": "inkoopfacturen (AI-gescand, extern document)",
            "verkoop": "verkoopfactuurregels (interne registratie)",
            "systeemstand": "handmatige telling per datum",
        }
    )


def _pct(deel: Decimal, geheel: Decimal) -> Decimal | None:
    if geheel == 0:
        return None
    return (deel / geheel * 100).quantize(_HONDERDSTE, rounding=ROUND_HALF_UP)


def aansluiting(*, administratie_id: uuid.UUID, van: date, tot: date) -> Aansluiting:
    """Per artikelgroep: begin (Σ vóór `van`) + inkoop − verkoop = theoretisch; systeemstand = laatste
    telling ≤ `tot`; verschil = systeemstand − theoretisch; signaal op de tolerantie van de groep.
    Regels zonder aantal tellen niet in de aantallen (wél in de regeltelling)."""
    if tot < van:
        raise OngeldigeInvoer("Einddatum ligt vóór de begindatum")
    _vereis_ingeschakeld(administratie_id)
    with scoped_session(administratie_id) as session:
        groepen = list(
            session.scalars(
                select(Artikelgroep)
                .where(Artikelgroep.administratie_id == administratie_id, Artikelgroep.actief.is_(True))
                .order_by(Artikelgroep.naam)
            )
        )
        regels = list(
            session.scalars(
                select(VoorraadRegel).where(
                    VoorraadRegel.administratie_id == administratie_id, VoorraadRegel.datum <= tot
                )
            )
        )
        tellingen = list(
            session.scalars(
                select(VoorraadTelling)
                .where(VoorraadTelling.administratie_id == administratie_id, VoorraadTelling.datum <= tot)
                .order_by(VoorraadTelling.datum.desc())
            )
        )
        session.expunge_all()

    per_groep: dict[uuid.UUID, dict[str, Decimal | int]] = defaultdict(
        lambda: {"begin": Decimal(0), "in": Decimal(0), "uit": Decimal(0), "n_in": 0, "n_uit": 0, "onzeker": 0}
    )
    niet_in = niet_uit = onzeker_totaal = totaal = 0
    for r in regels:
        if van <= r.datum <= tot:
            totaal += 1
            if r.normalisatie_status == "niet_genormaliseerd":
                if r.richting == "in":
                    niet_in += 1
                else:
                    niet_uit += 1
                continue
            if r.normalisatie_status == "uitgesloten" or r.artikelgroep_id is None:
                continue
            g = per_groep[r.artikelgroep_id]
            g["n_in" if r.richting == "in" else "n_uit"] += 1  # type: ignore[operator]
            if r.normalisatie_status == "onzeker":
                g["onzeker"] += 1  # type: ignore[operator]
                onzeker_totaal += 1
            if r.aantal is not None:
                g["in" if r.richting == "in" else "uit"] += r.aantal  # type: ignore[operator]
        elif r.datum < van and r.artikelgroep_id is not None and r.normalisatie_status != "uitgesloten":
            if r.aantal is not None:
                g = per_groep[r.artikelgroep_id]
                g["begin"] += r.aantal if r.richting == "in" else -r.aantal  # type: ignore[operator]

    laatste_telling: dict[uuid.UUID, VoorraadTelling] = {}
    for t in tellingen:
        laatste_telling.setdefault(t.artikelgroep_id, t)

    uit: list[GroepAansluiting] = []
    for groep in groepen:
        g = per_groep.get(
            groep.id, {"begin": Decimal(0), "in": Decimal(0), "uit": Decimal(0), "n_in": 0, "n_uit": 0, "onzeker": 0}
        )
        theoretisch = Decimal(g["begin"]) + Decimal(g["in"]) - Decimal(g["uit"])
        telling = laatste_telling.get(groep.id)
        systeemstand = telling.aantal if telling else None
        verschil = (systeemstand - theoretisch) if systeemstand is not None else None
        verschil_pct = _pct(verschil, theoretisch) if verschil is not None else None
        if systeemstand is None:
            signaal = "geen_telling"
        elif verschil_pct is None:
            signaal = "binnen_tolerantie" if verschil == 0 else "onderzoeken"
        else:
            signaal = "binnen_tolerantie" if abs(verschil_pct) <= groep.tolerantie_pct else "onderzoeken"
        n_regels = int(g["n_in"]) + int(g["n_uit"])
        onzeker_pct = (
            (Decimal(int(g["onzeker"])) / Decimal(n_regels) * 100).quantize(_HONDERDSTE, rounding=ROUND_HALF_UP)
            if n_regels
            else Decimal(0)
        )
        uit.append(
            GroepAansluiting(
                artikelgroep_id=groep.id,
                naam=groep.naam,
                eenheid=groep.eenheid,
                tolerantie_pct=groep.tolerantie_pct,
                begin=Decimal(g["begin"]).quantize(_DUIZENDSTE),
                inkoop=Decimal(g["in"]).quantize(_DUIZENDSTE),
                verkoop=Decimal(g["uit"]).quantize(_DUIZENDSTE),
                theoretisch=theoretisch.quantize(_DUIZENDSTE),
                systeemstand=systeemstand,
                telling_datum=telling.datum if telling else None,
                verschil=verschil.quantize(_DUIZENDSTE) if verschil is not None else None,
                verschil_pct=verschil_pct,
                signaal=signaal,
                onzeker_pct=onzeker_pct,
                regels_in=int(g["n_in"]),
                regels_uit=int(g["n_uit"]),
            )
        )
    return Aansluiting(
        administratie_id=administratie_id,
        van=van,
        tot=tot,
        groepen=uit,
        niet_genormaliseerd_in=niet_in,
        niet_genormaliseerd_uit=niet_uit,
        onzeker_totaal=onzeker_totaal,
        regels_totaal=totaal,
    )


@dataclass(frozen=True)
class DagStand:
    datum: date
    inkoop: Decimal
    verkoop: Decimal
    stand: Decimal


def dagstanden(*, administratie_id: uuid.UUID, artikelgroep_id: uuid.UUID, van: date, tot: date) -> list[DagStand]:
    """Dagniveau (besluit Peter 28-08): per dag de mutaties en de cumulatieve theoretische stand —
    de periode-weergave is een som van dagstanden, dus elke stand is per dag terug te bladeren."""
    _vereis_ingeschakeld(administratie_id)
    with scoped_session(administratie_id) as session:
        rijen = session.execute(
            select(VoorraadRegel.datum, VoorraadRegel.richting, func.coalesce(func.sum(VoorraadRegel.aantal), 0))
            .where(
                VoorraadRegel.administratie_id == administratie_id,
                VoorraadRegel.artikelgroep_id == artikelgroep_id,
                VoorraadRegel.normalisatie_status != "uitgesloten",
                VoorraadRegel.datum <= tot,
            )
            .group_by(VoorraadRegel.datum, VoorraadRegel.richting)
            .order_by(VoorraadRegel.datum)
        ).all()
    per_dag: dict[date, dict[str, Decimal]] = defaultdict(lambda: {"in": Decimal(0), "uit": Decimal(0)})
    for datum, richting, som in rijen:
        per_dag[datum][richting] += Decimal(som)
    stand = Decimal(0)
    uit: list[DagStand] = []
    for datum in sorted(per_dag):
        stand += per_dag[datum]["in"] - per_dag[datum]["uit"]
        if van <= datum <= tot:
            uit.append(
                DagStand(
                    datum=datum,
                    inkoop=per_dag[datum]["in"].quantize(_DUIZENDSTE),
                    verkoop=per_dag[datum]["uit"].quantize(_DUIZENDSTE),
                    stand=stand.quantize(_DUIZENDSTE),
                )
            )
    return uit


@dataclass(frozen=True)
class RegelData:
    id: uuid.UUID
    document_id: uuid.UUID
    richting: str
    bron: str
    datum: date
    relatie_naam: str | None
    artikeltekst: str
    aantal: Decimal | None
    eenheid: str | None
    prijs: Decimal | None
    netto_bedrag: Decimal | None
    artikelgroep_id: uuid.UUID | None
    artikelgroep_naam: str | None
    normalisatie_status: str
    normalisatie_zekerheid: Decimal | None


def regels(
    *,
    administratie_id: uuid.UUID,
    van: date,
    tot: date,
    artikelgroep_id: uuid.UUID | None = None,
    status: str | None = None,
) -> list[RegelData]:
    """Drill-down (mockup: "alle factuurregels achter het getal, mét link naar het document") of
    het normalisatie-scherm (status-filter: niet_genormaliseerd / onzeker)."""
    _vereis_ingeschakeld(administratie_id)
    with scoped_session(administratie_id) as session:
        q = select(VoorraadRegel).where(
            VoorraadRegel.administratie_id == administratie_id,
            VoorraadRegel.datum >= van,
            VoorraadRegel.datum <= tot,
        )
        if artikelgroep_id is not None:
            q = q.where(VoorraadRegel.artikelgroep_id == artikelgroep_id)
        if status is not None:
            q = q.where(VoorraadRegel.normalisatie_status == status)
        rijen = list(session.scalars(q.order_by(VoorraadRegel.datum.desc(), VoorraadRegel.regel_volgnummer)))
        namen = dict(
            session.execute(
                select(Artikelgroep.id, Artikelgroep.naam).where(Artikelgroep.administratie_id == administratie_id)
            ).all()
        )
        session.expunge_all()
    return [
        RegelData(
            id=r.id,
            document_id=r.document_id,
            richting=r.richting,
            bron=r.bron,
            datum=r.datum,
            relatie_naam=r.relatie_naam,
            artikeltekst=r.artikeltekst,
            aantal=r.aantal,
            eenheid=r.eenheid,
            prijs=r.prijs,
            netto_bedrag=r.netto_bedrag,
            artikelgroep_id=r.artikelgroep_id,
            artikelgroep_naam=namen.get(r.artikelgroep_id) if r.artikelgroep_id else None,
            normalisatie_status=r.normalisatie_status,
            normalisatie_zekerheid=r.normalisatie_zekerheid,
        )
        for r in rijen
    ]


# --- telling + groepen + correctie -----------------------------------------------------------------


def voer_telling_in(
    *,
    administratie_id: uuid.UUID,
    artikelgroep_id: uuid.UUID,
    datum: date,
    aantal: Decimal,
    opmerking: str | None,
    actor_id: uuid.UUID,
) -> None:
    """Systeemstand fase 1: telling per groep per datum (upsert op datum), audit oud→nieuw."""
    _vereis_ingeschakeld(administratie_id)
    if aantal < 0:
        raise OngeldigeInvoer("Een telling kan niet negatief zijn")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        groep = session.get(Artikelgroep, artikelgroep_id)
        if groep is None or groep.administratie_id != administratie_id:
            raise OngeldigeInvoer("Onbekende artikelgroep")
        bestaande = session.scalars(
            select(VoorraadTelling).where(
                VoorraadTelling.artikelgroep_id == artikelgroep_id, VoorraadTelling.datum == datum
            )
        ).first()
        oud = bestaande.aantal if bestaande else None
        if bestaande is None:
            session.add(
                VoorraadTelling(
                    administratie_id=administratie_id,
                    artikelgroep_id=artikelgroep_id,
                    datum=datum,
                    aantal=aantal,
                    opmerking=opmerking,
                    ingevoerd_door=actor_id,
                )
            )
        else:
            bestaande.aantal = aantal
            bestaande.opmerking = opmerking
            bestaande.ingevoerd_door = actor_id
        record_audit_event(
            session,
            actor_id=actor_id,
            module="mi",
            tabel="voorraad_telling",
            record_id=artikelgroep_id,
            actie="voorraad_telling_ingevoerd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"aantal": str(oud)} if oud is not None else None,
            nieuwe_waarde={"datum": datum.isoformat(), "aantal": str(aantal), "opmerking": opmerking},
            administratie_id=administratie_id,
        )


@dataclass(frozen=True)
class GroepData:
    id: uuid.UUID
    naam: str
    eenheid: str
    tolerantie_pct: Decimal
    actief: bool


def groepen(*, administratie_id: uuid.UUID) -> list[GroepData]:
    with scoped_session(administratie_id) as session:
        rijen = list(
            session.scalars(
                select(Artikelgroep)
                .where(Artikelgroep.administratie_id == administratie_id)
                .order_by(Artikelgroep.naam)
            )
        )
        session.expunge_all()
    return [
        GroepData(id=g.id, naam=g.naam, eenheid=g.eenheid, tolerantie_pct=g.tolerantie_pct, actief=g.actief)
        for g in rijen
    ]


def maak_groep(
    *, administratie_id: uuid.UUID, naam: str, eenheid: str, tolerantie_pct: Decimal, actor_id: uuid.UUID
) -> GroepData:
    _vereis_ingeschakeld(administratie_id)
    schoon = " ".join(naam.split())
    if not schoon:
        raise OngeldigeInvoer("Naam van de artikelgroep ontbreekt")
    if not (Decimal(0) <= tolerantie_pct <= Decimal(100)):
        raise OngeldigeInvoer("Tolerantie moet tussen 0 en 100 procent liggen")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        bestaat = session.scalars(
            select(Artikelgroep.id).where(
                Artikelgroep.administratie_id == administratie_id,
                Artikelgroep.actief.is_(True),
                func.lower(Artikelgroep.naam) == schoon.lower(),
            )
        ).first()
        if bestaat is not None:
            raise OngeldigeInvoer(f"Er bestaat al een artikelgroep '{schoon}'")
        groep = Artikelgroep(
            administratie_id=administratie_id,
            naam=schoon,
            eenheid=(eenheid or "st")[:16],
            tolerantie_pct=tolerantie_pct,
            aangemaakt_door=actor_id,
        )
        session.add(groep)
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module="mi",
            tabel="artikelgroep",
            record_id=groep.id,
            actie="artikelgroep_aangemaakt",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"naam": schoon, "eenheid": groep.eenheid, "tolerantie_pct": str(tolerantie_pct)},
            administratie_id=administratie_id,
        )
        return GroepData(
            id=groep.id, naam=groep.naam, eenheid=groep.eenheid, tolerantie_pct=groep.tolerantie_pct, actief=True
        )


def zet_tolerantie(
    *, administratie_id: uuid.UUID, artikelgroep_id: uuid.UUID, tolerantie_pct: Decimal, actor_id: uuid.UUID
) -> None:
    _vereis_ingeschakeld(administratie_id)
    if not (Decimal(0) <= tolerantie_pct <= Decimal(100)):
        raise OngeldigeInvoer("Tolerantie moet tussen 0 en 100 procent liggen")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        groep = session.get(Artikelgroep, artikelgroep_id)
        if groep is None or groep.administratie_id != administratie_id:
            raise OngeldigeInvoer("Onbekende artikelgroep")
        oud = groep.tolerantie_pct
        groep.tolerantie_pct = tolerantie_pct
        record_audit_event(
            session,
            actor_id=actor_id,
            module="mi",
            tabel="artikelgroep",
            record_id=artikelgroep_id,
            actie="artikelgroep_tolerantie_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"tolerantie_pct": str(oud)},
            nieuwe_waarde={"tolerantie_pct": str(tolerantie_pct)},
            administratie_id=administratie_id,
        )


def corrigeer_normalisatie(
    *,
    administratie_id: uuid.UUID,
    regel_id: uuid.UUID,
    artikelgroep_id: uuid.UUID | None,
    uitgesloten: bool,
    actor_id: uuid.UUID,
) -> int:
    """Optionele correctie (mockup §2): geldt vanaf dan voor álle regels met dezelfde leverancier +
    artikeltekst (historie herrekend, bron 'handmatig' — wint van de AI). Geeft het aantal herrekende
    feitenregels terug."""
    _vereis_ingeschakeld(administratie_id)
    if not uitgesloten and artikelgroep_id is None:
        raise OngeldigeInvoer("Kies een artikelgroep of markeer de regel als 'geen artikel'")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        regel = session.get(VoorraadRegel, regel_id)
        if regel is None or regel.administratie_id != administratie_id:
            raise OngeldigeInvoer("Onbekende regel")
        if artikelgroep_id is not None:
            groep = session.get(Artikelgroep, artikelgroep_id)
            if groep is None or groep.administratie_id != administratie_id or not groep.actief:
                raise OngeldigeInvoer("Onbekende of inactieve artikelgroep")
        norm = normalisatie.normaliseer_tekst(regel.artikeltekst)
        vendor = regel.vendor_id or ONBEKENDE_LEVERANCIER
        bestaande = normalisatie.zoek_regel(
            session, administratie_id=administratie_id, vendor_id=vendor, tekst_norm=norm
        )
        oud = None
        if bestaande is None:
            bestaande = NormalisatieRegel(
                administratie_id=administratie_id, vendor_id=vendor, artikeltekst_norm=norm, bron="handmatig"
            )
            session.add(bestaande)
        else:
            oud = {
                "artikelgroep_id": str(bestaande.artikelgroep_id) if bestaande.artikelgroep_id else None,
                "uitgesloten": bestaande.uitgesloten,
                "bron": bestaande.bron,
            }
        bestaande.artikelgroep_id = None if uitgesloten else artikelgroep_id
        bestaande.uitgesloten = uitgesloten
        bestaande.zekerheid = Decimal("1.000")
        bestaande.bron = "handmatig"
        bestaande.bijgewerkt_door = actor_id
        session.flush()
        uitkomst = normalisatie.pas_regel_toe(bestaande)
        # Historie herrekenen: álle feitenregels met dezelfde (leverancier, tekst).
        betrokken = list(
            session.scalars(
                select(VoorraadRegel).where(
                    VoorraadRegel.administratie_id == administratie_id,
                    (VoorraadRegel.vendor_id == regel.vendor_id)
                    if regel.vendor_id
                    else VoorraadRegel.vendor_id.is_(None),
                )
            )
        )
        n = 0
        for r in betrokken:
            if normalisatie.normaliseer_tekst(r.artikeltekst) != norm:
                continue
            r.artikelgroep_id = uitkomst.artikelgroep_id
            r.normalisatie_status = uitkomst.status
            r.normalisatie_zekerheid = uitkomst.zekerheid
            n += 1
        record_audit_event(
            session,
            actor_id=actor_id,
            module="mi",
            tabel="normalisatie_regel",
            record_id=bestaande.id,
            actie="normalisatie_gecorrigeerd",
            correlatie_id=regel_id,
            oude_waarde=oud,
            nieuwe_waarde={
                "artikeltekst_norm": norm,
                "artikelgroep_id": str(artikelgroep_id) if artikelgroep_id else None,
                "uitgesloten": uitgesloten,
                "herrekend": n,
            },
            administratie_id=administratie_id,
        )
        return n
