"""Blok A2 ProfX (Peter 16-09): LEES-ONLY rapport "kassarapporten in de inkoopstroom" — documenten die als
INKOOPFACTUUR in de module staan maar op inhoud een ProfX Journaal/Margerapport zijn (de intake classificeerde ze vóór
16-09 via de AI als factuur; casus De Bazar Apeldoorn). Per administratie mét status: een GEBOEKT exemplaar wordt alleen
gemeld (nooit automatisch herclassificeren), de rest gaat via de bestaande type-wissel-/bulkroute (Type wijzigen →
kassarapport). Geen writes, geen RLZ/Odoo-calls, geen AI: herkenning op de tekstlaag (herkenning.herken_pdf)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.models import Document, DocumentSoort, DocumentStatus
from app.documenten.storage import DocumentOpslag, standaard_opslag
from app.omzet.bronnen import herkenning

#: Eindstatussen die niet meer herclassificeerbaar zijn (afgehandeld) — alleen gemeld als het om GEBOEKT gaat.
_OVERGESLAGEN = {
    DocumentStatus.SAMENGEVOEGD,
    DocumentStatus.AFGEVOERD_DUPLICAAT,
    DocumentStatus.VERWIJDERD,
    DocumentStatus.AFGEWEZEN,
}


@dataclass(frozen=True)
class Treffer:
    document_id: uuid.UUID
    bestandsnaam: str
    status: str
    bron: str
    aangemaakt_op: datetime
    actie: str  # 'herclassificeren' | 'melden (geboekt)'


@dataclass
class AdministratieRapport:
    administratie_id: uuid.UUID | None
    naam: str
    onderzocht: int = 0
    onleesbaar: int = 0
    treffers: list[Treffer] = field(default_factory=list)


def _onderzoek(session, *, naam: str, administratie_id: uuid.UUID | None, sinds: datetime, opslag: DocumentOpslag):  # noqa: ANN001
    rapport = AdministratieRapport(administratie_id=administratie_id, naam=naam)
    q = select(Document).where(
        Document.soort == DocumentSoort.INKOOPFACTUUR.value,
        Document.aangemaakt_op >= sinds,
        Document.bestandsnaam.ilike("%.pdf"),
    )
    q = (
        q.where(Document.administratie_id == administratie_id)
        if administratie_id
        else q.where(Document.administratie_id.is_(None))
    )
    for doc in session.scalars(q.order_by(Document.aangemaakt_op)):
        if doc.status in _OVERGESLAGEN:
            continue
        rapport.onderzocht += 1
        try:
            bron = herkenning.herken_pdf(opslag.lezen(pad=doc.opslag_pad))
        except Exception:  # noqa: BLE001 — ontbrekend/onleesbaar bestand = teller, geen crash
            rapport.onleesbaar += 1
            continue
        if bron is None:
            continue
        rapport.treffers.append(
            Treffer(
                document_id=doc.id,
                bestandsnaam=doc.bestandsnaam,
                status=str(doc.status.value if hasattr(doc.status, "value") else doc.status),
                bron=bron,
                aangemaakt_op=doc.aangemaakt_op,
                actie="melden (geboekt)" if doc.status == DocumentStatus.GEBOEKT else "herclassificeren",
            )
        )
    return rapport


def rapport(
    *, dagen: int = 90, administratie_ids: list[uuid.UUID] | None = None, opslag: DocumentOpslag | None = None
) -> list[AdministratieRapport]:
    """Alle actieve administraties (of de gegeven) + de verzamelbak (administratie NULL), lees-only."""
    opslag = opslag or standaard_opslag()
    sinds = datetime.now(UTC) - timedelta(days=dagen)
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        q = select(Administratie).where(Administratie.actief.is_(True))
        if administratie_ids:
            q = q.where(Administratie.id.in_(administratie_ids))
        administraties = [(a.id, a.naam) for a in session.scalars(q.order_by(Administratie.naam))]
    uit: list[AdministratieRapport] = []
    for aid, naam in administraties:
        with scoped_session(aid) as session:
            uit.append(_onderzoek(session, naam=naam, administratie_id=aid, sinds=sinds, opslag=opslag))
    if not administratie_ids:
        with scoped_session(None) as session:  # RLS: alleen rijen mét administratie_id IS NULL
            uit.append(
                _onderzoek(
                    session, naam="Niet toegewezen (verzamelbak)", administratie_id=None, sinds=sinds, opslag=opslag
                )
            )
    return uit


def print_rapport(rapporten: list[AdministratieRapport], *, dagen: int) -> None:
    totaal = sum(len(r.treffers) for r in rapporten)
    geboekt = sum(1 for r in rapporten for t in r.treffers if t.actie.startswith("melden"))
    print(
        f"Kassarapporten in de inkoopstroom — laatste {dagen} dagen, {len(rapporten)} scopes, {totaal} treffer(s) "
        f"({geboekt} geboekt = alleen melden). LEES-ONLY."
    )
    for r in rapporten:
        if not r.treffers and r.onleesbaar == 0:
            continue
        print(
            f"\n{r.naam} ({r.administratie_id or '—'}) — {r.onderzocht} PDF-inkoopdocumenten onderzocht"
            + (f", {r.onleesbaar} onleesbaar/ontbrekend" if r.onleesbaar else "")
        )
        for t in r.treffers:
            print(
                f"  {t.aangemaakt_op:%Y-%m-%d}  {t.status:<18} {t.bron:<20} {t.actie:<20} {t.document_id}  "
                f"{t.bestandsnaam}"
            )
    if totaal == 0:
        print("\nGeen ProfX-rapporten als inkoopfactuur gevonden.")
    else:
        print(
            "\nHerclassificeren: documentenlijst → selecteer → ⋯ Type wijzigen → kassarapport (bulk, 16-09); geboekte"
            " exemplaren eerst storneren in RLZ (mens), daarna 'Tegenboeken…'/type wijzigen."
        )
