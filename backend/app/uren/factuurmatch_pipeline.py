"""Factuurmatch fase 2 — pipeline-glue (akkoord Peter 2026-08-21, BESLISSINGEN
"FACTUURMATCH ZZP-/BUREAUFACTUREN").

De motor (app/uren/factuurmatch.py) is puur; deze module verbindt 'm met de document-pipeline:

- `draai_match_voor_document` — de standaard match-run: ná extractie (post-commit hook,
  vóór de autoboek-poging), ná élke voorstel-opslag en ná een expliciete herbereken-vraag.
  Leest het boekvoorstel via dezelfde bron als het controlescherm (`haal_boekvoorstel_op`:
  opgeslagen voorstel wint, anders het veldvoorstel-prefill) zodat de match direct ná
  extractie al bestaat — dat voedt de werkvoorraad-teller/chip vóórdat iemand het document
  opent. `factuur_uren` komt uit het AI-veldvoorstel (regel-hoeveelheden, conservatief:
  álle regels parseerbaar of níets — nooit half optellen; UBL-voorstellen dragen geen
  hoeveelheid → geen uren-toets, het bedrag blijft het hoofdmechanisme).
- `herbereken_voor_veldwerker` — ná een weekstaat-goedkeuring (post-commit hook in
  app/uren/service.py): elke bestaande match van deze ZZP'er (of van de detacheerder(s)
  waaraan die gekoppeld is) op een niet-terminaal document wordt ververst — een nieuwe
  getekende staat kan een `afwijking` alsnog laten sluiten.
- `lees_match` — de actuele match-rij als data (werkvoorraad/detail/response-DTO's).

Álle berekeningen draaien onder de SYSTEEM-ACTOR, ongeacht wie triggert: de lees-policy op
platform.detacheerder_koppeling is actor-gebonden (0056/0057) en een niet-Beheerder zou de
bureau-tarieven anders stil missen — de matchuitkomst mag nooit van de toevallige actor
afhangen. De berekening zelf wordt bewust niet geauditeerd (deterministisch afgeleide,
`berekend_op` toont de versheid)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DetacheerderKoppeling
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.models import Document, DocumentStatus
from app.uren.factuurmatch import FactuurmatchData, bereken_match_in_sessie
from app.uren.models import Factuurmatch

# Terminale documentstatussen: een match op zo'n document wordt nooit meer ververst (geboekt =
# vastgelegd resultaat; verwijderd/gesplitst = geen werk meer).
_TERMINALE_STATUSSEN = (DocumentStatus.GEBOEKT, DocumentStatus.VERWIJDERD, DocumentStatus.GESPLITST)


# --- lezen ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FactuurmatchGegevens:
    """De opgeslagen match-rij als losse data (sessieloos bruikbaar in routers/DTO's)."""

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
    berekend_op: datetime
    afwijking_bevestigd_door: uuid.UUID | None
    afwijking_bevestigd_op: datetime | None


def _naar_gegevens(session: Session, match: Factuurmatch) -> FactuurmatchGegevens:
    from app.db.models import Gebruiker

    veldwerker = session.get(Gebruiker, match.veldwerker_gebruiker_id)
    return FactuurmatchGegevens(
        document_id=match.document_id,
        veldwerker_gebruiker_id=match.veldwerker_gebruiker_id,
        veldwerker_naam=veldwerker.naam if veldwerker else None,
        uitkomst=match.uitkomst,
        staten_som_uren=match.staten_som_uren,
        staten_som_bedrag=match.staten_som_bedrag,
        factuur_bedrag=match.factuur_bedrag,
        factuur_uren=match.factuur_uren,
        verschil_bedrag=match.verschil_bedrag,
        verschil_uren=match.verschil_uren,
        tarief_ontbreekt=match.tarief_ontbreekt,
        details=match.details,
        berekend_op=match.berekend_op,
        afwijking_bevestigd_door=match.afwijking_bevestigd_door,
        afwijking_bevestigd_op=match.afwijking_bevestigd_op,
    )


def lees_match(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> FactuurmatchGegevens | None:
    with scoped_session(administratie_id) as session:
        match = session.get(Factuurmatch, document_id)
        return _naar_gegevens(session, match) if match else None


def lees_matches(
    *, administratie_id: uuid.UUID, document_ids: list[uuid.UUID]
) -> dict[uuid.UUID, FactuurmatchGegevens]:
    """Bulk-variant voor de documentenlijst (geen N+1)."""
    if not document_ids:
        return {}
    with scoped_session(administratie_id) as session:
        matches = session.scalars(select(Factuurmatch).where(Factuurmatch.document_id.in_(document_ids))).all()
        return {m.document_id: _naar_gegevens(session, m) for m in matches}


# --- factuur-uren uit het veldvoorstel -------------------------------------------------------------


def _als_uren(waarde: object) -> Decimal | None:
    if not isinstance(waarde, str) or not waarde.strip():
        return None
    try:
        return Decimal(waarde.strip().replace(",", "."))
    except InvalidOperation:
        return None


def _factuur_uren_uit_veldvoorstel(session: Session, document_id: uuid.UUID) -> Decimal | None:
    """Som van de regel-hoeveelheden uit het laatste AI-veldvoorstel. Conservatief (zelfde
    lijn als _netto_som in de motor): élke regel moet een parseerbare hoeveelheid dragen,
    anders is er geen vergelijkbaar uren-totaal — nooit half optellen."""
    from app.documenten.boekvoorstel import _laatste_veldvoorstel

    veldvoorstel = _laatste_veldvoorstel(session, document_id)
    if veldvoorstel is None:
        return None
    regels = veldvoorstel.get("regels")
    if not isinstance(regels, list) or not regels:
        return None
    uren = [_als_uren(r.get("hoeveelheid")) if isinstance(r, dict) else None for r in regels]
    if any(u is None for u in uren):
        return None
    return sum(uren, Decimal("0"))


# --- match-runs ------------------------------------------------------------------------------------


def draai_match_voor_document(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    weekstaat_ids: list[uuid.UUID] | None = None,
    factuur_uren: Decimal | None = None,
) -> FactuurmatchData | None:
    """Bereken (of ververs) de match voor één document. `weekstaat_ids` = de expliciete
    staten-selectie ("periode-keuze", herbereken-endpoint; gevalideerd in de motor);
    `factuur_uren` = mens-opgave die de veldvoorstel-som overschrijft. Retourneert None
    wanneer de match niet van toepassing is (geen inkoopfactuur / geen (voorgestelde)
    crediteur / crediteur niet aan een veldwerker gekoppeld) — bewust geen ruis."""
    from app.documenten.boekvoorstel import haal_boekvoorstel_op

    voorstel = haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
    if voorstel.vendor_id is None:
        return None
    nettos = [r.netto_bedrag for r in voorstel.regels]
    factuur_bedrag = sum(nettos, Decimal("0")) if nettos and all(n is not None for n in nettos) else None

    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        if factuur_uren is None:
            factuur_uren = _factuur_uren_uit_veldvoorstel(session, document_id)
        return bereken_match_in_sessie(
            session,
            administratie_id=administratie_id,
            document_id=document_id,
            weekstaat_ids=weekstaat_ids,
            factuur_uren=factuur_uren,
            factuur_bedrag=factuur_bedrag,
            vendor_id=voorstel.vendor_id,
            factuurdatum=voorstel.factuurdatum,
        )


def herbereken_voor_veldwerker(*, administratie_id: uuid.UUID, gebruiker_id: uuid.UUID) -> int:
    """Ná een weekstaat-goedkeuring: ververs elke bestaande match waarin deze ZZP'er meetelt —
    de eigen ZZP-koppeling én de bureaufacturen van detacheerders waaraan die gekoppeld is.
    Alleen matches op niet-terminale documenten (een geboekt document is vastgelegd).
    Retourneert het aantal ververste matches (logging/tests)."""
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        detacheerder_ids = session.scalars(
            select(DetacheerderKoppeling.detacheerder_gebruiker_id).where(
                DetacheerderKoppeling.zzper_gebruiker_id == gebruiker_id
            )
        ).all()
        veldwerker_ids = [gebruiker_id, *detacheerder_ids]
        document_ids = session.scalars(
            select(Factuurmatch.document_id)
            .join(Document, Document.id == Factuurmatch.document_id)
            .where(
                Factuurmatch.administratie_id == administratie_id,
                Factuurmatch.veldwerker_gebruiker_id.in_(veldwerker_ids),
                Document.status.notin_(_TERMINALE_STATUSSEN),
            )
        ).all()

    ververst = 0
    for document_id in document_ids:
        if draai_match_voor_document(administratie_id=administratie_id, document_id=document_id) is not None:
            ververst += 1
    return ververst
