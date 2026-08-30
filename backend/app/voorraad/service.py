"""Voorraad-aansluiting fase 1 — Universal Verkoop (bouwrun 28-08 blok D; mockup
voorraad-aansluiting.html §1 = bouwnorm). Controle-laag: instroom = regel-niveau feiten uit het
inkoop-veldvoorstel (extern document), uitstroom = verkoopfactuurregels (de in de app geboekte
verkoopdocumenten mét UBL-hoeveelheden ÉN — sinds 29-08, `rlz_uitstroom.py` — de eigen
RLZ-verkoopfacturen van de administratie via de dagelijkse leesroute; Odoo = parkeerpost),
systeemstand = handmatige telling per datum. Mutaties op DAGNIVEAU; verschil buiten de tolerantie =
vlag, puur MI — nooit een boeking, nooit RLZ-writes. Code voor cijfers: alle telling deterministisch.

v2 (30-08, besluiten Peter 29-08 avond): dienst-/transportregels blijven in de feitenlaag mét
soort-label (tellen niet in de aansluiting, wél zichtbaar/corrigeerbaar in de dienst-inzage en
queryable als omzet-/dienstregel); artikelcode als deterministische sleutel per richting mét
codes-inzage + correctie; élke correctie herleidt de historie deterministisch (geen AI)."""

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
from app.voorraad.models import (
    ONBEKENDE_LEVERANCIER,
    SOORTEN,
    ArtikelcodeKoppeling,
    Artikelgroep,
    VoorraadRegel,
    VoorraadTelling,
)
from app.voorraad.normalisatie import LEGACY_UITGESLOTEN, SOORT_ARTIKEL, RegelInvoer

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
        # Artikelcode = de leverancierscode uit het veldvoorstel (AI-veld `a`, v2 30-08), anders uit
        # de omschrijving; richting 'in' — een andere sleutelruimte dan de eigen verkoopcodes.
        normalisaties = normalisatie.normaliseer_regels(
            session,
            administratie_id=administratie_id,
            document_id=document_id,
            regels=[
                RegelInvoer(
                    str(r["omschrijving"]),
                    vendor_id,
                    leverancier,
                    "in",
                    str(r["artikelcode"]) if r.get("artikelcode") else None,
                )
                for r in regels
            ],
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
                    artikelcode=n.artikelcode,
                    soort=n.soort,
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
            regels=[RegelInvoer(str(r.omschrijving), None, None, "uit") for r in bruikbaar],
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
                    artikelcode=n.artikelcode,
                    soort=n.soort,
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


def herreken_administratie(*, administratie_id: uuid.UUID, actor_id: uuid.UUID, met_ai: bool = True) -> dict[str, int]:
    """ "⟳ Verversen" / hernormalisatie (CLI `voorraad-hernormaliseer`): alle inkoopdocumenten mét
    veldvoorstel en alle geboekte verkoopdocumenten opnieuw door de feitenlaag én de opgeslagen
    RLZ-regels hernormaliseren (bestaande tekstregels/code-koppelingen = deterministisch, dus geen
    nieuwe AI-calls voor bekende teksten; `met_ai=False` = alleen deterministisch). Zet de legacy-
    status 'uitgesloten' (pre-0088) om naar het soort-label. Audit per run mét de stand ná afloop."""
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
    telling = {
        "inkoop_documenten": 0,
        "inkoop_regels": 0,
        "verkoop_documenten": 0,
        "verkoop_regels": 0,
        "rlz_regels": 0,
    }
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
    # RLZ-verkoopfacturen (blok A 29-08): alleen de opgeslagen regels hernormaliseren — géén RLZ-calls
    # vanuit de UI-knop (504-les); het lezen zelf zit in de dagelijkse sync / `voorraad-rlz-sync`.
    from app.voorraad import rlz_uitstroom

    telling["rlz_regels"] = rlz_uitstroom.hernormaliseer_rlz_regels(administratie_id=administratie_id, met_ai=met_ai)
    stand = normalisatie_stand(administratie_id=administratie_id)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        record_audit_event(
            session,
            actor_id=actor_id,
            module="mi",
            tabel="voorraad_regel",
            record_id=administratie_id,
            actie="voorraad_herrekend",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={**telling, "stand": stand},
            administratie_id=administratie_id,
        )
    return telling


def _soort_van_rij(r: VoorraadRegel) -> str:
    """Legacy-rijen (status 'uitgesloten', pre-0088) gelden als dienst tot de hernormalisatie ze omzet."""
    if r.normalisatie_status == LEGACY_UITGESLOTEN:
        return "dienst"
    return r.soort


def normalisatie_stand(*, administratie_id: uuid.UUID) -> dict[str, int]:
    """Rapportstand per administratie (CLI-rapport blok D): genormaliseerd / onzeker / dienst /
    transport / niet_genormaliseerd / legacy_uitgesloten + codes gekoppeld. Puur tellen."""
    with scoped_session(administratie_id) as session:
        rijen = session.execute(
            select(VoorraadRegel.soort, VoorraadRegel.normalisatie_status, func.count())
            .where(VoorraadRegel.administratie_id == administratie_id)
            .group_by(VoorraadRegel.soort, VoorraadRegel.normalisatie_status)
        ).all()
        codes = session.scalar(
            select(func.count())
            .select_from(ArtikelcodeKoppeling)
            .where(ArtikelcodeKoppeling.administratie_id == administratie_id)
        )
        met_code = session.scalar(
            select(func.count()).where(
                VoorraadRegel.administratie_id == administratie_id, VoorraadRegel.artikelcode.is_not(None)
            )
        )
    stand = {
        "regels": 0,
        "genormaliseerd": 0,
        "onzeker": 0,
        "dienst": 0,
        "transport": 0,
        "niet_genormaliseerd": 0,
        "legacy_uitgesloten": 0,
        "regels_met_code": int(met_code or 0),
        "codes_gekoppeld": int(codes or 0),
    }
    for soort, status, n in rijen:
        stand["regels"] += n
        if status == LEGACY_UITGESLOTEN:
            stand["legacy_uitgesloten"] += n
        elif soort != SOORT_ARTIKEL:
            stand[soort] += n
        else:
            stand[status] += n
    return stand


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
    # v2: dienst-/transportregels in de periode (soort-label) — niet in de aansluiting, wél bewaard.
    dienst_regels: int = 0
    transport_regels: int = 0
    bronnen: dict[str, str] = field(
        default_factory=lambda: {
            "inkoop": "inkoopfacturen (AI-gescand, extern document)",
            "verkoop": (
                "verkoopfactuurregels (in de app geboekt) + RLZ-verkoopfacturen "
                "(dagelijkse leesroute, Quantity per regel)"
            ),
            "verkoop_rlz": (
                "RLZ-verkoopfacturen van de administratie (alleen geboekt, Status 2/3; "
                "creditregels = negatieve Quantity)"
            ),
            "systeemstand": "handmatige telling per datum",
            "diensten": (
                "dienst-/transportregels (soort-label: regex, AI of correctie) — tellen niet in de "
                "aansluiting, blijven bewaard als omzet-/dienstinformatie"
            ),
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
    niet_in = niet_uit = onzeker_totaal = totaal = dienst_n = transport_n = 0
    for r in regels:
        soort = _soort_van_rij(r)
        if van <= r.datum <= tot:
            totaal += 1
            if soort != SOORT_ARTIKEL:
                if soort == "transport":
                    transport_n += 1
                else:
                    dienst_n += 1
                continue
            if r.normalisatie_status == "niet_genormaliseerd":
                if r.richting == "in":
                    niet_in += 1
                else:
                    niet_uit += 1
                continue
            if r.artikelgroep_id is None:
                continue
            g = per_groep[r.artikelgroep_id]
            g["n_in" if r.richting == "in" else "n_uit"] += 1  # type: ignore[operator]
            if r.normalisatie_status == "onzeker":
                g["onzeker"] += 1  # type: ignore[operator]
                onzeker_totaal += 1
            if r.aantal is not None:
                g["in" if r.richting == "in" else "uit"] += r.aantal  # type: ignore[operator]
        elif r.datum < van and r.artikelgroep_id is not None and soort == SOORT_ARTIKEL:
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
        dienst_regels=dienst_n,
        transport_regels=transport_n,
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
                VoorraadRegel.soort == SOORT_ARTIKEL,
                VoorraadRegel.normalisatie_status != LEGACY_UITGESLOTEN,
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
    document_id: uuid.UUID | None
    rlz_document_id: uuid.UUID | None
    rlz_referentie: str | None
    richting: str
    bron: str
    datum: date
    relatie_naam: str | None
    artikeltekst: str
    artikelcode: str | None
    soort: str
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
    soort: str | None = None,
) -> list[RegelData]:
    """Drill-down (mockup: "alle factuurregels achter het getal, mét link naar het document"), het
    normalisatie-scherm (status-filter: niet_genormaliseerd / onzeker) of de dienst-/omzetregels
    (soort-filter: dienst / transport — MI-query, v2)."""
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
            if status != LEGACY_UITGESLOTEN:
                q = q.where(VoorraadRegel.soort == SOORT_ARTIKEL)
        if soort is not None:
            q = q.where(VoorraadRegel.soort == soort)
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
            rlz_document_id=r.rlz_document_id,
            rlz_referentie=r.rlz_referentie,
            richting=r.richting,
            bron=r.bron,
            datum=r.datum,
            relatie_naam=r.relatie_naam,
            artikeltekst=r.artikeltekst,
            artikelcode=r.artikelcode,
            soort=_soort_van_rij(r),
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


# --- v2: dienst-inzage + codes-inzage (controlemechanisme, eis Peter: nooit blind vertrouwen) --------


@dataclass(frozen=True)
class DienstTekst:
    voorbeeld_regel_id: uuid.UUID
    artikeltekst: str
    artikeltekst_norm: str
    vendor_id: uuid.UUID | None
    relatie_naam: str | None
    soort: str  # dienst | transport
    bron: str  # regel | ai | handmatig | legacy
    richtingen: str  # in | uit | in+uit
    regels: int
    som_aantal: Decimal
    som_netto: Decimal


def dienst_teksten(*, administratie_id: uuid.UUID, van: date, tot: date) -> list[DienstTekst]:
    """ "Als dienst geclassificeerd" — per unieke (leverancier, tekst) mét aantallen, soort en de bron van
    de classificatie (regex 'regel' / AI / handmatig / legacy pre-0088). Meest voorkomend eerst."""
    _vereis_ingeschakeld(administratie_id)
    with scoped_session(administratie_id) as session:
        rijen = list(
            session.scalars(
                select(VoorraadRegel).where(
                    VoorraadRegel.administratie_id == administratie_id,
                    VoorraadRegel.datum >= van,
                    VoorraadRegel.datum <= tot,
                    (VoorraadRegel.soort != SOORT_ARTIKEL) | (VoorraadRegel.normalisatie_status == LEGACY_UITGESLOTEN),
                )
            )
        )
        tekstregels, _ = normalisatie._bestaande_kennis(session, administratie_id=administratie_id)
        session.expunge_all()
    groepen: dict[tuple[uuid.UUID, str], dict] = {}
    for r in rijen:
        vendor = r.vendor_id or ONBEKENDE_LEVERANCIER
        norm = normalisatie.normaliseer_tekst(r.artikeltekst)
        g = groepen.setdefault(
            (vendor, norm),
            {
                "voorbeeld": r,
                "richtingen": set(),
                "n": 0,
                "aantal": Decimal(0),
                "netto": Decimal(0),
                "soort": _soort_van_rij(r),
            },
        )
        g["richtingen"].add(r.richting)
        g["n"] += 1
        g["aantal"] += r.aantal or Decimal(0)
        g["netto"] += r.netto_bedrag or Decimal(0)
    uit: list[DienstTekst] = []
    for (vendor, norm), g in groepen.items():
        regel = tekstregels.get((vendor, norm))
        voorbeeld: VoorraadRegel = g["voorbeeld"]
        uit.append(
            DienstTekst(
                voorbeeld_regel_id=voorbeeld.id,
                artikeltekst=voorbeeld.artikeltekst,
                artikeltekst_norm=norm,
                vendor_id=voorbeeld.vendor_id,
                relatie_naam=voorbeeld.relatie_naam,
                soort=g["soort"],
                bron=regel.bron if regel is not None else "legacy",
                richtingen="+".join(sorted(g["richtingen"])),
                regels=g["n"],
                som_aantal=Decimal(g["aantal"]).quantize(_DUIZENDSTE),
                som_netto=Decimal(g["netto"]).quantize(_HONDERDSTE),
            )
        )
    uit.sort(key=lambda d: (-d.regels, d.artikeltekst_norm))
    return uit


@dataclass(frozen=True)
class ArtikelcodeData:
    id: uuid.UUID
    richting: str
    vendor_id: uuid.UUID | None
    relatie_naam: str | None
    code: str
    soort: str
    artikelgroep_id: uuid.UUID | None
    artikelgroep_naam: str | None
    zekerheid: Decimal | None
    bron: str
    voorbeeld_tekst: str | None
    regels: int
    teksten: int


def artikelcodes(*, administratie_id: uuid.UUID) -> list[ArtikelcodeData]:
    """Codes-inzage: élke koppeling (code → groep/soort per richting + leverancier) mét bron (AI-voorstel
    vs handmatig), zekerheid en het aantal feitenregels/unieke teksten dat erop steunt."""
    _vereis_ingeschakeld(administratie_id)
    with scoped_session(administratie_id) as session:
        koppelingen = list(
            session.scalars(
                select(ArtikelcodeKoppeling)
                .where(ArtikelcodeKoppeling.administratie_id == administratie_id)
                .order_by(ArtikelcodeKoppeling.richting, ArtikelcodeKoppeling.code)
            )
        )
        tellingen = session.execute(
            select(
                VoorraadRegel.richting,
                VoorraadRegel.vendor_id,
                VoorraadRegel.artikelcode,
                func.count(),
                func.count(func.distinct(VoorraadRegel.artikeltekst)),
            )
            .where(VoorraadRegel.administratie_id == administratie_id, VoorraadRegel.artikelcode.is_not(None))
            .group_by(VoorraadRegel.richting, VoorraadRegel.vendor_id, VoorraadRegel.artikelcode)
        ).all()
        namen = dict(
            session.execute(
                select(Artikelgroep.id, Artikelgroep.naam).where(Artikelgroep.administratie_id == administratie_id)
            ).all()
        )
        vendors = dict(
            session.execute(
                select(VendorCache.id, VendorCache.naam).where(VendorCache.administratie_id == administratie_id)
            ).all()
        )
        session.expunge_all()
    per_sleutel = {(ri, v or ONBEKENDE_LEVERANCIER, c): (int(n), int(t)) for ri, v, c, n, t in tellingen}
    uit: list[ArtikelcodeData] = []
    for k in koppelingen:
        n, t = per_sleutel.get((k.richting, k.vendor_id, k.code), (0, 0))
        vendor = None if k.vendor_id == ONBEKENDE_LEVERANCIER else k.vendor_id
        uit.append(
            ArtikelcodeData(
                id=k.id,
                richting=k.richting,
                vendor_id=vendor,
                relatie_naam=vendors.get(vendor) if vendor else None,
                code=k.code,
                soort=k.soort,
                artikelgroep_id=k.artikelgroep_id,
                artikelgroep_naam=namen.get(k.artikelgroep_id) if k.artikelgroep_id else None,
                zekerheid=k.zekerheid,
                bron=k.bron,
                voorbeeld_tekst=k.voorbeeld_tekst,
                regels=n,
                teksten=t,
            )
        )
    uit.sort(key=lambda d: (-d.regels, d.richting, d.code))
    return uit


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


def _toets_soort_en_groep(
    session: Session, *, administratie_id: uuid.UUID, soort: str, artikelgroep_id: uuid.UUID | None
) -> uuid.UUID | None:
    if soort not in SOORTEN:
        raise OngeldigeInvoer("Onbekende soort — kies artikel, dienst of transport")
    if soort != SOORT_ARTIKEL:
        return None
    if artikelgroep_id is None:
        raise OngeldigeInvoer("Kies een artikelgroep, of markeer de regel als dienst/transport")
    groep = session.get(Artikelgroep, artikelgroep_id)
    if groep is None or groep.administratie_id != administratie_id or not groep.actief:
        raise OngeldigeInvoer("Onbekende of inactieve artikelgroep")
    return artikelgroep_id


def _herleid(session: Session, *, administratie_id: uuid.UUID, rijen: list[VoorraadRegel]) -> int:
    """Historie herrekenen ná een correctie: de betrokken feitenregels opnieuw door het
    deterministische pad (handmatig > tekstregel > code > regex — géén AI)."""
    if not rijen:
        return 0
    normalisaties = normalisatie.normaliseer_regels(
        session,
        administratie_id=administratie_id,
        document_id=None,
        regels=[RegelInvoer(r.artikeltekst, r.vendor_id, r.relatie_naam, r.richting, r.artikelcode) for r in rijen],
        met_ai=False,
    )
    for r, n in zip(rijen, normalisaties, strict=True):
        r.artikelgroep_id = n.artikelgroep_id
        r.normalisatie_status = n.status
        r.normalisatie_zekerheid = n.zekerheid
        r.soort = n.soort
        r.artikelcode = n.artikelcode
    return len(rijen)


def corrigeer_normalisatie(
    *,
    administratie_id: uuid.UUID,
    regel_id: uuid.UUID,
    soort: str,
    artikelgroep_id: uuid.UUID | None,
    actor_id: uuid.UUID,
) -> int:
    """Optionele correctie (mockup §2, v2 mét soort): geldt vanaf dan voor álle regels met dezelfde
    leverancier + artikeltekst ÉN — draagt de regel een artikelcode — voor álle regels met dezelfde
    (richting, leverancier, code); bron 'handmatig' wint van de AI. Historie herrekend (deterministisch).
    Geeft het aantal herrekende feitenregels terug."""
    _vereis_ingeschakeld(administratie_id)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        regel = session.get(VoorraadRegel, regel_id)
        if regel is None or regel.administratie_id != administratie_id:
            raise OngeldigeInvoer("Onbekende regel")
        groep_id = _toets_soort_en_groep(
            session, administratie_id=administratie_id, soort=soort, artikelgroep_id=artikelgroep_id
        )
        norm = normalisatie.normaliseer_tekst(regel.artikeltekst)
        vendor = regel.vendor_id or ONBEKENDE_LEVERANCIER
        code = regel.artikelcode or normalisatie.artikelcode_uit_tekst(regel.artikeltekst)
        tekstregel, oud = normalisatie.zet_tekstregel(
            session,
            administratie_id=administratie_id,
            vendor_id=vendor,
            tekst_norm=norm,
            soort=soort,
            artikelgroep_id=groep_id,
            zekerheid=Decimal("1.000"),
            bron="handmatig",
            actor_id=actor_id,
        )
        if code:
            normalisatie.zet_koppeling(
                session,
                administratie_id=administratie_id,
                richting=regel.richting,
                vendor_id=vendor,
                code=code,
                soort=soort,
                artikelgroep_id=groep_id,
                zekerheid=Decimal("1.000"),
                bron="handmatig",
                voorbeeld_tekst=regel.artikeltekst,
                actor_id=actor_id,
            )
        # Historie: álle feitenregels met dezelfde (leverancier, tekst) óf dezelfde (richting, leverancier, code).
        kandidaten = list(
            session.scalars(
                select(VoorraadRegel).where(
                    VoorraadRegel.administratie_id == administratie_id,
                    (VoorraadRegel.vendor_id == regel.vendor_id)
                    if regel.vendor_id
                    else VoorraadRegel.vendor_id.is_(None),
                )
            )
        )
        betrokken = [
            r
            for r in kandidaten
            if normalisatie.normaliseer_tekst(r.artikeltekst) == norm
            or (code is not None and r.richting == regel.richting and r.artikelcode == code)
        ]
        n = _herleid(session, administratie_id=administratie_id, rijen=betrokken)
        record_audit_event(
            session,
            actor_id=actor_id,
            module="mi",
            tabel="normalisatie_regel",
            record_id=tekstregel.id,
            actie="normalisatie_gecorrigeerd",
            correlatie_id=regel_id,
            oude_waarde=oud,
            nieuwe_waarde={
                "artikeltekst_norm": norm,
                "artikelcode": code,
                "soort": soort,
                "artikelgroep_id": str(groep_id) if groep_id else None,
                "herrekend": n,
            },
            administratie_id=administratie_id,
        )
        return n


def corrigeer_artikelcode(
    *,
    administratie_id: uuid.UUID,
    koppeling_id: uuid.UUID,
    soort: str,
    artikelgroep_id: uuid.UUID | None,
    actor_id: uuid.UUID,
) -> int:
    """Correctie vanuit de codes-inzage: de koppeling wordt 'handmatig' (wint van de AI) en álle
    feitenregels met dezelfde (richting, leverancier, code) worden deterministisch herleid. Een
    handmatige TEKSTregel op één specifieke omschrijving blijft daarbij voorgaan (prioriteitsregel)."""
    _vereis_ingeschakeld(administratie_id)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        koppeling = session.get(ArtikelcodeKoppeling, koppeling_id)
        if koppeling is None or koppeling.administratie_id != administratie_id:
            raise OngeldigeInvoer("Onbekende artikelcode-koppeling")
        groep_id = _toets_soort_en_groep(
            session, administratie_id=administratie_id, soort=soort, artikelgroep_id=artikelgroep_id
        )
        _, oud = normalisatie.zet_koppeling(
            session,
            administratie_id=administratie_id,
            richting=koppeling.richting,
            vendor_id=koppeling.vendor_id,
            code=koppeling.code,
            soort=soort,
            artikelgroep_id=groep_id,
            zekerheid=Decimal("1.000"),
            bron="handmatig",
            voorbeeld_tekst=koppeling.voorbeeld_tekst,
            actor_id=actor_id,
        )
        vendor_filter = (
            VoorraadRegel.vendor_id.is_(None)
            if koppeling.vendor_id == ONBEKENDE_LEVERANCIER
            else VoorraadRegel.vendor_id == koppeling.vendor_id
        )
        betrokken = list(
            session.scalars(
                select(VoorraadRegel).where(
                    VoorraadRegel.administratie_id == administratie_id,
                    VoorraadRegel.richting == koppeling.richting,
                    VoorraadRegel.artikelcode == koppeling.code,
                    vendor_filter,
                )
            )
        )
        n = _herleid(session, administratie_id=administratie_id, rijen=betrokken)
        record_audit_event(
            session,
            actor_id=actor_id,
            module="mi",
            tabel="artikelcode_koppeling",
            record_id=koppeling.id,
            actie="artikelcode_gecorrigeerd",
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde={
                "richting": koppeling.richting,
                "code": koppeling.code,
                "soort": soort,
                "artikelgroep_id": str(groep_id) if groep_id else None,
                "herrekend": n,
            },
            administratie_id=administratie_id,
        )
        return n
