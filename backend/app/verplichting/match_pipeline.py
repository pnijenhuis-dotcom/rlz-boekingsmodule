"""Glue rond de pure match-motor (`app/verplichting/match.py`): DB-feiten ophalen, de uitkomst in
`verplichting_match` verversen, het verbruik verrekenen ín de boek-transactie en terugdraaien bij
tegenboeken/storno.

Patroon = `app/uren/factuurmatch_pipeline.py`: post-commit, systeem-actor, NOOIT blokkerend — de
offerte-match is een signaal bovenop de normale flow (⑤: buiten offerte = oranje vlag, geen blokkade).
Geen AI, geen RLZ-/Odoo-calls.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.crediteur_kenmerk import btw_per_vendor
from app.documenten.models import Boekvoorstel, Document, DocumentGebeurtenis, DocumentSoort, DocumentStatus
from app.verplichting import match as match_motor
from app.verplichting.models import Verplichting, VerplichtingMatch

logger = logging.getLogger(__name__)

#: Statussen waarin een inkoopdocument nog "open werk" is — de teller/chip "buiten offerte" en de
#: herberekening kijken alleen daarnaar (zelfde definitie als de werkvoorraad-tellers).
#: `afgevoerd_duplicaat` (blok 3, fixrun 08-09) hoort erbij, net als afgewezen.
_TERMINALE_STATUSSEN = (
    DocumentStatus.VERWIJDERD,
    DocumentStatus.GESPLITST,
    DocumentStatus.SAMENGEVOEGD,
    DocumentStatus.AFGEWEZEN,
    DocumentStatus.AFGEVOERD_DUPLICAAT,
    DocumentStatus.NIET_TOEGEWEZEN,
)

#: Peter 18-09 (casus Bouwadvies "hij moet wel doortellen"): een gematchte factuur die NIET geboekt en NIET terminaal
#: is, is ONDERWEG en telt in het verbruik van de verplichting mee (ter accordering, klaar om te boeken, wordt geboekt,
#: boeken mislukt, in controle, vraag open, …). Eén definitie voor toets, reviewscherm en Inzicht › Verplichtingen.
ONDERWEG_UITGESLOTEN_STATUSSEN = (*_TERMINALE_STATUSSEN, DocumentStatus.GEBOEKT)


def telt_als_onderweg(status: DocumentStatus) -> bool:
    return status not in ONDERWEG_UITGESLOTEN_STATUSSEN


@dataclass(frozen=True)
class OnderwegStand:
    aantal: int = 0
    bedrag_excl: Decimal = Decimal("0.00")
    ter_accordering: int = 0


def vendor_sleutel(vendor_id: uuid.UUID | None, btw: dict[str, str]) -> str | None:
    """Crediteur-identiteit voor de match — identiek aan `duplicaat_afvoer._vendor_sleutel`:
    btw-nummer als bekend (dekt dubbele crediteuren in RLZ), anders de vendor zelf."""
    if vendor_id is None:
        return None
    nummer = btw.get(str(vendor_id))
    return f"btw:{nummer}" if nummer else f"vendor:{vendor_id}"


# --------------------------------------------------------------------------- feiten uit de DB


def _teksten_van(voorstel, veldvoorstel: dict | None) -> tuple[str, ...]:
    teksten: list[str] = []
    for waarde in (voorstel.referentie, voorstel.betalingskenmerk):
        if waarde:
            teksten.append(str(waarde))
    for regel in voorstel.regels:
        if regel.omschrijving:
            teksten.append(str(regel.omschrijving))
    if veldvoorstel:
        for sleutel in ("factuurnummer", "betalingskenmerk"):
            waarde = veldvoorstel.get(sleutel)
            if isinstance(waarde, str) and waarde.strip():
                teksten.append(waarde)
        for regel in veldvoorstel.get("regels") or []:
            if isinstance(regel, dict) and isinstance(regel.get("omschrijving"), str):
                teksten.append(regel["omschrijving"])
    return tuple(teksten)


def _bedrag_excl_van(voorstel, veldvoorstel: dict | None) -> Decimal | None:
    """Σ netto_bedrag van het (opgeslagen óf prefill) boekvoorstel; geen regels → veldvoorstel
    `totaal_excl`; niets → None (niet toetsbaar). Geld in CODE, nooit AI-rekenwerk."""
    netto = [r.netto_bedrag for r in voorstel.regels]
    if netto and all(bedrag is not None for bedrag in netto):
        return sum(netto, Decimal(0)).quantize(Decimal("0.01"))
    if veldvoorstel:
        from app.extractie.controle import parse_bedrag

        ruw = veldvoorstel.get("totaal_excl")
        bedrag = parse_bedrag(ruw if isinstance(ruw, str) else None)
        if bedrag is not None:
            return bedrag.quantize(Decimal("0.01"))
    return None


def _project_sleutel(voorstel) -> uuid.UUID | None:
    """De ENE distinct project_id over de regels; 0 of > 1 distinct = geen project-sleutel."""
    projecten = {r.project_id for r in voorstel.regels if r.project_id is not None}
    return next(iter(projecten)) if len(projecten) == 1 else None


def _laatste_veldvoorstel(session: Session, document_id: uuid.UUID) -> dict | None:
    laatste: dict | None = None
    for gebeurtenis in session.scalars(
        select(DocumentGebeurtenis)
        .where(DocumentGebeurtenis.document_id == document_id, DocumentGebeurtenis.detail.has_key("veldvoorstel"))
        .order_by(DocumentGebeurtenis.tijdstip)
    ):
        laatste = gebeurtenis.detail["veldvoorstel"]
    return laatste


def _aantal_gematcht_per_verplichting(
    session: Session, *, administratie_id: uuid.UUID, behalve_document_id: uuid.UUID | None
) -> dict[uuid.UUID, int]:
    """Peter 15-09 (termijnen): per verplichting het aantal ándere facturen dat er al aan gematcht is
    (binnen/buiten). Sinds 18-09 tellen alleen geboekte én onderweg-facturen als termijn — een afgewezen/verwijderde
    factuur is geen termijn meer (zelfde statusdefinitie als het onderweg-verbruik)."""
    rijen = session.execute(
        select(VerplichtingMatch.verplichting_document_id, func.count())
        .join(Document, Document.id == VerplichtingMatch.document_id)
        .where(
            VerplichtingMatch.administratie_id == administratie_id,
            VerplichtingMatch.uitkomst.in_([match_motor.BINNEN, match_motor.BUITEN]),
            VerplichtingMatch.verplichting_document_id.is_not(None),
            Document.status.notin_(_TERMINALE_STATUSSEN),
            *([VerplichtingMatch.document_id != behalve_document_id] if behalve_document_id is not None else []),
        )
        .group_by(VerplichtingMatch.verplichting_document_id)
    ).all()
    return {vid: int(n) for vid, n in rijen}


def onderweg_per_verplichting(
    session: Session, *, administratie_id: uuid.UUID, behalve_document_id: uuid.UUID | None = None
) -> dict[uuid.UUID, OnderwegStand]:
    """Peter 18-09: per verplichting (aantal, Σ bedrag excl., waarvan ter accordering) van de gematchte facturen
    (binnen/buiten) die nog niet geboekt/verrekend en niet terminaal zijn — het eigen document uitgezonderd. Eén
    query, nooit opgeslagen: de stand volgt de documentstatussen op het moment van de toets."""
    rijen = session.execute(
        select(
            VerplichtingMatch.verplichting_document_id,
            func.count(),
            func.coalesce(func.sum(VerplichtingMatch.bedrag_excl), 0),
            func.count().filter(Document.status == DocumentStatus.TER_ACCORDERING),
        )
        .join(Document, Document.id == VerplichtingMatch.document_id)
        .where(
            VerplichtingMatch.administratie_id == administratie_id,
            VerplichtingMatch.uitkomst.in_([match_motor.BINNEN, match_motor.BUITEN]),
            VerplichtingMatch.verplichting_document_id.is_not(None),
            VerplichtingMatch.verrekend_op.is_(None),
            Document.status.notin_(ONDERWEG_UITGESLOTEN_STATUSSEN),
            *([VerplichtingMatch.document_id != behalve_document_id] if behalve_document_id is not None else []),
        )
        .group_by(VerplichtingMatch.verplichting_document_id)
    ).all()
    return {
        vid: OnderwegStand(
            aantal=int(n), bedrag_excl=Decimal(som or 0).quantize(Decimal("0.01")), ter_accordering=int(ter_acc or 0)
        )
        for vid, n, som, ter_acc in rijen
    }


def lopende_kandidaten(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    sleutel: str,
    btw: dict[str, str],
    document_id: uuid.UUID | None = None,
) -> list[match_motor.Kandidaat]:
    """Lopende verplichtingen (document GEACCORDEERD, niet vervallen) van dezelfde crediteur-
    identiteit. De geldigheidstoets t.o.v. de factuurdatum zit in de pure motor. `document_id` = de factuur zelf
    (telt niet mee in `aantal_gematcht`)."""
    rijen = session.execute(
        select(Verplichting, Document.status)
        .join(Document, Document.id == Verplichting.document_id)
        .where(
            Verplichting.administratie_id == administratie_id,
            Verplichting.vervallen_op.is_(None),
            Document.status == DocumentStatus.GEACCORDEERD,
        )
    ).all()
    from app.crediteuren.voorkeur import verliezers as verliezers_kaart  # B13 07-09: verliezer telt als voorkeur

    kaart = verliezers_kaart(session, administratie_id=administratie_id)
    gematcht = _aantal_gematcht_per_verplichting(
        session, administratie_id=administratie_id, behalve_document_id=document_id
    )
    onderweg = onderweg_per_verplichting(session, administratie_id=administratie_id, behalve_document_id=document_id)
    kandidaten: list[match_motor.Kandidaat] = []
    for rij, _status in rijen:
        if vendor_sleutel(kaart.get(rij.vendor_id, rij.vendor_id), btw) != sleutel:
            continue
        stand = onderweg.get(rij.document_id, OnderwegStand())
        kandidaten.append(
            match_motor.Kandidaat(
                document_id=rij.document_id,
                project_id=rij.project_id,
                offertenummer=rij.offertenummer,
                soort_label=rij.soort_label,
                goedgekeurd_bedrag_excl=rij.goedgekeurd_bedrag_excl,
                verbruikt_bedrag_excl=Decimal(rij.verbruikt_bedrag_excl or 0),
                geldig_tot=rij.geldig_tot,
                aantal_gematcht=gematcht.get(rij.document_id, 0),
                onderweg_bedrag_excl=stand.bedrag_excl,
                onderweg_aantal=stand.aantal,
                onderweg_ter_accordering=stand.ter_accordering,
            )
        )
    return sorted(kandidaten, key=lambda k: (k.offertenummer or "", str(k.document_id)))


#: Statussen van een verplichting-document die "nog niet goedgekeurd" betekenen (concept/controle/accordering);
#: terminale statussen (afgewezen, verwijderd, …) zijn géén wachtende verplichting.
_WACHT_STATUS_LABEL = {
    DocumentStatus.ONTVANGEN: "nog in behandeling",
    DocumentStatus.EXTRACTIE_WACHTRIJ: "nog in behandeling",
    DocumentStatus.EXTRACTIE_BEZIG: "nog in behandeling",
    DocumentStatus.TE_CONTROLEREN: "nog niet goedgekeurd (te controleren)",
    DocumentStatus.KLAAR_OM_TE_BOEKEN: "nog niet goedgekeurd (klaar, nog niet aangeboden)",
    DocumentStatus.TER_ACCORDERING: "nog niet goedgekeurd (wacht op accordering)",
}


def wachtende_verplichtingen(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    sleutel: str,
    vendor_id: uuid.UUID | None,
    btw: dict[str, str],
) -> list[match_motor.Wachtende]:
    """Peter 15-09 (casus Olieman: offerte wachtte op één accordeur → stil `geen_verplichting`): verplichtingen van deze
    leverancier die NIET als kandidaat tellen — (1) zelfde crediteur-identiteit maar nog niet goedgekeurd (status
    ≠ geaccordeerd, niet vervallen, niet terminaal), (2) een niet-vervallen verplichting op een ANDER crediteurrecord
    met dezelfde naam (dubbele crediteur zonder btw-nummer)."""
    from app.bank.matchmotor import naam_komt_overeen  # puur: dezelfde naam-tokenregel als de bankmatch
    from app.crediteuren.voorkeur import verliezers as verliezers_kaart
    from app.sync.models import VendorCache

    kaart = verliezers_kaart(session, administratie_id=administratie_id)
    rijen = session.execute(
        select(Verplichting, Document.status)
        .join(Document, Document.id == Verplichting.document_id)
        .where(
            Verplichting.administratie_id == administratie_id,
            Verplichting.vervallen_op.is_(None),
            Document.status.notin_(_TERMINALE_STATUSSEN),
        )
    ).all()
    if not rijen:
        return []
    namen = {
        rij.id: rij.naam
        for rij in session.scalars(select(VendorCache).where(VendorCache.administratie_id == administratie_id))
    }
    eigen_naam = namen.get(vendor_id) if vendor_id is not None else None
    uit: list[match_motor.Wachtende] = []
    for rij, status in rijen:
        rij_sleutel = vendor_sleutel(kaart.get(rij.vendor_id, rij.vendor_id), btw)
        if rij_sleutel == sleutel:
            if status == DocumentStatus.GEACCORDEERD:
                continue  # dat is een gewone kandidaat
            uit.append(
                match_motor.Wachtende(
                    document_id=rij.document_id,
                    reden_code=match_motor.WACHT_NIET_GOEDGEKEURD,
                    reden=_WACHT_STATUS_LABEL.get(status, f"nog niet goedgekeurd ({status.value.replace('_', ' ')})"),
                    offertenummer=rij.offertenummer,
                )
            )
        elif eigen_naam and rij.vendor_id is not None and naam_komt_overeen(eigen_naam, namen.get(rij.vendor_id)):
            uit.append(
                match_motor.Wachtende(
                    document_id=rij.document_id,
                    reden_code=match_motor.WACHT_ANDERE_CREDITEUR,
                    reden=f"staat op een ander crediteurrecord ({namen.get(rij.vendor_id)}) — dubbele crediteur?",
                    offertenummer=rij.offertenummer,
                )
            )
    return sorted(uit, key=lambda w: (w.offertenummer or "", str(w.document_id)))


def _onthouden_koppeling(
    session: Session, *, administratie_id: uuid.UUID, document_id: uuid.UUID, project_id: uuid.UUID | None
) -> uuid.UUID | None:
    """De LAATSTE handmatige koppeling voor dezelfde crediteur + project (②: "daarna onthouden").
    Sleutel = het project van de verplichting zelf; de crediteur volgt uit de kandidatenlijst
    (de aanroeper geeft alleen kandidaten van dezelfde crediteur mee)."""
    if project_id is None:
        return None
    rijen = session.execute(
        select(VerplichtingMatch.verplichting_document_id, VerplichtingMatch.berekend_op)
        .join(Verplichting, Verplichting.document_id == VerplichtingMatch.verplichting_document_id)
        .where(
            VerplichtingMatch.administratie_id == administratie_id,
            VerplichtingMatch.handmatig_gekoppeld.is_(True),
            VerplichtingMatch.document_id != document_id,
            Verplichting.project_id == project_id,
        )
        .order_by(VerplichtingMatch.berekend_op.desc())
    ).all()
    return rijen[0][0] if rijen else None


# --------------------------------------------------------------------------- herberekening


def bereken_match(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> match_motor.MatchUitkomst | None:
    """Berekent + schrijft de matchstand voor één INKOOPdocument. None = niet van toepassing
    (ander documentsoort of document weg). Eigen transactie(s), systeem-actor."""
    from app.documenten.boekvoorstel import haal_boekvoorstel_op

    with scoped_session(administratie_id) as session:
        document = session.get(Document, document_id)
        if document is None or document.soort != DocumentSoort.INKOOPFACTUUR.value:
            return None
        if document.status in _TERMINALE_STATUSSEN:
            return None
        # BEVROREN zodra verrekend (⑥ "gematchte facturen blijven ongemoeid"): de match van een
        # GEBOEKTE factuur is de stand op het boekmoment — die mag niet meer verschuiven als de
        # verplichting later vervalt of een tweede offerte erbij komt. Terugdraaien gebeurt
        # uitsluitend via tegenboeken/storno (`draai_verbruik_terug_in_sessie`), dat zet
        # `verrekend_op` op NULL en dán rekent de volgende run weer mee.
        bevroren = session.get(VerplichtingMatch, document_id)
        if bevroren is not None and bevroren.verrekend_op is not None:
            return match_motor.MatchUitkomst(
                uitkomst=bevroren.uitkomst,
                verplichting_document_id=bevroren.verplichting_document_id,
                bedrag_excl=bevroren.bedrag_excl,
                verbruik_voor=bevroren.verbruik_voor,
                verbruik_na=bevroren.verbruik_na,
                overschrijding_excl=bevroren.overschrijding_excl,
                melding=str((bevroren.details or {}).get("melding") or ""),
                grond=(bevroren.details or {}).get("grond"),
                details=dict(bevroren.details or {}),
            )
        veldvoorstel = _laatste_veldvoorstel(session, document_id)
        btw = btw_per_vendor(session, administratie_id=administratie_id)

    voorstel = haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
    sleutel = vendor_sleutel(voorstel.vendor_id, btw)
    feiten = match_motor.FactuurFeiten(
        document_id=document_id,
        vendor_sleutel=sleutel,
        project_id=_project_sleutel(voorstel),
        bedrag_excl=_bedrag_excl_van(voorstel, veldvoorstel),
        factuurdatum=voorstel.factuurdatum,
        teksten=_teksten_van(voorstel, veldvoorstel),
    )

    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        bestaand = session.get(VerplichtingMatch, document_id)
        kandidaten = (
            lopende_kandidaten(
                session, administratie_id=administratie_id, sleutel=sleutel, btw=btw, document_id=document_id
            )
            if sleutel
            else []
        )
        wachtende = (
            wachtende_verplichtingen(
                session, administratie_id=administratie_id, sleutel=sleutel, vendor_id=voorstel.vendor_id, btw=btw
            )
            if sleutel
            else []
        )
        handmatig = bestaand.verplichting_document_id if bestaand is not None and bestaand.handmatig_gekoppeld else None
        # Al verrekend (geboekt) → het eigen bedrag zit al in verbruikt_bedrag_excl.
        eigen_verrekend = (
            Decimal(bestaand.bedrag_excl or 0) if bestaand is not None and bestaand.verrekend_op is not None else None
        )
        onthouden = _onthouden_koppeling(
            session, administratie_id=administratie_id, document_id=document_id, project_id=feiten.project_id
        )
        uitkomst = match_motor.bepaal_match(
            match_motor.FactuurFeiten(
                document_id=feiten.document_id,
                vendor_sleutel=feiten.vendor_sleutel,
                project_id=feiten.project_id,
                bedrag_excl=feiten.bedrag_excl,
                factuurdatum=feiten.factuurdatum,
                teksten=feiten.teksten,
                eigen_verrekend=eigen_verrekend,
            ),
            kandidaten,
            handmatig_gekoppeld_id=handmatig,
            onthouden_id=onthouden,
            wachtende=wachtende,
        )
        _schrijf_match(
            session,
            administratie_id=administratie_id,
            document_id=document_id,
            uitkomst=uitkomst,
            bestaand=bestaand,
        )
    return uitkomst


def _schrijf_match(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    uitkomst: match_motor.MatchUitkomst,
    bestaand: VerplichtingMatch | None,
) -> VerplichtingMatch:
    rij = bestaand
    if rij is None:
        rij = VerplichtingMatch(document_id=document_id, administratie_id=administratie_id, uitkomst=uitkomst.uitkomst)
        session.add(rij)
    rij.uitkomst = uitkomst.uitkomst
    # Een handmatige koppeling die niet meer lopend is (vervallen/afgewezen) verliest haar
    # koppeling: de motor koos dan een andere of geen kandidaat — nooit stil aan een dode
    # verplichting blijven hangen.
    if uitkomst.grond != "handmatig" and rij.handmatig_gekoppeld:
        rij.handmatig_gekoppeld = False
    rij.verplichting_document_id = uitkomst.verplichting_document_id
    rij.bedrag_excl = uitkomst.bedrag_excl
    rij.verbruik_voor = uitkomst.verbruik_voor
    rij.verbruik_na = uitkomst.verbruik_na
    rij.overschrijding_excl = uitkomst.overschrijding_excl
    rij.berekend_op = datetime.now(UTC)
    rij.details = {
        "melding": uitkomst.melding,
        "grond": uitkomst.grond,
        "kandidaten": [str(k) for k in uitkomst.kandidaat_ids],
        **uitkomst.details,
    }
    return rij


def draai_match_stil(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> None:
    """Post-commit-trigger (ná extractie, ná voorstel-opslag, ná koppelen): elke fout is een
    gelogde waarschuwing — de match is signalering, nooit een blokkade van de verwerking."""
    try:
        bereken_match(administratie_id=administratie_id, document_id=document_id)
    except Exception:  # noqa: BLE001 — signalering, nooit een blokkade
        logger.exception("Verplichting-match mislukt voor document %s", document_id)


def herbereken_na_verplichting_wijziging(*, administratie_id: uuid.UUID, verplichting_document_id: uuid.UUID) -> int:
    """Ná geaccordeerd / afgewezen / vervallen van een verplichting: de OPEN inkoopdocumenten van
    dezelfde crediteur in deze administratie opnieuw toetsen (⑥ — vervallen stopt nieuwe matches,
    al verrekende facturen blijven ongemoeid: hun verbruik blijft staan).

    Retourneert het aantal herberekende documenten. Stil: fouten worden gelogd."""
    with scoped_session(administratie_id) as session:
        verplichting = session.get(Verplichting, verplichting_document_id)
        if verplichting is None:
            return 0
        from app.crediteuren.voorkeur import voorkeur_van  # B13 07-09

        btw = btw_per_vendor(session, administratie_id=administratie_id)
        sleutel = vendor_sleutel(
            voorkeur_van(session, administratie_id=administratie_id, vendor_id=verplichting.vendor_id), btw
        )
        if sleutel is None:
            return 0
        kandidaat_documenten = [
            rij.id
            for rij in session.scalars(
                select(Document).where(
                    Document.administratie_id == administratie_id,
                    Document.soort == DocumentSoort.INKOOPFACTUUR.value,
                    Document.status.notin_(_TERMINALE_STATUSSEN),
                )
            )
        ]
    aantal = 0
    for document_id in kandidaat_documenten:
        try:
            uitkomst = bereken_match(administratie_id=administratie_id, document_id=document_id)
            if uitkomst is not None:
                aantal += 1
                # Peter 15-09 (aanvulling: offerte wacht op één accordeur, factuur wordt nu geboekt): een al GEBOEKTE
                # factuur die ná de goedkeuring alsnog binnen/buiten matcht, wordt achteraf verrekend — verbruik
                # bijgeschreven, tijdlijnregel + audit. Meerduidig (meerdere_kandidaten) = niet koppelen, melden.
                if uitkomst.uitkomst in (match_motor.BINNEN, match_motor.BUITEN):
                    _verreken_achteraf(administratie_id=administratie_id, document_id=document_id, uitkomst=uitkomst)
        except Exception:  # noqa: BLE001 — één document mag de rest niet stoppen
            logger.exception("Verplichting-herberekening mislukt voor document %s", document_id)
    return aantal


def _verreken_achteraf(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, uitkomst: match_motor.MatchUitkomst
) -> bool:
    """Alleen voor een GEBOEKT document waarvan de match nog niet verrekend is: verbruik bijschrijven
    (`verreken_in_sessie`, systeem-actor), tijdlijnregel "achteraf gekoppeld aan offerte …" en audit
    `verplichting_achteraf_gekoppeld`. → True als er verrekend is."""
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        document = session.get(Document, document_id)
        rij = session.get(VerplichtingMatch, document_id)
        if document is None or rij is None or document.status != DocumentStatus.GEBOEKT or rij.verrekend_op is not None:
            return False
        verreken_in_sessie(
            session, administratie_id=administratie_id, document_id=document_id, actor_id=SYSTEEM_ACTOR_ID
        )
        if rij.verrekend_op is None:
            return False
        verplichting = session.get(Verplichting, rij.verplichting_document_id) if rij.verplichting_document_id else None
        nummer = (verplichting.offertenummer if verplichting is not None else None) or "zonder nummer"
        termijn = (rij.details or {}).get("termijn")
        reden = (
            f"achteraf gekoppeld aan offerte {nummer}"
            + (f" ({termijn}e termijn)" if termijn else "")
            + f" — {uitkomst.uitkomst}, verbruik ná deze factuur {rij.verbruik_na} (offerte later goedgekeurd)"
        )
        session.add(
            DocumentGebeurtenis(
                id=uuid.uuid4(),
                document_id=document_id,
                van_status=document.status,
                naar_status=document.status,
                actor_id=SYSTEEM_ACTOR_ID,
                detail={
                    "verplichting_achteraf_gekoppeld": {
                        "verplichting_document_id": str(rij.verplichting_document_id),
                        "uitkomst": uitkomst.uitkomst,
                        "termijn": termijn,
                    },
                    "reden": reden,
                },
            )
        )
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="boekhouding",
            tabel="verplichting_match",
            record_id=document_id,
            actie="verplichting_achteraf_gekoppeld",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "verplichting_document_id": str(rij.verplichting_document_id),
                "uitkomst": uitkomst.uitkomst,
                "bedrag_excl": str(rij.bedrag_excl),
                "verbruik_na": str(rij.verbruik_na),
                "termijn": termijn,
            },
            administratie_id=administratie_id,
        )
        return True


def herbereken_na_verplichting_wijziging_stil(
    *, administratie_id: uuid.UUID, verplichting_document_id: uuid.UUID
) -> None:
    try:
        herbereken_na_verplichting_wijziging(
            administratie_id=administratie_id, verplichting_document_id=verplichting_document_id
        )
    except Exception:  # noqa: BLE001 — signalering, nooit een blokkade
        logger.exception("Verplichting-herberekening mislukt voor verplichting %s", verplichting_document_id)


# --------------------------------------------------------------------------- statuswissel → siblings herberekenen

_STATUSWISSEL_SLEUTEL = "verplichting_statuswissels"


def registreer_statuswissel(session: Session, *, document: Document, van: DocumentStatus, naar: DocumentStatus) -> bool:
    """Peter 18-09 (volgorde-effect): aangeroepen vanuit `documenten.service._schrijf_overgang` ÍN de transactie.
    Verandert deze overgang of het document als ONDERWEG telt (bv. te_controleren → afgewezen, ter_accordering →
    geboekt, verwijderd → hersteld), en heeft het document een binnen/buiten-match, dan wordt de herberekening van de
    ándere open documenten op dezelfde verplichting klaargezet voor NÁ de commit (`after_commit` op deze sessie —
    de herberekening opent eigen transacties en mag nooit de statusovergang zelf blokkeren). → True = geregistreerd."""
    if document.soort != DocumentSoort.INKOOPFACTUUR.value or telt_als_onderweg(van) == telt_als_onderweg(naar):
        return False
    rij = session.get(VerplichtingMatch, document.id)
    if rij is None or rij.verplichting_document_id is None:
        return False
    if rij.uitkomst not in (match_motor.BINNEN, match_motor.BUITEN):
        return False
    wachtrij: list[dict] = session.info.setdefault(_STATUSWISSEL_SLEUTEL, [])
    if not wachtrij:
        event.listen(session, "after_commit", _na_commit_statuswissels)
    wachtrij.append(
        {
            "administratie_id": document.administratie_id,
            "document_id": document.id,
            "verplichting_document_id": rij.verplichting_document_id,
            "van": van.value,
            "naar": naar.value,
        }
    )
    return True


def _na_commit_statuswissels(session: Session) -> None:
    wachtrij = session.info.pop(_STATUSWISSEL_SLEUTEL, None) or []
    for item in wachtrij:
        try:
            herbereken_na_statuswissel(
                administratie_id=item["administratie_id"],
                document_id=item["document_id"],
                verplichting_document_id=item["verplichting_document_id"],
                van=item["van"],
                naar=item["naar"],
            )
        except Exception:  # noqa: BLE001 — signalering, nooit een blokkade
            logger.exception("Verplichting-herberekening ná statuswissel mislukt voor document %s", item["document_id"])


def herbereken_na_statuswissel(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    verplichting_document_id: uuid.UUID,
    van: str,
    naar: str,
) -> int:
    """Herbereken de match van de ÁNDERE open (niet-terminale, niet-geboekte) inkoopdocumenten op dezelfde
    verplichting; wijzigt uitkomst of verbruik-ná, dan komt er een tijdlijnregel op dát document ("offerte-toets
    herberekend: buiten → binnen — … (aanleiding: factuur ‹ref› afgewezen)") mét systeem-actor — nooit stil.
    Retourneert het aantal documenten waarvan de stand veranderde."""
    with scoped_session(administratie_id) as session:
        aanleiding_ref = session.scalar(select(Boekvoorstel.referentie).where(Boekvoorstel.document_id == document_id))
        siblings = [
            (rij.document_id, rij.uitkomst, rij.verbruik_na)
            for rij in session.scalars(
                select(VerplichtingMatch)
                .join(Document, Document.id == VerplichtingMatch.document_id)
                .where(
                    VerplichtingMatch.administratie_id == administratie_id,
                    VerplichtingMatch.verplichting_document_id == verplichting_document_id,
                    VerplichtingMatch.document_id != document_id,
                    VerplichtingMatch.verrekend_op.is_(None),
                    Document.status.notin_(ONDERWEG_UITGESLOTEN_STATUSSEN),
                )
            )
        ]
    gewijzigd = 0
    aanleiding = f"factuur {aanleiding_ref or document_id} {naar.replace('_', ' ')} (was {van.replace('_', ' ')})"
    for sibling_id, oud_uitkomst, oud_na in siblings:
        try:
            nieuw = bereken_match(administratie_id=administratie_id, document_id=sibling_id)
        except Exception:  # noqa: BLE001 — één document mag de rest niet stoppen
            logger.exception("Verplichting-herberekening (statuswissel) mislukt voor document %s", sibling_id)
            continue
        if nieuw is None:
            continue
        oud_na_dec = Decimal(oud_na).quantize(Decimal("0.01")) if oud_na is not None else None
        if nieuw.uitkomst == oud_uitkomst and nieuw.verbruik_na == oud_na_dec:
            continue
        gewijzigd += 1
        _schrijf_herberekend_tijdlijn(
            administratie_id=administratie_id,
            document_id=sibling_id,
            oud_uitkomst=oud_uitkomst,
            nieuw=nieuw,
            aanleiding=aanleiding,
        )
    return gewijzigd


def _schrijf_herberekend_tijdlijn(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    oud_uitkomst: str,
    nieuw: match_motor.MatchUitkomst,
    aanleiding: str,
) -> None:
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        document = session.get(Document, document_id)
        if document is None:
            return
        reden = (
            f"offerte-toets herberekend: {oud_uitkomst.replace('_', ' ')} → {nieuw.uitkomst.replace('_', ' ')} — "
            f"verbruik ná deze factuur {nieuw.verbruik_na} (aanleiding: {aanleiding})"
        )
        session.add(
            DocumentGebeurtenis(
                id=uuid.uuid4(),
                document_id=document_id,
                van_status=document.status,
                naar_status=document.status,
                actor_id=SYSTEEM_ACTOR_ID,
                detail={
                    "verplichting_match_herberekend": {
                        "van_uitkomst": oud_uitkomst,
                        "naar_uitkomst": nieuw.uitkomst,
                        "verbruik_na": str(nieuw.verbruik_na),
                        "verplichting_document_id": str(nieuw.verplichting_document_id),
                    },
                    "reden": reden,
                },
            )
        )
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="boekhouding",
            tabel="verplichting_match",
            record_id=document_id,
            actie="verplichting_match_herberekend",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"uitkomst": oud_uitkomst},
            nieuwe_waarde={"uitkomst": nieuw.uitkomst, "verbruik_na": str(nieuw.verbruik_na), "aanleiding": aanleiding},
            administratie_id=administratie_id,
        )


# --------------------------------------------------------------------------- verbruik (geld!)


def verreken_in_sessie(
    session: Session, *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID
) -> None:
    """ÍN de boek-transactie (`app/documenten/boeken.py`), ná een geslaagde adapter-boeking: het
    bedrag van deze factuur bij het verbruik van de gematchte verplichting optellen en de match als
    verrekend markeren — samen met de GEBOEKT-overgang, of samen niet. Idempotent: een al
    verrekende match doet niets (herboeking ná tegenboeken verrekent opnieuw, want het terugdraaien
    zette `verrekend_op` op NULL)."""
    rij = session.get(VerplichtingMatch, document_id)
    if rij is None or rij.verrekend_op is not None:
        return
    if rij.uitkomst not in (match_motor.BINNEN, match_motor.BUITEN) or rij.verplichting_document_id is None:
        return
    bedrag = Decimal(rij.bedrag_excl or 0)
    if bedrag == 0:
        return
    verplichting = session.get(Verplichting, rij.verplichting_document_id)
    if verplichting is None:
        return
    oud = Decimal(verplichting.verbruikt_bedrag_excl or 0)
    nieuw = (oud + bedrag).quantize(Decimal("0.01"))
    verplichting.verbruikt_bedrag_excl = nieuw
    rij.verrekend_op = datetime.now(UTC)
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="verplichting",
        record_id=verplichting.document_id,
        actie="verplichting_verbruik_bijgewerkt",
        correlatie_id=uuid.uuid4(),
        oude_waarde={"verbruikt_bedrag_excl": str(oud)},
        nieuwe_waarde={
            "verbruikt_bedrag_excl": str(nieuw),
            "document_id": str(document_id),
            "bedrag_excl": str(bedrag),
            "uitkomst": rij.uitkomst,
        },
        administratie_id=administratie_id,
    )


def draai_verbruik_terug_in_sessie(
    session: Session, *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, reden: str
) -> None:
    """Tegenboeken (volledig én "tegenboeken én opnieuw boeken") en storno: het verbruik van deze
    factuur van de verplichting AFhalen en de match op niet-verrekend zetten, zodat een herboeking
    opnieuw verrekent. Verbruik wordt nooit negatief (clamp + audit-waarschuwing)."""
    rij = session.get(VerplichtingMatch, document_id)
    if rij is None or rij.verrekend_op is None or rij.verplichting_document_id is None:
        return
    bedrag = Decimal(rij.bedrag_excl or 0)
    verplichting = session.get(Verplichting, rij.verplichting_document_id)
    if verplichting is None:
        return
    oud = Decimal(verplichting.verbruikt_bedrag_excl or 0)
    ruw = (oud - bedrag).quantize(Decimal("0.01"))
    geclampt = ruw < 0
    nieuw = Decimal("0.00") if geclampt else ruw
    if geclampt:
        logger.warning(
            "Verplichting-verbruik zou negatief worden (verplichting %s, document %s: %s − %s) — geclampt op 0",
            verplichting.document_id,
            document_id,
            oud,
            bedrag,
        )
    verplichting.verbruikt_bedrag_excl = nieuw
    rij.verrekend_op = None
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="verplichting",
        record_id=verplichting.document_id,
        actie="verplichting_verbruik_teruggedraaid",
        correlatie_id=uuid.uuid4(),
        oude_waarde={"verbruikt_bedrag_excl": str(oud)},
        nieuwe_waarde={
            "verbruikt_bedrag_excl": str(nieuw),
            "document_id": str(document_id),
            "bedrag_excl": str(bedrag),
            "reden": reden,
            **({"geclampt_op_nul": True} if geclampt else {}),
        },
        administratie_id=administratie_id,
    )


# --------------------------------------------------------------------------- leesroutes (lijst/teller)


@dataclass(frozen=True)
class MatchKort:
    """Chipdata voor de documentenlijst (bulk, geen N+1)."""

    uitkomst: str
    overschrijding_excl: Decimal | None
    offertenummer: str | None


def matches_voor_documenten(session: Session, document_ids: list[uuid.UUID]) -> dict[uuid.UUID, MatchKort]:
    if not document_ids:
        return {}
    rijen = session.execute(
        select(VerplichtingMatch, Verplichting.offertenummer)
        .join(
            Verplichting,
            Verplichting.document_id == VerplichtingMatch.verplichting_document_id,
            isouter=True,
        )
        .where(VerplichtingMatch.document_id.in_(document_ids))
    ).all()
    return {
        rij.document_id: MatchKort(
            uitkomst=rij.uitkomst, overschrijding_excl=rij.overschrijding_excl, offertenummer=offertenummer
        )
        for rij, offertenummer in rijen
    }


def tel_buiten_offerte(session: Session, administratie_id: uuid.UUID) -> int:
    """Werkvoorraad-signaalteller "buiten offerte" (⑤, duplicaat-patroon): open inkoopdocumenten met
    uitkomst `buiten` óf `geen_match`. Signaal, geen status — telt niet mee in `heeft_openstaand_werk`."""
    return (
        session.scalar(
            select(func.count())
            .select_from(VerplichtingMatch)
            .join(Document, Document.id == VerplichtingMatch.document_id)
            .where(
                VerplichtingMatch.administratie_id == administratie_id,
                VerplichtingMatch.uitkomst.in_(list(match_motor.TELT_ALS_BUITEN_OFFERTE)),
                Document.status.notin_([*_TERMINALE_STATUSSEN, DocumentStatus.GEBOEKT]),
            )
        )
        or 0
    )
