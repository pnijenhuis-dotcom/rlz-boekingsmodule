"""RLZ-bron voor de replay (run 2 VGG 12-09, blok 6) — LEES-ONLY lezers op alle collecties die de migratie nodig heeft.

Eén gepagineerde reeks per collectie via `app/rlz/lezen.py::lees_collectie` (alleen GET's; een 400 op `$expand` valt
zichtbaar terug zónder expand; 403/404/5xx = één regel onder `fouten`, nooit een crash):

- documenten: PurchaseInvoices/SalesInvoices (`$expand=Entity`), ManualJournals (`$expand=JournalEntryDiary`),
Receipts —
  op VGG is Receipts een UNIE-collectie van álle documenten (STAP-0 knip 12-09: de eerste Receipts-rij is de
  PurchaseInvoice RLZ-04-00000887); ná ontdubbeling tegen de drie andere collecties blijven de bank-directe boekingen
  (DocumentType 19, `IsSystemGenerated`) over. Geboekt = Status 2/3; Status 1 = concept; een systeemhuls = concept +
  `IsSystemGenerated` óf concept zonder Entity met |bedrag| + datum gelijk aan een OPEN PaymentTransaction (regel A,
  `bankdekking.is_bank_direct` lazy geïmporteerd — anders de minimale eigen versie hieronder).
- regels per GEBOEKT document — BLOK 7b 13-09 (api-verkenning "Webfilter-blokkering bij >N calls"): NIET meer per
  document. De 1.089 losse regel-calls van de nameting 13-09 lieten RLZ's webfilter ná ~700 calls elke route weigeren
  (403 + HTML "Access Denied"; 305 documenten zonder regels, daarna ook PaymentAccounts/JournalEntryLines/Ledgers/
  TaxRates dicht). Regels komen nu mee op de COLLECTIE-reeks: `$expand=Entity,DocumentLineList($expand=Account,
  TaxRate)` (resp. `JournalEntryDiary,…`); weigert RLZ die expand (400) dan valt `lees_collectie` zichtbaar terug op de
  oude expand en worden alleen de documenten zónder `DocumentLineList` per document gelezen (`{collectie}/{id}/Lines`,
  DocumentType 19 via `BankMutationDirectBookings/{id}/Lines` met terugval `…/{id}?$expand=DocumentLineList(…)`) —
  door de token-bucket van `RlzClient` (`rlz_max_calls_per_seconde`) in tempo. De Receipts-collectie expandeert
  `DocumentLineList` niet (api-verkenning "Receipts-verkenning") → bank-directe boekingen blijven per document.
  Een webfilter-403 die de client ná backoff nog ziet = `RlzBron.blokkering` gezet, lezen STOPT, het rapport wordt
  ROOD mét "RLZ-blokkering — meting ongeldig" — nooit doorrekenen met halve data. JournalEntryLines per document is
  géén alternatief: `JournalEntry` draagt alleen id/BookDate/DocumentType/EventID.
- PaymentTransactions `$expand=PaymentAccount,PaymentReferenceList($expand=Document)` (terugval zichtbaar),
PaymentAccounts +
  `PaymentAccounts/{id}/Statements` (alleen koppen: Number, Date, Debits, Credits, saldi), JournalEntryLines
  (`$expand=Account,JournalEntry`, volledig — een BookDate-filter is niet nodig: het rapport heeft 31-12-2025 én
  vandaag),
  Ledgers, TaxRates.

Geen writes, geen AI, geld in Decimal (`als_bedrag`)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.rlz.client import RlzApiError, RlzWebfilterError
from app.rlz.lezen import LeesClient, LeesUitkomst, als_bedrag, als_datum, als_int, entity_van, lees_collectie

logger = logging.getLogger(__name__)

STATUS_CONCEPT = 1
GEBOEKT_STATUSSEN: frozenset[int] = frozenset({2, 3})
#: RLZ DocumentType (bewezen: 1 inkoop, 10 verkoop/receipt, 11 memoriaal, 19 bank-directe boeking).
DOCTYPE_INKOOP = 1
DOCTYPE_VERKOOP = 10
DOCTYPE_MEMORIAAL = 11
DOCTYPE_BANK_DIRECT = 19
#: Boekstukreeksen van bankdagboeken op VGG (contract §Besluiten 6) — alleen gebruikt als `bankdekking` ontbreekt.
BANK_REEKSEN: frozenset[str] = frozenset({"RLZ-09", "RLZ-25", "RLZ-28", "RLZ-46", "RLZ-60"})

#: Per collectie de basis-expand (relaties) — de regels komen er als `DocumentLineList(…)` bij (blok 7b 13-09).
DOCUMENT_COLLECTIES: tuple[tuple[str, str | None], ...] = (
    ("PurchaseInvoices", "Entity"),
    ("SalesInvoices", "Entity"),
    ("ManualJournals", "JournalEntryDiary"),
)
REGELS_EXPAND_COLLECTIE = "DocumentLineList($expand=Account,TaxRate)"
ROUTE_COLLECTIE_EXPAND = "collectie $expand=DocumentLineList"
BLOKKERING_TEKST = "RLZ-blokkering — meting ongeldig"


def collectie_expand(basis: str | None) -> str:
    return f"{basis},{REGELS_EXPAND_COLLECTIE}" if basis else REGELS_EXPAND_COLLECTIE


RECEIPTS = "Receipts"
BANK_EXPAND = "PaymentAccount,PaymentReferenceList($expand=Document)"
JOURNAALREGEL_EXPAND = "Account,JournalEntry"
REGEL_EXPAND = "Account,TaxRate,Project"
VOORTGANG_STAP = 100


@dataclass(frozen=True)
class Fout:
    route: str
    status: int | None
    melding: str

    def als_dict(self) -> dict[str, Any]:
        return {"route": self.route, "status": self.status, "melding": self.melding}


@dataclass
class RlzBron:
    """Alles wat de replay uit RLZ gelezen heeft — puur data, geen interpretatie behalve de tellers."""

    documenten: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # per collectie, Receipts = rest
    regels: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # per rlz_id (alleen geboekt)
    regels_route: dict[str, str] = field(default_factory=dict)  # per rlz_id: de route waarmee de regels kwamen
    bank: list[dict[str, Any]] = field(default_factory=list)
    bank_expand_gelukt: bool = True
    rekeningen: list[dict[str, Any]] = field(default_factory=list)
    statements: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # per rekening-id
    journaalregels: list[dict[str, Any]] = field(default_factory=list)
    ledgers: list[dict[str, Any]] = field(default_factory=list)
    taxrates: list[dict[str, Any]] = field(default_factory=list)
    gelezen: dict[str, int] = field(default_factory=dict)
    fouten: list[Fout] = field(default_factory=list)
    overgeslagen: list[str] = field(default_factory=list)
    regel_calls: int = 0
    regel_fouten: dict[str, str] = field(default_factory=dict)  # per rlz_id: melding
    #: Blok 7b 13-09: documenten waarvan de regels via de collectie-expand meekwamen (geen losse call).
    regels_via_collectie: int = 0
    #: Gezet zodra de RLZ-webfilter ná backoff nog blokkeert: "<route>: <melding>". Lezen stopt; rapport = ongeldig.
    blokkering: str | None = None
    #: Tempo-tellers van de client (als die een `Tempo` draagt): calls, webfilter-treffers (hervat), gewacht (s).
    client_calls: int | None = None
    webfilter_treffers: int | None = None
    gewacht_seconden: float | None = None

    def alle_documenten(self) -> list[tuple[str, dict[str, Any]]]:
        return [(pad, r) for pad, rijen in self.documenten.items() for r in rijen]


# ---- classificatie van een document-rij (puur) -------------------------------------------------------


def doc_id(rij: dict[str, Any]) -> str | None:
    return str(rij["id"]) if rij.get("id") else None


def boekstuk_van(rij: dict[str, Any]) -> str | None:
    return str(rij["ReceiptNumber"]) if rij.get("ReceiptNumber") else None


def reeks_van(boekstuk: str | None) -> str | None:
    """`RLZ-06-00000026` → `RLZ-06`."""
    if not boekstuk:
        return None
    delen = boekstuk.split("-")
    return "-".join(delen[:2]) if len(delen) >= 3 else None


def is_geboekt(rij: dict[str, Any]) -> bool:
    return als_int(rij.get("Status")) in GEBOEKT_STATUSSEN


def is_concept(rij: dict[str, Any]) -> bool:
    return als_int(rij.get("Status")) == STATUS_CONCEPT


def _eigen_is_bank_direct(collectie: str, boekstuk: str | None, dagboek: str | None) -> bool:
    """Minimale kopie van A's regel — alleen actief als `app.migratie.bankdekking` (nog) niet bestaat."""
    if collectie == RECEIPTS:
        return True
    reeks = reeks_van(boekstuk)
    if reeks in BANK_REEKSEN:
        return True
    return bool(dagboek and "bank" in dagboek.lower())


def is_bank_direct(collectie: str, boekstuk: str | None, dagboek: str | None) -> bool:
    try:
        from app.migratie.bankdekking import is_bank_direct as _a  # noqa: PLC0415 — lazy: A bouwt 'm parallel

        return bool(_a(collectie, boekstuk, dagboek, bank_reeksen=BANK_REEKSEN))
    except ImportError:
        return _eigen_is_bank_direct(collectie, boekstuk, dagboek)


def dagboek_van(rij: dict[str, Any]) -> str | None:
    d = rij.get("JournalEntryDiary")
    if isinstance(d, dict):
        naam = d.get("Name") or d.get("Description")
        return str(naam) if naam else None
    return None


def open_bank_sleutels(bank: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """(|bedrag|, datum) van élke OPEN PaymentTransaction (OpenAmount ≠ 0; nooit IsComplete — stale ná storno)."""
    uit: set[tuple[str, str]] = set()
    for tx in bank:
        open_bedrag = als_bedrag(tx.get("OpenAmount"))
        bedrag = als_bedrag(tx.get("Amount"))
        datum = als_datum(tx.get("BookDate")) or als_datum(tx.get("Date"))
        if open_bedrag and open_bedrag != 0 and bedrag is not None and datum is not None:
            uit.add((str(abs(bedrag)), datum.isoformat()))
    return uit


def is_huls(rij: dict[str, Any], open_bank: set[tuple[str, str]]) -> bool:
    """Systeemhuls: concept dat RLZ zelf per open bankmutatie aanmaakt (api-verkenning "Bankmodule STAP 0" §4)."""
    if not is_concept(rij):
        return False
    if rij.get("IsSystemGenerated") is True:
        return True
    if entity_van(rij)[0] is not None:
        return False
    bedrag = als_bedrag(rij.get("BaseInvoiceAmount"))
    datum = als_datum(rij.get("BookDate")) or als_datum(rij.get("Date"))
    return bedrag is not None and datum is not None and (str(abs(bedrag)), datum.isoformat()) in open_bank


def documenttype_van(collectie: str, rij: dict[str, Any]) -> int | None:
    dt = als_int(rij.get("DocumentType"))
    if dt is not None:
        return dt
    return {
        "PurchaseInvoices": DOCTYPE_INKOOP,
        "SalesInvoices": DOCTYPE_VERKOOP,
        "ManualJournals": DOCTYPE_MEMORIAAL,
    }.get(collectie)


# ---- regels ----------------------------------------------------------------------------------------------


def _waarde_lijst(antwoord: Any) -> list[dict[str, Any]] | None:
    if isinstance(antwoord, list):
        return [r for r in antwoord if isinstance(r, dict)]
    if isinstance(antwoord, dict):
        if isinstance(antwoord.get("value"), list):
            return [r for r in antwoord["value"] if isinstance(r, dict)]
        if isinstance(antwoord.get("DocumentLineList"), list):
            return [r for r in antwoord["DocumentLineList"] if isinstance(r, dict)]
    return None


def regel_routes(collectie: str, rij: dict[str, Any]) -> list[tuple[str, dict[str, str]]]:
    """Kandidaat-routes (pad, params) voor de regels van één document, in volgorde van bewijs."""
    rlz_id = doc_id(rij) or ""
    dt = documenttype_van(collectie, rij)
    if collectie in ("PurchaseInvoices", "SalesInvoices", "ManualJournals"):
        return [(f"{collectie}/{rlz_id}/Lines", {"$expand": REGEL_EXPAND})]
    if dt == DOCTYPE_BANK_DIRECT:
        return [
            (f"BankMutationDirectBookings/{rlz_id}/Lines", {"$expand": REGEL_EXPAND}),
            (f"BankMutationDirectBookings/{rlz_id}", {"$expand": "DocumentLineList($expand=Account,TaxRate)"}),
        ]
    if dt == DOCTYPE_VERKOOP:
        return [(f"SalesInvoices/{rlz_id}/Lines", {"$expand": REGEL_EXPAND})]
    if dt == DOCTYPE_INKOOP:
        return [(f"PurchaseInvoices/{rlz_id}/Lines", {"$expand": REGEL_EXPAND})]
    if dt == DOCTYPE_MEMORIAAL:
        return [(f"ManualJournals/{rlz_id}/Lines", {"$expand": REGEL_EXPAND})]
    return [(f"SalesInvoices/{rlz_id}/Lines", {"$expand": REGEL_EXPAND})]


def lees_regels(client: LeesClient, collectie: str, rij: dict[str, Any]) -> tuple[list[dict[str, Any]] | None, str]:
    """(regels, route) — None = geen enkele route gaf regels (melding in de route-tekst)."""
    laatste = "geen route"
    for pad, params in regel_routes(collectie, rij):
        try:
            regels = _waarde_lijst(client.get(pad, params=params))
        except RlzWebfilterError:
            raise  # blokkering: de aanroeper stopt de hele run (nooit doorrekenen met halve data)
        except RlzApiError as exc:
            laatste = f"{pad}: {exc.status_code} {exc.body[:80]}"
            continue
        if regels is not None:
            return regels, pad
        laatste = f"{pad}: antwoord zonder regels"
    return None, laatste


# ---- de bron -------------------------------------------------------------------------------------------


def _registreer(bron: RlzBron, uitkomst: LeesUitkomst, *, optioneel: bool = False) -> bool:
    if uitkomst.fout is not None:
        melding = f"{uitkomst.fout.status_code}: {uitkomst.fout.body[:160]}"
        if isinstance(uitkomst.fout, RlzWebfilterError):
            bron.blokkering = f"{uitkomst.pad}: webfilter 403 ná backoff — {melding}"
            bron.fouten.append(Fout(route=uitkomst.pad, status=403, melding=f"{BLOKKERING_TEKST}: {melding}"))
            return False
        if optioneel:
            bron.overgeslagen.append(f"{uitkomst.pad}: niet leesbaar ({melding}) — overgeslagen")
        else:
            bron.fouten.append(Fout(route=uitkomst.pad, status=uitkomst.fout.status_code, melding=melding))
        return False
    bron.gelezen[uitkomst.pad] = len(uitkomst.rijen)
    if not uitkomst.expand_gelukt:
        bron.overgeslagen.append(f"{uitkomst.pad}: $expand geweigerd — gelezen zonder relaties")
    return True


def _regels_uit_rij(rij: dict[str, Any]) -> list[dict[str, Any]] | None:
    """`DocumentLineList` zoals de collectie-expand 'm geeft: lijst = regels (ook leeg), anders None (niet mee)."""
    lijst = rij.get("DocumentLineList")
    if isinstance(lijst, list):
        return [r for r in lijst if isinstance(r, dict)]
    return None


def _tempo_tellers(bron: RlzBron, client: LeesClient) -> None:
    tempo = getattr(client, "tempo", None)
    if tempo is None:
        return
    bron.client_calls = int(getattr(tempo, "calls", 0))
    bron.webfilter_treffers = int(getattr(tempo, "webfilter_treffers", 0))
    bron.gewacht_seconden = round(float(getattr(tempo, "gewacht_seconden", 0.0)), 1)


def lees_bron(
    client: LeesClient,
    *,
    regels_lezen: bool = True,
    voortgang: Callable[[str], None] | None = None,
) -> RlzBron:
    """Alles lezen, niets schrijven. Volgorde: documenten (mét regels via de collectie-expand) → bank (voor de huls-
    regel) → regels per document alleen voor GEBOEKTE documenten zónder meegekomen regels → rekeningen + statements →
    journaalregels → ledgers/taxrates. Een webfilter-blokkering stopt de reeks direct (`bron.blokkering`)."""
    bron = RlzBron()
    melden = voortgang or (lambda t: logger.info("vgg-replay: %s", t))

    def geblokkeerd() -> bool:
        if bron.blokkering:
            melden(f"{BLOKKERING_TEKST}: {bron.blokkering} — lezen gestopt")
            _tempo_tellers(bron, client)
            return True
        return False

    for pad, basis in DOCUMENT_COLLECTIES:
        uitkomst = lees_collectie(client, pad, expand=collectie_expand(basis), expand_terugval=(basis,))
        if not _registreer(bron, uitkomst):
            if geblokkeerd():
                return bron
            continue
        bron.documenten[pad] = uitkomst.rijen
        if regels_lezen:
            met_regels = 0
            for r in uitkomst.rijen:
                rid = doc_id(r)
                if not rid or not is_geboekt(r):
                    continue
                regels = _regels_uit_rij(r)
                if regels is not None:
                    bron.regels[rid] = regels
                    bron.regels_route[rid] = ROUTE_COLLECTIE_EXPAND
                    met_regels += 1
            bron.regels_via_collectie += met_regels
            geboekt = sum(1 for r in uitkomst.rijen if is_geboekt(r) and doc_id(r))
            if geboekt and met_regels == 0:
                bron.overgeslagen.append(
                    f"{pad}: $expand={uitkomst.expand_gebruikt or '—'} gaf geen DocumentLineList — regels per document "
                    f"gelezen ({geboekt} calls, in tempo)"
                )
    receipts = lees_collectie(client, RECEIPTS)
    if _registreer(bron, receipts, optioneel=True):
        bekend = {doc_id(r) for rijen in bron.documenten.values() for r in rijen}
        bron.documenten[RECEIPTS] = [r for r in receipts.rijen if doc_id(r) not in bekend]
    elif geblokkeerd():
        return bron

    bank = lees_collectie(client, "PaymentTransactions", expand=BANK_EXPAND)
    if _registreer(bron, bank):
        bron.bank = bank.rijen
        bron.bank_expand_gelukt = bank.expand_gelukt
    elif geblokkeerd():
        return bron

    if regels_lezen:
        te_lezen = [
            (pad, r)
            for pad, r in bron.alle_documenten()
            if is_geboekt(r) and doc_id(r) and doc_id(r) not in bron.regels
        ]
        melden(
            f"regels: {bron.regels_via_collectie} documenten via de collectie-expand; "
            f"{len(te_lezen)} per document te lezen (in tempo)"
        )
        for n, (pad, r) in enumerate(te_lezen, start=1):
            rid = doc_id(r) or ""
            try:
                regels, route = lees_regels(client, pad, r)
            except RlzWebfilterError as exc:
                bron.blokkering = f"{pad}/{rid}/Lines: webfilter 403 ná backoff — {exc.body[:160]}"
                bron.fouten.append(Fout(route=f"{pad}/{{id}}/Lines", status=403, melding=BLOKKERING_TEKST))
                geblokkeerd()
                return bron
            bron.regel_calls += 1
            if regels is None:
                bron.regel_fouten[rid] = route
            else:
                bron.regels[rid] = regels
                bron.regels_route[rid] = route
            if n % VOORTGANG_STAP == 0 or n == len(te_lezen):
                melden(f"regels: {n}/{len(te_lezen)} documenten per document ({len(bron.regel_fouten)} zonder regels)")

    rekeningen = lees_collectie(client, "PaymentAccounts")
    if _registreer(bron, rekeningen):
        bron.rekeningen = rekeningen.rijen
        for rek in bron.rekeningen:
            rid = str(rek.get("id") or "")
            if not rid:
                continue
            st = lees_collectie(client, f"PaymentAccounts/{rid}/Statements")
            if not _registreer(bron, st, optioneel=True):
                if geblokkeerd():
                    return bron
                continue
            bron.statements[rid] = st.rijen
    elif geblokkeerd():
        return bron

    jr = lees_collectie(client, "JournalEntryLines", expand=JOURNAALREGEL_EXPAND)
    if _registreer(bron, jr):
        bron.journaalregels = jr.rijen
    elif geblokkeerd():
        return bron

    for pad in ("Ledgers", "TaxRates"):
        uitkomst = lees_collectie(client, pad)
        if _registreer(bron, uitkomst):
            setattr(bron, pad.lower(), uitkomst.rijen)
        elif geblokkeerd():
            return bron
    _tempo_tellers(bron, client)
    return bron


# ---- veld-helpers op regels/journaalregels (één plek) --------------------------------------------------------


def ref_id(waarde: Any) -> str | None:
    if isinstance(waarde, dict) and waarde.get("id"):
        return str(waarde["id"])
    return None


def debet_credit(regel: dict[str, Any]) -> tuple[Decimal, Decimal]:
    """(debet, credit) uit een document- of journaalregel: `DebitAmount`/`CreditAmount` als ze er zijn (memoriaal,
    JournalEntryLines), anders `NetAmount` (+ `TaxAmount`) mét teken: positief = debet (inkoop) — de aanroeper keert
    voor verkoopregels om."""
    d = als_bedrag(regel.get("DebitAmount"))
    c = als_bedrag(regel.get("CreditAmount"))
    if d is not None or c is not None:
        return (d or Decimal("0.00")), (c or Decimal("0.00"))
    cod = als_int(regel.get("CreditOrDebit"))
    bedrag = als_bedrag(regel.get("Amount"))
    if cod is not None and bedrag is not None:
        return (bedrag, Decimal("0.00")) if cod == 1 else (Decimal("0.00"), bedrag)
    net = als_bedrag(regel.get("NetAmount")) or Decimal("0.00")
    tax = als_bedrag(regel.get("TaxAmount")) or Decimal("0.00")
    tot = (net + tax).quantize(Decimal("0.01"))
    return (tot, Decimal("0.00")) if tot >= 0 else (Decimal("0.00"), -tot)


def journaalregel_datum(regel: dict[str, Any]) -> date | None:
    je = regel.get("JournalEntry")
    return (
        als_datum(regel.get("BookDate"))
        or (als_datum(je.get("BookDate")) if isinstance(je, dict) else None)
        or als_datum(regel.get("Date"))
    )


def journaalregel_bron_id(regel: dict[str, Any]) -> str | None:
    """Het document/de mutatie waar de journaalregel bij hoort: `Document.id`, `DocumentId`, anders
    `JournalEntry.EventID` (AANNAME: EventID = bron-id; het rapport meldt hoeveel regels géén bekend brondocument
    treffen, dus een verkeerde aanname is zichtbaar, nooit stil)."""
    for sleutel in ("Document", "SourceDocument"):
        rid = ref_id(regel.get(sleutel))
        if rid:
            return rid
    for sleutel in ("DocumentId", "EventID", "EventId"):
        if regel.get(sleutel):
            return str(regel[sleutel])
    je = regel.get("JournalEntry")
    if isinstance(je, dict):
        for sleutel in ("EventID", "EventId", "DocumentId"):
            if je.get(sleutel):
                return str(je[sleutel])
    return None
