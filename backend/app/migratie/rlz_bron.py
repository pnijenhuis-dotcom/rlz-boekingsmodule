"""RLZ-bron voor de replay (run 2 VGG 12-09, blok 6; herzien blok 7b 13-09 en blok 7c 13-09) — LEES-ONLY lezers op alle
collecties die de migratie nodig heeft.

Eén gepagineerde reeks per collectie via `app/rlz/lezen.py::lees_collectie` (alleen GET's; een 400 op `$expand` valt
zichtbaar terug zónder expand; 403/404/5xx = één regel onder `fouten`, nooit een crash):

- documenten: PurchaseInvoices/SalesInvoices (`$expand=Entity`), ManualJournals (`$expand=JournalEntryDiary`),
  Receipts — op VGG is Receipts een UNIE-collectie van álle documenten (STAP-0 knip 12-09: de eerste Receipts-rij is de
  PurchaseInvoice RLZ-04-00000887); ná ontdubbeling tegen de drie andere collecties blijven de bank-directe boekingen
  (DocumentType 19, `IsSystemGenerated`) over. Geboekt = Status 2/3; Status 1 = concept; een systeemhuls = concept +
  `IsSystemGenerated` óf concept zonder Entity met |bedrag| + datum gelijk aan een OPEN PaymentTransaction (regel A,
  `bankdekking.is_bank_direct` lazy geïmporteerd — anders de minimale eigen versie hieronder).
- **regels + kop per GEBOEKT document = de DOCUMENT-vorm, één call per document (blok 7c 13-09, STAP-0 13-09 in
  api-verkenning "Memoriaalregels + EventID/BookDate — STAP-0 13-09"):** `{collectie}/{id}?$expand=DocumentLineList(
  $expand=Account,TaxRate)` geeft de kop (mét `BookDate`, dat op de PurchaseInvoices-COLLECTIE ontbreekt) én de regels.
  Bewezen feiten: (1) de collectie-vorm `…?$expand=DocumentLineList(…)` wordt door RLZ op PurchaseInvoices,
  SalesInvoices én ManualJournals STIL GENEGEERD (200, de sleutel ontbreekt; blok 7b probeerde 'm, 13-09 live: 0 van
  1.012 documenten) — de per-document-route is de facto de enige route en wordt niet meer als uitzondering gelogd;
  (2) de route `ManualJournals/{id}/Lines` BESTAAT NIET (404 mét HTML, ook zonder `$expand`; de Help-lijst kent alleen
  `ManualJournals/{id}`, `/Actions`, `/Uploads`, `/DocumentTaskHistory`, `/QuickPaymentSelections`) — voor memorialen is
  de document-vorm de enige regelroute; (3) `PurchaseInvoices/{id}/Lines` en `SalesInvoices/{id}/Lines` bestaan (Help)
  en blijven de zichtbare TERUGVAL als de document-vorm geen `DocumentLineList` geeft (dan zonder kop-aanvulling);
  (4) bank-directe boekingen (DocumentType 19): `BankMutationDirectBookings/{id}?$expand=DocumentLineList(…)` (bewezen,
  schrijf-PoC 02-08), terugval `…/{id}/Lines`. Alles door de token-bucket van `RlzClient` (`rlz_max_calls_per_seconde`)
  in tempo; een webfilter-403 die de client ná backoff nog ziet = `RlzBron.blokkering` gezet, lezen STOPT, het rapport
  wordt ROOD mét "RLZ-blokkering — meting ongeldig" — nooit doorrekenen met halve data. Een document zónder leesbare
  regels staat in `regel_fouten`; > 0 daarvan = rapport "ONVOLLEDIG — niet doorrekenen" (blok 7c punt 1).
- JournalEntryLines (`$expand=Account,JournalEntry`, volledig): per regel `DebitAmount`/`CreditAmount`/`VatAmount`/
  `Description`/`Account`; `JournalEntry` draagt ALLEEN `id`, `BookDate`, `DocumentType` en `EventID` — en **`EventID`
  is een klein geheel getal (soortcode van het type `JournalEvent`: 71 bij DocumentType 1, 51 bij 10), GEEN document-
  id** (STAP-0 13-09: `$filter=JournalEntry/EventID eq <guid>` = 400 "incompatible types 'JournalEvent' and 'Edm.Guid'";
  `JournalEntry/id eq <document-id>` = 0 treffers; het document zelf kent geen JournalEntry-navigatie). Een koppeling
  journaalregel ↔ document bestaat dus NIET in de RLZ-API; de RLZ-kolom van de saldibalans is de som per grootboek en
  de BookDate per document komt van de document-vorm (hierboven), niet van de journaalpost.
- PaymentTransactions `$expand=PaymentAccount,PaymentReferenceList($expand=Document)` (terugval zichtbaar),
  PaymentAccounts + `PaymentAccounts/{id}/Statements` (alleen koppen), Ledgers, TaxRates.

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
DOCTYPE_RESULTAAT = 0  # RLZ's eigen resultaatboekingen (7999 Winst / 8999 Verlies / 0509 Resultaat lopend boekjaar)
DOCTYPE_NAMEN: dict[int, str] = {
    DOCTYPE_RESULTAAT: "RLZ-resultaatposten (0)",
    DOCTYPE_INKOOP: "inkoop (1)",
    DOCTYPE_VERKOOP: "verkoop/receipt (10)",
    DOCTYPE_MEMORIAAL: "memoriaal (11)",
    DOCTYPE_BANK_DIRECT: "bank-direct (19)",
}
#: Blok 7d punt 2 — `JournalEntry.EventID` (soortcode `JournalEvent`, STAP-0 13-09) per DocumentType: welke codes de
#: DOCUMENTPOST zelf zijn (bewezen: 71 = inkoopfactuur geboekt, 51 = verkoop/receipt geboekt). Alle andere codes bij dat
#: DocumentType telt de volledigheidstoets apart als "betalings-/afletter-/correctieposten". Een DocumentType dat hier
#: NIET in staat (11 memoriaal, 19 bank-direct) is nog niet vastgesteld → de toets meldt "niet uitvoerbaar" mét de
#: codes die RLZ gaf, nooit stil (STAP-0 14-09 vult deze tabel aan; api-verkenning "Memoriaalregels — teken per regel,
#: STAP-0 14-09").
DOCUMENT_EVENTIDS: dict[int, frozenset[int]] = {
    DOCTYPE_INKOOP: frozenset({71}),
    DOCTYPE_VERKOOP: frozenset({51}),
}
#: Boekstukreeksen van bankdagboeken op VGG (contract §Besluiten 6) — alleen gebruikt als `bankdekking` ontbreekt.
BANK_REEKSEN: frozenset[str] = frozenset({"RLZ-09", "RLZ-25", "RLZ-28", "RLZ-46", "RLZ-60"})

#: Per collectie de basis-expand (relaties). Géén `DocumentLineList(…)` meer op de collectie: RLZ negeert die stil
#: (bewezen 13-09) — de regels komen per document via `regel_routes`.
DOCUMENT_COLLECTIES: tuple[tuple[str, str | None], ...] = (
    ("PurchaseInvoices", "Entity"),
    ("SalesInvoices", "Entity"),
    ("ManualJournals", "JournalEntryDiary"),
)
DOCUMENTVORM_EXPAND = "DocumentLineList($expand=Account,TaxRate)"
ROUTE_DOCUMENTVORM = "documentvorm"
ROUTE_LINES = "lines"
BLOKKERING_TEKST = "RLZ-blokkering — meting ongeldig"
ONVOLLEDIG_TEKST = "ONVOLLEDIG — niet doorrekenen"
#: Collecties mét een bewezen `…/{id}/Lines`-route (Help-lijst); ManualJournals staat er bewust NIET in (404-HTML).
LINES_ROUTE_COLLECTIES: frozenset[str] = frozenset({"PurchaseInvoices", "SalesInvoices", "BankMutationDirectBookings"})
#: Kop-velden die de document-vorm aanvult op de collectie-rij (de collectie draagt bij PurchaseInvoices geen BookDate).
KOP_AANVULLING_VELDEN: tuple[str, ...] = ("BookDate", "Date", "DueDate", "BaseInvoiceAmount", "BaseRemainingAmount")

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
    #: Blok 7c: kop-aanvulling uit de document-vorm per rlz_id (o.a. `BookDate`, dat op de collectie kan ontbreken).
    koppen: dict[str, dict[str, Any]] = field(default_factory=dict)
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
    #: Blok 7c 13-09: documenten waarvan kop + regels via de document-vorm kwamen resp. via de `/Lines`-terugval.
    regels_via_documentvorm: int = 0
    regels_via_lines: int = 0
    #: Gezet zodra de RLZ-webfilter ná backoff nog blokkeert: "<route>: <melding>". Lezen stopt; rapport = ongeldig.
    blokkering: str | None = None
    #: Tempo-tellers van de client (als die een `Tempo` draagt): calls, webfilter-treffers (hervat), gewacht (s).
    client_calls: int | None = None
    webfilter_treffers: int | None = None
    gewacht_seconden: float | None = None

    def alle_documenten(self) -> list[tuple[str, dict[str, Any]]]:
        return [(pad, r) for pad, rijen in self.documenten.items() for r in rijen]

    def rij_met_kop(self, rij: dict[str, Any]) -> dict[str, Any]:
        """De collectie-rij aangevuld met de kop-velden uit de document-vorm (BookDate …); de rij zelf wint alleen als
        de document-vorm het veld niet kent."""
        rid = doc_id(rij)
        kop = self.koppen.get(rid or "")
        if not kop:
            return rij
        aanvulling = {k: kop[k] for k in KOP_AANVULLING_VELDEN if kop.get(k) is not None}
        return {**rij, **aanvulling}


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
    """Regels uit een `/Lines`-antwoord (`value`-lijst) of uit een document-vorm (`DocumentLineList`); None = niet
    mee."""
    if isinstance(antwoord, list):
        return [r for r in antwoord if isinstance(r, dict)]
    if isinstance(antwoord, dict):
        if isinstance(antwoord.get("value"), list):
            return [r for r in antwoord["value"] if isinstance(r, dict)]
        if isinstance(antwoord.get("DocumentLineList"), list):
            return [r for r in antwoord["DocumentLineList"] if isinstance(r, dict)]
    return None


def _kop_uit(antwoord: Any) -> dict[str, Any] | None:
    """De kop-velden van een document-vorm-antwoord (alles behalve de regel-lijst); None bij een `/Lines`-antwoord."""
    if isinstance(antwoord, dict) and "value" not in antwoord and antwoord.get("id"):
        return {k: v for k, v in antwoord.items() if k != "DocumentLineList"}
    return None


def documentpad_van(collectie: str, rij: dict[str, Any]) -> str:
    """De collectie waaronder het document als record leeft (Receipts heeft geen record-route: DocumentType beslist)."""
    dt = documenttype_van(collectie, rij)
    if collectie in ("PurchaseInvoices", "SalesInvoices", "ManualJournals"):
        return collectie
    return {
        DOCTYPE_BANK_DIRECT: "BankMutationDirectBookings",
        DOCTYPE_INKOOP: "PurchaseInvoices",
        DOCTYPE_MEMORIAAL: "ManualJournals",
    }.get(dt, "SalesInvoices")


def regel_routes(collectie: str, rij: dict[str, Any]) -> list[tuple[str, dict[str, str], str]]:
    """Kandidaat-routes (pad, params, soort) voor kop + regels van één document, in volgorde van bewijs: eerst de
    document-vorm (kop mét BookDate + `DocumentLineList`), dan — alleen waar de Help-lijst 'm kent — `…/{id}/Lines`.
    ManualJournals heeft géén Lines-route (404-HTML, STAP-0 13-09)."""
    rlz_id = doc_id(rij) or ""
    pad = documentpad_van(collectie, rij)
    routes: list[tuple[str, dict[str, str], str]] = [
        (f"{pad}/{rlz_id}", {"$expand": DOCUMENTVORM_EXPAND}, ROUTE_DOCUMENTVORM)
    ]
    if pad in LINES_ROUTE_COLLECTIES:
        routes.append((f"{pad}/{rlz_id}/Lines", {"$expand": REGEL_EXPAND}, ROUTE_LINES))
    return routes


def lees_regels(
    client: LeesClient, collectie: str, rij: dict[str, Any]
) -> tuple[list[dict[str, Any]] | None, str, dict[str, Any] | None, str | None]:
    """(regels, route-tekst, kop, soort) — regels None = geen enkele route gaf regels (melding in de route-tekst)."""
    laatste = "geen route"
    for pad, params, soort in regel_routes(collectie, rij):
        try:
            antwoord = client.get(pad, params=params)
        except RlzWebfilterError:
            raise  # blokkering: de aanroeper stopt de hele run (nooit doorrekenen met halve data)
        except RlzApiError as exc:
            laatste = f"{pad}: {exc.status_code} {exc.body[:80]}"
            continue
        regels = _waarde_lijst(antwoord)
        if regels is not None:
            return regels, pad, _kop_uit(antwoord) if soort == ROUTE_DOCUMENTVORM else None, soort
        laatste = f"{pad}: antwoord zonder DocumentLineList/regels"
    if documentpad_van(collectie, rij) == "ManualJournals":
        laatste += " — ManualJournals/{id}/Lines bestaat niet in RLZ (404-HTML, STAP-0 13-09); geen terugval"
    return None, laatste, None, None


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
    """Alles lezen, niets schrijven. Volgorde: documenten (collecties, alleen relaties) → bank (voor de huls-regel) →
    kop + regels per GEBOEKT document via de document-vorm (in tempo) → rekeningen + statements → journaalregels →
    ledgers/taxrates. Een webfilter-blokkering stopt de reeks direct (`bron.blokkering`)."""
    bron = RlzBron()
    melden = voortgang or (lambda t: logger.info("vgg-replay: %s", t))

    def geblokkeerd() -> bool:
        if bron.blokkering:
            melden(f"{BLOKKERING_TEKST}: {bron.blokkering} — lezen gestopt")
            _tempo_tellers(bron, client)
            return True
        return False

    for pad, basis in DOCUMENT_COLLECTIES:
        uitkomst = lees_collectie(client, pad, expand=basis)
        if not _registreer(bron, uitkomst):
            if geblokkeerd():
                return bron
            continue
        bron.documenten[pad] = uitkomst.rijen
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
        te_lezen = [(pad, r) for pad, r in bron.alle_documenten() if is_geboekt(r) and doc_id(r)]
        melden(f"regels: {len(te_lezen)} geboekte documenten per document te lezen (document-vorm, in tempo)")
        for n, (pad, r) in enumerate(te_lezen, start=1):
            rid = doc_id(r) or ""
            try:
                regels, route, kop, soort = lees_regels(client, pad, r)
            except RlzWebfilterError as exc:
                bron.blokkering = f"{documentpad_van(pad, r)}/{rid}: webfilter 403 ná backoff — {exc.body[:160]}"
                bron.fouten.append(
                    Fout(route=f"{documentpad_van(pad, r)}/{{id}}", status=403, melding=BLOKKERING_TEKST)
                )
                geblokkeerd()
                return bron
            bron.regel_calls += 1
            if regels is None:
                bron.regel_fouten[rid] = route
                continue
            bron.regels[rid] = regels
            bron.regels_route[rid] = route
            if soort == ROUTE_DOCUMENTVORM:
                bron.regels_via_documentvorm += 1
                if kop:
                    bron.koppen[rid] = kop
            else:
                bron.regels_via_lines += 1
            if n % VOORTGANG_STAP == 0 or n == len(te_lezen):
                melden(
                    f"regels: {n}/{len(te_lezen)} documenten ({bron.regels_via_documentvorm} document-vorm, "
                    f"{bron.regels_via_lines} via /Lines, {len(bron.regel_fouten)} zonder regels)"
                )

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


def heeft_debet_credit_velden(regel: dict[str, Any]) -> bool:
    """Draagt de regel `DebitAmount` en/of `CreditAmount` (memoriaal-/journaalregel)?"""
    return als_bedrag(regel.get("DebitAmount")) is not None or als_bedrag(regel.get("CreditAmount")) is not None


def memoriaal_debet_credit(regel: dict[str, Any]) -> tuple[Decimal, Decimal] | None:
    """(debet, credit) van een MEMORIAALREGEL — UITSLUITEND uit `DebitAmount`/`CreditAmount` (blok 7d 14-09, punt 1).

    Nooit uit `CreditOrDebit` (RLZ geeft die code op lezen gespiegeld/rekeningzijde-afhankelijk terug — api-verkenning
    "Memoriaalregels — teken per regel, STAP-0 14-09" en de lees-observatie onder "Bank fallback-PoC") en nooit uit
    `NetAmount`: de saldibalans-nameting 13-09 klapte precies de regels op passiva- en opbrengstrekeningen om (0500,
    1601–1606, 0899, 1710, 8000, 8199) terwijl activa- en kostenregels (1100, 1011, 4000, 7000) klopten — een teken dat
    NIET debet/credit is maar de "normale zijde" van de rekening volgt. None = de regel draagt geen van beide
    bedragvelden → de aanroeper maakt het document ZICHTBAAR niet vertaalbaar (nooit een gok via een code)."""
    if not heeft_debet_credit_velden(regel):
        return None
    d = als_bedrag(regel.get("DebitAmount")) or Decimal("0.00")
    c = als_bedrag(regel.get("CreditAmount")) or Decimal("0.00")
    return d.quantize(Decimal("0.01")), c.quantize(Decimal("0.01"))


def debet_credit(regel: dict[str, Any]) -> tuple[Decimal, Decimal]:
    """(debet, credit) uit een document- of journaalregel: `DebitAmount`/`CreditAmount` als ze er zijn (memoriaal,
    JournalEntryLines), anders `NetAmount` (+ `TaxAmount`) mét teken: positief = debet (inkoop) — de aanroeper keert
    voor verkoopregels om. De `CreditOrDebit`-code wordt sinds blok 7d (14-09) NERGENS meer als richting gelezen."""
    dc = memoriaal_debet_credit(regel)
    if dc is not None:
        return dc
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


def journaalregel_documenttype(regel: dict[str, Any]) -> int | None:
    """`JournalEntry.DocumentType` (1 inkoop, 10 verkoop/receipt, 11 memoriaal, …) — het enige soort-kenmerk dat een
    journaalregel draagt (STAP-0 13-09)."""
    je = regel.get("JournalEntry")
    if isinstance(je, dict):
        return als_int(je.get("DocumentType"))
    return als_int(regel.get("DocumentType"))


def journaalregel_journaalpost_id(regel: dict[str, Any]) -> str | None:
    je = regel.get("JournalEntry")
    return ref_id(je) if isinstance(je, dict) else None


def journaalregel_eventid(regel: dict[str, Any]) -> int | None:
    """`JournalEntry.EventID` als soortcode (int); een dict-vorm (`{id: n}` of `{Name: …}`) wordt op `id` gelezen."""
    je = regel.get("JournalEntry")
    ev = je.get("EventID") if isinstance(je, dict) else regel.get("EventID")
    if isinstance(ev, dict):
        ev = ev.get("id")
    return als_int(ev)


def is_resultaatpost(regel: dict[str, Any]) -> bool:
    """Blok 7d punt 3: DocumentType 0 = RLZ's eigen resultaatboeking — nooit gemigreerd, Odoo berekent het resultaat."""
    return journaalregel_documenttype(regel) == DOCTYPE_RESULTAAT


def journaalregel_bron_id(regel: dict[str, Any]) -> str | None:
    """Het document/de mutatie waar de journaalregel bij hoort — ALLEEN als RLZ ooit een expliciete verwijzing
    (`Document.id`, `SourceDocument.id`, `DocumentId`) zou meegeven. `JournalEntry.EventID` is GEEN bron-id maar een
    soortcode (int; STAP-0 13-09) en telt hier bewust niet — op de huidige API geeft dit dus altijd None."""
    for sleutel in ("Document", "SourceDocument"):
        rid = ref_id(regel.get(sleutel))
        if rid:
            return rid
    if regel.get("DocumentId"):
        return str(regel["DocumentId"])
    return None
