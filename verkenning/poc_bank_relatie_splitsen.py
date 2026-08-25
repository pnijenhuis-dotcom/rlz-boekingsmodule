#!/usr/bin/env python3
"""STAP-0 PoC (feedbackronde 25-08 deel 4, punten 3 + 4): bankmutatie op een RELATIE boeken
(verrekenbare open post zonder factuur) en één mutatie SPLITSEN over meerdere bestemmingen.

Verifiëren, niet bouwen. Schrijven uitsluitend tegen de RLZ-test-administratie; alles herkenbaar
aan TEST-referenties (`TEST-RELPOC-…`, `TEST-SPLITPOC-…`); terugdraaien = actie 19 (Correct) op
het gekoppelde document — nooit DELETE (besluit 0005 / kernprincipe 3).

Waarborgen (identiek aan poc_afletteren_betaalkant.py):
- ADMIN-PIN: de schrijf-client weigert te starten als de login iets anders ziet dan de
  test-administratie.
- KILL SWITCH: bestand verkenning/POC_STOP aanwezig → elke schrijfactie geweigerd.
- TOGGLE: draait alleen met expliciet subcommando.
- AUDIT: append-only JSONL per actie in output/relpoc_audit.jsonl.

Read-only recon mag óók tegen een productie-administratie (RLZ_USERNAME/RLZ_PASSWORD, BLOW):
uitsluitend GET's — doel: zien welk documenttype RLZ's eigen UI aanmaakt bij "boeken op relatie".

Gebruik:
    backend/.venv/bin/python verkenning/poc_bank_relatie_splitsen.py <stap> [args]
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER.parent / "backend"))

from dotenv import load_dotenv  # noqa: E402

from app.rlz.client import RlzApiError, RlzClient  # noqa: E402

load_dotenv(HIER / ".env")

TESTADMIN_ID = "8dbfb856-d75b-4ec3-9124-c8b739fe3bc5"
TEST_ACCOUNT_ID = "79b6f64a-dad9-4683-9e47-9c182ebae1c1"  # 4699 Diverse algemene kosten
TEST_TAXRATE_ID = "1e44993a-15f6-419f-87e5-3e31ac3d9383"  # 21% NL

KILL_SWITCH = HIER / "POC_STOP"
OUTPUT = HIER / "output"
AUDIT_LOG = OUTPUT / "relpoc_audit.jsonl"
STATE_FILE = OUTPUT / "relpoc_state.json"
BANKPOC_STATE = OUTPUT / "bankpoc_state.json"

ACTION_BOOK = 17
ACTION_CORRECT = 19

TX_EXPAND = "MatchedPaymentItem,PaymentReferenceList($expand=Document($expand=Entity,Account))"


def _nu() -> str:
    return datetime.now(UTC).isoformat()


def _audit(entry: dict[str, Any]) -> None:
    OUTPUT.mkdir(exist_ok=True)
    entry = {"ts": _nu(), **entry}
    with AUDIT_LOG.open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def _state() -> dict[str, Any]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def _save_state(state: dict[str, Any]) -> None:
    OUTPUT.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def _dump(label: str, data: Any) -> None:
    print(f"\n=== {label} ===")
    print(json.dumps(data, indent=2, default=str, ensure_ascii=False))


def _values(resp: Any) -> list[Any]:
    if isinstance(resp, dict) and "value" in resp:
        return list(resp["value"])
    return list(resp) if isinstance(resp, list) else [resp]


class ReadOnlyClient:
    """Alleen GET — voor recon op productie-administraties (BLOW) én de test-administratie."""

    def __init__(self, user_var: str, pw_var: str) -> None:
        user = os.environ.get(user_var)
        pw = os.environ.get(pw_var)
        if not user or not pw:
            raise SystemExit(f"{user_var}/{pw_var} niet gevuld in verkenning/.env")
        self.login = RlzClient(username=user, password=pw)
        self.admins = self.login.list_administrations()

    def for_admin(self, admin_id: str) -> RlzClient:
        return self.login.for_administration(admin_id)


class PocClient:
    """Dunne schil om RlzClient: admin-pin, kill switch vóór elke write, audit per actie."""

    def __init__(self) -> None:
        user = os.environ.get("TESTADMIN_USERNAME")
        pw = os.environ.get("TESTADMIN_PASSWORD")
        if not user or not pw:
            raise SystemExit("TESTADMIN_USERNAME/TESTADMIN_PASSWORD niet gevuld in verkenning/.env")
        self._login_naam = user
        login = RlzClient(username=user, password=pw)
        ids = [a["id"] for a in login.list_administrations()]
        if ids != [TESTADMIN_ID]:
            raise SystemExit(
                f"FAILSAFE: login ziet administraties {ids}, verwacht uitsluitend de "
                f"test-administratie {TESTADMIN_ID}. Gestopt zonder één schrijfactie."
            )
        self.rlz = login.for_administration(TESTADMIN_ID)

    def _check_kill_switch(self) -> None:
        if KILL_SWITCH.exists():
            _audit({"actie": "geweigerd_kill_switch", "login": self._login_naam})
            raise SystemExit(f"KILL SWITCH actief ({KILL_SWITCH}) — schrijfactie geweigerd.")

    def get(self, path: str, **params: Any) -> Any:
        return self.rlz.get(path, params=params or None)

    def put(self, path: str, body: dict[str, Any], *, lees_terug: bool = True) -> Any:
        self._check_kill_switch()
        try:
            r = self.rlz.put(path, body)
            status: Any = r.status_code
        except RlzApiError as e:
            status = f"{e.status_code}: {e.body[:400]}"
            _audit({"actie": "PUT", "admin": TESTADMIN_ID, "pad": path, "payload": body, "status": status})
            raise
        _audit({"actie": "PUT", "admin": TESTADMIN_ID, "pad": path, "payload": body, "status": status})
        return self.rlz.get(path) if lees_terug else status

    def put_probe(self, path: str, body: dict[str, Any]) -> Any:
        """PUT waarvan een fout een RESULTAAT is (probe) — geeft status of foutstring terug."""
        self._check_kill_switch()
        try:
            r = self.rlz.put(path, body)
            status: Any = r.status_code
        except RlzApiError as e:
            status = f"{e.status_code}: {e.body[:400]}"
        _audit({"actie": "PUT (probe)", "admin": TESTADMIN_ID, "pad": path, "payload": body, "status": status})
        return status

    def actie(self, doc_pad: str, actie_type: int, **extra: Any) -> Any:
        self._check_kill_switch()
        try:
            r = self.rlz.post_action(doc_pad, actie_type, **extra)
            status: Any = r.status_code
        except RlzApiError as e:
            status = f"{e.status_code}: {e.body[:400]}"
            _audit({"actie": f"POST Actions {actie_type}", "admin": TESTADMIN_ID, "pad": doc_pad,
                    "extra_body": extra, "status": status})
            raise
        _audit({"actie": f"POST Actions {actie_type}", "admin": TESTADMIN_ID, "pad": doc_pad,
                "extra_body": extra, "status": status})
        return status

    def post_raw_actions(self, doc_pad: str, body: Any) -> Any:
        self._check_kill_switch()
        try:
            r = self.rlz.request_raw("POST", f"{doc_pad.rstrip('/')}/Actions", json=body)
            status: Any = r.status_code
        except RlzApiError as e:
            status = f"{e.status_code}: {e.body[:400]}"
        _audit({"actie": "POST Actions (raw)", "admin": TESTADMIN_ID, "pad": doc_pad, "payload": body,
                "status": status})
        return status


def _koppel_body(*, item_id: str, linked_amount: float, is_completely_paid: bool = False) -> dict[str, Any]:
    """De bewezen afletter-body (api-verkenning "Afletteren betaal-kant — REPLAY GESLAAGD")."""
    return {
        "Type": 15,
        "PaymentItemList": [{"id": item_id}],
        "LinkedAmount": linked_amount,
        "IsCompletelyPaid": is_completely_paid,
        "PaymentCorrectionMethod": 1,
    }


def _tx_staat(rlz: RlzClient, tx_id: str) -> dict[str, Any]:
    t = rlz.get(f"PaymentTransactions/{tx_id}", params={"$expand": TX_EXPAND})
    refs = []
    for r in t.get("PaymentReferenceList") or []:
        d = r.get("Document") or {}
        refs.append({
            "Sequence": r.get("Sequence"), "Amount": r.get("Amount"),
            "Bron": r.get("PaymentReconciliationSource"),
            "Document": {
                "id": d.get("id"), "DocumentType": d.get("DocumentType"), "Status": d.get("Status"),
                "IsSystemGenerated": d.get("IsSystemGenerated"), "ReceiptNumber": d.get("ReceiptNumber"),
                "Reference": d.get("Reference"),
                "Entity": (d.get("Entity") or {}).get("Name"),
                "Account": (d.get("Account") or {}).get("AccountNumber"),
            },
        })
    return {
        "id": t.get("id"), "Reference": t.get("Reference"), "Amount": t.get("Amount"),
        "OpenAmount": t.get("OpenAmount"), "IsComplete (stale!)": t.get("IsComplete"),
        "MatchedPaymentItem": (t.get("MatchedPaymentItem") or {}).get("id"),
        "PaymentReferenceList": refs,
    }


def _items_voor_entity(rlz: RlzClient, entity_id: str) -> list[dict[str, Any]]:
    """Open posten van een relatie — via Document/Entity-filter (PaymentItems kent alleen collectie-GET)."""
    try:
        items = _values(rlz.get("PaymentItems", params={
            "$filter": f"Document/Entity/id eq {entity_id}",
            "$expand": "Document($expand=Entity)"}))
    except RlzApiError as e:
        return [{"fout": f"{e.status_code}: {e.body[:300]}"}]
    return [{k: i.get(k) for k in ("id", "Amount", "OpenAmount", "PaymentStatus", "Description", "Type")}
            | {"Document": {kk: (i.get("Document") or {}).get(kk) for kk in
                            ("id", "DocumentType", "Status", "Reference", "ReceiptNumber")}}
            for i in items]


def _journaal(rlz: RlzClient, collectie: str, doc_id: str) -> Any:
    """Grootboek-effect van een document: JournalEntryList → regels met Account + bedragen."""
    try:
        d = rlz.get(f"{collectie}/{doc_id}", params={
            "$expand": "JournalEntryList($expand=JournalEntryLines($expand=Account,Entity))"})
    except RlzApiError as e:
        return f"{e.status_code}: {e.body[:300]}"
    uit = []
    for je in d.get("JournalEntryList") or []:
        for l in je.get("JournalEntryLines") or []:
            uit.append({
                "Account": (l.get("Account") or {}).get("AccountNumber"),
                "AccountNaam": (l.get("Account") or {}).get("Description"),
                "Debit": l.get("DebitAmount"), "Credit": l.get("CreditAmount"),
                "Entity": (l.get("Entity") or {}).get("Name") if isinstance(l.get("Entity"), dict) else l.get("Entity"),
                "Description": l.get("Description"),
            })
    return uit or {"geen JournalEntryList/regels": {k: d.get(k) for k in ("Status", "DocumentType")}}


# --------------------------------------------------------------------------- recon (read-only)


def _recon_admin(rlz: RlzClient, label: str, *, max_tx: int = 400) -> None:
    print(f"\n##### RECON {label}")
    try:
        types = _values(rlz.get("DocumentTypes"))
        _dump("DocumentTypes", [{k: t.get(k) for k in ("id", "Name", "Description")} for t in types])
    except RlzApiError as e:
        print("DocumentTypes:", e.status_code, e.body[:200])
    for pad in ("Ledgers/VendorBalanceAccounts", "Ledgers/CustomerBalanceAccounts"):
        try:
            _dump(pad, [{k: a.get(k) for k in ("id", "AccountNumber", "Description", "AccountType")}
                        for a in _values(rlz.get(pad))])
        except RlzApiError as e:
            print(pad, e.status_code, e.body[:200])
    # OpenBalances: hoe zien bestaande "openstaande posten zonder factuur" eruit?
    try:
        obs = _values(rlz.get("OpenBalances", params={
            "$top": 25, "$expand": "Entity,Account,PaymentAccount,PaymentReferenceList($expand=Document)"}))
        _dump("OpenBalances (sample)", [{
            "id": o.get("id"), "DocumentType": o.get("DocumentType"), "Status": o.get("Status"),
            "Date": o.get("Date"), "Reference": o.get("Reference"), "ReceiptNumber": o.get("ReceiptNumber"),
            "CreditDebit": o.get("CreditDebit"), "AmountBase": o.get("AmountBase"),
            "BaseInvoiceAmount": o.get("BaseInvoiceAmount"), "BaseRemainingAmount": o.get("BaseRemainingAmount"),
            "Entity": (o.get("Entity") or {}).get("Name"), "EntityKind": (o.get("Entity") or {}).get("EntityKind"),
            "Account": (o.get("Account") or {}).get("AccountNumber"),
            "PaymentAccount": (o.get("PaymentAccount") or {}).get("Name"),
            "Refs": [{"Amount": r.get("Amount"), "DocType": (r.get("Document") or {}).get("DocumentType")}
                     for r in o.get("PaymentReferenceList") or []],
            "OpenBalanceDescription": o.get("OpenBalanceDescription"),
        } for o in obs])
        if obs:
            try:
                _dump("OpenBalances/{id}/Actions (eerste)", rlz.get(f"OpenBalances/{obs[0]['id']}/Actions"))
            except RlzApiError as e:
                print("Actions:", e.status_code, e.body[:200])
            _dump("Journaal eerste OpenBalance", _journaal(rlz, "OpenBalances", obs[0]["id"]))
    except RlzApiError as e:
        print("OpenBalances:", e.status_code, e.body[:300])
    # Afgeletterde mutaties: naar welk documenttype wijzen de koppelingen? (mét Entity-vlag)
    try:
        txs = _values(rlz.get("PaymentTransactions", params={
            "$top": max_tx, "$orderby": "BookDate desc",
            "$expand": "PaymentReferenceList($expand=Document($expand=Entity,Account))"}))
    except RlzApiError as e:
        print("PaymentTransactions:", e.status_code, e.body[:300])
        return
    teller: Counter[str] = Counter()
    voorbeelden: dict[str, Any] = {}
    for t in txs:
        for r in t.get("PaymentReferenceList") or []:
            d = r.get("Document") or {}
            sleutel = (f"DocType {d.get('DocumentType')} | Status {d.get('Status')} | "
                       f"Entity={'ja' if d.get('Entity') else 'nee'} | Account={(d.get('Account') or {}).get('AccountNumber')} | "
                       f"Sys={d.get('IsSystemGenerated')}")
            teller[sleutel] += 1
            voorbeelden.setdefault(sleutel, {
                "tx": t.get("id"), "tx_Amount": t.get("Amount"), "tx_Open": t.get("OpenAmount"),
                "ref_Amount": r.get("Amount"), "doc_id": d.get("id"), "ReceiptNumber": d.get("ReceiptNumber"),
                "Reference": d.get("Reference"), "Entity": (d.get("Entity") or {}).get("Name")})
    _dump(f"Koppelingen per documentvorm over {len(txs)} mutaties", teller.most_common())
    _dump("Voorbeeld per vorm", voorbeelden)
    state = _state()
    state.setdefault("recon", {})[label] = {"vormen": teller.most_common(), "voorbeelden": voorbeelden}
    _save_state(state)


def stap_recon_test(_c: PocClient | None = None) -> None:
    ro = ReadOnlyClient("TESTADMIN_USERNAME", "TESTADMIN_PASSWORD")
    _recon_admin(ro.for_admin(TESTADMIN_ID), "TEST-administratie")


def stap_recon_prod(_c: PocClient | None = None, welke: str = "RLZ") -> None:
    """READ-ONLY tegen productie (BLOW = RLZ_USERNAME): geen enkele schrijfactie."""
    ro = ReadOnlyClient(f"{welke}_USERNAME", f"{welke}_PASSWORD")
    for a in ro.admins:
        _recon_admin(ro.for_admin(a["id"]), f"{welke} {a.get('Name')} ({a['id']})")


def stap_recon_doc(_c: PocClient | None, welke: str, admin_id: str, collectie: str, doc_id: str) -> None:
    """READ-ONLY: één document volledig dumpen (voor het ontleden van een UI-relatieboeking)."""
    ro = ReadOnlyClient(f"{welke}_USERNAME", f"{welke}_PASSWORD")
    rlz = ro.for_admin(admin_id)
    d = rlz.get(f"{collectie}/{doc_id}", params={
        "$expand": "Entity,Account,PaymentAccount,DocumentCategory,DocumentLineList($expand=Account,TaxRate),"
                   "PaymentReferenceList($expand=Document)"})
    _dump(f"{collectie}/{doc_id}", d)
    _dump("Journaal", _journaal(rlz, collectie, doc_id))
    try:
        items = _values(rlz.get("PaymentItems", params={"$filter": f"Document/id eq {doc_id}"}))
        _dump("PaymentItems bij dit document", items)
    except RlzApiError as e:
        print("PaymentItems:", e.status_code, e.body[:200])


# --------------------------------------------------------------------------- schrijf-probes (TEST)

VENDOR_ID = "1cfe3147-a457-4814-a34e-0dd6b59d16b4"        # "TEST PoC bank-fallback — storneren" (bestaand)
REKENING_ID = "dc47ca86-ec65-4ca9-8add-12e26d4eaeec"       # NL38 INGB 0008 2334 72 (test-administratie)
BANK_GB_ID = "cb6016e8-7ffe-4232-8555-0f19d5f79dca"        # 1004 = GB van die rekening
GB_CREDITEUREN = "6ebb1407-a909-47b5-b55a-64861f5d7f63"    # 1600 (VendorBalanceAccounts)
GB_DEBITEUREN = "fe0020f8-c704-457a-8028-581e92e66ac6"     # 1200 (CustomerBalanceAccounts)
GB_KRUISPOSTEN = "184fa7f0-c6b3-4542-af9e-5867c17719f6"    # kruisposten (fallback-PoC)
DIARY_ID = "b4407a30-6f3d-f7f6-be6c-e2a8ba43ab1e"          # memoriaal-dagboek (fallback-PoC)
CAT_MEMORIAAL = "aaa3e834-4870-4a03-9a1f-f56a414893a7"     # DocumentCategory "Memoriaal" (type 11)


def _nieuwe_tx(c: PocClient, *, bedrag: float, referentie: str, naam: str) -> str:
    tx_id = str(uuid.uuid4())
    c.put(f"PaymentTransactions/{tx_id}", {
        "id": tx_id, "PaymentAccount": {"id": REKENING_ID},
        "BookDate": datetime.now(UTC).date().isoformat(),
        "Amount": bedrag, "Name": naam, "Reference": referentie,
    }, lees_terug=False)
    return tx_id


def _nieuwe_factuur(c: PocClient, *, netto: float, btw: float, referentie: str) -> tuple[str, str]:
    inv = str(uuid.uuid4())
    c.put(f"PurchaseInvoices/{inv}", {
        "id": inv, "Entity": {"id": VENDOR_ID}, "Reference": referentie,
        "DocumentLineList": [{"Account": {"id": TEST_ACCOUNT_ID}, "TaxRate": {"id": TEST_TAXRATE_ID},
                              "NetAmount": netto, "TaxAmount": btw}],
    }, lees_terug=False)
    c.actie(f"PurchaseInvoices/{inv}", ACTION_BOOK)
    items = _values(c.get("PaymentItems", **{"$filter": f"Document/id eq {inv}"}))
    if not items:
        raise SystemExit(f"Geen open PaymentItem bij {referentie} — stop.")
    return inv, items[0]["id"]


def stap_setup(c: PocClient) -> None:
    """Testopstelling: debiteur, drie TX'en (relatie-probes + splits-probe) en twee geboekte facturen."""
    state = _state()
    if not state.get("customer_id"):
        cid = str(uuid.uuid4())
        c.rlz.put_customer(uuid.UUID(cid), name="TEST PoC debiteur relatie — storneren")
        _audit({"actie": "PUT Customer", "admin": TESTADMIN_ID, "id": cid})
        state["customer_id"] = cid
    _save_state(state)
    if not state.get("tx_r1"):
        state["tx_r1"] = _nieuwe_tx(c, bedrag=-100.00, referentie="TEST-RELPOC-TX1", naam="TEST PoC vooruitbetaling crediteur")
        _save_state(state)
    if not state.get("tx_r2") and not state.get("tx_r2_fout"):
        # Positief bedrag (ontvangst): eerste poging met Amount gaf 400 _InvalidData — varianten proberen.
        for variant in ({"Amount": 80.00}, {"Amount": 80.00, "DebitAmount": 80.00}, {"DebitAmount": 80.00},
                        {"Amount": 80.00, "CreditAmount": 80.00}):
            tx_id = str(uuid.uuid4())
            status = c.put_probe(f"PaymentTransactions/{tx_id}", {
                "id": tx_id, "PaymentAccount": {"id": REKENING_ID},
                "BookDate": datetime.now(UTC).date().isoformat(), "Name": "TEST PoC ontvangst debiteur zonder factuur",
                "Reference": "TEST-RELPOC-TX2", **variant})
            print(f"TX_R2 variant {variant}: {status}")
            if status == 204:
                state["tx_r2"] = tx_id
                break
        else:
            state["tx_r2_fout"] = "positieve PaymentTransaction niet aan te maken via PUT (400 _InvalidData in alle varianten)"
        _save_state(state)
    if not state.get("f1"):
        state["f1"], state["f1_item"] = _nieuwe_factuur(c, netto=82.64, btw=17.36, referentie="TEST-SPLITPOC-F1")  # 100,00
        _save_state(state)
    if not state.get("f2"):
        state["f2"], state["f2_item"] = _nieuwe_factuur(c, netto=41.32, btw=8.68, referentie="TEST-SPLITPOC-F2")   # 50,00
        _save_state(state)
    if not state.get("tx_s1"):
        state["tx_s1"] = _nieuwe_tx(c, bedrag=-300.00, referentie="TEST-SPLITPOC-TX1", naam="TEST PoC splitsen")
        _save_state(state)
    for k in ("tx_r1", "tx_r2", "tx_s1"):
        if state.get(k):
            _dump(k, _tx_staat(c.rlz, state[k]))
    _dump("open posten vendor", _items_voor_entity(c.rlz, VENDOR_ID))


def _bmdb_probe(c: PocClient, label: str, tx: str, body_extra: dict[str, Any]) -> dict[str, Any]:
    doc_id = str(uuid.uuid4())
    body = {"id": doc_id, "PaymentTransaction": {"id": tx}, "Description": label, **body_extra}
    status = c.put_probe(f"BankMutationDirectBookings/{doc_id}", body)
    na = _tx_staat(c.rlz, tx)
    doc: Any = None
    if status == 204:
        try:
            d = c.get(f"BankMutationDirectBookings/{doc_id}", **{"$expand": "Entity,Account"})
            doc = {k: d.get(k) for k in ("Status", "DocumentType", "ReceiptNumber", "BaseInvoiceAmount")} | {
                "Entity": (d.get("Entity") or {}).get("Name"), "Account": (d.get("Account") or {}).get("AccountNumber")}
        except RlzApiError as e:
            doc = f"{e.status_code}"
    return {"probe": label, "status": status, "doc_id": doc_id, "doc": doc, "OpenAmount na": na["OpenAmount"],
            "refs na": na["PaymentReferenceList"]}


def stap_probe_relatie(c: PocClient) -> None:
    """Punt 3 STAP-0: welke boekvorm zet TX_R1 (−100) op de CREDITEUR als verrekenbare open post?
    Succescriterium: OpenAmount 0 én een open PaymentItem op de vendor (Document mét Entity)."""
    state = _state()
    tx = state["tx_r1"]
    voor = _tx_staat(c.rlz, tx)
    _dump("TX_R1 vóór", voor)
    _dump("open posten vendor vóór", _items_voor_entity(c.rlz, VENDOR_ID))
    if (voor["OpenAmount"] or 0) == 0:
        raise SystemExit("TX_R1 is al dicht — eerst storneren.")
    resultaten: list[dict[str, Any]] = []
    probes = [
        ("A: BMDB Entity + document-Account 1600, zonder regels",
         {"Entity": {"id": VENDOR_ID}, "Account": {"id": GB_CREDITEUREN}}),
        ("B: BMDB Entity + regel op 1600",
         {"Entity": {"id": VENDOR_ID}, "DocumentLineList": [{"Account": {"id": GB_CREDITEUREN}, "NetAmount": -100.00}]}),
        ("C: BMDB Entity + document-Account 1600 + regel 1600",
         {"Entity": {"id": VENDOR_ID}, "Account": {"id": GB_CREDITEUREN},
          "DocumentLineList": [{"Account": {"id": GB_CREDITEUREN}, "NetAmount": -100.00}]}),
        ("D: BMDB zónder Entity, regel op 1600 (koppelrekening kaal)",
         {"DocumentLineList": [{"Account": {"id": GB_CREDITEUREN}, "NetAmount": -100.00}]}),
    ]
    for label, extra in probes:
        r = _bmdb_probe(c, label, tx, extra)
        r["open posten vendor na"] = _items_voor_entity(c.rlz, VENDOR_ID)
        resultaten.append(r)
        print(f"\n→ {label}: status {r['status']}, OpenAmount → {r['OpenAmount na']}")
        if r["status"] == 204 and (r["OpenAmount na"] or 0) == 0:
            state.setdefault("relatie_docs", []).append(r["doc_id"])
            _save_state(state)
            _dump("BMDB-vorm boekte de mutatie — details", r)
            _dump("Journaal", _journaal(c.rlz, "BankMutationDirectBookings", r["doc_id"]))
            break
    else:
        # E: OpenBalance als losse open post op de vendor (vordering = Debit)
        ob = str(uuid.uuid4())
        body = {"id": ob, "Entity": {"id": VENDOR_ID}, "Account": {"id": GB_CREDITEUREN}, "CreditDebit": 2,
                "AmountBase": 100.00, "BaseInvoiceAmount": 100.00, "Date": datetime.now(UTC).date().isoformat(),
                "Reference": "TEST-RELPOC-OB1", "OpenBalanceDescription": "TEST PoC vooruitbetaling als open post"}
        status = c.put_probe(f"OpenBalances/{ob}", body)
        r: dict[str, Any] = {"probe": "E: OpenBalance op vendor (Debit 100)", "status": status, "doc_id": ob}
        if status == 204:
            d = c.get(f"OpenBalances/{ob}", **{"$expand": "Entity,Account"})
            r["doc"] = {k: d.get(k) for k in ("Status", "DocumentType", "ReceiptNumber", "BaseInvoiceAmount",
                                               "BaseRemainingAmount", "CreditDebit")}
            r["items"] = _values(c.get("PaymentItems", **{"$filter": f"Document/id eq {ob}"}))
            r["journaal"] = _journaal(c.rlz, "OpenBalances", ob)
            r["acties"] = c.get(f"OpenBalances/{ob}/Actions")
            state["openbalance_id"] = ob
            _save_state(state)
        resultaten.append(r)
        print(f"\n→ E OpenBalance: status {status}")
        # F: ManualJournal mét Entity + categorie Memoriaal (D 1600 / C bank-GB)
        mj = str(uuid.uuid4())
        body = {"id": mj, "JournalEntryDiary": {"id": DIARY_ID}, "DocumentCategory": {"id": CAT_MEMORIAAL},
                "Entity": {"id": VENDOR_ID}, "Reference": "TEST-RELPOC-MJ1",
                "DocumentLineList": [
                    {"Account": {"id": GB_CREDITEUREN}, "CreditOrDebit": 1, "DebitAmount": 100.00, "Description": "TEST vooruitbetaling"},
                    {"Account": {"id": BANK_GB_ID}, "CreditOrDebit": 2, "CreditAmount": 100.00, "Description": "TEST vooruitbetaling"},
                ]}
        status = c.put_probe(f"ManualJournals/{mj}", body)
        r = {"probe": "F: ManualJournal Entity + categorie Memoriaal", "status": status, "doc_id": mj}
        if status == 204:
            state["memoriaal_id"] = mj
            _save_state(state)
            d = c.get(f"ManualJournals/{mj}", **{"$expand": "Entity"})
            r["doc"] = {k: d.get(k) for k in ("Status", "Entity")}
        resultaten.append(r)
        print(f"\n→ F ManualJournal: status {status}")
        # G: actie 161 mét Entity in de body
        status = c.post_raw_actions(f"PaymentTransactions/{tx}", {"Type": 161, "Entity": {"id": VENDOR_ID}})
        na = _tx_staat(c.rlz, tx)
        r = {"probe": "G: actie 161 + Entity", "status": status, "OpenAmount na": na["OpenAmount"], "refs na": na["PaymentReferenceList"]}
        if (na["OpenAmount"] or 0) == 0:
            for ref in na["PaymentReferenceList"]:
                if ref["Document"]["DocumentType"] == 1:
                    state.setdefault("docs_161", []).append(ref["Document"]["id"])
            _save_state(state)
        resultaten.append(r)
        print(f"\n→ G actie 161 + Entity: status {status}, OpenAmount → {na['OpenAmount']}")
    _dump("RESULTATEN probe-relatie", resultaten)
    _dump("open posten vendor ná", _items_voor_entity(c.rlz, VENDOR_ID))
    state["probe_relatie"] = resultaten
    _save_state(state)


def stap_probe_splitsen(c: PocClient) -> None:
    """Punt 4 STAP-0 op TX_S1 (−300): S0 twee open posten in één actie-15-call (F1 100 + F2 50),
    S2 deel direct-op-grootboek (BMDB −100 op 4699), S3 rest (−50) op kruisposten — sluit de som?"""
    state = _state()
    tx = state["tx_s1"]
    voor = _tx_staat(c.rlz, tx)
    _dump("TX_S1 vóór", voor)
    uit: list[dict[str, Any]] = []
    # S0: twee items in één call
    body = {"Type": 15, "PaymentItemList": [{"id": state["f1_item"]}, {"id": state["f2_item"]}],
            "LinkedAmount": -150.00, "IsCompletelyPaid": False, "PaymentCorrectionMethod": 1}
    status = c.post_raw_actions(f"PaymentTransactions/{tx}", body)
    na = _tx_staat(c.rlz, tx)
    uit.append({"stap": "S0 twee PaymentItems in één actie 15 (−150)", "status": status, "OpenAmount na": na["OpenAmount"],
                "refs": na["PaymentReferenceList"], "posten vendor": _items_voor_entity(c.rlz, VENDOR_ID)})
    print(f"\n→ S0: status {status}, OpenAmount {voor['OpenAmount']} → {na['OpenAmount']}")
    if na["OpenAmount"] == voor["OpenAmount"]:
        # Fallback: één voor één (bewezen vorm)
        for item, bedrag, label in ((state["f1_item"], -100.00, "S0b F1 los"), (state["f2_item"], -50.00, "S0c F2 los")):
            status = c.post_raw_actions(f"PaymentTransactions/{tx}", _koppel_body(item_id=item, linked_amount=bedrag))
            na = _tx_staat(c.rlz, tx)
            uit.append({"stap": label, "status": status, "OpenAmount na": na["OpenAmount"]})
            print(f"\n→ {label}: status {status}, OpenAmount → {na['OpenAmount']}")
    # S2: deel direct-op-grootboek (−100) terwijl de mutatie nog −150 open heeft
    r = _bmdb_probe(c, "S2 deel −100 op 4699", tx, {"DocumentLineList": [
        {"Account": {"id": TEST_ACCOUNT_ID}, "TaxRate": {"id": TEST_TAXRATE_ID}, "NetAmount": -82.64, "TaxAmount": -17.36}]})
    uit.append(r)
    print(f"\n→ S2: status {r['status']}, OpenAmount → {r['OpenAmount na']}")
    if r["status"] == 204:
        state["split_bmdb_1"] = r["doc_id"]
        _save_state(state)
    # S3: rest op kruisposten
    rest = _tx_staat(c.rlz, tx)["OpenAmount"] or 0
    if rest != 0:
        r = _bmdb_probe(c, f"S3 rest {rest} op kruisposten", tx, {"DocumentLineList": [
            {"Account": {"id": GB_KRUISPOSTEN}, "NetAmount": rest}]})
        uit.append(r)
        print(f"\n→ S3: status {r['status']}, OpenAmount → {r['OpenAmount na']}")
        if r["status"] == 204:
            state["split_bmdb_2"] = r["doc_id"]
            _save_state(state)
    eind = _tx_staat(c.rlz, tx)
    _dump("TX_S1 eindstaat", eind)
    for f in ("f1", "f2"):
        d = c.get(f"PurchaseInvoices/{state[f]}")
        _dump(f"factuur {f}", {k: d.get(k) for k in ("Status", "BaseInvoiceAmount", "BasePaidAmount", "BaseRemainingAmount")})
    state["probe_splitsen"] = uit
    _save_state(state)
    _dump("RESULTATEN probe-splitsen", uit)


def stap_storno_splitsen(c: PocClient) -> None:
    """Storno per deel: eerst het BMDB-deel (actie 19 op het BMDB-document), dan F1 (actie 19 op de
    factuur) — effect op OpenAmount van TX_S1 en op de PaymentReferenceList per stap vastleggen."""
    state = _state()
    tx = state["tx_s1"]
    uit: list[dict[str, Any]] = []
    for sleutel, pad in (("split_bmdb_1", "BankMutationDirectBookings"), ("f1", "PurchaseInvoices")):
        doc = state.get(sleutel)
        if not doc:
            continue
        voor = _tx_staat(c.rlz, tx)
        status = c.actie(f"{pad}/{doc}", ACTION_CORRECT)
        na = _tx_staat(c.rlz, tx)
        uit.append({"storno": f"{sleutel} ({pad})", "status": status, "OpenAmount voor": voor["OpenAmount"],
                    "OpenAmount na": na["OpenAmount"], "refs na": na["PaymentReferenceList"]})
        print(f"\n→ storno {sleutel}: {status}, OpenAmount {voor['OpenAmount']} → {na['OpenAmount']}")
    # herstel-poging: kan het gestorneerde BMDB-deel opnieuw (her-PUT zelfde GUID)?
    if state.get("split_bmdb_1"):
        status = c.put_probe(f"BankMutationDirectBookings/{state['split_bmdb_1']}", {
            "id": state["split_bmdb_1"], "PaymentTransaction": {"id": tx}, "Description": "S2 her-PUT na storno",
            "DocumentLineList": [{"Account": {"id": TEST_ACCOUNT_ID}, "TaxRate": {"id": TEST_TAXRATE_ID},
                                  "NetAmount": -82.64, "TaxAmount": -17.36}]})
        na = _tx_staat(c.rlz, tx)
        uit.append({"her-PUT BMDB-deel na storno": status, "OpenAmount na": na["OpenAmount"], "refs na": na["PaymentReferenceList"]})
        print(f"\n→ her-PUT BMDB-deel: {status}, OpenAmount → {na['OpenAmount']}")
    state["storno_splitsen"] = uit
    _save_state(state)
    _dump("RESULTATEN storno-splitsen", uit)


def stap_cleanup(c: PocClient) -> None:
    """Alles storneren (actie 19) wat nog geboekt staat; TX'en blijven (DELETE verboden)."""
    state = _state()
    for sleutel, pad in (("f1", "PurchaseInvoices"), ("f2", "PurchaseInvoices"), ("split_bmdb_1", "BankMutationDirectBookings"),
                         ("split_bmdb_2", "BankMutationDirectBookings"), ("split_bmdb_1b", "BankMutationDirectBookings"), ("openbalance_id", "OpenBalances"),
                         ("memoriaal_id", "ManualJournals"), ("aanbetaling_id", "PurchaseInvoices"), ("p2_id", "PurchaseInvoices")):
        doc = state.get(sleutel)
        if not doc:
            continue
        try:
            d = c.get(f"{pad}/{doc}")
        except RlzApiError as e:
            print(f"{sleutel}: {e.status_code}")
            continue
        if d.get("Status") != 1:
            try:
                print(f"{sleutel}: actie 19 → {c.actie(f'{pad}/{doc}', ACTION_CORRECT)}")
            except RlzApiError as e:
                print(f"{sleutel}: storno faalt {e.status_code} {e.body[:200]}")
        else:
            print(f"{sleutel}: al concept")
    for lijst, pad in (("relatie_docs", "BankMutationDirectBookings"), ("docs_161", "PurchaseInvoices")):
        for doc in state.get(lijst, []):
            try:
                d = c.get(f"{pad}/{doc}")
                if d.get("Status") != 1:
                    print(f"{lijst} {doc}: actie 19 → {c.actie(f'{pad}/{doc}', ACTION_CORRECT)}")
            except RlzApiError as e:
                print(f"{lijst} {doc}: {e.status_code}")
    for k in ("tx_r1", "tx_r2", "tx_s1"):
        if state.get(k):
            _dump(f"{k} eindstaat", _tx_staat(c.rlz, state[k]))


GB_VOORUIT_INKOOP = "847a312d-5190-4bc9-aadd-fdf83682f750"   # 1403 Vooruit betaalde inkoopfacturen (systeemrekening, type 3)
GB_VOORUIT_OVERIG = "96595533-a2ae-4dd7-8c36-2d9986493d37"   # 1405 Overige vooruitbetaalde bedragen (inkoop + bank toegestaan)
TAXRATE_GEEN = "4c8a31dd-d20b-4335-b4e3-9dd623589d62"        # 0% (gebruikt op RLZ's eigen salaris-memoriaal)


def _factuur_staat(c: PocClient, inv: str) -> dict[str, Any]:
    d = c.get(f"PurchaseInvoices/{inv}")
    return {k: d.get(k) for k in ("Status", "ReceiptNumber", "Reference", "BaseInvoiceAmount", "BasePaidAmount",
                                  "BaseRemainingAmount")}


def stap_probe_relatie_2(c: PocClient) -> None:
    """Vervolg: D (BMDB kaal op 1600) storneren, daarna E (OpenBalance), F (memoriaal mét Entity) en
    H = AANBETALINGSDOCUMENT: PurchaseInvoice op de crediteur met één regel op de vooruitbetalings-
    balansrekening (géén btw) → open post op de Entity → mutatie afletteren (actie 15) → later
    verrekenen via een tegenregel op de echte factuur (P2) → storno (actie 19) P1."""
    state = _state()
    tx = state["tx_r1"]
    uit: list[dict[str, Any]] = []
    # 0. storno D
    for doc in state.get("relatie_docs", []):
        d = c.get(f"BankMutationDirectBookings/{doc}")
        if d.get("Status") != 1:
            st = c.actie(f"BankMutationDirectBookings/{doc}", ACTION_CORRECT)
            uit.append({"stap": "0 storno D (BMDB kaal 1600)", "status": st, "TX na": _tx_staat(c.rlz, tx)})
    voor = _tx_staat(c.rlz, tx)
    if (voor["OpenAmount"] or 0) == 0:
        raise SystemExit("TX_R1 nog dicht na storno — stop.")
    # E. OpenBalance op de vendor
    if not state.get("openbalance_id"):
        ob = str(uuid.uuid4())
        status = c.put_probe(f"OpenBalances/{ob}", {
            "id": ob, "Entity": {"id": VENDOR_ID}, "Account": {"id": GB_CREDITEUREN}, "CreditDebit": 2,
            "AmountBase": 100.00, "BaseInvoiceAmount": 100.00, "Date": datetime.now(UTC).date().isoformat(),
            "Reference": "TEST-RELPOC-OB1", "OpenBalanceDescription": "TEST PoC vooruitbetaling als open post"})
        r: dict[str, Any] = {"stap": "E OpenBalance op vendor (Debit 100, Account 1600)", "status": status, "doc_id": ob}
        if status == 204:
            state["openbalance_id"] = ob
            _save_state(state)
            try:
                d = c.get(f"OpenBalances/{ob}", **{"$expand": "Entity,Account"})
                r["doc"] = {k: d.get(k) for k in ("Status", "DocumentType", "ReceiptNumber", "BaseInvoiceAmount",
                                                   "BaseRemainingAmount", "CreditDebit")} | {"Entity": (d.get("Entity") or {}).get("Name")}
                r["items"] = _values(c.get("PaymentItems", **{"$filter": f"Document/id eq {ob}"}))
                r["journaal"] = _journaal(c.rlz, "OpenBalances", ob)
                r["acties"] = c.get(f"OpenBalances/{ob}/Actions")
            except RlzApiError as e:
                r["lees_fout"] = f"{e.status_code}: {e.body[:200]}"
        uit.append(r)
        print(f"\n→ E: {status}")
    # F. ManualJournal mét Entity + categorie Memoriaal
    mj = str(uuid.uuid4())
    status = c.put_probe(f"ManualJournals/{mj}", {
        "id": mj, "JournalEntryDiary": {"id": DIARY_ID}, "DocumentCategory": {"id": CAT_MEMORIAAL},
        "Entity": {"id": VENDOR_ID}, "Reference": "TEST-RELPOC-MJ1",
        "DocumentLineList": [
            {"Account": {"id": GB_CREDITEUREN}, "CreditOrDebit": 1, "DebitAmount": 100.00, "Description": "TEST vooruitbetaling"},
            {"Account": {"id": BANK_GB_ID}, "CreditOrDebit": 2, "CreditAmount": 100.00, "Description": "TEST vooruitbetaling"}]})
    r = {"stap": "F ManualJournal Entity + categorie Memoriaal (D1600/C1004)", "status": status, "doc_id": mj}
    if status == 204:
        state["memoriaal_id"] = mj
        _save_state(state)
        d = c.get(f"ManualJournals/{mj}", **{"$expand": "Entity"})
        r["doc"] = {"Status": d.get("Status"), "Entity": (d.get("Entity") or {}).get("Name")}
    uit.append(r)
    print(f"\n→ F: {status}")
    # H. Aanbetalingsdocument
    for gb, label in ((GB_VOORUIT_INKOOP, "1403 Vooruit betaalde inkoopfacturen"), (GB_VOORUIT_OVERIG, "1405 Overige vooruitbetaalde bedragen")):
        if state.get("aanbetaling_id"):
            break
        p1 = str(uuid.uuid4())
        status = c.put_probe(f"PurchaseInvoices/{p1}", {
            "id": p1, "Entity": {"id": VENDOR_ID}, "Reference": "TEST-RELPOC-AANB1",
            "DocumentLineList": [{"Account": {"id": gb}, "TaxRate": {"id": TAXRATE_GEEN}, "NetAmount": 100.00,
                                  "TaxAmount": 0.0, "Description": "TEST aanbetaling zonder factuur"}]})
        r = {"stap": f"H1 PUT aanbetalingsdocument op {label}", "status": status, "doc_id": p1}
        if status == 204:
            try:
                st = c.actie(f"PurchaseInvoices/{p1}", ACTION_BOOK)
                r["boeken"] = st
                r["factuur"] = _factuur_staat(c, p1)
                r["journaal"] = _journaal(c.rlz, "PurchaseInvoices", p1)
                items = _values(c.get("PaymentItems", **{"$filter": f"Document/id eq {p1}"}))
                r["items"] = items
                if items:
                    state["aanbetaling_id"] = p1
                    state["aanbetaling_item"] = items[0]["id"]
                    state["aanbetaling_gb"] = gb
                    _save_state(state)
            except RlzApiError as e:
                r["boeken"] = f"{e.status_code}: {e.body[:300]}"
        uit.append(r)
        print(f"\n→ {r['stap']}: {status} / boeken {r.get('boeken')}")
    if state.get("aanbetaling_id"):
        # H2. mutatie afletteren tegen de aanbetalingspost (bewezen actie 15)
        voor = _tx_staat(c.rlz, tx)
        status = c.post_raw_actions(f"PaymentTransactions/{tx}", _koppel_body(item_id=state["aanbetaling_item"], linked_amount=voor["OpenAmount"]))
        na = _tx_staat(c.rlz, tx)
        uit.append({"stap": "H2 actie 15 TX_R1 → aanbetalingspost", "status": status, "OpenAmount voor": voor["OpenAmount"],
                    "OpenAmount na": na["OpenAmount"], "refs": na["PaymentReferenceList"],
                    "aanbetaling": _factuur_staat(c, state["aanbetaling_id"]),
                    "open posten vendor": _items_voor_entity(c.rlz, VENDOR_ID)})
        print(f"\n→ H2: {status}, OpenAmount {voor['OpenAmount']} → {na['OpenAmount']}")
        # H3. verrekening: echte factuur P2 (200 incl.) mét tegenregel −100 op dezelfde vooruit-rekening
        if not state.get("p2_id"):
            p2 = str(uuid.uuid4())
            status = c.put_probe(f"PurchaseInvoices/{p2}", {
                "id": p2, "Entity": {"id": VENDOR_ID}, "Reference": "TEST-RELPOC-F-VERREKEN",
                "DocumentLineList": [
                    {"Account": {"id": TEST_ACCOUNT_ID}, "TaxRate": {"id": TEST_TAXRATE_ID}, "NetAmount": 165.29, "TaxAmount": 34.71,
                     "Description": "TEST kosten"},
                    {"Account": {"id": state["aanbetaling_gb"]}, "TaxRate": {"id": TAXRATE_GEEN}, "NetAmount": -100.00, "TaxAmount": 0.0,
                     "Description": "TEST verrekening aanbetaling TEST-RELPOC-AANB1"}]})
            r = {"stap": "H3 factuur mét verrekenregel −100 op vooruit-rekening", "status": status, "doc_id": p2}
            if status == 204:
                state["p2_id"] = p2
                _save_state(state)
                try:
                    r["boeken"] = c.actie(f"PurchaseInvoices/{p2}", ACTION_BOOK)
                except RlzApiError as e:
                    r["boeken"] = f"{e.status_code}: {e.body[:300]}"
                r["factuur"] = _factuur_staat(c, p2)
                r["items"] = _values(c.get("PaymentItems", **{"$filter": f"Document/id eq {p2}"}))
                r["journaal"] = _journaal(c.rlz, "PurchaseInvoices", p2)
            uit.append(r)
            print(f"\n→ H3: {status} / boeken {r.get('boeken')} / {r.get('factuur')}")
        # H4. storno aanbetalingsdocument → komt TX_R1 weer open?
        voor = _tx_staat(c.rlz, tx)
        st = c.actie(f"PurchaseInvoices/{state['aanbetaling_id']}", ACTION_CORRECT)
        na = _tx_staat(c.rlz, tx)
        uit.append({"stap": "H4 storno (19) aanbetalingsdocument", "status": st, "OpenAmount voor": voor["OpenAmount"],
                    "OpenAmount na": na["OpenAmount"], "refs": na["PaymentReferenceList"],
                    "aanbetaling": _factuur_staat(c, state["aanbetaling_id"]),
                    "open posten vendor": _items_voor_entity(c.rlz, VENDOR_ID)})
        print(f"\n→ H4 storno: {st}, OpenAmount {voor['OpenAmount']} → {na['OpenAmount']}")
        # H5. herboeken zelfde GUID (her-PUT + 17) en opnieuw koppelen — idempotentie-pad
        status = c.put_probe(f"PurchaseInvoices/{state['aanbetaling_id']}", {
            "id": state["aanbetaling_id"], "Entity": {"id": VENDOR_ID}, "Reference": "TEST-RELPOC-AANB1",
            "DocumentLineList": [{"Account": {"id": state["aanbetaling_gb"]}, "TaxRate": {"id": TAXRATE_GEEN}, "NetAmount": 100.00,
                                  "TaxAmount": 0.0, "Description": "TEST aanbetaling zonder factuur (herboekt)"}]})
        r = {"stap": "H5 her-PUT + herboeken aanbetalingsdocument", "put": status}
        try:
            r["boeken"] = c.actie(f"PurchaseInvoices/{state['aanbetaling_id']}", ACTION_BOOK)
            items = _values(c.get("PaymentItems", **{"$filter": f"Document/id eq {state['aanbetaling_id']}"}))
            r["items"] = items
            if items:
                state["aanbetaling_item"] = items[0]["id"]
                _save_state(state)
                voor = _tx_staat(c.rlz, tx)
                r["koppel"] = c.post_raw_actions(f"PaymentTransactions/{tx}", _koppel_body(item_id=items[0]["id"], linked_amount=voor["OpenAmount"]))
                r["TX na"] = _tx_staat(c.rlz, tx)
        except RlzApiError as e:
            r["boeken"] = f"{e.status_code}: {e.body[:300]}"
        uit.append(r)
        print(f"\n→ H5: {r}")
    state["probe_relatie_2"] = uit
    _save_state(state)
    _dump("RESULTATEN probe-relatie-2", uit)


STAPPEN: dict[str, Any] = {
    "probe-relatie-2": (stap_probe_relatie_2, True),
    "setup": (stap_setup, True),
    "probe-relatie": (stap_probe_relatie, True),
    "probe-splitsen": (stap_probe_splitsen, True),
    "storno-splitsen": (stap_storno_splitsen, True),
    "cleanup": (stap_cleanup, True),

    "recon-test": (stap_recon_test, False),
    "recon-prod": (stap_recon_prod, False),
    "recon-doc": (stap_recon_doc, False),
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in STAPPEN:
        raise SystemExit(f"Gebruik: poc_bank_relatie_splitsen.py <{'|'.join(STAPPEN)}> [args]")
    fn, schrijft = STAPPEN[sys.argv[1]]
    client = PocClient() if schrijft else None
    fn(client, *sys.argv[2:])


if __name__ == "__main__":
    main()
