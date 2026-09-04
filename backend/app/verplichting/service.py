"""Servicelaag documenttype "verplichting" (offerte / prijsopgave / opdrachtbevestiging — wens Peter
04-09, mockup `offerte-matching.html` ①/⑥/⑦).

Reviewscherm-kant: het veldvoorstel (AI-lezing) + de door de mens opgeslagen kopvelden, de harde
checks, "laat vervallen" (⑥) en de leesroutes voor de match/verbruiksstand. Geen RLZ-/Odoo-boeking —
een verplichting is een dossierstuk met een verbruiksstand; het accorderen zelf hergebruikt de
BESTAANDE klant-accorderingsflow (`app/accordering/service.py`, vertakking op documentsoort).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.documenten.checks import CheckRapport, CheckResultaat
from app.documenten.models import Boekvoorstel, Document, DocumentGebeurtenis, DocumentSoort, DocumentStatus
from app.extractie.verplichting import HERKOMST_VELDEN, SOORT_LABELS
from app.sync.models import ProjectCache, VendorCache
from app.verplichting import match as match_motor
from app.verplichting import match_pipeline
from app.verplichting.models import Verplichting, VerplichtingMatch

logger = logging.getLogger(__name__)

MIN_REDEN_LENGTE = 3


class VerplichtingFout(Exception):
    """Domeinfout in de verplichting-servicelaag."""


class GeenVerplichtingDocument(VerplichtingFout):
    """Het document bestaat wel, maar is geen verplichting (409)."""


class OngeldigeVerplichtingActie(VerplichtingFout):
    """Actie past niet bij de huidige stand (409)."""


class OngeldigeInvoer(VerplichtingFout):
    """Invoer is inhoudelijk onbruikbaar (422)."""


# --------------------------------------------------------------------------- datacontainers


@dataclass(frozen=True)
class GoedgekeurdStand:
    bedrag_excl: Decimal | None
    op: datetime | None
    door_naam: str | None


@dataclass(frozen=True)
class VerbruikStand:
    verbruikt_excl: Decimal
    totaal_excl: Decimal
    percentage: int
    over_excl: Decimal | None
    #: Voorwaarschuwing (besluit Peter 04-09, mee-lift-punt 0.1): gematchte facturen die nog NIET
    #: geboekt zijn — informatief, tellen niet in het verbruik (③ blijft: verbruik = geboekt).
    open_facturen_aantal: int = 0
    open_facturen_excl: Decimal = Decimal("0.00")


@dataclass(frozen=True)
class VervallenStand:
    op: datetime
    reden: str | None
    door_naam: str | None


@dataclass(frozen=True)
class GekoppeldeFactuur:
    document_id: uuid.UUID
    referentie: str | None
    factuurdatum: date | None
    bedrag_excl: Decimal | None
    status: str
    verrekend: bool


@dataclass(frozen=True)
class Suggestie:
    id: uuid.UUID
    naam: str | None
    match: str | None


@dataclass(frozen=True)
class VerplichtingVoorstel:
    document_id: uuid.UUID
    status: str
    soort_label: str | None = None
    vendor_id: uuid.UUID | None = None
    vendor_naam: str | None = None
    project_id: uuid.UUID | None = None
    project_naam: str | None = None
    offertenummer: str | None = None
    datum: date | None = None
    totaalbedrag_excl: Decimal | None = None
    geldig_tot: date | None = None
    omschrijving: str | None = None
    opgeslagen: bool = False
    herkomst: dict[str, str | None] = field(default_factory=dict)
    zekerheid: dict[str, float] = field(default_factory=dict)
    zekerheid_drempel: float = 0.0
    vendor_suggestie: Suggestie | None = None
    project_suggestie: Suggestie | None = None
    goedgekeurd: GoedgekeurdStand | None = None
    verbruik: VerbruikStand | None = None
    vervallen: VervallenStand | None = None
    gekoppelde_facturen: list[GekoppeldeFactuur] = field(default_factory=list)
    checks: list[CheckResultaat] = field(default_factory=list)
    ai_overgeslagen_reden: str | None = None


# --------------------------------------------------------------------------- lezen


def _laad_verplichting_document(session: Session, document_id: uuid.UUID) -> Document:
    from app.documenten.service import DocumentNietGevonden

    document = session.get(Document, document_id)
    if document is None:
        raise DocumentNietGevonden(f"Onbekend document: {document_id}")
    if document.soort != DocumentSoort.VERPLICHTING.value:
        raise GeenVerplichtingDocument(
            f"Document {document_id} heeft soort {document.soort} — dit is geen verplichting"
        )
    return document


def _laatste_extractie_detail(session: Session, document_id: uuid.UUID) -> dict:
    """Het NIEUWSTE extractie-detail uit de tijdlijn (veldvoorstel óf overgeslagen-reden) —
    zelfde bron/regel als het inkoop-controlescherm ("opnieuw extraheren": de laatste wint)."""
    laatste: dict = {}
    for gebeurtenis in session.scalars(
        select(DocumentGebeurtenis)
        .where(DocumentGebeurtenis.document_id == document_id)
        .order_by(DocumentGebeurtenis.tijdstip)
    ):
        detail = gebeurtenis.detail or {}
        if "veldvoorstel" in detail or "ai_extractie_overgeslagen" in detail or "ai_extractie_fout" in detail:
            laatste = detail
    return laatste


def _naam_van_gebruiker(session: Session, gebruiker_id: uuid.UUID | None) -> str | None:
    if gebruiker_id is None:
        return None
    from app.db.models import Gebruiker

    gebruiker = session.get(Gebruiker, gebruiker_id)
    return gebruiker.naam if gebruiker is not None else None


def _vendor_naam(session: Session, *, administratie_id: uuid.UUID, vendor_id: uuid.UUID | None) -> str | None:
    if vendor_id is None:
        return None
    rij = session.get(VendorCache, (vendor_id, administratie_id))
    return rij.naam if rij is not None else None


def _project_naam(session: Session, *, administratie_id: uuid.UUID, project_id: uuid.UUID | None) -> str | None:
    if project_id is None:
        return None
    rij = session.get(ProjectCache, (project_id, administratie_id))
    return rij.naam if rij is not None else None


def _als_uuid(waarde: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(waarde)) if waarde else None
    except ValueError:
        return None


def _als_decimal(waarde: object) -> Decimal | None:
    from app.extractie.controle import parse_bedrag

    if isinstance(waarde, Decimal):
        return waarde
    return parse_bedrag(waarde if isinstance(waarde, str) else None)


def _als_datum(waarde: object) -> date | None:
    from app.extractie.controle import parse_datum

    if isinstance(waarde, date):
        return waarde
    return parse_datum(waarde if isinstance(waarde, str) else None)


def _gekoppelde_facturen(
    session: Session, *, administratie_id: uuid.UUID, document_id: uuid.UUID
) -> list[GekoppeldeFactuur]:
    rijen = session.execute(
        select(VerplichtingMatch, Document, Boekvoorstel)
        .join(Document, Document.id == VerplichtingMatch.document_id)
        .join(Boekvoorstel, Boekvoorstel.document_id == VerplichtingMatch.document_id, isouter=True)
        .where(
            VerplichtingMatch.administratie_id == administratie_id,
            VerplichtingMatch.verplichting_document_id == document_id,
            VerplichtingMatch.uitkomst.in_([match_motor.BINNEN, match_motor.BUITEN]),
        )
        .order_by(Document.aangemaakt_op)
    ).all()
    return [
        GekoppeldeFactuur(
            document_id=match.document_id,
            referentie=voorstel.referentie if voorstel is not None else None,
            factuurdatum=voorstel.factuurdatum if voorstel is not None else None,
            bedrag_excl=match.bedrag_excl,
            status=doc.status.value,
            verrekend=match.verrekend_op is not None,
        )
        for match, doc, voorstel in rijen
    ]


#: Een gematchte factuur in één van deze statussen is geen "open factuur" meer: geboekt = verrekend
#: (telt in het verbruik), de rest is afgevoerd/terminaal zonder verbruik.
_GEEN_OPEN_FACTUUR = frozenset(
    {
        DocumentStatus.GEBOEKT.value,
        DocumentStatus.AFGEWEZEN.value,
        DocumentStatus.VERWIJDERD.value,
        DocumentStatus.GESPLITST.value,
        DocumentStatus.SAMENGEVOEGD.value,
    }
)


def is_open_factuur(status: str, *, verrekend: bool) -> bool:
    """Voorwaarschuwing 0.1 (besluit Peter 04-09): een gematchte (binnen/buiten) factuur die nog niet
    geboekt/verrekend is en nog in de werkstroom zit. Eén definitie voor het controlescherm, het
    reviewscherm én Inzicht › Verplichtingen — informatief, telt nooit in het verbruik."""
    return not verrekend and status not in _GEEN_OPEN_FACTUUR


def open_facturen_per_verplichting(
    session: Session, *, administratie_id: uuid.UUID, verplichting_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, Decimal]]:
    """Bulk: (aantal, Σ bedrag excl.) van de open gematchte facturen per verplichting."""
    if not verplichting_ids:
        return {}
    rijen = session.execute(
        select(VerplichtingMatch.verplichting_document_id, VerplichtingMatch.bedrag_excl, Document.status)
        .join(Document, Document.id == VerplichtingMatch.document_id)
        .where(
            VerplichtingMatch.administratie_id == administratie_id,
            VerplichtingMatch.verplichting_document_id.in_(verplichting_ids),
            VerplichtingMatch.uitkomst.in_([match_motor.BINNEN, match_motor.BUITEN]),
            VerplichtingMatch.verrekend_op.is_(None),
        )
    ).all()
    per: dict[uuid.UUID, tuple[int, Decimal]] = {}
    for verplichting_id, bedrag, status in rijen:
        if not is_open_factuur(status.value if hasattr(status, "value") else str(status), verrekend=False):
            continue
        aantal, som = per.get(verplichting_id, (0, Decimal("0.00")))
        per[verplichting_id] = (aantal + 1, (som + Decimal(bedrag or 0)).quantize(Decimal("0.01")))
    return per


def _verbruik_stand(session: Session, rij: Verplichting) -> VerbruikStand | None:
    totaal = rij.goedgekeurd_bedrag_excl
    if totaal is None:
        return None
    verbruikt = Decimal(rij.verbruikt_bedrag_excl or 0)
    over = (verbruikt - totaal).quantize(Decimal("0.01"))
    aantal, som = open_facturen_per_verplichting(
        session, administratie_id=rij.administratie_id, verplichting_ids=[rij.document_id]
    ).get(rij.document_id, (0, Decimal("0.00")))
    return VerbruikStand(
        verbruikt_excl=verbruikt,
        totaal_excl=totaal,
        percentage=match_motor.percentage(verbruikt, totaal) or 0,
        over_excl=over if over > 0 else None,
        open_facturen_aantal=aantal,
        open_facturen_excl=som,
    )


def _bouw_voorstel(
    session: Session, *, administratie_id: uuid.UUID, document: Document, met_checks: bool = True
) -> VerplichtingVoorstel:
    rij = session.get(Verplichting, document.id)
    detail = _laatste_extractie_detail(session, document.id)
    veldvoorstel = detail.get("veldvoorstel") or {}
    opgeslagen = rij is not None and rij.opgeslagen_op is not None

    if opgeslagen:
        assert rij is not None
        waarden: dict[str, object] = {
            "soort_label": rij.soort_label,
            "vendor_id": rij.vendor_id,
            "project_id": rij.project_id,
            "offertenummer": rij.offertenummer,
            "datum": rij.datum,
            "totaalbedrag_excl": rij.totaalbedrag_excl,
            "geldig_tot": rij.geldig_tot,
            "omschrijving": rij.omschrijving,
        }
        bron = "mens"
    else:
        waarden = {
            "soort_label": veldvoorstel.get("soort_label"),
            "vendor_id": _als_uuid((veldvoorstel.get("vendor_suggestie") or {}).get("vendor_id")),
            "project_id": _als_uuid((veldvoorstel.get("project_suggestie") or {}).get("project_id")),
            "offertenummer": veldvoorstel.get("offertenummer"),
            "datum": _als_datum(veldvoorstel.get("datum")),
            "totaalbedrag_excl": _als_decimal(veldvoorstel.get("totaal_excl")),
            "geldig_tot": _als_datum(veldvoorstel.get("geldig_tot")),
            "omschrijving": veldvoorstel.get("omschrijving"),
        }
        bron = str(veldvoorstel.get("bron") or "ai")

    veld_naar_dto = {
        "soort_label": "soort_label",
        "leverancier": "vendor_id",
        "project": "project_id",
        "offertenummer": "offertenummer",
        "totaalbedrag_excl": "totaalbedrag_excl",
        "geldig_tot": "geldig_tot",
        "omschrijving": "omschrijving",
    }
    herkomst = {
        veld: (bron if waarden.get(veld_naar_dto[veld]) is not None else None) for veld in HERKOMST_VELDEN
    }

    vendor_suggestie = veldvoorstel.get("vendor_suggestie") or None
    project_suggestie = veldvoorstel.get("project_suggestie") or None
    vendor_id = waarden["vendor_id"]
    project_id = waarden["project_id"]
    assert vendor_id is None or isinstance(vendor_id, uuid.UUID)
    assert project_id is None or isinstance(project_id, uuid.UUID)

    ai_overgeslagen = detail.get("ai_extractie_overgeslagen") or detail.get("ai_extractie_fout")

    voorstel = VerplichtingVoorstel(
        document_id=document.id,
        status=document.status.value,
        soort_label=waarden["soort_label"],  # type: ignore[arg-type]
        vendor_id=vendor_id,
        vendor_naam=_vendor_naam(session, administratie_id=administratie_id, vendor_id=vendor_id),
        project_id=project_id,
        project_naam=_project_naam(session, administratie_id=administratie_id, project_id=project_id),
        offertenummer=waarden["offertenummer"],  # type: ignore[arg-type]
        datum=waarden["datum"],  # type: ignore[arg-type]
        totaalbedrag_excl=waarden["totaalbedrag_excl"],  # type: ignore[arg-type]
        geldig_tot=waarden["geldig_tot"],  # type: ignore[arg-type]
        omschrijving=waarden["omschrijving"],  # type: ignore[arg-type]
        opgeslagen=opgeslagen,
        herkomst=herkomst,
        zekerheid={k: float(v) for k, v in (veldvoorstel.get("zekerheid") or {}).items()},
        zekerheid_drempel=float(veldvoorstel.get("zekerheid_drempel") or 0.0),
        vendor_suggestie=(
            Suggestie(
                id=_als_uuid(vendor_suggestie.get("vendor_id")),  # type: ignore[arg-type]
                naam=vendor_suggestie.get("naam"),
                match=vendor_suggestie.get("match"),
            )
            if vendor_suggestie and _als_uuid(vendor_suggestie.get("vendor_id"))
            else None
        ),
        project_suggestie=(
            Suggestie(
                id=_als_uuid(project_suggestie.get("project_id")),  # type: ignore[arg-type]
                naam=project_suggestie.get("naam"),
                match=project_suggestie.get("match"),
            )
            if project_suggestie and _als_uuid(project_suggestie.get("project_id"))
            else None
        ),
        goedgekeurd=(
            GoedgekeurdStand(
                bedrag_excl=rij.goedgekeurd_bedrag_excl,
                op=rij.goedgekeurd_op,
                door_naam=_naam_van_gebruiker(session, rij.goedgekeurd_door),
            )
            if rij is not None and rij.goedgekeurd_op is not None
            else None
        ),
        verbruik=_verbruik_stand(session, rij) if rij is not None else None,
        vervallen=(
            VervallenStand(
                op=rij.vervallen_op,
                reden=rij.vervallen_reden,
                door_naam=_naam_van_gebruiker(session, rij.vervallen_door),
            )
            if rij is not None and rij.vervallen_op is not None
            else None
        ),
        gekoppelde_facturen=_gekoppelde_facturen(
            session, administratie_id=administratie_id, document_id=document.id
        ),
        ai_overgeslagen_reden=str(ai_overgeslagen) if ai_overgeslagen else None,
    )
    if not met_checks:
        return voorstel
    rapport = _checks(session, administratie_id=administratie_id, voorstel=voorstel)
    return replace(voorstel, checks=list(rapport.resultaten))


def haal_voorstel_op(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> VerplichtingVoorstel:
    with scoped_session(administratie_id) as session:
        document = _laad_verplichting_document(session, document_id)
        return _bouw_voorstel(session, administratie_id=administratie_id, document=document)


# --------------------------------------------------------------------------- checks (hard)


def _checks(
    session: Session, *, administratie_id: uuid.UUID, voorstel: VerplichtingVoorstel
) -> CheckRapport:
    """De harde checks van een verplichting (CONTRACT_B):
    1. "Verplichte velden" — leverancier, soort-label, totaalbedrag excl. > 0 (+ project zodra de
       administratie projectplicht heeft);
    2. "Geldigheid" — geldig t/m vóór de documentdatum = blokkerend (onmogelijk); verstreken t.o.v.
       vandaag = oranje SIGNAAL (geen blokkade: een verstreken offerte accorderen kan zinvol zijn,
       de match-motor negeert 'm daarna gewoon voor latere facturen);
    3. "Duplicaat offerte" — zelfde crediteur + zelfde offertenummer al lopend/geaccordeerd =
       blokkerend (anders zou hetzelfde aanbod twee verbruiksstanden krijgen)."""
    resultaten: list[CheckResultaat] = []

    administratie = session.get(Administratie, administratie_id)
    project_verplicht = bool(administratie is not None and administratie.project_verplicht)
    ontbrekend: list[str] = []
    if voorstel.vendor_id is None:
        ontbrekend.append("leverancier")
    if voorstel.soort_label not in SOORT_LABELS:
        ontbrekend.append("soort (offerte/prijsopgave/opdrachtbevestiging)")
    if voorstel.totaalbedrag_excl is None or voorstel.totaalbedrag_excl <= 0:
        ontbrekend.append("totaalbedrag exclusief btw (groter dan nul)")
    if project_verplicht and voorstel.project_id is None:
        ontbrekend.append("project")
    resultaten.append(
        CheckResultaat(
            naam="Verplichte velden",
            ok=not ontbrekend,
            melding=(
                "Alle verplichte velden zijn gevuld"
                if not ontbrekend
                else "Vul eerst: " + ", ".join(ontbrekend)
            ),
        )
    )

    vandaag = datetime.now(UTC).date()
    if voorstel.geldig_tot is None:
        resultaten.append(
            CheckResultaat(
                naam="Geldigheid", ok=True, melding="Geen geldigheidsdatum vermeld — geen beperking"
            )
        )
    elif voorstel.datum is not None and voorstel.geldig_tot < voorstel.datum:
        resultaten.append(
            CheckResultaat(
                naam="Geldigheid",
                ok=False,
                melding=(
                    f"Geldig t/m {voorstel.geldig_tot.isoformat()} ligt vóór de documentdatum "
                    f"{voorstel.datum.isoformat()} — controleer de gelezen datums"
                ),
            )
        )
    elif voorstel.geldig_tot < vandaag:
        resultaten.append(
            CheckResultaat(
                naam="Geldigheid",
                ok=True,
                signaal=True,
                melding=(
                    f"De geldigheid is verstreken ({voorstel.geldig_tot.isoformat()}) — facturen ná die datum "
                    "worden niet meer tegen deze verplichting gematcht"
                ),
            )
        )
    else:
        resultaten.append(
            CheckResultaat(
                naam="Geldigheid", ok=True, melding=f"Geldig t/m {voorstel.geldig_tot.isoformat()}"
            )
        )

    resultaten.append(
        _check_duplicaat_offerte(
            session,
            administratie_id=administratie_id,
            document_id=voorstel.document_id,
            vendor_id=voorstel.vendor_id,
            offertenummer=voorstel.offertenummer,
        )
    )
    return CheckRapport(tuple(resultaten))


def _check_duplicaat_offerte(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    vendor_id: uuid.UUID | None,
    offertenummer: str | None,
) -> CheckResultaat:
    genormaliseerd = match_motor.normaliseer_nummer(offertenummer)
    if vendor_id is None or genormaliseerd is None:
        return CheckResultaat(
            naam="Duplicaat offerte",
            ok=True,
            melding="Geen leverancier of offertenummer om op te toetsen — niet van toepassing",
        )
    rijen = session.execute(
        select(Verplichting, Document.status)
        .join(Document, Document.id == Verplichting.document_id)
        .where(
            Verplichting.administratie_id == administratie_id,
            Verplichting.document_id != document_id,
            Verplichting.vendor_id == vendor_id,
            Verplichting.vervallen_op.is_(None),
            Document.status.in_([DocumentStatus.GEACCORDEERD, DocumentStatus.TER_ACCORDERING]),
        )
    ).all()
    treffers = [
        rij for rij, _ in rijen if match_motor.normaliseer_nummer(rij.offertenummer) == genormaliseerd
    ]
    if treffers:
        return CheckResultaat(
            naam="Duplicaat offerte",
            ok=False,
            melding=(
                f"Offerte {offertenummer} van deze leverancier is al in behandeling of goedgekeurd "
                f"({len(treffers)}×) — laat vervallen of gebruik de bestaande verplichting"
            ),
        )
    return CheckResultaat(
        naam="Duplicaat offerte", ok=True, melding="Geen andere lopende verplichting met dit nummer"
    )


def voer_checks_uit(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> CheckRapport:
    """Publieke checks-ingang (reviewscherm + de accordering-aanbiedpoort)."""
    with scoped_session(administratie_id) as session:
        document = _laad_verplichting_document(session, document_id)
        voorstel = _bouw_voorstel(session, administratie_id=administratie_id, document=document, met_checks=False)
        return _checks(session, administratie_id=administratie_id, voorstel=voorstel)


# --------------------------------------------------------------------------- opslaan


_BEVROREN = frozenset({DocumentStatus.GEACCORDEERD, DocumentStatus.TER_ACCORDERING, DocumentStatus.VERWIJDERD})


def sla_voorstel_op(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    soort_label: str | None,
    vendor_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    offertenummer: str | None,
    datum: date | None,
    totaalbedrag_excl: Decimal | None,
    geldig_tot: date | None,
    omschrijving: str | None,
) -> VerplichtingVoorstel:
    """De mens slaat de gecontroleerde kopvelden op (upsert; de documentstatus blijft ongewijzigd —
    de weg naar de klant loopt via de bestaande "Ter accordering"-route). Audit oud→nieuw.

    Bevroren zodra het document bij de klant ligt of geaccordeerd is: het goedgekeurde bedrag moet
    exact het bedrag zijn waarop de accordeur "akkoord" tikte."""
    if soort_label is not None and soort_label not in SOORT_LABELS:
        raise OngeldigeInvoer(f"Onbekend soort-label: {soort_label}")
    if totaalbedrag_excl is not None and totaalbedrag_excl < 0:
        raise OngeldigeInvoer("Het totaalbedrag exclusief btw kan niet negatief zijn")

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = _laad_verplichting_document(session, document_id)
        if document.status in _BEVROREN:
            raise OngeldigeVerplichtingActie(
                f"Deze verplichting staat op {document.status.value} en kan niet meer gewijzigd worden"
            )
        rij = session.get(Verplichting, document_id)
        oud = (
            {
                "soort_label": rij.soort_label,
                "vendor_id": str(rij.vendor_id) if rij.vendor_id else None,
                "project_id": str(rij.project_id) if rij.project_id else None,
                "offertenummer": rij.offertenummer,
                "datum": rij.datum.isoformat() if rij.datum else None,
                "totaalbedrag_excl": str(rij.totaalbedrag_excl) if rij.totaalbedrag_excl is not None else None,
                "geldig_tot": rij.geldig_tot.isoformat() if rij.geldig_tot else None,
                "omschrijving": rij.omschrijving,
            }
            if rij is not None
            else {}
        )
        if rij is None:
            rij = Verplichting(document_id=document_id, administratie_id=administratie_id)
            session.add(rij)
        rij.soort_label = soort_label
        rij.vendor_id = vendor_id
        rij.project_id = project_id
        rij.offertenummer = (offertenummer or "").strip() or None
        rij.datum = datum
        rij.totaalbedrag_excl = totaalbedrag_excl
        rij.geldig_tot = geldig_tot
        rij.omschrijving = (omschrijving or "").strip() or None
        rij.opgeslagen_door = actor_id
        rij.opgeslagen_op = datetime.now(UTC)
        nieuw = {
            "soort_label": rij.soort_label,
            "vendor_id": str(rij.vendor_id) if rij.vendor_id else None,
            "project_id": str(rij.project_id) if rij.project_id else None,
            "offertenummer": rij.offertenummer,
            "datum": rij.datum.isoformat() if rij.datum else None,
            "totaalbedrag_excl": str(rij.totaalbedrag_excl) if rij.totaalbedrag_excl is not None else None,
            "geldig_tot": rij.geldig_tot.isoformat() if rij.geldig_tot else None,
            "omschrijving": rij.omschrijving,
        }
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="verplichting",
            record_id=document_id,
            actie="verplichting_voorstel_opgeslagen",
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde=nieuw,
            administratie_id=administratie_id,
        )
        session.flush()
        return _bouw_voorstel(session, administratie_id=administratie_id, document=document)


# --------------------------------------------------------------------------- vervallen (⑥)


def laat_vervallen(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, reden: str
) -> VerplichtingVoorstel:
    """Kantoor laat een GEACCORDEERDE verplichting vervallen (⑥): het document blijft geaccordeerd
    (bewaarplicht + herleidbaarheid), de verplichting-rij krijgt vervallen_op/reden/door. Gevolg:
    geen nieuwe matches meer; al verrekende facturen blijven ongemoeid (hun verbruik blijft staan).
    Tijdlijnregel zónder statuswissel + audit."""
    schone_reden = (reden or "").strip()
    if len(schone_reden) < MIN_REDEN_LENGTE:
        raise OngeldigeInvoer(f"Reden is verplicht (minimaal {MIN_REDEN_LENGTE} tekens)")

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = _laad_verplichting_document(session, document_id)
        if document.status != DocumentStatus.GEACCORDEERD:
            raise OngeldigeVerplichtingActie(
                f"Alleen een geaccordeerde verplichting kan vervallen (staat op {document.status.value})"
            )
        rij = session.get(Verplichting, document_id)
        if rij is None:
            raise OngeldigeVerplichtingActie("Er is geen verplichting-registratie voor dit document")
        if rij.vervallen_op is not None:
            raise OngeldigeVerplichtingActie("Deze verplichting is al vervallen")
        rij.vervallen_op = datetime.now(UTC)
        rij.vervallen_reden = schone_reden
        rij.vervallen_door = actor_id
        session.add(
            DocumentGebeurtenis(
                id=uuid.uuid4(),
                document_id=document_id,
                van_status=document.status,
                naar_status=document.status,
                actor_id=actor_id,
                detail={
                    "verplichting_vervallen": {"reden": schone_reden},
                    "reden": f"verplichting vervallen: {schone_reden}",
                },
            )
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="verplichting",
            record_id=document_id,
            actie="verplichting_vervallen",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"reden": schone_reden},
            administratie_id=administratie_id,
        )
        session.flush()
        voorstel = _bouw_voorstel(session, administratie_id=administratie_id, document=document)

    # Nieuwe matches stoppen: de open inkoopdocumenten van deze crediteur opnieuw toetsen.
    match_pipeline.herbereken_na_verplichting_wijziging_stil(
        administratie_id=administratie_id, verplichting_document_id=document_id
    )
    return voorstel


# --------------------------------------------------------------------------- goedkeuring vastleggen


def leg_goedkeuring_vast_in_sessie(
    session: Session, *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID
) -> Decimal | None:
    """Ná het LAATSTE klant-akkoord (aangeroepen door `app/accordering/service.py`, ín dezelfde
    transactie als de overgang naar `geaccordeerd`): het goedgekeurde bedrag + wie/wanneer vastleggen.
    Dát is het discrepantie-doel (①). Retourneert het vastgelegde bedrag."""
    rij = session.get(Verplichting, document_id)
    if rij is None:
        logger.warning("Verplichting-rij ontbreekt bij goedkeuring van document %s", document_id)
        return None
    rij.goedgekeurd_bedrag_excl = rij.totaalbedrag_excl
    rij.goedgekeurd_op = datetime.now(UTC)
    rij.goedgekeurd_door = actor_id
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="verplichting",
        record_id=document_id,
        actie="verplichting_goedgekeurd",
        correlatie_id=uuid.uuid4(),
        nieuwe_waarde={
            "goedgekeurd_bedrag_excl": str(rij.goedgekeurd_bedrag_excl)
            if rij.goedgekeurd_bedrag_excl is not None
            else None,
            "offertenummer": rij.offertenummer,
            "soort_label": rij.soort_label,
        },
        administratie_id=administratie_id,
    )
    return rij.goedgekeurd_bedrag_excl


# --------------------------------------------------------------------------- match-leesroute + koppelen


@dataclass(frozen=True)
class MatchKandidaat:
    document_id: uuid.UUID
    offertenummer: str | None
    soort_label: str | None
    totaal_excl: Decimal | None
    verbruikt_excl: Decimal
    project_naam: str | None
    geldig_tot: date | None


@dataclass(frozen=True)
class VerplichtingKort:
    document_id: uuid.UUID
    offertenummer: str | None
    soort_label: str | None
    leverancier_naam: str | None
    project_naam: str | None
    totaal_excl: Decimal | None
    goedgekeurd_op: datetime | None
    goedgekeurd_door_naam: str | None


@dataclass(frozen=True)
class MatchData:
    document_id: uuid.UUID
    uitkomst: str
    verplichting: VerplichtingKort | None
    bedrag_excl: Decimal | None
    verbruik_voor: Decimal | None
    verbruik_na: Decimal | None
    percentage_na: int | None
    overschrijding_excl: Decimal | None
    handmatig_gekoppeld: bool
    kandidaten: list[MatchKandidaat]
    berekend_op: datetime | None
    melding: str


def _verplichting_kort(
    session: Session, *, administratie_id: uuid.UUID, document_id: uuid.UUID
) -> VerplichtingKort | None:
    rij = session.get(Verplichting, document_id)
    if rij is None:
        return None
    return VerplichtingKort(
        document_id=document_id,
        offertenummer=rij.offertenummer,
        soort_label=rij.soort_label,
        leverancier_naam=_vendor_naam(session, administratie_id=administratie_id, vendor_id=rij.vendor_id),
        project_naam=_project_naam(session, administratie_id=administratie_id, project_id=rij.project_id),
        totaal_excl=rij.goedgekeurd_bedrag_excl or rij.totaalbedrag_excl,
        goedgekeurd_op=rij.goedgekeurd_op,
        goedgekeurd_door_naam=_naam_van_gebruiker(session, rij.goedgekeurd_door),
    )


def _kandidaten_van_details(
    session: Session, *, administratie_id: uuid.UUID, details: dict
) -> list[MatchKandidaat]:
    ids = [_als_uuid(k) for k in (details.get("kandidaten") or [])]
    kandidaten: list[MatchKandidaat] = []
    for kandidaat_id in [k for k in ids if k is not None]:
        rij = session.get(Verplichting, kandidaat_id)
        if rij is None:
            continue
        kandidaten.append(
            MatchKandidaat(
                document_id=kandidaat_id,
                offertenummer=rij.offertenummer,
                soort_label=rij.soort_label,
                totaal_excl=rij.goedgekeurd_bedrag_excl or rij.totaalbedrag_excl,
                verbruikt_excl=Decimal(rij.verbruikt_bedrag_excl or 0),
                project_naam=_project_naam(session, administratie_id=administratie_id, project_id=rij.project_id),
                geldig_tot=rij.geldig_tot,
            )
        )
    return kandidaten


def haal_match_op(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> MatchData:
    """De matchstand van een INKOOPdocument. Nog nooit berekend → `geen_verplichting` (stil: het
    controlescherm rendert dan niets)."""
    from app.documenten.service import DocumentNietGevonden

    with scoped_session(administratie_id) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        rij = session.get(VerplichtingMatch, document_id)
        if rij is None:
            return MatchData(
                document_id=document_id,
                uitkomst=match_motor.GEEN_VERPLICHTING,
                verplichting=None,
                bedrag_excl=None,
                verbruik_voor=None,
                verbruik_na=None,
                percentage_na=None,
                overschrijding_excl=None,
                handmatig_gekoppeld=False,
                kandidaten=[],
                berekend_op=None,
                melding="Nog niet getoetst tegen goedgekeurde verplichtingen.",
            )
        details = rij.details or {}
        percentage_na = details.get("percentage_na")
        return MatchData(
            document_id=document_id,
            uitkomst=rij.uitkomst,
            verplichting=(
                _verplichting_kort(
                    session, administratie_id=administratie_id, document_id=rij.verplichting_document_id
                )
                if rij.verplichting_document_id is not None
                else None
            ),
            bedrag_excl=rij.bedrag_excl,
            verbruik_voor=rij.verbruik_voor,
            verbruik_na=rij.verbruik_na,
            percentage_na=int(percentage_na) if isinstance(percentage_na, int) else None,
            overschrijding_excl=rij.overschrijding_excl,
            handmatig_gekoppeld=rij.handmatig_gekoppeld,
            kandidaten=_kandidaten_van_details(session, administratie_id=administratie_id, details=details),
            berekend_op=rij.berekend_op,
            melding=str(details.get("melding") or ""),
        )


def koppel_verplichting(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    verplichting_document_id: uuid.UUID | None,
) -> MatchData:
    """ "Koppel offerte…" (②) resp. ontkoppelen (`verplichting_document_id=None`). De handmatige
    koppeling wint daarna altijd zolang die verplichting lopend is en wordt onthouden voor dezelfde
    crediteur + project. 409 als de gekozen verplichting niet (meer) lopend is."""
    from app.documenten.service import DocumentNietGevonden

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        if document.soort != DocumentSoort.INKOOPFACTUUR.value:
            raise GeenVerplichtingDocument(
                f"Document {document_id} heeft soort {document.soort} — offerte-koppeling geldt voor inkoopfacturen"
            )
        rij = session.get(VerplichtingMatch, document_id)
        if rij is not None and rij.verrekend_op is not None:
            # De factuur is geboekt en het verbruik is al bijgeschreven: de matchstand is bevroren
            # (⑥). Omkoppelen zou het verbruik van twee verplichtingen scheeftrekken — de weg terug
            # is tegenboeken (dat draait het verbruik terug en maakt de match weer beweegbaar).
            raise OngeldigeVerplichtingActie(
                "Deze factuur is al geboekt en verrekend met een verplichting — corrigeer via "
                "tegenboeken; daarna kan de offerte opnieuw gekoppeld worden"
            )
        oud = str(rij.verplichting_document_id) if rij is not None and rij.verplichting_document_id else None
        if verplichting_document_id is not None:
            doel_document = session.get(Document, verplichting_document_id)
            doel = session.get(Verplichting, verplichting_document_id)
            if doel is None or doel_document is None:
                raise OngeldigeVerplichtingActie("Onbekende verplichting in deze administratie")
            if doel_document.status != DocumentStatus.GEACCORDEERD or doel.vervallen_op is not None:
                raise OngeldigeVerplichtingActie(
                    "Deze verplichting is niet (meer) lopend — alleen een goedgekeurde, niet-vervallen "
                    "verplichting kan gekoppeld worden"
                )
            if rij is None:
                rij = VerplichtingMatch(
                    document_id=document_id,
                    administratie_id=administratie_id,
                    uitkomst=match_motor.NIET_TOETSBAAR,
                )
                session.add(rij)
            rij.verplichting_document_id = verplichting_document_id
            rij.handmatig_gekoppeld = True
        else:
            if rij is None:
                raise OngeldigeVerplichtingActie("Er is niets om te ontkoppelen")
            rij.verplichting_document_id = None
            rij.handmatig_gekoppeld = False
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="verplichting_match",
            record_id=document_id,
            actie="verplichting_match_gekoppeld" if verplichting_document_id else "verplichting_match_ontkoppeld",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"verplichting_document_id": oud},
            nieuwe_waarde={
                "verplichting_document_id": str(verplichting_document_id) if verplichting_document_id else None
            },
            administratie_id=administratie_id,
        )

    # Herberekening met de nieuwe koppeling (cumulatieve stand + melding).
    match_pipeline.draai_match_stil(administratie_id=administratie_id, document_id=document_id)
    return haal_match_op(administratie_id=administratie_id, document_id=document_id)


def offerte_match_kort(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> MatchData | None:
    """Voor de accordeur-wachtrij: alleen een `binnen`/`buiten`-uitkomst is daar zichtbaar (OPTIE A,
    ④) — elke andere uitkomst rendeert niets."""
    data = haal_match_op(administratie_id=administratie_id, document_id=document_id)
    if data.uitkomst not in (match_motor.BINNEN, match_motor.BUITEN):
        return None
    return data
