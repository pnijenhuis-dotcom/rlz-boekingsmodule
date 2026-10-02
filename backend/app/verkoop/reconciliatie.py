"""Reconciliatieblok `vastly_verkoop` (Peter 29-09, punt 1/2/7; herzien 01-10 "100 % auto zonder menselijke tussenstap,
hou het simpel"): élk Vastly-verkoopdocument dat niet automatisch geboekt is, is één bevinding — nooit een document in
een lijst (verzamelbak/werkvoorraad) en sinds 01-10 nooit een mens-keuze in de module.

Drie bevindingssoorten (alle direct in stand `actie`, besluit Peter 28/29-09 — een bestaand deterministisch pad, geen
nieuwe domeinhypothese; explosie-rem blijft):
- `vastly_entiteit_niet_gekoppeld` — platformbreed, één per entiteitsleutel (KvK of genormaliseerde naam) uit de
  niet-gekoppelde documenten; tekst "UBL draagt geen administratie-id en geen bekende KvK — melden bij Vastly" (of: het
  id uit de UBL is onbekend). Géén koppelknop (de mens-koppeling van 29-09 is per 01-10 vervallen; de UBL hoort het
  platform-administratie-id te dragen, koppelcontract §2d-notitie 01-10).
- `vastly_omzetrekening_ontbreekt` — per open document waarvan het autoboek-pad weigerde op `omzetrekening_ontbreekt`
  (geen of onbekende `AccountingCost`); handeling alleen "Opnieuw aanbieden" (`POST /reconciliatie/vastly/documenten/
  {id}/opnieuw-aanbieden`) ná de herzending van de UBL door Vastly — "Rekening kiezen" is per 01-10 weg.
- `vastly_verkoop_niet_geboekt` — per open Vastly-verkoopdocument > `MINIMUM_LEEFTIJD` (1 dag) in een
  vastgoed-administratie mét de reden (lees-only oordeel `autoboeken.beoordeel_lees_only`); handeling "Opnieuw
  aanbieden" + deeplink naar het document. Een document dat al onder `omzetrekening_ontbreekt` valt krijgt géén
  tweede rij (één feit, één handeling).
Lees-only: geen RLZ-call (de duplicaat-/RLZ-checks lopen pas in de motor), geen writes."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.session import scoped_session
from app.documenten.models import Document, DocumentSoort, DocumentStatus
from app.verkoop import autoboeken, entiteit, heraanbieden, omzetrekening
from app.verkoop.models import VASTLY_REGELSOORTEN

BLOK = "vastly_verkoop"
SOORT_ENTITEIT = "vastly_entiteit_niet_gekoppeld"
SOORT_OMZETREKENING = "vastly_omzetrekening_ontbreekt"
SOORT_NIET_GEBOEKT = "vastly_verkoop_niet_geboekt"
#: Een document dat jonger is dan dit is "onderweg" (intake + autoboek gebeuren binnen minuten) — geen bevinding.
MINIMUM_LEEFTIJD = timedelta(days=1)
#: Open statussen die een Vastly-verkoopdocument in een administratie kan hebben zonder boeking.
OPEN_STATUSSEN = (
    DocumentStatus.TE_CONTROLEREN,
    DocumentStatus.HANDMATIG_AFMAKEN,
    DocumentStatus.KLAAR_OM_TE_BOEKEN,
    DocumentStatus.BOEKEN_MISLUKT,
    DocumentStatus.VRAAG_OPEN,
    DocumentStatus.WACHT_OP_IBAN_ACCORDERING,
    DocumentStatus.TER_ACCORDERING,
)
MAX_DOCUMENTEN_IN_DETAIL = 50


def _vingerafdruk(*delen: str) -> str:
    return f"{BLOK}:" + hashlib.sha256("|".join(delen).encode()).hexdigest()[:16]


def _bevinding(verzamelaar, **kw) -> None:  # noqa: ANN001, ANN003
    if verzamelaar is not None:
        verzamelaar.bevinding(**kw)


def _entiteit_bevindingen(*, stdout: Callable[[str], None], verzamelaar, nu: datetime) -> int:  # noqa: ANN001
    """(a) niet-gekoppelde documenten → één bevinding per entiteitsleutel."""
    from app.documenten.service import _standaard_opslag

    opslag = _standaard_opslag()
    groepen: dict[tuple[str, str], dict] = {}
    for k in heraanbieden.vind_niet_gekoppeld():
        with scoped_session(None) as session:
            document = session.get(Document, k.document_id)
            if document is None:
                continue
            sleutels = heraanbieden._sleutels_voor(document, opslag=opslag)
            reden = heraanbieden._jongste_reden(session, k.document_id)
        if sleutels is None:
            sleutels = entiteit.sleutels_uit_reden(reden)
        primair = sleutels.primair or ("naam", document.tenaamstelling or "?")
        g = groepen.setdefault(
            primair,
            {
                "weergave": sleutels.weergave or document.tenaamstelling,
                "kvk": sleutels.kvk,
                "administratie_id_ubl": sleutels.administratie_id_ruw or None,
                "documenten": [],
            },
        )
        g["documenten"].append(
            {
                "document_id": str(k.document_id),
                "bestandsnaam": k.bestandsnaam,
                "ontvangen_op": k.aangemaakt_op.isoformat() if k.aangemaakt_op else None,
            }
        )
    for (soort, sleutel), g in sorted(groepen.items()):
        naam = g["weergave"] or sleutel
        aantal = len(g["documenten"])
        weigering = entiteit.WEIGERING_ID_ONBEKEND if g["administratie_id_ubl"] else entiteit.WEIGERING_GEEN_ID_GEEN_KVK
        reden = entiteit.weigering_tekst(
            entiteit.EntiteitSleutels(
                kvk=g["kvk"], naam_norm=None, weergave=g["weergave"], administratie_id_ruw=g["administratie_id_ubl"]
            ),
            weigering,
        )
        tekst = (
            f"AFWIJKING  vastly_verkoop: {aantal} Vastly-verkoopfactu{'ur' if aantal == 1 else 'ren'} van entiteit "
            f"{naam!r} ({soort} {sleutel}) niet gekoppeld aan een administratie — {reden}"
        )
        stdout(tekst)
        _bevinding(
            verzamelaar,
            soort="afwijking",
            administratie_id=None,
            vingerafdruk=_vingerafdruk(SOORT_ENTITEIT, soort, sleutel),
            tekst=tekst[:1000],
            detail={
                "afwijking_soort": SOORT_ENTITEIT,
                "sleutel_soort": soort,
                "sleutel": sleutel,
                "kvk": g["kvk"],
                "weergave": g["weergave"],
                "administratie_id_ubl": g["administratie_id_ubl"],
                "reden": reden,
                "aantal": aantal,
                "documenten": g["documenten"][:MAX_DOCUMENTEN_IN_DETAIL],
                "doel_pad": "/reconciliatie",
            },
            blok=BLOK,
        )
    return len(groepen)


def _open_documenten(administratie_id: uuid.UUID, *, nu: datetime) -> list[Document]:
    with scoped_session(administratie_id) as session:
        rijen = session.scalars(
            select(Document)
            .where(
                Document.administratie_id == administratie_id,
                Document.soort == DocumentSoort.VERKOOPFACTUUR.value,
                Document.status.in_(OPEN_STATUSSEN),
                Document.aangemaakt_op <= nu - MINIMUM_LEEFTIJD,
            )
            .order_by(Document.aangemaakt_op.asc())
        ).all()
        session.expunge_all()
        return list(rijen)


def _reden_voor(administratie_id: uuid.UUID, document: Document) -> str:
    if document.status == DocumentStatus.TE_CONTROLEREN:
        return autoboeken.beoordeel_lees_only(administratie_id=administratie_id, document_id=document.id) or (
            "zou automatisch boeken — de eerstvolgende heraanbieding (dagelijkse run) neemt het mee"
        )
    if document.status == DocumentStatus.BOEKEN_MISLUKT:
        return "RLZ-boekfout bij de vorige poging (boeken_mislukt) — opnieuw aanbieden herhaalt de boeking"
    return f"status {document.status.value} — een mens heeft dit document in behandeling (vraag/accordering/handmatig)"


def _administratie_bevindingen(*, stdout: Callable[[str], None], verzamelaar, nu: datetime) -> tuple[int, int, int]:  # noqa: ANN001
    """(b)+(c): per vastgoed-administratie. → (gecontroleerd, omzetrekening-bevindingen, niet-geboekt-bevindingen).
    Sinds 01-10 is (b) per DOCUMENT (de handeling is "Opnieuw aanbieden" ná de herzending door Vastly, niet meer een
    rekening kiezen per administratie)."""
    gecontroleerd = 0
    n_rek = 0
    n_doc = 0
    for administratie_id, naam in heraanbieden.vastgoed_administraties():
        documenten = _open_documenten(administratie_id, nu=nu)
        gecontroleerd += len(documenten)
        for d in documenten:
            reden = _reden_voor(administratie_id, d)
            code_ontbreekt = reden.startswith(autoboeken.REDEN_OMZETREKENING_ONTBREEKT)
            soort = SOORT_OMZETREKENING if code_ontbreekt else SOORT_NIET_GEBOEKT
            if code_ontbreekt:
                n_rek += 1
                tekst = (
                    f"AFWIJKING  vastly_verkoop {naam}: {d.bestandsnaam} ({d.status.value}) sinds "
                    f"{d.aangemaakt_op:%d-%m} zonder (bekende) grootboekcode in de UBL — melden bij Vastly, ná herzending "
                    f"opnieuw aanbieden — {reden}"
                )
            else:
                n_doc += 1
                tekst = (
                    f"AFWIJKING  vastly_verkoop {naam}: {d.bestandsnaam} ({d.status.value}) sinds "
                    f"{d.aangemaakt_op:%d-%m} niet geboekt — {reden}"
                )
            stdout(tekst)
            detail = {
                "afwijking_soort": soort,
                "document_id": str(d.id),
                "bestandsnaam": d.bestandsnaam,
                "status": d.status.value,
                "reden": reden[:500],
                "sinds": d.aangemaakt_op.isoformat() if d.aangemaakt_op else None,
                "doel_pad": f"/verkoop/{administratie_id}/{d.id}",
            }
            if code_ontbreekt:
                detail["regelsoort"] = _regelsoort_uit_reden(reden)
            _bevinding(
                verzamelaar,
                soort="afwijking",
                administratie_id=administratie_id,
                vingerafdruk=_vingerafdruk(soort, str(d.id)),
                tekst=tekst[:1000],
                detail=detail,
                blok=BLOK,
            )
    return gecontroleerd, n_rek, n_doc


def _regelsoort_uit_reden(reden: str) -> str:
    for soort in VASTLY_REGELSOORTEN:
        if f"({soort})" in reden:
            return soort
    return omzetrekening.REGELSOORT_OVERIG


def cli_blok(  # noqa: ANN001
    args, verzamelaar=None, *, stdout: Callable[[str], None] = print, nu: datetime | None = None
) -> int:
    """Blokfunctie voor `reconciliatie-alles`. Exit 1 zodra er een bevinding is."""
    nu = nu or datetime.now(UTC)
    n_ent = _entiteit_bevindingen(stdout=stdout, verzamelaar=verzamelaar, nu=nu)
    gecontroleerd, n_rek, n_doc = _administratie_bevindingen(stdout=stdout, verzamelaar=verzamelaar, nu=nu)
    if verzamelaar is not None:
        verzamelaar.gecontroleerd(gecontroleerd + n_ent)
    stdout(
        f"VASTLY     {gecontroleerd} open Vastly-verkoopdocument(en) > 1 dag getoetst in de vastgoed-administraties; "
        f"entiteiten niet gekoppeld {n_ent}, omzetrekening ontbreekt {n_rek}, niet geboekt {n_doc}"
    )
    return 1 if (n_ent or n_rek or n_doc) else 0
