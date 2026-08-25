"""Materiaalmatch (steigerbouw-run D6, besluit Peter 24-08: model aantal × huurperiode per item).

Inkoopfacturen van een gekoppelde verhuur-crediteur (`MateriaalLeverancier.vendor_id` =
`Boekvoorstel.vendor_id`) worden per project getoetst tegen de geregistreerde leveringen/
huurperiodes (app/materiaal/service.py::materiaalstand_in_sessie). Deterministisch, geen AI in
de vergelijking:

- Factuurregels = het laatste AI-veldvoorstel (omschrijving + hoeveelheid per regel; dezelfde
  bron als `factuur_uren` in de urenmatch). Elke regel wordt op naam gekoppeld aan een
  catalogusproduct van de leverancier (genormaliseerde tekst: het product met de langste
  naam die in de regelomschrijving voorkomt, of andersom). Niet te koppelen = 'onbekend'
  (gemeld, telt niet als afwijking).
- Verwacht per product = ofwel het AANTAL op locatie t/m de factuurdatum, ofwel de
  HUUR-EENHEDEN (Σ aantal × dagen / 7, item-weken) — een huurfactuur zet de hoeveelheid soms
  als stuks en soms als stuks×weken; de regel is 'match' als de hoeveelheid met één van beide
  sluit (tolerantie 1 % of 0,5), en de details melden welke basis paste.
- Uitkomst: geen leverancier-koppeling → geen match-rij; geen project/leveringen/regels →
  `niet_toetsbaar`; ≥ 1 afwijkende regel → `afwijking`; anders `match`. Zelfde vlag-patroon
  als de urenmatch (besluit 3): signaal + teller, boeken alleen mét expliciete bevestiging
  ("geboekt ondanks materiaal-afwijking", persistent op de rij, herberekening wist 'm).

Project: uit de boekvoorstel-regels (`project_id`), anders het enige project met leveringen
van deze leverancier; meerdere kandidaten zonder projectkeuze = niet toetsbaar (nooit gokken)."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.models import Boekvoorstel, BoekvoorstelRegel, Document, DocumentSoort
from app.materiaal.models import (
    MateriaalLeverancier,
    Materiaalmatch,
    MateriaalmatchUitkomst,
    MateriaalProduct,
    MateriaalTransport,
    TransportStatus,
)

logger = logging.getLogger(__name__)
MODULE = "boekhouding"
TOLERANTIE_REL = Decimal("0.01")
TOLERANTIE_ABS = Decimal("0.5")


class MateriaalAfwijkingBevestigingVereist(Exception):
    """Boeken mág, maar alleen mét de bewuste "boeken ondanks materiaal-afwijking"-klik
    (409 + match-cijfers in detail.materiaalmatch; de client toont de pop-up)."""

    def __init__(self, match_info: dict) -> None:
        self.match_info = match_info
        super().__init__("De materiaalmatch van dit document wijkt af — bevestig 'boeken ondanks materiaal-afwijking'")


def _normaliseer(tekst: str) -> str:
    t = tekst.lower().replace("mtr", "m").replace("meter", "m").replace(",", ".")
    t = re.sub(r"[^a-z0-9.+ ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def koppel_product(omschrijving: str, producten: list[MateriaalProduct]) -> MateriaalProduct | None:
    """Pure koppeling: langste productnaam die in de regel voorkomt (of de regel in de naam)."""
    regel = _normaliseer(omschrijving)
    if not regel:
        return None
    beste: MateriaalProduct | None = None
    beste_len = 0
    for p in producten:
        naam = _normaliseer(p.naam)
        if not naam:
            continue
        if (naam in regel or (len(regel) >= 6 and regel in naam)) and len(naam) > beste_len:
            beste, beste_len = p, len(naam)
    return beste


def _als_decimal(waarde: object) -> Decimal | None:
    if isinstance(waarde, int | float):
        return Decimal(str(waarde))
    if not isinstance(waarde, str) or not waarde.strip():
        return None
    try:
        return Decimal(waarde.strip().replace(",", "."))
    except InvalidOperation:
        return None


def _sluit(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= max(TOLERANTIE_ABS, abs(b) * TOLERANTIE_REL)


@dataclass(frozen=True)
class MateriaalmatchData:
    document_id: uuid.UUID
    leverancier_id: uuid.UUID
    leverancier_naam: str | None
    project_id: uuid.UUID | None
    project_naam: str | None
    uitkomst: str
    aantal_regels_getoetst: int
    aantal_regels_afwijkend: int
    aantal_regels_onbekend: int
    details: dict | None
    berekend_op: datetime
    afwijking_bevestigd: bool
    afwijking_bevestigd_op: datetime | None


def _naar_data(session: Session, m: Materiaalmatch) -> MateriaalmatchData:
    from app.sync.models import ProjectCache

    lev = session.get(MateriaalLeverancier, m.leverancier_id)
    project = session.get(ProjectCache, (m.project_id, m.administratie_id)) if m.project_id else None
    return MateriaalmatchData(
        document_id=m.document_id,
        leverancier_id=m.leverancier_id,
        leverancier_naam=lev.naam if lev else None,
        project_id=m.project_id,
        project_naam=project.naam if project else None,
        uitkomst=m.uitkomst,
        aantal_regels_getoetst=m.aantal_regels_getoetst,
        aantal_regels_afwijkend=m.aantal_regels_afwijkend,
        aantal_regels_onbekend=m.aantal_regels_onbekend,
        details=m.details,
        berekend_op=m.berekend_op,
        afwijking_bevestigd=m.afwijking_bevestigd_op is not None,
        afwijking_bevestigd_op=m.afwijking_bevestigd_op,
    )


def bereken_materiaalmatch_in_sessie(
    session: Session, *, administratie_id: uuid.UUID, document_id: uuid.UUID
) -> MateriaalmatchData | None:
    from app.documenten.boekvoorstel import _laatste_veldvoorstel
    from app.materiaal.service import materiaalstand_in_sessie

    document = session.get(Document, document_id)
    if document is None or document.soort != DocumentSoort.INKOOPFACTUUR.value:
        return None
    voorstel = session.get(Boekvoorstel, document_id)
    vendor_id = voorstel.vendor_id if voorstel is not None else None
    veldvoorstel = _laatste_veldvoorstel(session, document_id) or {}
    if vendor_id is None:
        vendor_id = _als_uuid(veldvoorstel.get("vendor_id"))
    if vendor_id is None:
        return None
    lev = session.scalars(
        select(MateriaalLeverancier).where(
            MateriaalLeverancier.administratie_id == administratie_id, MateriaalLeverancier.vendor_id == vendor_id
        )
    ).first()
    if lev is None:
        return None

    factuurdatum: date | None = voorstel.factuurdatum if voorstel is not None and voorstel.factuurdatum else None
    project_id: uuid.UUID | None = None
    if voorstel is not None:
        project_ids = {
            r.project_id
            for r in session.scalars(select(BoekvoorstelRegel).where(BoekvoorstelRegel.document_id == document_id))
            if r.project_id
        }
        if len(project_ids) == 1:
            project_id = project_ids.pop()
    reden: str | None = None
    if project_id is None:
        kandidaten = set(
            session.scalars(
                select(MateriaalTransport.project_id)
                .where(
                    MateriaalTransport.administratie_id == administratie_id,
                    MateriaalTransport.leverancier_id == lev.id,
                    MateriaalTransport.status == TransportStatus.GELEVERD.value,
                )
                .distinct()
            )
        )
        if len(kandidaten) == 1:
            project_id = kandidaten.pop()
        elif not kandidaten:
            reden = "geen geleverde transporten van deze leverancier geregistreerd"
        else:
            reden = "meerdere projecten met leveringen van deze leverancier — kies het project op de boekregels"

    producten = list(session.scalars(select(MateriaalProduct).where(MateriaalProduct.leverancier_id == lev.id)))
    regels_in = veldvoorstel.get("regels") if isinstance(veldvoorstel.get("regels"), list) else []
    regels_uit: list[dict] = []
    afwijkend = onbekend = getoetst = 0
    stand = None
    if project_id is not None:
        stand = materiaalstand_in_sessie(
            session, administratie_id=administratie_id, project_id=project_id, tot_en_met=factuurdatum or date.today()
        )
        per_product = {r.product_id: r for r in stand.regels}
        if not stand.regels:
            reden = "geen geleverd materiaal geregistreerd op dit project t/m de factuurdatum"
        for r in regels_in:
            if not isinstance(r, dict):
                continue
            omschrijving = str(r.get("omschrijving") or r.get("beschrijving") or "")
            hoeveelheid = _als_decimal(r.get("hoeveelheid"))
            product = koppel_product(omschrijving, producten)
            if product is None:
                onbekend += 1
                regels_uit.append(
                    {
                        "omschrijving": omschrijving,
                        "hoeveelheid": str(hoeveelheid) if hoeveelheid is not None else None,
                        "status": "onbekend",
                    }
                )
                continue
            sr = per_product.get(product.id)
            verwacht_aantal = Decimal(sr.op_locatie if sr else 0)
            verwacht_eenheden = sr.huur_eenheden if sr else Decimal("0")
            if hoeveelheid is None:
                status = "geen_hoeveelheid"
                onbekend += 1
            else:
                getoetst += 1
                if _sluit(hoeveelheid, verwacht_aantal):
                    status = "match_aantal"
                elif _sluit(hoeveelheid, verwacht_eenheden):
                    status = "match_huur_eenheden"
                else:
                    status = "afwijking"
                    afwijkend += 1
            regels_uit.append(
                {
                    "omschrijving": omschrijving,
                    "product_id": str(product.id),
                    "product_naam": product.naam,
                    "hoeveelheid": str(hoeveelheid) if hoeveelheid is not None else None,
                    "verwacht_aantal": str(verwacht_aantal),
                    "verwacht_huur_eenheden": str(verwacht_eenheden),
                    "huurdagen": sr.huurdagen_tot_vandaag if sr else 0,
                    "eerste_levering": sr.eerste_levering.isoformat() if sr and sr.eerste_levering else None,
                    "status": status,
                }
            )
    if project_id is None or stand is None or not stand.regels or getoetst == 0:
        uitkomst = MateriaalmatchUitkomst.NIET_TOETSBAAR
        reden = reden or (
            "geen factuurregels met hoeveelheid herkend als catalogusproduct"
            if regels_in
            else "geen factuurregels beschikbaar"
        )
    elif afwijkend:
        uitkomst = MateriaalmatchUitkomst.AFWIJKING
    else:
        uitkomst = MateriaalmatchUitkomst.MATCH

    details = {
        "regels": regels_uit,
        "reden": reden,
        "factuurdatum": factuurdatum.isoformat() if factuurdatum else None,
        "stand": [
            {
                "product_naam": r.naam,
                "op_locatie": r.op_locatie,
                "huurdagen": r.huurdagen_tot_vandaag,
                "huur_eenheden": str(r.huur_eenheden),
                "eerste_levering": r.eerste_levering.isoformat() if r.eerste_levering else None,
            }
            for r in (stand.regels if stand else [])
        ],
        "m2_op_locatie": str(stand.m2_op_locatie) if stand else None,
    }
    match = session.get(Materiaalmatch, document_id)
    if match is None:
        match = Materiaalmatch(document_id=document_id, administratie_id=administratie_id, leverancier_id=lev.id)
        session.add(match)
    match.leverancier_id, match.project_id, match.uitkomst = lev.id, project_id, uitkomst.value
    match.aantal_regels_getoetst, match.aantal_regels_afwijkend, match.aantal_regels_onbekend = (
        getoetst,
        afwijkend,
        onbekend,
    )
    match.details, match.berekend_op = details, datetime.now(UTC)
    match.afwijking_bevestigd_door = None  # nieuwe cijfers = nieuwe beslissing
    match.afwijking_bevestigd_op = None
    session.flush()
    return _naar_data(session, match)


def _als_uuid(waarde: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(waarde)) if waarde else None
    except ValueError:
        return None


def draai_materiaalmatch(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> MateriaalmatchData | None:
    """Pipeline-hook (ná extractie / voorstel-opslag / transport-statuswijziging): systeem-actor,
    fouten zijn gelogde waarschuwingen — de match is signalering, nooit een blokkade."""
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        return bereken_materiaalmatch_in_sessie(session, administratie_id=administratie_id, document_id=document_id)


def lees_materiaalmatch(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> MateriaalmatchData | None:
    with scoped_session(administratie_id) as session:
        m = session.get(Materiaalmatch, document_id)
        return _naar_data(session, m) if m else None


def open_materiaalmatches_in_sessie(session: Session, *, administratie_id: uuid.UUID) -> int:
    """Teller (werkvoorraad-/transport-zijbalk): afwijkingen op nog niet geboekte documenten."""
    from app.documenten.models import DocumentStatus

    return int(
        session.scalar(
            select(func.count())
            .select_from(Materiaalmatch)
            .join(Document, Document.id == Materiaalmatch.document_id)
            .where(
                Materiaalmatch.administratie_id == administratie_id,
                Materiaalmatch.uitkomst == MateriaalmatchUitkomst.AFWIJKING.value,
                Document.status != DocumentStatus.GEBOEKT.value,
            )
        )
        or 0
    )


def toets_materiaalmatch_poort(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, bevestigd: bool
) -> None:
    """Zelfde poort-vorm als boeken.toets_match_afwijking_poort (besluit 2): afwijking zonder
    bevestiging → 409 mét cijfers; bevestiging van een mens → persistent + audit
    ("geboekt ondanks materiaal-afwijking" in de tijdlijn via de boek-audit)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        match = session.get(Materiaalmatch, document_id)
        if match is None or match.uitkomst != MateriaalmatchUitkomst.AFWIJKING.value:
            return
        if match.afwijking_bevestigd_op is not None:
            return
        if not bevestigd or actor_id == SYSTEEM_ACTOR_ID:
            raise MateriaalAfwijkingBevestigingVereist(
                {
                    "uitkomst": match.uitkomst,
                    "aantal_regels_getoetst": match.aantal_regels_getoetst,
                    "aantal_regels_afwijkend": match.aantal_regels_afwijkend,
                    "aantal_regels_onbekend": match.aantal_regels_onbekend,
                    "regels": (match.details or {}).get("regels", []),
                }
            )
        match.afwijking_bevestigd_door, match.afwijking_bevestigd_op = actor_id, datetime.now(UTC)
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="materiaalmatch",
            record_id=document_id,
            actie="materiaalmatch_afwijking_bevestigd",
            correlatie_id=document_id,
            nieuwe_waarde={
                "aantal_regels_afwijkend": match.aantal_regels_afwijkend,
                "regels": (match.details or {}).get("regels", []),
            },
            administratie_id=administratie_id,
        )


def herbereken_voor_leverancier(*, administratie_id: uuid.UUID, leverancier_id: uuid.UUID) -> int:
    """Ná een transport-statuswijziging (geleverd): open matches van deze leverancier verversen."""
    from app.documenten.models import DocumentStatus

    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        ids = list(
            session.scalars(
                select(Materiaalmatch.document_id)
                .join(Document, Document.id == Materiaalmatch.document_id)
                .where(
                    Materiaalmatch.administratie_id == administratie_id,
                    Materiaalmatch.leverancier_id == leverancier_id,
                    Document.status != DocumentStatus.GEBOEKT.value,
                )
            )
        )
    n = 0
    for doc_id in ids:
        try:
            draai_materiaalmatch(administratie_id=administratie_id, document_id=doc_id)
            n += 1
        except Exception:  # noqa: BLE001
            logger.exception("Materiaalmatch-herberekening mislukt voor document %s", doc_id)
    return n
