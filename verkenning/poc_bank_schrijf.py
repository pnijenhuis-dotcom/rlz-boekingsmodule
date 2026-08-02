#!/usr/bin/env python3
"""Bankmodule SCHRIJF-PoC (fase 2) — uitsluitend tegen de RLZ-test-administratie.

Uitgevoerd 2 augustus 2026. Resultaten canoniek in verkenning/api-verkenning.md
("Bankmodule schrijf-PoC"); elke schrijfactie (ook de mislukte experimenten, die via losse
inline-runs met dezelfde waarborgen liepen) staat in `output/bankpoc_audit.jsonl`,
de aangemaakte id's in `output/bankpoc_state.json`.

Kernuitkomsten (details in api-verkenning.md):
- Actie 15/16 (Link/UnlinkPayment): payload NIET gevonden — elke gedocumenteerde
  ApiAction-vorm geeft 400 _InvalidData → supportvraag aan RLZ.
- Afletteren-op-grootboek (bankkosten e.d.): PUT BankMutationDirectBookings/{nieuw-guid}
  met PaymentTransaction + DocumentLineList boekt direct (Status 3) én lettert de mutatie
  af (OpenAmount 0). Terugdraaien = actie 19 op dat document.
- Verwachte-betaling-flow: PUT QuickPaymentSelection "Betaald per bank" op de factuur +
  actie 148 op het betaal-item (= verwachte bankregel, zelfde id) boekt de betaling en
  maakt daarbij een EIGEN bankregel aan (niet bruikbaar bij een echte bankfeed).
- Leesspoor "waartegen afgeletterd": $expand=PaymentReferenceList($expand=Document).
- MatchedPaymentItem = RLZ's eigen matchvoorstel (auto-gevuld bij exacte bedrag-match).
- IsComplete blijft na terugdraaien stale op true — OpenAmount is de betrouwbare indicator.

Waarborgen (equivalent van de app-failsafes, besluit 0005 + kernprincipes):
- ADMIN-PIN: het script weigert te starten als de login iets anders ziet dan de
  test-administratie; elke request loopt via de gepinde admin-scope.
- KILL SWITCH: bestaat het bestand `verkenning/POC_STOP`, dan wordt vóór elke
  schrijfactie geweigerd.
- TOGGLE: draait alleen met een expliciet subcommando; zonder argument gebeurt er niets.
- TEST-referenties: alles herkenbaar aan `TEST-BANKPOC-`.
- AUDIT: append-only JSONL per actie (wie/wat/wanneer/status/oud→nieuw).
- NOOIT DELETE: opruimen = actie 19 (storneren). De aangemaakte test-PaymentTransactions
  blijven bewust staan (RLZ kent geen storno voor een kale bankregel; DELETE is verboden).

Gebruik:
    backend/.venv/bin/python verkenning/poc_bank_schrijf.py <stap> [args]
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER.parent / "backend"))

from dotenv import load_dotenv  # noqa: E402

from app.rlz.client import RlzApiError, RlzClient  # noqa: E402

load_dotenv(HIER / ".env")

# Platform/registers/entiteiten.md — RLZ-test-administratie "Administratiekantoor Nijenhuis".
TESTADMIN_ID = "8dbfb856-d75b-4ec3-9124-c8b739fe3bc5"
# Vaste testrekeningen (zelfde als tests/integration/test_write_integration.py):
# 4699 Diverse algemene kosten / 21% NL.
TEST_ACCOUNT_ID = "79b6f64a-dad9-4683-9e47-9c182ebae1c1"
TEST_TAXRATE_ID = "1e44993a-15f6-419f-87e5-3e31ac3d9383"

KILL_SWITCH = HIER / "POC_STOP"
OUTPUT = HIER / "output"
AUDIT_LOG = OUTPUT / "bankpoc_audit.jsonl"
STATE_FILE = OUTPUT / "bankpoc_state.json"

ACTION_BOOK = 17
ACTION_CORRECT = 19
ACTION_BOOK_EXPECTED = 148  # "Boek verwachte bankregel" — alleen op verwachte regels (Type 2)


def _nu() -> str:
    return datetime.now(UTC).isoformat()


def _audit(entry: dict[str, Any]) -> None:
    OUTPUT.mkdir(exist_ok=True)
    entry = {"ts": _nu(), "admin": TESTADMIN_ID, **entry}
    with AUDIT_LOG.open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def _state() -> dict[str, Any]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def _save_state(state: dict[str, Any]) -> None:
    OUTPUT.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


class PocClient:
    """Dunne schil om RlzClient: admin-pin, kill switch vóór elke write, audit per actie."""

    def __init__(self) -> None:
        import os

        user = os.environ.get("TESTADMIN_USERNAME")
        pw = os.environ.get("TESTADMIN_PASSWORD")
        if not user or not pw:
            raise SystemExit("TESTADMIN_USERNAME/TESTADMIN_PASSWORD niet gevuld in verkenning/.env")
        self._login_naam = user
        login = RlzClient(username=user, password=pw)
        admins = login.list_administrations()
        ids = [a["id"] for a in admins]
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

    def put(self, path: str, body: dict[str, Any], *, params: dict[str, Any] | None = None) -> Any:
        self._check_kill_switch()
        oud = self._snapshot(path)
        try:
            r = self.rlz.put(path, body, params=params)
            status: Any = r.status_code
        except RlzApiError as e:
            status = f"{e.status_code}: {e.body[:300]}"
            _audit({"actie": "PUT", "login": self._login_naam, "pad": path, "payload": body,
                    "status": status, "oud": oud})
            raise
        nieuw = self._snapshot(path)
        _audit({"actie": "PUT", "login": self._login_naam, "pad": path, "payload": body,
                "status": status, "oud": oud, "nieuw": nieuw})
        return nieuw

    def actie(self, doc_pad: str, actie_type: int, **extra: Any) -> Any:
        self._check_kill_switch()
        oud = self._snapshot(doc_pad)
        try:
            r = self.rlz.post_action(doc_pad, actie_type, **extra)
            status: Any = r.status_code
        except RlzApiError as e:
            status = f"{e.status_code}: {e.body[:300]}"
            _audit({"actie": f"POST Actions {actie_type}", "login": self._login_naam,
                    "pad": doc_pad, "extra_body": extra, "status": status, "oud": oud})
            raise
        nieuw = self._snapshot(doc_pad)
        _audit({"actie": f"POST Actions {actie_type}", "login": self._login_naam, "pad": doc_pad,
                "extra_body": extra, "status": status, "oud": oud, "nieuw": nieuw})
        return nieuw

    def _snapshot(self, path: str) -> Any:
        try:
            return self.rlz.get(path)
        except RlzApiError:
            return None


def _dump(label: str, data: Any) -> None:
    print(f"\n=== {label} ===")
    print(json.dumps(data, indent=2, default=str, ensure_ascii=False))


# --------------------------------------------------------------------------- stappen


def stap_setup(c: PocClient) -> None:
    """Bankrekening kiezen + testcrediteur + geboekte inkoopfactuur (€121) → open PaymentItem."""
    state = _state()

    accounts = c.get("PaymentAccounts")["value"]
    bank = [a for a in accounts if a.get("Type") == 1 and not a.get("IsArchived")]
    _dump("PaymentAccounts (Type 1, niet gearchiveerd)", [
        {k: a.get(k) for k in ("id", "Description", "IBAN", "Type", "IsDefault")} for a in bank
    ])
    if not bank:
        raise SystemExit("Geen bankrekening (Type 1) in de test-administratie.")
    rekening = next((a for a in bank if a.get("IsDefault")), bank[0])
    state["rekening_id"] = rekening["id"]

    vendor_id = state.get("vendor_id") or str(uuid.uuid4())
    c.put(f"Vendors/{vendor_id}", {"id": vendor_id, "Name": "TEST PoC bankmodule — storneren"})
    state["vendor_id"] = vendor_id

    invoice_id = state.get("invoice_id") or str(uuid.uuid4())
    ref = "TEST-BANKPOC-INV1"
    c.put(
        f"PurchaseInvoices/{invoice_id}",
        {
            "id": invoice_id,
            "Entity": {"id": vendor_id},
            "Reference": ref,
            "DocumentLineList": [
                {
                    "Account": {"id": TEST_ACCOUNT_ID},
                    "TaxRate": {"id": TEST_TAXRATE_ID},
                    "NetAmount": 100.00,
                    "TaxAmount": 21.00,
                }
            ],
        },
    )
    state["invoice_id"] = invoice_id
    factuur_na_boeken = c.actie(f"PurchaseInvoices/{invoice_id}", ACTION_BOOK)
    _dump("Factuur na boeken (verwacht Status 2)", {
        k: factuur_na_boeken.get(k)
        for k in ("id", "Status", "Reference", "BaseInvoiceAmount", "BaseRemainingAmount",
                  "BasePaidAmount", "ReceiptNumber")
    })

    items = c.get("PaymentItems", **{"$filter": f"Document/id eq {invoice_id}"})["value"]
    _dump("PaymentItems bij de factuur", items)
    if items:
        state["item_id"] = items[0]["id"]
    _save_state(state)
    print(f"\nState opgeslagen: {STATE_FILE}")


def stap_tx(c: PocClient, bedrag: str = "-121.00", suffix: str = "TX1") -> None:
    """PaymentTransaction aanmaken via PUT + client-GUID (geverifieerd: minimale payload
    volstaat; RLZ maakt automatisch een systeemhuls (DocumentType 19) + PaymentReference aan
    en vult MatchedPaymentItem als er een openstaand item met exact hetzelfde bedrag is)."""
    state = _state()
    tx_id = str(uuid.uuid4())
    body = {
        "id": tx_id,
        "PaymentAccount": {"id": state["rekening_id"]},
        "BookDate": datetime.now(UTC).date().isoformat(),
        "Amount": float(bedrag),
        "Name": "TEST PoC bankmodule",
        "Reference": f"TEST-BANKPOC-{suffix}",
    }
    nieuw = c.put(f"PaymentTransactions/{tx_id}", body)
    _dump(f"PaymentTransaction {suffix} na PUT", nieuw)
    state.setdefault("tx", {})[suffix] = tx_id
    _save_state(state)


def stap_direct(c: PocClient, suffix: str = "TX1") -> None:
    """GEVERIFIEERDE flow 'mutatie direct op grootboek': PUT nieuw BankMutationDirectBookings-
    document met PaymentTransaction + regel(s) → boekt direct (Status 3, reeks RLZ-07) én
    lettert de mutatie af (OpenAmount 0). Geen actie 17 nodig (409 NotAllowed)."""
    state = _state()
    tx = state["tx"][suffix]
    db_id = str(uuid.uuid4())
    t = c.get(f"PaymentTransactions/{tx}")
    body = {
        "id": db_id,
        "PaymentTransaction": {"id": tx},
        "Description": "TEST-BANKPOC direct op GB",
        "DocumentLineList": [{
            "Account": {"id": TEST_ACCOUNT_ID},
            "NetAmount": t["Amount"],
            "Description": "TEST-BANKPOC directe boeking",
        }],
    }
    nieuw = c.put(f"BankMutationDirectBookings/{db_id}", body)
    _dump("Directe boeking na PUT (verwacht Status 3)", nieuw)
    state["directbooking_id"] = db_id
    _save_state(state)
    stap_inspect(c)


def stap_inspect(c: PocClient) -> None:
    """Actuele staat van alle betrokken objecten dumpen (read-only). Let op: OpenAmount is
    de betrouwbare afgeletterd-indicator; IsComplete blijft na terugdraaien stale op true."""
    state = _state()
    if inv := state.get("invoice_id"):
        f = c.get(f"PurchaseInvoices/{inv}")
        _dump("Factuur", {k: f.get(k) for k in (
            "id", "Status", "Reference", "BaseInvoiceAmount", "BaseRemainingAmount",
            "BasePaidAmount", "ReceiptNumber")})
        items = c.get("PaymentItems", **{"$filter": f"Document/id eq {inv}"})["value"]
        _dump("PaymentItems (leeg = betaald of factuur in concept)", items)
    for suffix, tx in (state.get("tx") or {}).items():
        t = c.get(f"PaymentTransactions/{tx}",
                  **{"$expand": "MatchedPaymentItem,PaymentReferenceList($expand=Document)"})
        _dump(f"PaymentTransaction {suffix}", {
            "IsComplete (stale na terugdraaien!)": t.get("IsComplete"),
            "OpenAmount": t.get("OpenAmount"),
            "MatchedPaymentItem (= RLZ-matchvoorstel)": t.get("MatchedPaymentItem"),
            "PaymentReferenceList (= waartegen afgeletterd)": t.get("PaymentReferenceList"),
        })


def stap_cleanup(c: PocClient) -> None:
    """Alles terugdraaien met actie 19 (besluit 0005) — geen enkele DELETE. De aangemaakte
    test-PaymentTransactions blijven bewust staan (kale bankregels kennen geen storno)."""
    state = _state()
    for sleutel in ("directbooking_id", "directbooking2_id", "directbooking3_id"):
        if db := state.get(sleutel):
            try:
                d = c.get(f"BankMutationDirectBookings/{db}")
                if d and d.get("Status") != 1:
                    c.actie(f"BankMutationDirectBookings/{db}", ACTION_CORRECT)
                    print(f"{sleutel}: gestorneerd (19) → concept")
            except RlzApiError as e:
                print(f"{sleutel}: {e.status_code}")
    if inv := state.get("invoice_id"):
        f = c.get(f"PurchaseInvoices/{inv}")
        if f.get("Status") != 1:
            c.actie(f"PurchaseInvoices/{inv}", ACTION_CORRECT)
            print("Factuur gestorneerd (19) → concept (maakt ook de betaling ongedaan)")
    stap_inspect(c)


STAPPEN = {
    "setup": stap_setup,
    "tx": stap_tx,
    "direct": stap_direct,
    "inspect": stap_inspect,
    "cleanup": stap_cleanup,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in STAPPEN:
        raise SystemExit(f"Gebruik: poc_bank_schrijf.py <{'|'.join(STAPPEN)}> [args]")
    client = PocClient()
    STAPPEN[sys.argv[1]](client, *sys.argv[2:])


if __name__ == "__main__":
    main()
