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
- regels per GEBOEKT document: `{collectie}/{id}/Lines?$expand=Account,TaxRate,Project` (bewezen op Purchase/Sales/
  ManualJournals: seed.py, poc voorraad-uitstroom); DocumentType 19 via `BankMutationDirectBookings/{id}/Lines` met
  terugval
  `…/{id}?$expand=DocumentLineList($expand=Account,TaxRate)`. Per document één call — 800+ calls in een job is traag
  maar
  acceptabel (voortgang per 100 via `voortgang`-callback/logger). JournalEntryLines per document is géén alternatief:
  `JournalEntry` draagt alleen id/BookDate/DocumentType/EventID (api-verkenning "Boekingsdatum = BookDate").
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

from app.rlz.client import RlzApiError
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

DOCUMENT_COLLECTIES: tuple[tuple[str, str | None], ...] = (
    ("PurchaseInvoices", "Entity"),
    ("SalesInvoices", "Entity"),
    ("ManualJournals", "JournalEntryDiary"),
)
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
        if optioneel:
            bron.overgeslagen.append(f"{uitkomst.pad}: niet leesbaar ({melding}) — overgeslagen")
        else:
            bron.fouten.append(Fout(route=uitkomst.pad, status=uitkomst.fout.status_code, melding=melding))
        return False
    bron.gelezen[uitkomst.pad] = len(uitkomst.rijen)
    if not uitkomst.expand_gelukt:
        bron.overgeslagen.append(f"{uitkomst.pad}: $expand geweigerd — gelezen zonder relaties")
    return True


def lees_bron(
    client: LeesClient,
    *,
    regels_lezen: bool = True,
    voortgang: Callable[[str], None] | None = None,
) -> RlzBron:
    """Alles lezen, niets schrijven. Volgorde: documenten → bank (voor de huls-regel) → regels van GEBOEKTE documenten →
    rekeningen + statements → journaalregels → ledgers/taxrates."""
    bron = RlzBron()
    melden = voortgang or (lambda t: logger.info("vgg-replay: %s", t))

    for pad, expand in DOCUMENT_COLLECTIES:
        uitkomst = lees_collectie(client, pad, expand=expand)
        if _registreer(bron, uitkomst):
            bron.documenten[pad] = uitkomst.rijen
    receipts = lees_collectie(client, RECEIPTS)
    if _registreer(bron, receipts, optioneel=True):
        bekend = {doc_id(r) for rijen in bron.documenten.values() for r in rijen}
        bron.documenten[RECEIPTS] = [r for r in receipts.rijen if doc_id(r) not in bekend]

    bank = lees_collectie(client, "PaymentTransactions", expand=BANK_EXPAND)
    if _registreer(bron, bank):
        bron.bank = bank.rijen
        bron.bank_expand_gelukt = bank.expand_gelukt

    if regels_lezen:
        te_lezen = [(pad, r) for pad, r in bron.alle_documenten() if is_geboekt(r) and doc_id(r)]
        melden(f"regels lezen voor {len(te_lezen)} geboekte documenten")
        for n, (pad, r) in enumerate(te_lezen, start=1):
            rid = doc_id(r) or ""
            regels, route = lees_regels(client, pad, r)
            bron.regel_calls += 1
            if regels is None:
                bron.regel_fouten[rid] = route
            else:
                bron.regels[rid] = regels
                bron.regels_route[rid] = route
            if n % VOORTGANG_STAP == 0 or n == len(te_lezen):
                melden(f"regels: {n}/{len(te_lezen)} documenten ({len(bron.regel_fouten)} zonder regels)")

    rekeningen = lees_collectie(client, "PaymentAccounts")
    if _registreer(bron, rekeningen):
        bron.rekeningen = rekeningen.rijen
        for rek in bron.rekeningen:
            rid = str(rek.get("id") or "")
            if not rid:
                continue
            st = lees_collectie(client, f"PaymentAccounts/{rid}/Statements")
            if _registreer(bron, st, optioneel=True):
                bron.statements[rid] = st.rijen

    jr = lees_collectie(client, "JournalEntryLines", expand=JOURNAALREGEL_EXPAND)
    if _registreer(bron, jr):
        bron.journaalregels = jr.rijen

    for pad in ("Ledgers", "TaxRates"):
        uitkomst = lees_collectie(client, pad)
        if _registreer(bron, uitkomst):
            setattr(bron, pad.lower(), uitkomst.rijen)
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
