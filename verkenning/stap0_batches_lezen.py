#!/usr/bin/env python3
"""STAP-0 (LEES-ONLY) — incasso-/betaalbatches uit Reeleezee (run 11-09 middag, blok 10).

Vraag Peter 11-09: "RLZ herkent zijn eigen batches, wij niet." Een bankregel die het TOTAAL van een SEPA-incasso- of
betaalbatch draagt, koppelt RLZ in de UI aan álle onderliggende facturen; onze matchmotor ziet één bedrag zonder open
post en valt terug op "handmatig". Deze STAP-0 brengt lees-only in kaart wat de API over batches prijsgeeft:

    1. Help-routelijst + modelpagina's (er is géén $metadata — 08-09/10-09 herbevestigd): Remittances, DirectDebits,
       CreditTransfers, PaymentTransaction.Batch (PaymentTransactionBatch), PaymentBatchId, PaymentBatchInformation.
    2. Kandidaatroutes met $top=5: bestaat (200/404/400), velden, regels (items) en via welke $expand.
    3. Hoe RLZ een binnengekomen batch-bankregel koppelt: PaymentTransactions mét
       $expand=Batch,PaymentReferenceList($expand=Document),MatchedPaymentItem — één mutatie, N koppelingen?
    4. R-transacties (storno/afkeuring): ReturnReason, negatieve items, zoektermen.

Dit script doet UITSLUITEND GET-requests. Elke andere methode wordt door de `LeesClient` geweigerd (SystemExit) —
er is geen schrijfpad in dit bestand; ook `…/Actions` wordt nooit aangeroepen (alleen `GET …/Actions` = de
aangeboden-acties-lijst). Het laadt `verkenning/.env` zelf via dotenv; credentials en administratie-id's worden
nooit geprint (GUID's → eerste 8 tekens, IBAN's → laatste 4, namen → initialen; bedragen blijven).

Gebruik: backend/.venv/bin/python verkenning/stap0_batches_lezen.py [help|enums|admins|verdieping|sleutel|alles] [--login PREFIX …]
Output:  verkenning/output/stap0_batches_<stap>.json (gitignored) — geanonimiseerd met dezelfde functie als de print.
"""

from __future__ import annotations

import html
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER.parent / "backend"))

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from app.rlz.client import BASE_URL, RlzApiError, RlzClient  # noqa: E402
from app.rlz.credentials import lees_env_login  # noqa: E402

load_dotenv(HIER / ".env")

OUTPUT = HIER / "output"
HELP_ROOT = "https://apps.reeleezee.nl"
LOGIN_PREFIXEN = ("TESTADMIN", "BLOW", "UNIVERSAL")  # welke gevuld zijn bepaalt de .env; nooit hier hardgecodeerd
ROUTE_WOORDEN = re.compile(
    r"Direct|Debit|Collection|Payment|Batch|Sepa|Remittance|Order|File|Transmission|Mandate|Expected|Return|Revers|Reject",
    re.I,
)
ACTIE_WOORDEN = re.compile(r"remit|debit|transfer|batch|sepa|export|return|revers|reject|storn|incass|betaal|pay", re.I)
GUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{8,30}\b")
NAAM_SLEUTELS = {"Name", "OwnerName", "DebtorName", "CreditorName", "CounterName", "SearchName", "FullName",
                 "AccountHolder", "EntityName", "CounterPartyName"}
IBAN_SLEUTELS = {"IBAN", "CounterAccount", "Iban", "CounterIban", "DebtorIban", "CreditorIban"}


class LeesClient(RlzClient):
    """RlzClient die élke niet-GET weigert. Lees-only STAP-0: geen PUT/POST/DELETE, in geen enkele stap."""

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if method.upper() != "GET":
            raise SystemExit(f"LEES-ONLY: {method} {path} geweigerd — dit script schrijft nooit.")
        return super()._request(method, path, **kwargs)

    def for_administration(self, admin_id: str) -> LeesClient:
        return LeesClient(username="", password="", admin_id=admin_id, client=self._client)


# ------------------------------------------------------------------ anonimisering ---------------------------------


def _initialen(tekst: str) -> str:
    woorden = [w for w in re.split(r"\s+", tekst.strip()) if w]
    return "".join(w[0].upper() + "." for w in woorden[:4]) if woorden else ""


def _tekst_anon(t: str) -> str:
    t = GUID_RE.sub(lambda m: m.group(0)[:8] + "…", t)
    t = IBAN_RE.sub(lambda m: "…" + m.group(0)[-4:], t)
    return t


def anonimiseer(obj: Any, sleutel: str | None = None) -> Any:
    """GUID's → eerste 8, IBAN's → laatste 4, naamvelden → initialen; recursief. Bedragen/datums/enums blijven."""
    if isinstance(obj, dict):
        if "ShortDescription" in obj:  # enum-lid: Name is de enum-naam, geen persoon
            return {k: (v if k == "Name" else anonimiseer(v, k)) for k, v in obj.items()}
        return {k: anonimiseer(v, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [anonimiseer(v, sleutel) for v in obj]
    if isinstance(obj, str):
        if sleutel in NAAM_SLEUTELS:
            return _initialen(_tekst_anon(obj))
        if sleutel in IBAN_SLEUTELS or (sleutel == "AccountNumber" and IBAN_RE.fullmatch(obj or "")):
            return "…" + obj[-4:] if obj else obj
        return _tekst_anon(obj)
    return obj


def _nu() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _kort(obj: Any, n: int = 600) -> str:
    s = json.dumps(anonimiseer(obj), default=str, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + " …"


def _veilig(fn, *a, **kw) -> Any:
    try:
        return fn(*a, **kw)
    except RlzApiError as e:
        return {"_fout": e.status_code, "_body": _tekst_anon(e.body[:240])}


def _rauw(c: LeesClient, path: str, params: dict[str, Any] | None = None) -> Any:
    """GET met rauwe afhandeling: JSON als het JSON is, anders status + content-type + lengte (body niet bewaard)."""
    try:
        r = c.request_raw("GET", path, params=params)
    except RlzApiError as e:
        return {"_fout": e.status_code, "_body": _tekst_anon(e.body[:240])}
    try:
        return r.json()
    except ValueError:
        return {"_status": r.status_code, "_content_type": r.headers.get("content-type"), "_lengte": len(r.content),
                "_body_kop": _tekst_anon(r.text[:120])}


def _rows(uit: Any) -> list[dict[str, Any]]:
    if isinstance(uit, dict) and isinstance(uit.get("value"), list):
        return uit["value"]
    return uit if isinstance(uit, list) else []


def _samenvat_route(uit: Any) -> dict[str, Any]:
    """Per kandidaatroute: status, aantal, sleutels, eerste rij — de vaste kolommen van de routes-tabel."""
    if isinstance(uit, dict) and "_fout" in uit:
        return {"status": uit["_fout"], "body": uit["_body"]}
    if isinstance(uit, dict) and "_status" in uit:
        return {"status": uit["_status"], "geen_json": True, "content_type": uit.get("_content_type"), "lengte": uit.get("_lengte")}
    rijen = _rows(uit)
    return {
        "status": 200,
        "count": uit.get("@odata.count") if isinstance(uit, dict) else None,
        "aantal_in_top": len(rijen),
        "sleutels": sorted(rijen[0].keys()) if rijen else (sorted(uit.keys()) if isinstance(uit, dict) else None),
        "eerste": rijen[0] if rijen else (uit if isinstance(uit, dict) and "value" not in uit else None),
    }


def _html_naar_tekst(t: str) -> str:
    t = re.sub(r"<script.*?</script>", "", t, flags=re.S)
    t = re.sub(r"<style.*?</style>", "", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return html.unescape(re.sub(r"\s+", " ", t)).strip()


def _model_uit_help(tekst: str) -> list[str]:
    m = re.search(r"(?:Body Parameters|Resource Description|Response Information Resource Description) (.*?) (?:Request Formats|Response Formats|$)", tekst)
    bron = m.group(1) if m else tekst
    velden = re.findall(r" ([A-Z][A-Za-z0-9]+) ((?:Collection of )?[A-Za-z][A-Za-z0-9 ]*?) None\.", bron)
    return [f"{naam}: {typ.strip()}" for naam, typ in velden]


def _schrijf(stap: str, rapport: dict[str, Any]) -> Path:
    OUTPUT.mkdir(exist_ok=True)
    pad = OUTPUT / f"stap0_batches_{stap}.json"
    pad.write_text(json.dumps(anonimiseer(rapport), indent=2, default=str, ensure_ascii=False))
    print(f"\n→ rapport: {pad}")
    return pad


# ------------------------------------------------------------------ logins ----------------------------------------


def _logins(gewenst: list[str]) -> list[tuple[str, LeesClient, list[str]]]:
    """(prefix, root-client, admin-id's) per gevulde .env-login. De Help-pagina's gebruiken de eerste login."""
    uit = []
    for prefix in gewenst or LOGIN_PREFIXEN:
        login = lees_env_login(prefix)
        if login is None:
            print(f"   login {prefix}: niet gevuld in verkenning/.env — overgeslagen")
            continue
        root = LeesClient(username=login[0], password=login[1])
        try:
            admins = root.list_administrations()
        except RlzApiError as e:
            print(f"   login {prefix}: Administrations → {e.status_code} — overgeslagen")
            continue
        ids = [a["id"] for a in admins]
        print(f"   login {prefix}: ziet {len(ids)} administratie(s): {[i[:8] + '…' for i in ids]}")
        uit.append((prefix, root, ids))
    if not uit:
        raise SystemExit("Geen enkele lees-login gevuld (TESTADMIN/BLOW/UNIVERSAL) — STAP-0 kan niet draaien.")
    return uit


def _help_http(root: LeesClient) -> httpx.Client:
    """GET-only httpx-client voor de HTML-Help (zelfde Basic-Auth-header als de RlzClient)."""
    auth = root._client.headers.get("Authorization")
    return httpx.Client(headers={"Authorization": auth, "Accept": "text/html"}, timeout=60)


# ------------------------------------------------------------------ (1) Help ---------------------------------------


def stap_help(root: LeesClient) -> dict[str, Any]:
    rapport: dict[str, Any] = {"ts": _nu(), "base": BASE_URL}
    for pad in ("$metadata",):
        r = _veilig(root.request_raw, "GET", pad, headers={"Accept": "application/xml"})
        rapport[f"metadata:{pad}"] = r if isinstance(r, dict) else {"status": r.status_code, "lengte": len(r.text)}
    print("$metadata:", _kort(rapport["metadata:$metadata"], 200))
    h = _help_http(root)
    r = h.get(f"{HELP_ROOT}/api/v1/Help")
    routes = re.findall(r'href="/api/v1/Help/Api/([^"]+)"[^>]*>([^<]+)</a>', r.text)
    rapport["help_routes_totaal"] = len(routes)
    relevant = sorted({html.unescape(naam) for _, naam in routes if ROUTE_WOORDEN.search(naam)})
    # ruis weg: Order/File matchen ook op Orders/Uploads e.d. — alles bewaren in het rapport, print alleen de kern
    rapport["help_routes_relevant"] = relevant
    kern = [n for n in relevant if re.search(r"Remittance|DirectDebit|CreditTransfer|Batch|Sepa|Expected|Mandate|Return|Revers|Reject|PaymentItem|PaymentTransaction", n)]
    print(f"Help: {len(routes)} routes; treffers op batch-woorden: {len(relevant)}; kern ({len(kern)}):")
    for n in kern:
        print("   ", n)
    modellen: dict[str, Any] = {}
    for slug in (
        "GET-adminId-Remittances", "GET-adminId-Remittances-id", "GET-adminId-Remittances-id-Actions",
        "GET-adminId-Remittances-id-Export", "POST-adminId-Remittances-id-Actions",
        "GET-adminId-DirectDebits_expectedPaymentsFilter",
        "GET-adminId-CreditTransfers_paymentRecommendationCreditSalesinvoicesFilter_expectedPaymentsFilter",
        "GET-ExpectedPaymentsFilters", "GET-RemittanceStatuses", "GET-SepaDirectDebitSequenceTypes",
        "GET-SepaDirectDebitTypes", "GET-adminId-PaymentItems", "GET-adminId-PaymentTransactions-id",
    ):
        rr = h.get(f"{HELP_ROOT}/api/v1/Help/Api/{slug}")
        if rr.status_code >= 400:
            modellen[slug] = {"_fout": rr.status_code}
            continue
        tekst = _html_naar_tekst(rr.text)
        beschrijving = re.search(r"Help Page Home [A-Z]+ [^ ]+ (.*?) Request Information", tekst)
        modellen[slug] = {"beschrijving": beschrijving.group(1)[:240] if beschrijving else None,
                          "velden": _model_uit_help(tekst), "tekst_kort": tekst[:1500]}
        print(f"\n== Help {slug}: {beschrijving.group(1)[:160] if beschrijving else '?'}")
        for v in modellen[slug]["velden"][:50]:
            print("     ", v)
    rapport["help_modellen"] = modellen
    resource: dict[str, Any] = {}
    for naam in ("PaymentTransactionBatch", "Remittance", "DirectDebit", "CreditTransfer", "PaymentTerm", "PaymentItem",
                 "PaymentTransaction", "PaymentReference", "ExpectedPayment", "SepaDirectDebit", "BankRelation"):
        rr = h.get(f"{HELP_ROOT}/api/v1/Help/ResourceModel", params={"modelName": naam})
        if rr.status_code >= 400:
            resource[naam] = {"_fout": rr.status_code}
            print(f"\n== ResourceModel {naam}: {rr.status_code}")
            continue
        tekst = _html_naar_tekst(rr.text)
        velden = re.findall(r" ([A-Z][A-Za-z0-9]+) ((?:Collection of )?[A-Za-z][A-Za-z0-9 ]*?) (?:None\.|Required|Max)", tekst)
        resource[naam] = {"velden": [f"{a}: {b.strip()}" for a, b in velden], "tekst_kort": tekst[:1200]}
        print(f"\n== ResourceModel {naam}: {len(velden)} velden")
        for a, b in velden[:60]:
            print(f"      {a}: {b.strip()}")
    rapport["resource_modellen"] = resource
    return rapport


# ------------------------------------------------------------------ (2) enumeraties --------------------------------


def stap_enums(root: LeesClient) -> dict[str, Any]:
    rapport: dict[str, Any] = {"ts": _nu()}
    for route in ("RemittanceStatuses", "SepaDirectDebitSequenceTypes", "SepaDirectDebitTypes", "ExpectedPaymentsFilters",
                  "PaymentRecommendationCreditSalesinvoicesFilters", "PaymentStatuses", "PaymentTransactionTypes",
                  "PaymentMethods", "PaymentReconciliationSources", "ActionKinds"):
        uit = _veilig(root.get, route)
        waarden = _rows(uit) or uit
        if route == "ActionKinds" and isinstance(waarden, list):
            treffers = [w for w in waarden if ACTIE_WOORDEN.search(json.dumps(w, ensure_ascii=False))]
            rapport["ActionKinds_relevant"] = treffers
            print(f"\n== ActionKinds: {len(waarden)} leden, relevant {len(treffers)}:")
            for w in treffers:
                print("    ", _kort(w, 160))
            continue
        rapport[route] = waarden
        print(f"\n== {route}: {_kort(waarden, 900)}")
    return rapport


# ------------------------------------------------------------------ (3) per administratie ---------------------------

KANDIDAATROUTES: tuple[tuple[str, dict[str, str]], ...] = (
    ("Remittances", {"$top": "5", "$count": "true", "$orderby": "Date desc"}),
    ("Remittances", {"$top": "5"}),
    ("DirectDebits", {"$top": "5"}),
    ("DirectDebits", {"expectedPaymentsFilter": "1", "$top": "5"}),
    ("DirectDebits", {"expectedPaymentsFilter": "0", "$expand": "Document,PaymentTerm,BankRelation", "$top": "5"}),
    ("CreditTransfers", {"$top": "5"}),
    ("CreditTransfers", {"paymentRecommendationCreditSalesinvoicesFilter": "2", "expectedPaymentsFilter": "1", "$top": "5"}),
    ("CreditTransfers", {"paymentRecommendationCreditSalesinvoicesFilter": "2", "expectedPaymentsFilter": "0", "$expand": "Document,PaymentTerm,BankRelation,ExportFile", "$top": "5"}),
    ("PaymentBatches", {"$top": "5"}),
    ("DirectDebitBatches", {"$top": "5"}),
    ("PaymentTransactionBatches", {"$top": "5"}),
    ("Batches", {"$top": "5"}),
    ("PaymentOrders", {"$top": "5"}),
    ("CollectionOrders", {"$top": "5"}),
    ("SepaFiles", {"$top": "5"}),
    ("TransmittedFiles", {"$top": "5"}),
    ("Mandates", {"$top": "5"}),
    ("DirectDebitMandates", {"$top": "5"}),
    ("Files", {"$top": "5"}),
    ("ReeleezeeFiles", {"$top": "5"}),
    ("PaymentItems", {"$top": "5", "$count": "true"}),
    ("PaymentItems", {"$top": "5", "$expand": "Document,PaymentTerm,BankRelation,PaymentAccount"}),
    ("PaymentItems", {"$top": "5", "$filter": "PaymentInProgress eq true", "$count": "true"}),
    ("PaymentItems", {"$top": "5", "$filter": "ExportFile ne null", "$count": "true"}),
    ("PaymentItems", {"$top": "5", "$filter": "PaymentStatus eq 2", "$count": "true"}),
    ("PaymentTransactions", {"$top": "5", "$expand": "Batch", "$orderby": "BookDate desc"}),
    ("PaymentTransactions", {"$top": "5", "$filter": "Batch ne null", "$count": "true"}),
    ("PaymentTransactions", {"$top": "5", "$filter": "Batch/id ne null", "$count": "true"}),
    ("PaymentTransactions", {"$top": "5", "$filter": "PaymentBatchId ne null", "$count": "true"}),
    ("PaymentTransactions", {"$top": "5", "$filter": "PaymentBatchId ne ''", "$count": "true"}),
    ("PaymentTransactions", {"$top": "5", "$filter": "ReturnReason ne null", "$count": "true"}),
    ("PaymentTransactions", {"$top": "5", "$filter": "Type eq 3", "$count": "true"}),
)
ZOEKTERMEN_R = ("storno", "stornering", "terugboeking", "RETURN", "RTRN", "reversal", "afgekeurd", "incasso", "SEPA", "batch", "verzameld")


def _tx_samenvatting(tx: dict[str, Any]) -> dict[str, Any]:
    refs = []
    for r in tx.get("PaymentReferenceList") or []:
        d = r.get("Document") or {}
        refs.append({"Sequence": r.get("Sequence"), "Amount": r.get("Amount"),
                     "Source": r.get("PaymentReconciliationSource"),
                     "Document": {k: d.get(k) for k in ("DocumentType", "Status", "ReceiptNumber", "Reference", "IsSystemGenerated")} if d else None})
    return {"id": tx.get("id"), "BookDate": tx.get("BookDate"), "Amount": tx.get("Amount"), "OpenAmount": tx.get("OpenAmount"),
            "Type": tx.get("Type"), "Name": tx.get("Name"), "Reference": (tx.get("Reference") or "")[:160],
            "CounterAccount": tx.get("CounterAccount"), "PaymentBatchId": tx.get("PaymentBatchId"),
            "ReturnReason": tx.get("ReturnReason"), "Batch": tx.get("Batch"),
            "MatchedPaymentItem": (tx.get("MatchedPaymentItem") or {}).get("id") if tx.get("MatchedPaymentItem") else None,
            "refs_echt": [x for x in refs if not (x["Document"] or {}).get("IsSystemGenerated")],
            "refs_huls": sum(1 for x in refs if (x["Document"] or {}).get("IsSystemGenerated")),
            "_sleutels": sorted(tx.keys())}


def stap_admin(c: LeesClient, label: str) -> dict[str, Any]:
    rapport: dict[str, Any] = {"ts": _nu(), "administratie": label, "routes": []}
    print(f"\n######## administratie {label}")

    # 3a. kandidaatroutes
    for pad, params in KANDIDAATROUTES:
        uit = _rauw(c, pad, params=params)
        s = _samenvat_route(uit)
        s["route"] = pad
        s["params"] = params
        rapport["routes"].append(s)
        print(f"   {pad} {params}: status {s.get('status')} count={s.get('count')} n={s.get('aantal_in_top')} sleutels={_kort(s.get('sleutels'), 400)}")
        if s.get("eerste"):
            print("        eerste:", _kort(s["eerste"], 500))

    # 3b. Remittances verdiept: detail, Actions (GET = aangeboden acties), DocumentTaskHistory, $expand-varianten
    rem = _rauw(c, "Remittances", params={"$top": "5", "$orderby": "Date desc"})
    if isinstance(rem, dict) and "_fout" in rem:
        rem = _rauw(c, "Remittances", params={"$top": "5"})
    rijen = _rows(rem)
    rapport["remittances"] = {"aantal_top": len(rijen), "sleutels": sorted(rijen[0].keys()) if rijen else None, "detail": []}
    for rij in rijen[:3]:
        rid = rij.get("id")
        detail: dict[str, Any] = {"kop": rij}
        for exp in ("PaymentItemList", "PaymentItems", "Items", "Lines", "RemittanceLineList", "DocumentList", "PaymentAccount", "PaymentTransactionList", "PaymentTransactions"):
            d = _rauw(c, f"Remittances/{rid}", params={"$expand": exp})
            detail[f"expand:{exp}"] = _samenvat_route(d) if isinstance(d, dict) and ("_fout" in d or "_status" in d) else {"status": 200, "sleutels": sorted(d.keys()), "expand_gevuld": isinstance(d.get(exp), list) and len(d.get(exp)), "voorbeeld": (d.get(exp) or [None])[0] if isinstance(d.get(exp), list) else d.get(exp)}
        detail["Actions(GET)"] = _rauw(c, f"Remittances/{rid}/Actions")
        detail["DocumentTaskHistory"] = _rauw(c, f"Remittances/{rid}/DocumentTaskHistory", params={"$top": "5"})
        detail["Export(kop)"] = _rauw(c, f"Remittances/{rid}/Export")
        if isinstance(detail["Export(kop)"], dict) and "value" in detail["Export(kop)"]:
            detail["Export(kop)"] = {"json_sleutels": sorted(detail["Export(kop)"].keys())}
        rapport["remittances"]["detail"].append(detail)
        print(f"\n   Remittance {str(rid)[:8]}…: {_kort(rij, 600)}")
        for k, v in detail.items():
            if k != "kop":
                print(f"      {k}: {_kort(v, 400)}")

    # 3c. hoe hangt een batch-bankregel aan zijn facturen? mutaties met ≥ 2 echte koppelingen
    expand = "PaymentReferenceList($expand=Document),MatchedPaymentItem,Batch"
    alle = _rows(_veilig(c.get, "PaymentTransactions", params={"$expand": expand, "$orderby": "BookDate desc", "$top": "400"}))
    if not alle:
        alle = _rows(_veilig(c.get, "PaymentTransactions", params={"$expand": "PaymentReferenceList($expand=Document),MatchedPaymentItem", "$orderby": "BookDate desc", "$top": "400"}))
        rapport["expand_batch_faalt"] = True
    samen = [_tx_samenvatting(t) for t in alle]
    meervoudig = [s for s in samen if len(s["refs_echt"]) >= 2]
    met_batch = [s for s in samen if s.get("Batch") or s.get("PaymentBatchId")]
    met_return = [s for s in samen if s.get("ReturnReason")]
    rapport["mutaties"] = {"gelezen": len(alle), "meervoudig_gekoppeld": len(meervoudig), "met_batch_of_batchid": len(met_batch),
                          "met_returnreason": len(met_return), "type_verdeling": {},
                          "voorbeelden_meervoudig": meervoudig[:6], "voorbeelden_batch": met_batch[:6], "voorbeelden_return": met_return[:6]}
    for s in samen:
        rapport["mutaties"]["type_verdeling"][str(s["Type"])] = rapport["mutaties"]["type_verdeling"].get(str(s["Type"]), 0) + 1
    print(f"\n   PaymentTransactions gelezen {len(alle)}: ≥2 echte koppelingen {len(meervoudig)}, Batch/PaymentBatchId gevuld {len(met_batch)}, ReturnReason gevuld {len(met_return)}, types {rapport['mutaties']['type_verdeling']}")
    for s in meervoudig[:6]:
        print(f"      MEERVOUDIG {s['BookDate'][:10]} {s['Amount']} open {s['OpenAmount']} Name={anonimiseer(s['Name'], 'Name')!r} refs={len(s['refs_echt'])} som_refs={round(sum(float(x['Amount'] or 0) for x in s['refs_echt']), 2)} batchid={s['PaymentBatchId']!r} ref={_tekst_anon(s['Reference'])[:100]!r}")
        for x in s["refs_echt"][:5]:
            print("           ", _kort(x, 220))
    for s in met_batch[:6]:
        print(f"      BATCH {s['BookDate'][:10]} {s['Amount']} batchid={s['PaymentBatchId']!r} Batch={_kort(s['Batch'], 300)}")
    for s in met_return[:6]:
        print(f"      RETURN {s['BookDate'][:10]} {s['Amount']} ReturnReason={s['ReturnReason']!r} ref={_tekst_anon(s['Reference'])[:100]!r}")

    # 3d. verwachte bankregels (Type 2) — dragen die Batch/PaymentBatchId?
    verwacht = _rows(_veilig(c.get, "PaymentTransactions", params={"searchstring": "", "showExpectedPaymentTransactions": "true", "$top": "10", "$expand": "Batch"}))
    if not verwacht:
        verwacht = _rows(_veilig(c.get, "PaymentTransactions", params={"searchstring": "", "showExpectedPaymentTransactions": "true", "$top": "10"}))
    rapport["verwachte_regels"] = [_tx_samenvatting(t) for t in verwacht if t.get("Type") == 2][:5]
    print(f"\n   verwachte bankregels (Type 2) in top 10 met showExpected: {len(rapport['verwachte_regels'])}")
    for s in rapport["verwachte_regels"][:3]:
        print("      ", _kort({k: s[k] for k in ('BookDate', 'Amount', 'Type', 'PaymentBatchId', 'Batch', '_sleutels')}, 500))

    # 3e. facturen in een betaalbatch: PaymentTermList.PaymentBatchInformation
    facturen = _rows(_veilig(c.get, "PurchaseInvoices", params={"$expand": "PaymentTermList,QuickPaymentSelection", "$orderby": "Date desc", "$top": "60"}))
    in_batch = []
    term_sleutels: set[str] = set()
    for f in facturen:
        for t in f.get("PaymentTermList") or []:
            term_sleutels |= set(t.keys())
            if t.get("PaymentBatchInformation"):
                in_batch.append({"ReceiptNumber": f.get("ReceiptNumber"), "Status": f.get("Status"), "BaseRemainingAmount": f.get("BaseRemainingAmount"),
                                 "QuickPaymentSelection": (f.get("QuickPaymentSelection") or {}).get("Description"),
                                 "term": {k: t.get(k) for k in ("PaymentBatchInformation", "PaymentStatus", "OpenAmountBase", "DueDate", "PaymentMethod", "PaymentInProgress", "ExportFile")}})
    rapport["facturen"] = {"gelezen": len(facturen), "paymentterm_sleutels": sorted(term_sleutels), "in_betaalbatch": in_batch[:10], "aantal_in_batch": len(in_batch)}
    print(f"\n   PurchaseInvoices top 60: PaymentTerm-sleutels {sorted(term_sleutels)}; met PaymentBatchInformation: {len(in_batch)}")
    for x in in_batch[:5]:
        print("      ", _kort(x, 400))
    verkoop = _rows(_veilig(c.get, "SalesInvoices", params={"$expand": "PaymentTermList", "$orderby": "Date desc", "$top": "60"}))
    v_in_batch = [{"ReceiptNumber": f.get("ReceiptNumber"), "term": t} for f in verkoop for t in (f.get("PaymentTermList") or []) if t.get("PaymentBatchInformation")]
    rapport["verkoopfacturen"] = {"gelezen": len(verkoop), "in_incassobatch": v_in_batch[:10], "aantal": len(v_in_batch)}
    print(f"   SalesInvoices top 60: met PaymentBatchInformation (incasso): {len(v_in_batch)}")
    for x in v_in_batch[:5]:
        print("      ", _kort(x, 400))

    # 3f. R-transacties via zoektermen
    rapport["zoek"] = {}
    for term in ZOEKTERMEN_R:
        uit = _veilig(c.get, "PaymentTransactions", params={"searchstring": term, "showExpectedPaymentTransactions": "false", "$top": "5", "$expand": "PaymentReferenceList($expand=Document)"})
        rijen = _rows(uit)
        rapport["zoek"][term] = {"aantal_top5": len(rijen), "voorbeelden": [_tx_samenvatting(t) for t in rijen[:3]]} if rijen or not isinstance(uit, dict) or "_fout" not in uit else uit
        if rijen:
            print(f"\n   searchstring={term!r}: {len(rijen)} — {_kort([(s['BookDate'][:10], s['Amount'], s['ReturnReason'], _tekst_anon(s['Reference'])[:70]) for s in (rapport['zoek'][term]['voorbeelden'])], 500)}")
        else:
            print(f"   searchstring={term!r}: {_kort(uit, 120) if isinstance(uit, dict) and '_fout' in uit else 0}")

    # 3g. incassomachtigingen op relaties (Vendors/Customers BankRelations: DirectDebitAuthorization)
    br = _rows(_veilig(c.get, "Customers", params={"$top": "5"}))
    machtiging = []
    for k in br[:5]:
        rel = _rows(_veilig(c.get, f"Customers/{k['id']}/BankRelations"))
        for x in rel:
            machtiging.append({k2: x.get(k2) for k2 in x if re.search(r"Direct|Mandate|Debit|Sequence|Sepa|Authoriz", k2)} | {"_sleutels": sorted(x.keys())})
    rapport["bankrelaties_klanten"] = machtiging[:5]
    print(f"\n   Customers/{{id}}/BankRelations (incasso-velden): {_kort(machtiging[:2], 600)}")
    return rapport


# ------------------------------------------------------------------ (4) verdieping batch-id + onderweg + R ----------

SEPA_REDENCODES = ("retour", "terug", "MD06", "AC04", "AM04", "MS03", "AC01", "AG01", "MD01", "SL01", "reden", "geweigerd", "onbekend rekeningnummer")


def stap_verdieping(c: LeesClient, label: str) -> dict[str, Any]:
    """Ná de eerste meting: PaymentBatchId-mutaties uitgediept (verdeling, teken, koppelingen, Batch/Statement), items
    'onderweg' → document mét PaymentTermList, SEPA-redencodes als zoekterm, Statement-koppen."""
    rapport: dict[str, Any] = {"ts": _nu(), "administratie": label}
    print(f"\n######## verdieping {label}")
    expand = "PaymentReferenceList($expand=Document),MatchedPaymentItem,Batch,Statement,PaymentAccount"
    met_id = _rows(_veilig(c.get, "PaymentTransactions", params={"$filter": "PaymentBatchId ne null", "$expand": expand, "$orderby": "BookDate desc", "$top": "100", "$count": "true"}))
    per_id: dict[str, list] = {}
    for t in met_id:
        per_id.setdefault(t.get("PaymentBatchId") or "", []).append(t)
    rapport["batchid"] = {"aantal": len(met_id), "unieke_ids": len(per_id),
                          "positief": sum(1 for t in met_id if float(t.get("Amount") or 0) > 0),
                          "negatief": sum(1 for t in met_id if float(t.get("Amount") or 0) < 0),
                          "met_batch_nav": sum(1 for t in met_id if t.get("Batch")),
                          "refs_verdeling": {}, "voorbeelden": []}
    for t in met_id:
        s = _tx_samenvatting(t)
        n = len(s["refs_echt"])
        rapport["batchid"]["refs_verdeling"][str(n)] = rapport["batchid"]["refs_verdeling"].get(str(n), 0) + 1
    print(f"   PaymentBatchId gevuld: {len(met_id)} mutaties, {len(per_id)} unieke id's, +/−: {rapport['batchid']['positief']}/{rapport['batchid']['negatief']}, Batch-nav gevuld: {rapport['batchid']['met_batch_nav']}, koppelingen per mutatie: {rapport['batchid']['refs_verdeling']}")
    herhaald = {k: len(v) for k, v in per_id.items() if len(v) > 1}
    rapport["batchid"]["herhaalde_ids"] = herhaald
    print(f"   PaymentBatchId's die op meer dan één mutatie staan: {herhaald}")
    for t in met_id[:12]:
        s = _tx_samenvatting(t)
        st = t.get("Statement") or {}
        pa = t.get("PaymentAccount") or {}
        s["Statement"] = {k: st.get(k) for k in ("Number", "Date")}
        s["PaymentAccount"] = {k: pa.get(k) for k in ("Type", "CanExport", "CanReceiveDirectDebits", "SepaLimits")}
        rapport["batchid"]["voorbeelden"].append(s)
        print(f"      {s['BookDate'][:10]} {s['Amount']:>10} open {s['OpenAmount']} batchid={s['PaymentBatchId']!r} txid={t.get('TransactionId')!r} refs={len(s['refs_echt'])} som={round(sum(float(x['Amount'] or 0) for x in s['refs_echt']), 2)} Name={anonimiseer(s['Name'], 'Name')!r} ref={_tekst_anon(s['Reference'])[:80]!r}")
    # Acties die RLZ op zo'n mutatie aanbiedt (GET = lijst, nooit POST) + CancellationCandidates
    if met_id:
        t0 = met_id[0]
        rapport["batchid"]["actions_get"] = _veilig(c.get, f"PaymentTransactions/{t0['id']}/Actions")
        rapport["batchid"]["cancellation"] = _veilig(c.get, f"PaymentTransactions/{t0['id']}/CancellationCandidates", params={"$expand": "Document"})
        print("   GET Actions op de eerste batch-id-mutatie:", _kort(rapport["batchid"]["actions_get"], 500))
        print("   CancellationCandidates:", _kort(rapport["batchid"]["cancellation"], 300))

    # Items 'onderweg' (PaymentStatus 2 — filter op enum is 400, dus client-side) → document mét PaymentTermList
    items = _rows(_veilig(c.get, "PaymentItems", params={"$expand": "Document,PaymentTerm,BankRelation", "$top": "300"}))
    onderweg = [i for i in items if i.get("PaymentStatus") == 2]
    status_verdeling: dict[str, int] = {}
    for i in items:
        status_verdeling[str(i.get("PaymentStatus"))] = status_verdeling.get(str(i.get("PaymentStatus")), 0) + 1
    rapport["items"] = {"aantal": len(items), "per_status": status_verdeling, "onderweg": []}
    print(f"\n   PaymentItems {len(items)} per PaymentStatus {status_verdeling}; onderweg: {len(onderweg)}")
    for i in onderweg[:5]:
        d = i.get("Document") or {}
        route = {1: "PurchaseInvoices", 10: "SalesInvoices", 7: "TaxDeclarations"}.get(d.get("DocumentType") or i.get("DocumentType"))
        doc = _veilig(c.get, f"{route}/{d.get('id')}", params={"$expand": "PaymentTermList,QuickPaymentSelection,PaymentAccount"}) if route and d.get("id") else {"_geen_route": d.get("DocumentType")}
        termen = doc.get("PaymentTermList") if isinstance(doc, dict) else None
        uit = {"item": {k: i.get(k) for k in ("Amount", "DueDate", "PaymentStatus", "PaymentRefID", "Reference", "Reference2", "DocumentType")},
               "PaymentTerm(expand)": i.get("PaymentTerm"), "BankRelation": i.get("BankRelation"),
               "document": {k: doc.get(k) for k in ("ReceiptNumber", "Status", "BaseRemainingAmount")} if isinstance(doc, dict) and "_fout" not in doc else doc,
               "QuickPaymentSelection": ((doc.get("QuickPaymentSelection") or {}).get("Description") if isinstance(doc, dict) else None),
               "PaymentTermList": termen}
        rapport["items"]["onderweg"].append(uit)
        print("      ", _kort(uit, 900))

    # SEPA-redencodes / retour-teksten in bankregels
    rapport["zoek_r"] = {}
    for term in SEPA_REDENCODES:
        rijen = _rows(_veilig(c.get, "PaymentTransactions", params={"searchstring": term, "showExpectedPaymentTransactions": "false", "$top": "5"}))
        rapport["zoek_r"][term] = [_tx_samenvatting(t) for t in rijen[:3]]
        if rijen:
            print(f"   searchstring={term!r}: {len(rijen)} → {_kort([(s['BookDate'][:10], s['Amount'], s['ReturnReason'], _tekst_anon(s['Reference'])[:80]) for s in rapport['zoek_r'][term]], 500)}")
    # Statement-koppen (bank import file = Type 3?) op de eerste bankrekening
    accounts = _rows(_veilig(c.get, "PaymentAccounts"))
    bank = [a for a in accounts if a.get("Type") == 1 and not a.get("IsArchived")]
    if bank:
        st = _rows(_veilig(c.get, f"PaymentAccounts/{bank[0]['id']}/Statements", params={"$top": "3", "$orderby": "Date desc"}))
        rapport["statements"] = {"sleutels": sorted(st[0].keys()) if st else None, "voorbeeld": st[:2]}
        print("   Statements-kop sleutels:", rapport["statements"]["sleutels"])
        rapport["paymentaccount_sleutels"] = sorted(bank[0].keys())
        print("   PaymentAccount-sleutels (SEPA-vlaggen):", [k for k in bank[0] if re.search(r"Sepa|Export|DirectDebit|Receive|Batch", k)], {k: bank[0].get(k) for k in bank[0] if re.search(r"Sepa|Export|DirectDebit|Receive", k)})
    return rapport


# ------------------------------------------------------------------ (5) sleutelbewijs: PaymentBatchInformation == PaymentBatchId? --


def stap_sleutel(c: LeesClient, label: str) -> dict[str, Any]:
    """Draagt de factuur (PaymentTermList.PaymentBatchInformation) dezelfde batch-sleutel als de bankregel
    (PaymentTransaction.PaymentBatchId / Batch.BatchId)? Dat is de deterministische koppelsleutel voor de matchmotor."""
    rapport: dict[str, Any] = {"ts": _nu(), "administratie": label, "paren": []}
    print(f"\n######## sleutelbewijs {label}")
    txs = _rows(_veilig(c.get, "PaymentTransactions", params={"$filter": "PaymentBatchId ne null", "$expand": "PaymentReferenceList($expand=Document),Batch", "$orderby": "BookDate desc", "$top": "40"}))
    eigen = [t for t in txs if t.get("Batch")]
    for t in eigen[:3]:
        batch = t.get("Batch") or {}
        rij = {"BookDate": t.get("BookDate"), "Amount": t.get("Amount"), "PaymentBatchId": t.get("PaymentBatchId"), "Batch": batch, "documenten": []}
        for r in (t.get("PaymentReferenceList") or [])[:4]:
            d = r.get("Document") or {}
            route = {1: "PurchaseInvoices", 10: "SalesInvoices"}.get(d.get("DocumentType"))
            if not route or not d.get("id"):
                continue
            doc = _veilig(c.get, f"{route}/{d['id']}", params={"$expand": "PaymentTermList,QuickPaymentSelection"})
            termen = doc.get("PaymentTermList") if isinstance(doc, dict) else None
            rij["documenten"].append({"ReceiptNumber": d.get("ReceiptNumber"), "ref_amount": r.get("Amount"), "Status": doc.get("Status") if isinstance(doc, dict) else doc,
                                      "BasePaidAmount": doc.get("BasePaidAmount") if isinstance(doc, dict) else None,
                                      "QuickPaymentSelection": ((doc.get("QuickPaymentSelection") or {}).get("Description") if isinstance(doc, dict) else None),
                                      "termen": [{k: x.get(k) for k in ("PaymentBatchInformation", "IsPaymentProcessed", "PaymentDate", "OpenAmountBase", "BasePayedAmount", "PaymentRefID", "Sequence")} for x in (termen or [])]})
        rapport["paren"].append(rij)
        print(f"   bankregel {rij['BookDate'][:10]} {rij['Amount']} PaymentBatchId={rij['PaymentBatchId']!r} Batch.BatchId={batch.get('BatchId')!r} FileName={batch.get('FileName')!r} Remaining={batch.get('RemainingAmount')!r}")
        for d in rij["documenten"]:
            print("       doc", d["ReceiptNumber"], "ref", d["ref_amount"], "Status", d["Status"], "paid", d["BasePaidAmount"], "QPS", d["QuickPaymentSelection"], "termen", _kort(d["termen"], 400))
    return rapport


def main(argv: list[str]) -> None:
    args = [a for a in argv[1:] if not a.startswith("--")]
    stap = args[0] if args else "alles"
    gewenst: list[str] = []
    if "--login" in argv:
        i = argv.index("--login")
        gewenst = [a for a in argv[i + 1:] if not a.startswith("--") and a not in ("help", "enums", "admins", "verdieping", "sleutel", "alles")]
    print("logins:")
    logins = _logins(gewenst)
    root = logins[0][1]
    if stap in ("help", "alles"):
        _schrijf("help", stap_help(root))
    if stap in ("enums", "alles"):
        _schrijf("enums", stap_enums(root))
    if stap in ("admins", "alles"):
        rapport: dict[str, Any] = {"ts": _nu(), "administraties": []}
        for prefix, r, ids in logins:
            for admin_id in ids:
                rapport["administraties"].append(stap_admin(r.for_administration(admin_id), f"{prefix} {admin_id[:8]}…"))
        _schrijf("admins", rapport)
    if stap in ("verdieping", "alles"):
        rapport = {"ts": _nu(), "administraties": []}
        for prefix, r, ids in logins:
            for admin_id in ids:
                rapport["administraties"].append(stap_verdieping(r.for_administration(admin_id), f"{prefix} {admin_id[:8]}…"))
        _schrijf("verdieping", rapport)
    if stap in ("sleutel", "alles"):
        rapport = {"ts": _nu(), "administraties": []}
        for prefix, r, ids in logins:
            for admin_id in ids:
                rapport["administraties"].append(stap_sleutel(r.for_administration(admin_id), f"{prefix} {admin_id[:8]}…"))
        _schrijf("sleutel", rapport)


if __name__ == "__main__":
    main(sys.argv)
