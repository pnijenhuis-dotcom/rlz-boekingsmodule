"""Factuurmatch ZZP-/bureaufacturen — fase 1: deterministische match-motor (akkoord Peter
2026-08-21, BESLISSINGEN "FACTUURMATCH ZZP-/BUREAUFACTUREN").

Code voor cijfers, geen AI: een inkoopfactuur van een gekoppelde veldwerker-crediteur
(veldwerker_crediteur) wordt vergeleken met de GETEKENDE (goedgekeurde) weekstaten.

- ZZP-factuur: som staten-uren × het uurtarief op de veldwerker-koppeling vs de som van de
  netto regelbedragen uit het boekvoorstel (btw-verlegd is de norm in de bouwketen — netto is
  de vergelijkbare grootheid; per lid afgerond op de cent, ROUND_HALF_UP).
- Bureaufactuur (detacheerder): som over de gekoppelde ZZP'ers van (staten-uren × het tarief
  per detacheerder↔zzp'er-koppeling) — het koppeling-tarief is het HOOFDMECHANISME (besluit 1).
- Ontbreekt een tarief (ZZP-koppeling zonder uurtarief, of ≥ 1 bureau-koppeling zonder):
  match alleen op uren → uitkomst `match_alleen_uren`, oranje "geen tarief bekend" — geen
  blokkade (besluit 1). Geen tarief én geen factuur-uren = `niet_toetsbaar`.
- Afwijking = losse vlag + eigen teller/chip (duplicaat-patroon, besluit 3) — geen
  documentstatus; boeken kan mét expliciete bevestiging (besluit 2, poort in fase 2) en het
  autoboek-slot (fase 4) is uitsluitend groen bij `match`.
- Dubbeltelling-preventie: bij boeken verrekent `verreken_staten` de betrokken staten
  (weekstaat.verrekend_met_document_id) — een verrekende staat doet nooit meer mee in een
  andere match; herberekening op hetzélfde document blijft ze zien (idempotent).
- Kandidaat-staten (default): goedgekeurd, onverrekend (of verrekend met dít document), t/m
  de ISO-week van de factuurdatum (zonder factuurdatum: alle). Een expliciete
  weekstaat_ids-selectie (match-sectie kantoor-UI, fase 3) vervangt de default ná validatie.

De berekening zelf wordt niet geauditeerd (deterministisch afgeleide van staten + voorstel,
herhaalbaar — resultaat + berekend_op staan in `factuurmatch`); de verrekening bij boeken wél
(audit_event). `factuur_uren` komt uit extractie/mens (fase 2/3) en is hier een parameter."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import DetacheerderKoppeling, Gebruiker, GebruikerRol
from app.db.session import scoped_session
from app.documenten.models import Boekvoorstel, BoekvoorstelRegel, Document, DocumentSoort
from app.sync.models import ProjectCache
from app.uren.models import (
    Factuurmatch,
    FactuurmatchStaat,
    FactuurmatchUitkomst,
    VeldwerkerCrediteur,
    Weekstaat,
    WeekstaatDag,
    WeekstaatStatus,
)
from app.uren.service import NietGevonden, OngeldigeInvoer

TOLERANTIE_BEDRAG = Decimal("0.01")
TOLERANTIE_UREN = Decimal("0.01")

_CENT = Decimal("0.01")


# --- pure geldlogica ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MatchLid:
    """Eén ZZP'er in de vergelijking (bij een ZZP-factuur precies één lid — de veldwerker
    zelf; bij een bureaufactuur één per gekoppelde ZZP'er, mét het koppeling-tarief)."""

    gebruiker_id: uuid.UUID
    naam: str | None
    uren: Decimal
    uurtarief: Decimal | None

    @property
    def bedrag(self) -> Decimal | None:
        if self.uurtarief is None:
            return None
        return (self.uren * self.uurtarief).quantize(_CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class MatchBerekening:
    uitkomst: FactuurmatchUitkomst
    staten_som_uren: Decimal
    staten_som_bedrag: Decimal | None
    factuur_bedrag: Decimal | None
    factuur_uren: Decimal | None
    verschil_bedrag: Decimal | None
    verschil_uren: Decimal | None
    tarief_ontbreekt: bool


def bepaal_uitkomst(
    *,
    leden: list[MatchLid],
    factuur_bedrag: Decimal | None,
    factuur_uren: Decimal | None,
) -> MatchBerekening:
    """Pure vergelijking (besluiten 1–3): bedrag is het hoofdmechanisme; élke beschikbare
    vergelijking moet sluiten voor `match` (een kloppend bedrag met afwijkende uren is een
    tariefverschil — dat is een afwijking, geen match)."""
    staten_som_uren = sum((lid.uren for lid in leden), Decimal("0"))
    tarief_ontbreekt = any(lid.uurtarief is None for lid in leden)
    staten_som_bedrag: Decimal | None = None
    if not tarief_ontbreekt:
        staten_som_bedrag = sum((lid.bedrag or Decimal("0") for lid in leden), Decimal("0"))

    bedrag_toetsbaar = staten_som_bedrag is not None and factuur_bedrag is not None
    uren_toetsbaar = factuur_uren is not None

    verschil_bedrag = factuur_bedrag - staten_som_bedrag if bedrag_toetsbaar else None
    verschil_uren = factuur_uren - staten_som_uren if uren_toetsbaar else None

    if not bedrag_toetsbaar and not uren_toetsbaar:
        uitkomst = FactuurmatchUitkomst.NIET_TOETSBAAR
    elif (verschil_bedrag is not None and abs(verschil_bedrag) > TOLERANTIE_BEDRAG) or (
        verschil_uren is not None and abs(verschil_uren) > TOLERANTIE_UREN
    ):
        uitkomst = FactuurmatchUitkomst.AFWIJKING
    elif bedrag_toetsbaar:
        uitkomst = FactuurmatchUitkomst.MATCH
    else:
        uitkomst = FactuurmatchUitkomst.MATCH_ALLEEN_UREN

    return MatchBerekening(
        uitkomst=uitkomst,
        staten_som_uren=staten_som_uren,
        staten_som_bedrag=staten_som_bedrag,
        factuur_bedrag=factuur_bedrag,
        factuur_uren=factuur_uren,
        verschil_bedrag=verschil_bedrag,
        verschil_uren=verschil_uren,
        tarief_ontbreekt=tarief_ontbreekt,
    )


# --- resultaat-DTO -----------------------------------------------------------------------------


@dataclass(frozen=True)
class FactuurmatchData:
    document_id: uuid.UUID
    veldwerker_gebruiker_id: uuid.UUID
    veldwerker_naam: str | None
    uitkomst: str
    staten_som_uren: Decimal
    staten_som_bedrag: Decimal | None
    factuur_bedrag: Decimal | None
    factuur_uren: Decimal | None
    verschil_bedrag: Decimal | None
    verschil_uren: Decimal | None
    tarief_ontbreekt: bool
    details: dict | None
    weekstaat_ids: list[uuid.UUID]


def _als_str(waarde: Decimal | None) -> str | None:
    return str(waarde) if waarde is not None else None


# --- staten-selectie ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _StaatRegel:
    weekstaat_id: uuid.UUID
    gebruiker_id: uuid.UUID
    project_naam: str | None
    jaar: int
    weeknummer: int
    uren: Decimal


def _kandidaat_staten(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    gebruiker_ids: list[uuid.UUID],
    tot_en_met: tuple[int, int] | None,
) -> list[_StaatRegel]:
    """Goedgekeurde, onverrekende (of met dít document verrekende) staten van de leden, t/m de
    ISO-(jaar, week) van de factuurdatum. Staat-uren = som van de dagregels (geen dagen = 0)."""
    query = (
        select(Weekstaat, ProjectCache.naam)
        .join(
            ProjectCache,
            (ProjectCache.id == Weekstaat.project_id)
            & (ProjectCache.administratie_id == Weekstaat.administratie_id),
        )
        .where(
            Weekstaat.administratie_id == administratie_id,
            Weekstaat.status == WeekstaatStatus.GOEDGEKEURD.value,
            Weekstaat.gebruiker_id.in_(gebruiker_ids),
            (Weekstaat.verrekend_met_document_id.is_(None))
            | (Weekstaat.verrekend_met_document_id == document_id),
        )
        .order_by(Weekstaat.jaar, Weekstaat.weeknummer)
    )
    rijen = session.execute(query).all()
    if tot_en_met is not None:
        rijen = [r for r in rijen if (r[0].jaar, r[0].weeknummer) <= tot_en_met]
    return [_met_uren(session, staat, project_naam) for staat, project_naam in rijen]


def _met_uren(session: Session, staat: Weekstaat, project_naam: str | None) -> _StaatRegel:
    dagen = session.scalars(select(WeekstaatDag.uren).where(WeekstaatDag.weekstaat_id == staat.id)).all()
    return _StaatRegel(
        weekstaat_id=staat.id,
        gebruiker_id=staat.gebruiker_id,
        project_naam=project_naam,
        jaar=staat.jaar,
        weeknummer=staat.weeknummer,
        uren=sum(dagen, Decimal("0")),
    )


def _expliciete_staten(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    weekstaat_ids: list[uuid.UUID],
    gebruiker_ids: list[uuid.UUID],
) -> list[_StaatRegel]:
    """Handmatige selectie (match-sectie, fase 3): elke staat moet bestaan, goedgekeurd zijn,
    van een betrokken ZZP'er zijn en onverrekend (of met dít document verrekend) — anders een
    zichtbare fout, nooit stil overslaan."""
    resultaat: list[_StaatRegel] = []
    for weekstaat_id in weekstaat_ids:
        staat = session.get(Weekstaat, weekstaat_id)
        if staat is None or staat.administratie_id != administratie_id:
            raise NietGevonden(f"Weekstaat {weekstaat_id} niet gevonden")
        if staat.status != WeekstaatStatus.GOEDGEKEURD.value:
            raise OngeldigeInvoer("Alleen goedgekeurde (getekende) weekstaten tellen mee in de match")
        if staat.gebruiker_id not in gebruiker_ids:
            raise OngeldigeInvoer("Weekstaat hoort niet bij een ZZP'er van deze veldwerker-koppeling")
        if staat.verrekend_met_document_id is not None and staat.verrekend_met_document_id != document_id:
            raise OngeldigeInvoer("Weekstaat is al verrekend met een andere geboekte factuur")
        project = session.get(ProjectCache, (staat.project_id, staat.administratie_id))
        resultaat.append(_met_uren(session, staat, project.naam if project else None))
    return resultaat


# --- motor -------------------------------------------------------------------------------------


def tarieven_voor_veldwerker(
    session: Session, *, veldwerker: Gebruiker, koppeling: VeldwerkerCrediteur
) -> dict[uuid.UUID, Decimal | None]:
    """Leden + tarieven van een veldwerker-koppeling: ZZP'er = zichzelf mét het
    koppeling-uurtarief; detacheerder = zijn gekoppelde ZZP'ers mét het tarief per
    detacheerder↔zzp'er-koppeling (besluit 1)."""
    if veldwerker.rol == GebruikerRol.ZZPER:
        return {veldwerker.id: koppeling.uurtarief}
    if veldwerker.rol == GebruikerRol.DETACHEERDER:
        bureau_koppelingen = session.scalars(
            select(DetacheerderKoppeling).where(
                DetacheerderKoppeling.detacheerder_gebruiker_id == veldwerker.id
            )
        ).all()
        return {k.zzper_gebruiker_id: k.uurtarief for k in bureau_koppelingen}
    raise OngeldigeInvoer(
        "Veldwerker-koppeling hoort bij een ZZP'er of detacheerder — deze rol levert geen urenstaten"
    )


def vind_veldwerker_koppeling(
    session: Session, *, administratie_id: uuid.UUID, vendor_id: uuid.UUID
) -> VeldwerkerCrediteur | None:
    return session.scalars(
        select(VeldwerkerCrediteur).where(
            VeldwerkerCrediteur.administratie_id == administratie_id,
            VeldwerkerCrediteur.vendor_id == vendor_id,
        )
    ).one_or_none()


def bereken_match_in_sessie(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    weekstaat_ids: list[uuid.UUID] | None = None,
    factuur_uren: Decimal | None = None,
    factuur_bedrag: Decimal | None = None,
    vendor_id: uuid.UUID | None = None,
    factuurdatum: date | None = None,
) -> FactuurmatchData | None:
    """Bereken (of herbereken) de match en sla het resultaat op. Geeft None als de match niet
    van toepassing is: geen inkoopfactuur, geen boekvoorstel/crediteur, of de crediteur is aan
    geen veldwerker gekoppeld. `factuur_bedrag` default = som van de netto regelbedragen uit
    het opgeslagen boekvoorstel (fase 2 kan het veldvoorstel-bedrag meegeven). `vendor_id` +
    `factuurdatum` zijn fallbacks voor de run direct ná extractie, wanneer er nog géén
    opgeslagen Boekvoorstel is — het veldvoorstel-prefill levert ze dan aan (fase 2,
    app/uren/factuurmatch_pipeline.py); een opgeslagen voorstel wint altijd."""
    document = session.get(Document, document_id)
    if document is None:
        raise NietGevonden(f"Document {document_id} niet gevonden")
    if document.soort != DocumentSoort.INKOOPFACTUUR.value:
        return None

    voorstel = session.get(Boekvoorstel, document_id)
    if voorstel is not None and voorstel.vendor_id is not None:
        vendor_id = voorstel.vendor_id
    if voorstel is not None and voorstel.factuurdatum is not None:
        factuurdatum = voorstel.factuurdatum
    if vendor_id is None:
        return None
    koppeling = vind_veldwerker_koppeling(session, administratie_id=administratie_id, vendor_id=vendor_id)
    if koppeling is None:
        return None

    veldwerker = session.get(Gebruiker, koppeling.gebruiker_id)
    if veldwerker is None:
        raise NietGevonden("Veldwerker van de koppeling niet gevonden")

    tarieven = tarieven_voor_veldwerker(session, veldwerker=veldwerker, koppeling=koppeling)
    gebruiker_ids = list(tarieven)
    if weekstaat_ids is not None:
        staten = _expliciete_staten(
            session,
            administratie_id=administratie_id,
            document_id=document_id,
            weekstaat_ids=weekstaat_ids,
            gebruiker_ids=gebruiker_ids,
        )
    else:
        tot_en_met: tuple[int, int] | None = None
        if factuurdatum is not None:
            iso = factuurdatum.isocalendar()
            tot_en_met = (iso.year, iso.week)
        staten = (
            _kandidaat_staten(
                session,
                administratie_id=administratie_id,
                document_id=document_id,
                gebruiker_ids=gebruiker_ids,
                tot_en_met=tot_en_met,
            )
            if gebruiker_ids
            else []
        )

    namen = {
        g.id: g.naam
        for g in session.scalars(select(Gebruiker).where(Gebruiker.id.in_(gebruiker_ids))).all()
    } if gebruiker_ids else {}
    leden = [
        MatchLid(
            gebruiker_id=gid,
            naam=namen.get(gid),
            uren=sum((s.uren for s in staten if s.gebruiker_id == gid), Decimal("0")),
            uurtarief=tarieven[gid],
        )
        for gid in gebruiker_ids
    ]

    if factuur_bedrag is None:
        factuur_bedrag = _netto_som(session, document_id=document_id)

    berekening = bepaal_uitkomst(leden=leden, factuur_bedrag=factuur_bedrag, factuur_uren=factuur_uren)

    details = {
        "leden": [
            {
                "gebruiker_id": str(lid.gebruiker_id),
                "naam": lid.naam,
                "uren": str(lid.uren),
                "uurtarief": _als_str(lid.uurtarief),
                "bedrag": _als_str(lid.bedrag),
            }
            for lid in leden
        ],
        "staten": [
            {
                "weekstaat_id": str(s.weekstaat_id),
                "gebruiker_id": str(s.gebruiker_id),
                "project_naam": s.project_naam,
                "jaar": s.jaar,
                "weeknummer": s.weeknummer,
                "uren": str(s.uren),
            }
            for s in staten
        ],
        "tarief_ontbreekt_voor": [lid.naam or str(lid.gebruiker_id) for lid in leden if lid.uurtarief is None],
    }

    match = session.get(Factuurmatch, document_id)
    if match is None:
        match = Factuurmatch(document_id=document_id, administratie_id=administratie_id)
        session.add(match)
    match.veldwerker_gebruiker_id = veldwerker.id
    match.uitkomst = berekening.uitkomst.value
    match.staten_som_uren = berekening.staten_som_uren
    match.staten_som_bedrag = berekening.staten_som_bedrag
    match.factuur_bedrag = berekening.factuur_bedrag
    match.factuur_uren = berekening.factuur_uren
    match.verschil_bedrag = berekening.verschil_bedrag
    match.verschil_uren = berekening.verschil_uren
    match.tarief_ontbreekt = berekening.tarief_ontbreekt
    match.details = details
    match.berekend_op = datetime.now(UTC)
    # Een (her)berekening wist een eerdere "boeken ondanks afwijking"-bevestiging: nieuwe
    # cijfers = nieuwe beslissing (besluit 2, migratie 0058 — de boekpoort toetst hierop).
    match.afwijking_bevestigd_door = None
    match.afwijking_bevestigd_op = None
    session.flush()

    # Herberekening vervangt de staat-selectie integraal (geen residu van een eerdere run).
    session.execute(delete(FactuurmatchStaat).where(FactuurmatchStaat.document_id == document_id))
    for s in staten:
        session.add(
            FactuurmatchStaat(
                document_id=document_id, weekstaat_id=s.weekstaat_id, administratie_id=administratie_id
            )
        )
    session.flush()

    return FactuurmatchData(
        document_id=document_id,
        veldwerker_gebruiker_id=veldwerker.id,
        veldwerker_naam=veldwerker.naam,
        uitkomst=berekening.uitkomst.value,
        staten_som_uren=berekening.staten_som_uren,
        staten_som_bedrag=berekening.staten_som_bedrag,
        factuur_bedrag=berekening.factuur_bedrag,
        factuur_uren=berekening.factuur_uren,
        verschil_bedrag=berekening.verschil_bedrag,
        verschil_uren=berekening.verschil_uren,
        tarief_ontbreekt=berekening.tarief_ontbreekt,
        details=details,
        weekstaat_ids=[s.weekstaat_id for s in staten],
    )


def _netto_som(session: Session, *, document_id: uuid.UUID) -> Decimal | None:
    """Som van de netto regelbedragen van het opgeslagen boekvoorstel. Geen regels of een
    regel zonder netto-bedrag = geen vergelijkbaar factuurbedrag (None) — nooit half optellen."""
    nettos = session.scalars(
        select(BoekvoorstelRegel.netto_bedrag).where(BoekvoorstelRegel.document_id == document_id)
    ).all()
    if not nettos or any(n is None for n in nettos):
        return None
    return sum(nettos, Decimal("0"))


def bereken_match(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    weekstaat_ids: list[uuid.UUID] | None = None,
    factuur_uren: Decimal | None = None,
    factuur_bedrag: Decimal | None = None,
    vendor_id: uuid.UUID | None = None,
    factuurdatum: date | None = None,
) -> FactuurmatchData | None:
    """`actor_id` = wie de berekening triggert (pipeline = SYSTEEM_ACTOR_ID) — nodig omdat de
    lees-policy op platform.detacheerder_koppeling actor-gebonden is (0056/0057)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        return bereken_match_in_sessie(
            session,
            administratie_id=administratie_id,
            document_id=document_id,
            weekstaat_ids=weekstaat_ids,
            factuur_uren=factuur_uren,
            factuur_bedrag=factuur_bedrag,
            vendor_id=vendor_id,
            factuurdatum=factuurdatum,
        )


# --- verrekening bij boeken --------------------------------------------------------------------


def verreken_staten_in_sessie(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> list[uuid.UUID]:
    """Markeer de staten van de laatste berekening als verrekend met dit document — aan te
    roepen ín de boek-transactie (fase 2), zodat verrekening en boeking samen slagen of samen
    terugrollen. Idempotent: al-met-dit-document-verrekende staten blijven ongemoeid; een staat
    die intussen met een ánder document verrekend is = zichtbare fout (nooit stil dubbel)."""
    match = session.get(Factuurmatch, document_id)
    if match is None:
        raise NietGevonden(f"Geen factuurmatch voor document {document_id}")
    weekstaat_ids = session.scalars(
        select(FactuurmatchStaat.weekstaat_id).where(FactuurmatchStaat.document_id == document_id)
    ).all()
    verrekend: list[uuid.UUID] = []
    nu = datetime.now(UTC)
    for weekstaat_id in weekstaat_ids:
        staat = session.get(Weekstaat, weekstaat_id)
        if staat is None:
            raise NietGevonden(f"Weekstaat {weekstaat_id} niet gevonden")
        if staat.verrekend_met_document_id == document_id:
            continue
        if staat.verrekend_met_document_id is not None:
            raise OngeldigeInvoer("Weekstaat is al verrekend met een andere geboekte factuur")
        staat.verrekend_met_document_id = document_id
        staat.verrekend_op = nu
        verrekend.append(weekstaat_id)
    if verrekend:
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="factuurmatch",
            record_id=document_id,
            actie="staten_verrekend",
            correlatie_id=document_id,
            nieuwe_waarde={"weekstaat_ids": [str(w) for w in verrekend]},
            administratie_id=administratie_id,
        )
        session.flush()
    return verrekend


def verreken_staten(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID
) -> list[uuid.UUID]:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        return verreken_staten_in_sessie(
            session, administratie_id=administratie_id, document_id=document_id, actor_id=actor_id
        )
