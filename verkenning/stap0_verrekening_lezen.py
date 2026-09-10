#!/usr/bin/env python3
"""STAP-0 (LEES-ONLY) — "verrekening tussen twee bankmutaties" (nachtrun 10/11-09, blok 3.4, agent N3c).

Casus (Zilver Beheer 10-09, geanonimiseerd): mutatie A +5.023,09 is gekoppeld aan verkoopfactuur € 2.512,04,
open rest 2.511,05; mutatie B −2.511,05 "retour dubbele betaling" van dezelfde tegenpartij. Vraag: welke
RLZ-vorm bestaat via de API om A-rest en B tegen elkaar weg te strepen?

    1. actie 15 (LinkPaymentItems) met een PaymentItem van de ANDERE mutatie — bestaat een mutatie als betaal-item?
    2. kruispost-/tussenrekening: BankMutationDirectBookings op één balansrekening aan beide kanten
    3. RLZ's eigen "verrekenen" (actie 34) of een andere ActionKind op PaymentTransactions

Dit script doet UITSLUITEND GET-requests (Help, enumeraties, TEST-administratie). Elke andere methode wordt door
de `LeesClient` geweigerd (SystemExit) — er is geen schrijfpad in dit bestand. Het laadt `verkenning/.env` via
dotenv (TESTADMIN_USERNAME/TESTADMIN_PASSWORD) en pint op de TEST-administratie; een login die méér ziet dan de
test-administratie stopt vóór de eerste admin-scoped call.

Gebruik: backend/.venv/bin/python verkenning/stap0_verrekening_lezen.py [help|enums|test|test2|test3|alles]
Output:  verkenning/output/stap0_verrekening_<stap>.json (rapport, buiten git zolang output/ ongetrackt blijft)
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

load_dotenv(HIER / ".env")

TESTADMIN_ID = "8dbfb856-d75b-4ec3-9124-c8b739fe3bc5"
OUTPUT = HIER / "output"
HELP_ROOT = "https://apps.reeleezee.nl"  # Help-pagina's hangen onder /api/v1/Help/Api/<METHOD>-<route>

ZOEK_ACTIEWOORDEN = re.compile(
    r"verreken|settle|cross|kruis|tussen|transfer|overboek|cancel|storn|link|match|reconcil|payment|betaal|bank",
    re.I,
)


class LeesClient(RlzClient):
    """RlzClient die élke niet-GET weigert. Lees-only STAP-0: geen PUT/POST/DELETE, in geen enkele stap."""

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if method.upper() != "GET":
            raise SystemExit(f"LEES-ONLY: {method} {path} geweigerd — dit script schrijft nooit.")
        return super()._request(method, path, **kwargs)

    def for_administration(self, admin_id: str) -> LeesClient:
        return LeesClient(username="", password="", admin_id=admin_id, client=self._client)


def _nu() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _kort(obj: Any, n: int = 700) -> str:
    s = json.dumps(obj, default=str, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + " …"


def _veilig(fn, *a, **kw) -> Any:
    """GET-uitkomst óf de letterlijke fout (statuscode + eerste 200 tekens body)."""
    try:
        return fn(*a, **kw)
    except RlzApiError as e:
        return {"_fout": e.status_code, "_body": e.body[:200]}


def _rauw(c: LeesClient, path: str, params: dict[str, Any] | None = None) -> Any:
    """GET met rauwe afhandeling: JSON als het JSON is, anders status + content-type + eerste 200 tekens."""
    try:
        r = c.request_raw("GET", path, params=params)
    except RlzApiError as e:
        return {"_fout": e.status_code, "_body": e.body[:200]}
    try:
        return r.json()
    except ValueError:
        return {"_status": r.status_code, "_content_type": r.headers.get("content-type"), "_body": r.text[:200]}


def _html_naar_tekst(t: str) -> str:
    t = re.sub(r"<script.*?</script>", "", t, flags=re.S)
    t = re.sub(r"<style.*?</style>", "", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return html.unescape(re.sub(r"\s+", " ", t)).strip()


def _help_http() -> "httpx.Client":
    """Aparte GET-only httpx-client voor de Help-pagina's (HTML; RlzClient plakt het admin-pad vóór elke URL)."""
    import os

    return httpx.Client(auth=(os.environ["TESTADMIN_USERNAME"], os.environ["TESTADMIN_PASSWORD"]), timeout=60,
                        headers={"Accept": "text/html"})


def _help_pagina(h: "httpx.Client", slug: str) -> str:
    """Eén Help-pagina als platte tekst (bijv. 'GET-adminId-PaymentItems')."""
    r = h.get(f"{HELP_ROOT}/api/v1/Help/Api/{slug}")
    if r.status_code >= 400:
        raise RlzApiError(r.status_code, "GET", slug, r.text)
    return _html_naar_tekst(r.text)


def _model_uit_help(tekst: str) -> list[str]:
    """'Body Parameters <Model> Name Type Description Additional information id ... Request Formats' → veldnamen+types."""
    m = re.search(r"(?:Body Parameters|Resource Description) (.*?) (?:Request Formats|Response Formats)", tekst)
    if not m:
        return []
    velden = re.findall(r" ([A-Z][A-Za-z0-9]+) ((?:Collection of )?[A-Za-z][A-Za-z0-9 ]*?) None\.", m.group(1))
    return [f"{naam}: {typ.strip()}" for naam, typ in velden]


def _schrijf(stap: str, rapport: dict[str, Any]) -> Path:
    OUTPUT.mkdir(exist_ok=True)
    pad = OUTPUT / f"stap0_verrekening_{stap}.json"
    pad.write_text(json.dumps(rapport, indent=2, default=str, ensure_ascii=False))
    print(f"\n→ rapport: {pad}")
    return pad


def _login() -> tuple[LeesClient, LeesClient]:
    import os

    user = os.environ.get("TESTADMIN_USERNAME")
    pw = os.environ.get("TESTADMIN_PASSWORD")
    if not user or not pw:
        raise SystemExit("TESTADMIN_USERNAME/TESTADMIN_PASSWORD niet gevuld in verkenning/.env — lees-only stap kan niet.")
    root = LeesClient(username=user, password=pw)
    ids = [a["id"] for a in root.list_administrations()]
    if ids != [TESTADMIN_ID]:
        raise SystemExit(f"FAILSAFE: login ziet {ids}, verwacht uitsluitend de test-administratie {TESTADMIN_ID}.")
    return root, root.for_administration(TESTADMIN_ID)


# ------------------------------------------------------------------ (a) Help + $metadata ----------------------


def stap_help(root: LeesClient) -> dict[str, Any]:
    rapport: dict[str, Any] = {"ts": _nu(), "base": BASE_URL}
    # $metadata (08-09: 404) — herbevestigen, root én admin-scoped
    for pad in ("$metadata", f"{TESTADMIN_ID}/$metadata"):
        r = _veilig(root.request_raw, "GET", pad, headers={"Accept": "application/xml"})
        rapport[f"metadata:{pad}"] = r if isinstance(r, dict) else {"status": r.status_code, "lengte": len(r.text)}
    # Routelijst
    h = _help_http()
    r = h.get(f"{HELP_ROOT}/api/v1/Help")
    routes = re.findall(r'href="/api/v1/Help/Api/([^"]+)"[^>]*>([^<]+)</a>', r.text)
    rapport["help_routes_totaal"] = len(routes)
    relevant = [(slug, html.unescape(naam)) for slug, naam in routes
                if re.search(r"PaymentTransaction|PaymentItem|PaymentReference|ActionKind|BankMutation|Settl|Cancellation|Reconcil|Transfer|Cross", naam)]
    rapport["help_routes_relevant"] = [naam for _, naam in relevant]
    print(f"Help: {len(routes)} routes; relevant voor verrekening: {len(relevant)}")
    for _, naam in relevant:
        print("   ", naam)
    # Modellen uit de Help-pagina's die de vraag raken
    modellen: dict[str, Any] = {}
    for slug in (
        "POST-adminId-PaymentTransactions-id-Actions",
        "GET-adminId-PaymentTransactions-id-Actions",
        "GET-adminId-PaymentTransactions-id-CancellationCandidates",
        "GET-adminId-PaymentItems",
        "GET-adminId-PaymentReferenceTypes",
        "GET-PaymentReconciliationSources",
        "GET-ActionKinds",
        "PUT-adminId-BankMutationDirectBookings-id",
        "PUT-adminId-PaymentTransactions-id",
    ):
        try:
            tekst = _help_pagina(h, slug)
        except RlzApiError as e:
            modellen[slug] = {"_fout": e.status_code}
            continue
        velden = _model_uit_help(tekst)
        beschrijving = re.search(r"Help Page Home [A-Z]+ [^ ]+ (.*?) Request Information", tekst)
        modellen[slug] = {
            "beschrijving": beschrijving.group(1)[:200] if beschrijving else None,
            "velden": velden,
            "tekst_kort": tekst[:1200],
        }
        print(f"\n== Help {slug}: {beschrijving.group(1)[:120] if beschrijving else '?'}")
        for v in velden[:60]:
            print("     ", v)
    rapport["help_modellen"] = modellen
    return rapport


# ------------------------------------------------------------------ (a2) enumeraties ---------------------------


def stap_enums(root: LeesClient) -> dict[str, Any]:
    rapport: dict[str, Any] = {"ts": _nu()}
    for route in ("ActionKinds", "DocumentTypes", "DocumentTypeIDEnums", "PaymentReconciliationSources",
                  "PaymentStatuses", "PaymentAccountTypes", "PaymentTransactionTypes"):
        uit = _veilig(root.get, route)
        waarden = uit.get("value", uit) if isinstance(uit, dict) else uit
        rapport[route] = waarden
        if isinstance(waarden, list):
            print(f"\n== {route}: {len(waarden)} leden")
            if route == "ActionKinds":
                treffers = [w for w in waarden if ZOEK_ACTIEWOORDEN.search(json.dumps(w, ensure_ascii=False))]
                rapport["ActionKinds_relevant"] = treffers
                for w in treffers:
                    print("    ", _kort(w, 160))
            else:
                for w in waarden[:40]:
                    print("    ", _kort(w, 160))
        else:
            print(f"\n== {route}: {_kort(waarden, 200)}")
    return rapport


# ------------------------------------------------------------------ (b)+(c) TEST-administratie lezen -----------


def _tx_samenvatting(tx: dict[str, Any]) -> dict[str, Any]:
    refs = []
    for r in tx.get("PaymentReferenceList") or []:
        d = r.get("Document") or {}
        refs.append({
            "Sequence": r.get("Sequence"), "Amount": r.get("Amount"), "Type": r.get("Type"),
            "PaymentReconciliationSource": r.get("PaymentReconciliationSource"),
            "Document": {k: d.get(k) for k in ("DocumentType", "Status", "ReceiptNumber", "Reference", "IsSystemGenerated")} if d else None,
            "_overige_sleutels": sorted(k for k in r if k not in ("id", "Sequence", "Amount", "Document", "Type", "PaymentReconciliationSource")),
        })
    return {
        "id": tx.get("id"), "BookDate": tx.get("BookDate"), "Amount": tx.get("Amount"), "OpenAmount": tx.get("OpenAmount"),
        "IsComplete": tx.get("IsComplete"), "Type": tx.get("Type"), "Name": tx.get("Name"), "Reference": (tx.get("Reference") or "")[:60],
        "ReturnReason": tx.get("ReturnReason"), "CounterAccount": tx.get("CounterAccount"),
        "MatchedPaymentItem": (tx.get("MatchedPaymentItem") or {}).get("id") if tx.get("MatchedPaymentItem") else None,
        "PaymentReferenceList": refs,
        "_alle_sleutels": sorted(tx.keys()),
    }


def stap_test(c: LeesClient) -> dict[str, Any]:
    rapport: dict[str, Any] = {"ts": _nu(), "administratie": "TEST (8dbfb856-…)"}
    expand = "PaymentReferenceList($expand=Document),MatchedPaymentItem,PaymentAccount"

    # 1. Mutaties: open, deels gekoppeld, volledig gekoppeld
    alle = c.list_payment_transactions(params={"$expand": expand, "$orderby": "BookDate desc", "$top": "200"})
    print(f"\n== PaymentTransactions (top 200): {len(alle)}")
    open_ = [t for t in alle if float(t.get("OpenAmount") or 0) != 0 and float(t.get("OpenAmount") or 0) == float(t.get("Amount") or 0)]
    deels = [t for t in alle if float(t.get("OpenAmount") or 0) != 0 and float(t.get("OpenAmount") or 0) != float(t.get("Amount") or 0)]
    dicht = [t for t in alle if float(t.get("OpenAmount") or 0) == 0]
    rapport["aantallen"] = {"totaal": len(alle), "open": len(open_), "deels_gekoppeld": len(deels), "dicht": len(dicht)}
    print("   open:", len(open_), "deels:", len(deels), "dicht:", len(dicht))
    rapport["tekens"] = {"positief": sum(1 for t in alle if float(t.get("Amount") or 0) > 0), "negatief": sum(1 for t in alle if float(t.get("Amount") or 0) < 0)}
    print("   tekens (+/−):", rapport["tekens"], "— ontvangsten via API aanmaken was 400 (25-08); positieve mutaties bestaan alleen als RLZ ze zelf maakte")
    rapport["voorbeelden"] = {
        "deels_gekoppeld": [_tx_samenvatting(t) for t in deels[:3]],
        "open": [_tx_samenvatting(t) for t in open_[:2]],
        "dicht": [_tx_samenvatting(t) for t in dicht[:3]],
    }
    for soort, lijst in rapport["voorbeelden"].items():
        for s in lijst:
            print(f"\n   [{soort}] {s['BookDate']} Amount {s['Amount']} Open {s['OpenAmount']} IsComplete {s['IsComplete']} ReturnReason={s['ReturnReason']!r} refs={len(s['PaymentReferenceList'])}")
            for r in s["PaymentReferenceList"]:
                print("        ref:", _kort(r, 260))
    if alle:
        rapport["paymenttransaction_sleutels"] = sorted(alle[0].keys())
        rapport["paymentreference_sleutels"] = sorted({k for t in alle for r in (t.get("PaymentReferenceList") or []) for k in r})
        print("\n   PaymentTransaction-sleutels:", rapport["paymenttransaction_sleutels"])
        print("   PaymentReference-sleutels:", rapport["paymentreference_sleutels"])

    # 2. Welke acties biedt RLZ per mutatie-staat aan?
    rapport["acties_per_staat"] = {}
    for soort, lijst in (("open", open_), ("deels_gekoppeld", deels), ("dicht", dicht)):
        for t in lijst[:2]:
            acties = _veilig(c.get, f"PaymentTransactions/{t['id']}/Actions")
            waarden = acties.get("value", acties) if isinstance(acties, dict) else acties
            rapport["acties_per_staat"].setdefault(soort, []).append({"tx": t["id"], "Amount": t.get("Amount"), "OpenAmount": t.get("OpenAmount"), "acties": waarden})
            print(f"\n== Actions op {soort} mutatie {t.get('Amount')}/{t.get('OpenAmount')}: {_kort(waarden, 500)}")
            kand = _veilig(c.get, f"PaymentTransactions/{t['id']}/CancellationCandidates")
            rapport["acties_per_staat"][soort][-1]["CancellationCandidates"] = kand
            print(f"   CancellationCandidates: {_kort(kand, 500)}")

    # 3. PaymentItems: bron = documenten? staan er ook bankmutaties/BMDB's tussen?
    items = _veilig(c.get, "PaymentItems", params={"$expand": "Document", "$top": "300"})
    lijst = items.get("value", []) if isinstance(items, dict) and "value" in items else []
    rapport["paymentitems"] = {"aantal": len(lijst), "sleutels": sorted(lijst[0].keys()) if lijst else None, "fout": items if not lijst else None}
    per_type: dict[str, int] = {}
    zonder_document = 0
    for it in lijst:
        d = it.get("Document")
        if not d:
            zonder_document += 1
            continue
        per_type[str(d.get("DocumentType"))] = per_type.get(str(d.get("DocumentType")), 0) + 1
    rapport["paymentitems"]["per_documenttype"] = per_type
    rapport["paymentitems"]["zonder_document"] = zonder_document
    rapport["paymentitems"]["voorbeeld"] = [{k: it.get(k) for k in ("id", "Amount", "OpenAmount", "BookDate", "Reference", "Reference2", "PaymentStatus")} | {"Document": {k: (it.get("Document") or {}).get(k) for k in ("DocumentType", "Status", "ReceiptNumber")}} for it in lijst[:3]]
    print(f"\n== PaymentItems: {len(lijst)} — per Document.DocumentType {per_type}, zonder Document: {zonder_document}")
    print("   sleutels:", rapport["paymentitems"]["sleutels"])
    for v in rapport["paymentitems"]["voorbeeld"]:
        print("   ", _kort(v, 300))
    # Filters die een bankmutatie-als-item zouden verraden
    for f in ("Document/DocumentType eq 19", "Document/DocumentType eq 10", "Document/DocumentType eq 1"):
        r = _veilig(c.get, "PaymentItems", params={"$filter": f, "$top": "5", "$count": "true"})
        aantal = r.get("@odata.count", len(r.get("value", []))) if isinstance(r, dict) and "value" in r else r
        rapport["paymentitems"][f"filter:{f}"] = aantal
        print(f"   $filter={f}: {_kort(aantal, 200)}")

    # 4. PaymentReferenceTypes (admin-scoped enum — wat kan een koppeling zijn?)
    prt = _veilig(c.get, "PaymentReferenceTypes")
    rapport["PaymentReferenceTypes"] = prt.get("value", prt) if isinstance(prt, dict) else prt
    print("\n== PaymentReferenceTypes:", _kort(rapport["PaymentReferenceTypes"], 900))

    # 5. Tussen-/kruispostrekeningen + RLZ's Verrekeningen-PaymentAccount (Type 4)
    rapport["ledgers"] = {}
    for zoek in ("kruis", "tussen", "verreken", "rubriceren", "vooruit", "tegenrekening", "overboek", "onderweg"):
        r = _veilig(c.get, "Ledgers", params={"search": zoek, "$top": "20"})
        rijen = r.get("value", []) if isinstance(r, dict) and "value" in r else []
        rapport["ledgers"][zoek] = [{k: l.get(k) for k in ("id", "AccountNumber", "Description", "AccountType", "UseForBankCashMutationDetails", "UseForPaymentAccount", "IsTopLevel")} for l in rijen] or r
        print(f"\n== Ledgers?search={zoek}: {[(l.get('AccountNumber'), l.get('Description'), 'bank-detail' if l.get('UseForBankCashMutationDetails') else '-') for l in rijen]}")
    accounts = _veilig(c.get, "PaymentAccounts", params={"$expand": "Account"})
    acc_lijst = accounts.get("value", []) if isinstance(accounts, dict) and "value" in accounts else []
    rapport["paymentaccounts"] = [{k: a.get(k) for k in ("id", "Name", "Type", "IsArchived")} | {"Account": {k: (a.get("Account") or {}).get(k) for k in ("AccountNumber", "Description")} if a.get("Account") else None, "_sleutels": sorted(a.keys())} for a in acc_lijst]
    print("\n== PaymentAccounts (Type 4 = Settling/verrekeningen):")
    for a in rapport["paymentaccounts"]:
        print("    ", _kort({k: a[k] for k in ("Name", "Type", "Account")}, 200))
    for a in acc_lijst:
        if a.get("Type") == 4:
            txs = _veilig(c.get, "PaymentTransactions", params={"$filter": f"PaymentAccount/id eq {a['id']}", "$top": "5", "$count": "true"})
            rapport[f"verrekeningen_account_{a['id'][:8]}_transacties"] = txs
            print(f"   PaymentTransactions op Verrekeningen-rekening {a.get('Name')!r}: {_kort(txs, 400)}")
            bmdb = _rauw(c, "BankMutationDirectBookings", params={"$filter": f"PaymentAccount/id eq {a['id']}", "$top": "5", "$count": "true"})
            rapport[f"verrekeningen_account_{a['id'][:8]}_bmdb"] = bmdb
            print(f"   BankMutationDirectBookings op die rekening: {_kort(bmdb, 400)}")

    # 6. Hoe ziet een BMDB op Kruisposten eruit (fallback-PoC §4 / splitsen §2 lieten er één achter)?
    bmdbs = _veilig(c.get, "BankMutationDirectBookings", params={"$expand": "DocumentLineList($expand=Account),PaymentTransaction", "$orderby": "Date desc", "$top": "40"})
    bl = bmdbs.get("value", []) if isinstance(bmdbs, dict) and "value" in bmdbs else []
    kruis = []
    for d in bl:
        regels = d.get("DocumentLineList") or []
        for rg in regels:
            acc = rg.get("Account") or {}
            if re.search(r"kruis|tussen|verreken", acc.get("Description") or "", re.I):
                kruis.append({"ReceiptNumber": d.get("ReceiptNumber"), "Status": d.get("Status"), "IsSystemGenerated": d.get("IsSystemGenerated"),
                              "regel": {"Account": f"{acc.get('AccountNumber')} {acc.get('Description')}", "NetAmount": rg.get("NetAmount")},
                              "PaymentTransaction": {k: (d.get("PaymentTransaction") or {}).get(k) for k in ("Amount", "OpenAmount", "BookDate")}})
    rapport["bmdb_op_kruisposten"] = kruis
    rapport["bmdb_totaal_gelezen"] = len(bl)
    print(f"\n== BMDB's (top 40) met regel op kruis-/tussen-/verrekenrekening: {len(kruis)}")
    for k in kruis[:5]:
        print("    ", _kort(k, 300))
    return rapport


# ------------------------------------------------------------------ (c2) RLZ's eigen verrekeningsrekening --------


def stap_test2(c: LeesClient) -> dict[str, Any]:
    """Verdieping run 2: de Type-4 'Verrekeningen'-rekening (RLZ's eigen settling), ReturnReason, journaal op 2001,
    BMDB's op tussenrekeningen, CancellationCandidates op positieve/RLZ-eigen transacties."""
    rapport: dict[str, Any] = {"ts": _nu(), "administratie": "TEST (8dbfb856-…)"}
    expand = "PaymentReferenceList($expand=Document),MatchedPaymentItem"
    accounts = _veilig(c.get, "PaymentAccounts", params={"$expand": "Account"})
    acc_lijst = accounts.get("value", []) if isinstance(accounts, dict) and "value" in accounts else []
    settling = [a for a in acc_lijst if a.get("Type") == 4]
    rapport["settling_accounts"] = [{"Type": a.get("Type"), "Account": (a.get("Account") or {}).get("AccountNumber"), "_sleutels": sorted(a.keys())} for a in settling]
    for a in settling:
        txs = _veilig(c.get, "PaymentTransactions", params={"$filter": f"PaymentAccount/id eq {a['id']}", "$expand": expand, "$orderby": "BookDate desc", "$top": "50"})
        lijst = txs.get("value", []) if isinstance(txs, dict) and "value" in txs else []
        rapport["settling_transacties"] = [_tx_samenvatting(t) for t in lijst]
        print(f"\n== Verrekeningen-rekening (Type 4, GB {(a.get('Account') or {}).get('AccountNumber')}): {len(lijst)} transacties")
        per_dag: dict[str, list[float]] = {}
        for t in lijst:
            per_dag.setdefault(t.get("BookDate"), []).append(float(t.get("Amount") or 0))
        rapport["settling_per_dag"] = per_dag
        print("   bedragen per boekdatum (paren met tegengesteld teken = verrekening?):")
        for d, b in sorted(per_dag.items()):
            print(f"      {d[:10]}: {b}  som={round(sum(b), 2)}")
        for s in rapport["settling_transacties"][:6]:
            print(f"\n   tx {s['BookDate'][:10]} Amount {s['Amount']} Open {s['OpenAmount']} Type {s['Type']} IsComplete {s['IsComplete']} Name={s['Name']!r} Ref={s['Reference']!r} Matched={s['MatchedPaymentItem']}")
            for r in s["PaymentReferenceList"]:
                print("        ref:", _kort(r, 300))
        if lijst:
            t0 = lijst[0]
            rapport["settling_actions"] = _veilig(c.get, f"PaymentTransactions/{t0['id']}/Actions")
            rapport["settling_cancellation"] = _veilig(c.get, f"PaymentTransactions/{t0['id']}/CancellationCandidates")
            print("   Actions op zo'n transactie:", _kort(rapport["settling_actions"], 400))
            print("   CancellationCandidates:", _kort(rapport["settling_cancellation"], 400))
            # Welke documenten hangen eraan → hoe boekte RLZ de verrekening (journaal)?
            doc_ids = {(r.get("Document") or {}).get("id") for t in lijst for r in (t.get("PaymentReferenceList") or []) if r.get("Document")}
            rapport["settling_documenttypen"] = {}
            for t in lijst:
                for r in t.get("PaymentReferenceList") or []:
                    d = r.get("Document") or {}
                    k = f"{d.get('DocumentType')}/{(d.get('ReceiptNumber') or '')[:6]}"
                    rapport["settling_documenttypen"][k] = rapport["settling_documenttypen"].get(k, 0) + 1
            print("   gekoppelde documenten per type/reeks:", rapport["settling_documenttypen"])
            rapport["settling_bmdb"] = _rauw(c, "BankMutationDirectBookings", params={"$filter": f"PaymentTransaction/PaymentAccount/id eq {a['id']}", "$top": "5", "$count": "true"})
            print("   BMDB via PaymentTransaction/PaymentAccount-filter:", _kort(rapport["settling_bmdb"], 300))

    # ReturnReason: bestaat er een transactie met gevulde ReturnReason (retourbetaling)?
    for f in ("ReturnReason ne null", "ReturnReason ne ''"):
        r = _veilig(c.get, "PaymentTransactions", params={"$filter": f, "$top": "5", "$count": "true"})
        rapport[f"returnreason:{f}"] = r if isinstance(r, dict) and "_fout" in r else {"count": r.get("@odata.count"), "voorbeeld": [_tx_samenvatting(t) for t in r.get("value", [])[:2]]}
        print(f"\n== PaymentTransactions $filter={f}: {_kort(rapport[f'returnreason:{f}'], 400)}")

    # CancellationCandidates op positieve (ontvangst-)transacties én op transacties mét koppeling naar een document
    alle = c.list_payment_transactions(params={"$expand": expand, "$orderby": "BookDate desc", "$top": "300"})
    pos = [t for t in alle if float(t.get("Amount") or 0) > 0]
    rapport["cancellation_op_positief"] = []
    for t in pos[:6]:
        kand = _veilig(c.get, f"PaymentTransactions/{t['id']}/CancellationCandidates")
        rapport["cancellation_op_positief"].append({"tx": _tx_samenvatting(t) | {"PaymentReferenceList": len(t.get("PaymentReferenceList") or [])}, "kandidaten": kand})
        print(f"\n== CancellationCandidates op positieve tx {t.get('BookDate','')[:10]} +{t.get('Amount')} (open {t.get('OpenAmount')}, refs {len(t.get('PaymentReferenceList') or [])}): {_kort(kand, 300)}")
    # Zijn er onder alle 300 transacties tegengestelde paren van dezelfde tegenpartij (casus-vorm)?
    paren = []
    for i, t in enumerate(alle):
        for u in alle[i + 1:]:
            if t.get("Name") and t.get("Name") == u.get("Name") and abs(float(t.get("Amount") or 0) + float(u.get("Amount") or 0)) < 0.005 and float(t.get("Amount") or 0) != 0:
                paren.append({"naam": t.get("Name"), "a": (t.get("BookDate"), t.get("Amount"), t.get("OpenAmount")), "b": (u.get("BookDate"), u.get("Amount"), u.get("OpenAmount"))})
    rapport["tegengestelde_paren_zelfde_naam"] = paren[:10]
    print(f"\n== Tegengestelde paren zelfde tegenpartijnaam in top 300: {len(paren)} → {_kort(paren[:5], 600)}")

    # Journaalregels op GB 2001 Verrekeningen / 1010 Kruisposten / 1808 Vooruitontvangen: hoe boekt RLZ erop?
    rapport["journaal"] = {}
    for nr in ("2001", "1010", "1808", "2100"):
        led = _veilig(c.get, "Ledgers", params={"$filter": f"AccountNumber eq '{nr}'"})
        lijst = led.get("value", []) if isinstance(led, dict) and "value" in led else []
        if not lijst:
            rapport["journaal"][nr] = {"ledger": led}
            continue
        lid = lijst[0]["id"]
        jl = _rauw(c, "JournalEntryLines", params={"$filter": f"Account/id eq {lid}", "$expand": "JournalEntry($expand=Document)", "$orderby": "JournalEntry/BookDate desc", "$top": "10", "$count": "true"})
        if isinstance(jl, dict) and "_fout" in jl:
            jl = _rauw(c, "JournalEntryLines", params={"$filter": f"Account/id eq {lid}", "$expand": "JournalEntry", "$top": "10", "$count": "true"})
        regels = jl.get("value", []) if isinstance(jl, dict) and "value" in jl else []
        samen = []
        for rg in regels:
            je = rg.get("JournalEntry") or {}
            doc = je.get("Document") or {}
            samen.append({"BookDate": (je.get("BookDate") or "")[:10], "Debit": rg.get("DebitAmount"), "Credit": rg.get("CreditAmount"), "Description": (rg.get("Description") or "")[:50],
                          "DocumentType": doc.get("DocumentType"), "ReceiptNumber": doc.get("ReceiptNumber"), "_je_sleutels": sorted(je.keys())[:20]})
        rapport["journaal"][nr] = {"count": jl.get("@odata.count") if isinstance(jl, dict) else None, "regels": samen, "fout": jl if not regels else None}
        print(f"\n== JournalEntryLines op {nr} {lijst[0].get('Description')}: count={rapport['journaal'][nr]['count']}")
        for x in samen[:6]:
            print("    ", _kort(x, 300))
        if not regels:
            print("     (geen regels / fout):", _kort(jl, 300))

    # BMDB's met regels op 1010/2001/1808/2000/2100 (documenten die RLZ of wij op een tussenrekening zetten)
    bmdbs = _veilig(c.get, "BankMutationDirectBookings", params={"$expand": "DocumentLineList($expand=Account),PaymentTransaction($expand=PaymentAccount)", "$orderby": "Date desc", "$top": "80"})
    bl = bmdbs.get("value", []) if isinstance(bmdbs, dict) and "value" in bmdbs else []
    tussen = []
    for d in bl:
        for rg in d.get("DocumentLineList") or []:
            acc = rg.get("Account") or {}
            if acc.get("AccountNumber") in ("1010", "1011", "2001", "1808", "1405", "2000", "2100", "1012"):
                pt = d.get("PaymentTransaction") or {}
                tussen.append({"ReceiptNumber": d.get("ReceiptNumber"), "Status": d.get("Status"), "IsSystemGenerated": d.get("IsSystemGenerated"), "Date": (d.get("Date") or "")[:10],
                               "regel": f"{acc.get('AccountNumber')} {acc.get('Description')} NetAmount {rg.get('NetAmount')}",
                               "tx": {"Amount": pt.get("Amount"), "OpenAmount": pt.get("OpenAmount"), "rekening": ((pt.get("PaymentAccount") or {}).get("Type"))}})
    rapport["bmdb_op_tussenrekeningen"] = tussen
    print(f"\n== BMDB's (top 80 van {len(bl)}) met regel op een tussen-/verreken-/vooruit-rekening: {len(tussen)}")
    for x in tussen[:8]:
        print("    ", _kort(x, 300))
    return rapport


# ------------------------------------------------------------------ (c3) CancellationCandidates + settling-documenten --


def stap_test3(c: LeesClient) -> dict[str, Any]:
    """Run 3: waar wijzen CancellationCandidates naar ($expand=Document,PaymentTransaction)? Hoe zien de twee
    documenten van een RLZ-verrekening eruit (verkoopfactuur + creditfactuur op de Verrekeningen-rekening)?"""
    rapport: dict[str, Any] = {"ts": _nu(), "administratie": "TEST (8dbfb856-…)"}
    expand = "PaymentReferenceList($expand=Document),MatchedPaymentItem"
    alle = c.list_payment_transactions(params={"$expand": expand, "$orderby": "BookDate desc", "$top": "300"})
    rapport["cancellation_expanded"] = []
    gevonden = 0
    for t in alle:
        if gevonden >= 4:
            break
        kand = _veilig(c.get, f"PaymentTransactions/{t['id']}/CancellationCandidates", params={"$expand": "Document,PaymentTransaction($expand=PaymentAccount)"})
        waarden = kand.get("value", []) if isinstance(kand, dict) and "value" in kand else []
        if not waarden and not (isinstance(kand, dict) and "_fout" in kand):
            continue
        gevonden += 1
        uit = []
        for k in waarden:
            d = k.get("Document") or {}
            pt = k.get("PaymentTransaction") or {}
            uit.append({"Amount": k.get("Amount"), "Sequence": k.get("Sequence"), "PaymentReconciliationSource": k.get("PaymentReconciliationSource"),
                        "Document": {x: d.get(x) for x in ("DocumentType", "Status", "ReceiptNumber", "Reference")} if d else None,
                        "PaymentTransaction": {x: pt.get(x) for x in ("BookDate", "Amount", "OpenAmount", "Name", "Type")} | {"rekening_type": (pt.get("PaymentAccount") or {}).get("Type")} if pt else None,
                        "_sleutels": sorted(k.keys())})
        rapport["cancellation_expanded"].append({"tx": {x: t.get(x) for x in ("BookDate", "Amount", "OpenAmount", "Name")} | {"refs": [(r.get("Amount"), (r.get("Document") or {}).get("ReceiptNumber")) for r in t.get("PaymentReferenceList") or []]}, "kandidaten": uit if waarden else kand})
        print(f"\n== CancellationCandidates($expand) op tx {t.get('BookDate','')[:10]} {t.get('Amount')} {t.get('Name')!r}: refs={rapport['cancellation_expanded'][-1]['tx']['refs']}")
        for u in uit:
            print("     kandidaat:", _kort(u, 500))
    # Settling-documenten: hoe zien de gekoppelde verkoop-/inkoopdocumenten eruit (betaalstatus, PaymentTermList)?
    accounts = _veilig(c.get, "PaymentAccounts")
    settling = [a for a in accounts.get("value", []) if a.get("Type") == 4]
    rapport["settling_documenten"] = []
    for a in settling[:1]:
        txs = _veilig(c.get, "PaymentTransactions", params={"$filter": f"PaymentAccount/id eq {a['id']}", "$expand": "PaymentReferenceList($expand=Document),PaymentAccount,Statement", "$orderby": "BookDate desc", "$top": "4"})
        for t in txs.get("value", []):
            st = t.get("Statement") or {}
            print(f"\n== settling-tx {t.get('BookDate','')[:10]} {t.get('Amount')} Statement={ {x: st.get(x) for x in ('Number','Date')} } TransactionId={t.get('TransactionId')!r} CreateDate={t.get('CreateDate')}")
            for r in t.get("PaymentReferenceList") or []:
                d = r.get("Document") or {}
                route = {1: "PurchaseInvoices", 10: "SalesInvoices"}.get(d.get("DocumentType"))
                if not route or not d.get("id"):
                    continue
                doc = _veilig(c.get, f"{route}/{d['id']}", params={"$expand": "QuickPaymentSelection,PaymentTermList,Entity"})
                samen = {x: doc.get(x) for x in ("ReceiptNumber", "Reference", "Status", "Date", "BaseInvoiceAmount", "BasePaidAmount", "BaseRemainingAmount", "InvoiceReference")} if isinstance(doc, dict) else doc
                if isinstance(doc, dict) and "_fout" not in doc:
                    samen["Entity"] = (doc.get("Entity") or {}).get("Name")
                    samen["QuickPaymentSelection"] = (doc.get("QuickPaymentSelection") or {}).get("Description") if doc.get("QuickPaymentSelection") else None
                    samen["PaymentTermList"] = [{x: p.get(x) for x in ("OpenAmountBase", "PaymentStatus", "PaymentBatchInformation")} for p in doc.get("PaymentTermList") or []]
                rapport["settling_documenten"].append({"tx_amount": t.get("Amount"), "ref_amount": r.get("Amount"), "document": samen})
                print(f"     → {route} {d.get('ReceiptNumber')}: {_kort(samen, 500)}")
    return rapport


def main(argv: list[str]) -> None:
    stap = argv[1] if len(argv) > 1 else "alles"
    root, test = _login()
    if stap in ("help", "alles"):
        _schrijf("help", stap_help(root))
    if stap in ("enums", "alles"):
        _schrijf("enums", stap_enums(root))
    if stap in ("test", "alles"):
        _schrijf("test", stap_test(test))
    if stap in ("test2", "alles"):
        _schrijf("test2", stap_test2(test))
    if stap in ("test3", "alles"):
        _schrijf("test3", stap_test3(test))


if __name__ == "__main__":
    main(sys.argv)
