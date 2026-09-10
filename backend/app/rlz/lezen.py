"""Gedeelde LEES-helpers op RLZ-collecties (bundel 10-09 blok D; gedeeld door `app/migratie/schoonlijst.py` en
`app/panden/service.py`).

Eén gepagineerde leesreeks per collectie ($top/$skip, zelfde vorm als `app/reconciliatie/rlz_dubbel.py::
lees_purchase_invoices` en `app/geheugen/seed.py::_facturen` — live bewezen op PurchaseInvoices/ManualJournals/
PaymentTransactions). Nooit een ongepagineerde bulk-GET. Een `$expand` die RLZ op een collectie niet kent (400) valt
terug op dezelfde reeks zónder expand — zichtbaar in de uitkomst (`expand_gelukt=False`), nooit stil. Alleen GET's."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Protocol

from app.rlz.client import RlzApiError, bedrag_cent_exact

PAGINA_GROOTTE = 200


class LeesClient(Protocol):
    """Het stukje `RlzClient` dat de lezers nodig hebben — zo kan een test een dict-client meegeven."""

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any: ...


@dataclass
class LeesUitkomst:
    pad: str
    rijen: list[dict[str, Any]] = field(default_factory=list)
    expand_gelukt: bool = True
    fout: RlzApiError | None = None
    paginas: int = 0

    @property
    def gelukt(self) -> bool:
        return self.fout is None


def lees_collectie(
    client: LeesClient,
    pad: str,
    *,
    filter_: str | None = None,
    expand: str | None = None,
    pagina_grootte: int | None = None,
) -> LeesUitkomst:
    """Alle rijen van een collectie in één gepagineerde reeks. Een 400 op `$expand` → opnieuw zonder expand
    (`expand_gelukt=False`); elke andere `RlzApiError` (403 rechten, 404 route bestaat niet, 5xx ná retries) komt
    als `fout` terug — de aanroeper maakt er een ZICHTBARE regel van, geen crash."""
    uit = LeesUitkomst(pad=pad)
    if pagina_grootte is None:
        pagina_grootte = PAGINA_GROOTTE  # runtime gelezen (tests pinnen de module-constante)
    try:
        uit.rijen, uit.paginas = _lees_alles(client, pad, filter_=filter_, expand=expand, pagina_grootte=pagina_grootte)
        return uit
    except RlzApiError as exc:
        if expand is None or exc.status_code != 400:
            uit.fout = exc
            return uit
    uit.expand_gelukt = False
    try:
        uit.rijen, uit.paginas = _lees_alles(client, pad, filter_=filter_, expand=None, pagina_grootte=pagina_grootte)
    except RlzApiError as exc:
        uit.fout = exc
    return uit


def _lees_alles(
    client: LeesClient, pad: str, *, filter_: str | None, expand: str | None, pagina_grootte: int
) -> tuple[list[dict[str, Any]], int]:
    rijen: list[dict[str, Any]] = []
    skip = 0
    paginas = 0
    while True:
        params: dict[str, Any] = {"$top": str(pagina_grootte), "$skip": str(skip)}
        if filter_:
            params["$filter"] = filter_
        if expand:
            params["$expand"] = expand
        antwoord = client.get(pad, params=params)
        batch = antwoord.get("value", []) if isinstance(antwoord, dict) else []
        paginas += 1
        rijen.extend(r for r in batch if isinstance(r, dict))
        if len(batch) < pagina_grootte:
            return rijen, paginas
        skip += pagina_grootte


# ---- veld-helpers (één plek, zelfde semantiek als rlz_dubbel) ---------------------------------------


def als_datum(waarde: object) -> date | None:
    if not isinstance(waarde, str) or len(waarde) < 10:
        return None
    try:
        return date.fromisoformat(waarde[:10])
    except ValueError:
        return None


def als_int(waarde: object) -> int | None:
    try:
        return int(waarde) if waarde is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def als_bedrag(waarde: object) -> Decimal | None:
    return bedrag_cent_exact(waarde)


def entity_van(rij: dict[str, Any]) -> tuple[str | None, str | None]:
    """(entity-id, entity-naam) uit een RLZ-rij; Entity is op de collecties alleen mét `$expand=Entity` een dict —
    zonder expand is het veld afwezig of null, dan (None, None)."""
    entity = rij.get("Entity")
    if not isinstance(entity, dict):
        return None, None
    eid = entity.get("id")
    naam = entity.get("Name") or entity.get("SearchName")
    return (str(eid) if eid else None), (str(naam) if naam else None)


def heeft_bijlage(client: LeesClient, pad: str, rlz_id: str) -> bool | None:
    """`GET {collectie}/{id}/Uploads?$top=1` — betrouwbare aanwezigheidscheck op PurchaseInvoices, SalesInvoices én
    ManualJournals (api-verkenning "Uploads bij een herstart-boekcyclus", 16-08). None = niet vast te stellen
    (route weigert), nooit stil als "geen bijlage" geteld."""
    try:
        antwoord = client.get(f"{pad}/{rlz_id}/Uploads", params={"$top": "1"})
    except RlzApiError:
        return None
    if isinstance(antwoord, dict):
        waarde = antwoord.get("value")
        if isinstance(waarde, list):
            return len(waarde) > 0
        return None
    if isinstance(antwoord, list):
        return len(antwoord) > 0
    return None
