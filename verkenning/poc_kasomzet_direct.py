#!/usr/bin/env python3
"""STAP 0 — losse verkoop-/inkomstenboeking via BankMutationDirectBookings tegen de KAS.

Verifiëren, niet bouwen (opdracht 2026-08-07). Vragen:
1. Boekt een contante omzet als BankMutationDirectBookings tegen de KAS-rekening
   (PaymentAccount Type 3) — regels Account(omzet-GB) + TaxRate per categorie, GÉÉN Entity?
   Verwacht: boekt direct (Status 3), geen debiteur nodig, btw per regel geaccepteerd.
2. BESLISSEND: landt de btw van die directboeking correct in de aangifte
   (TaxDeclarations/{id}/TaxSources vóór en ná) — net als bij een SalesInvoice?
3. Gemengd rapport: vrijgestelde categorie (BLOW-cannabis-patroon) + btw-categorie.
4. Alles storneren (actie 19).

Waarborgen (identiek aan poc_bank_schrijf.py / poc_omzet_schrijf.py, besluit 0005):
- ADMIN-PIN: weigert te starten als de login iets anders ziet dan de test-administratie.
- KILL SWITCH: bestaat `verkenning/POC_STOP`, dan weigert elke schrijfactie.
- TOGGLE: draait alleen met een expliciet subcommando.
- TEST-referenties: alles herkenbaar aan `TEST-KASPOC-`.
- AUDIT: append-only JSONL (output/kaspoc_audit.jsonl).
- NOOIT DELETE: opruimen = actie 19; test-PaymentTransactions blijven bewust staan
  (kale bankregels kennen geen storno).

Gebruik:
    backend/.venv/bin/python verkenning/poc_kasomzet_direct.py <stap>
Stappen: verken | aangifte | tx | direct | gemengd | inspect | storno
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
TEST_TAXRATE_21_ID = "1e44993a-15f6-419f-87e5-3e31ac3d9383"  # 21% NL

KILL_SWITCH = HIER / "POC_STOP"
OUTPUT = HIER / "output"
AUDIT_LOG = OUTPUT / "kaspoc_audit.jsonl"
STATE_FILE = OUTPUT / "kaspoc_state.json"

ACTION_CORRECT = 19


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


def stap_verken(c: PocClient) -> None:
    """Read-only: kas-rekening (Type 3), omzet-GB, vrijgesteld-tarief, TaxDeclarations-vorm."""
    state = _state()

    accounts = c.get("PaymentAccounts")["value"]
    _dump("PaymentAccounts (alle)", [
        {k: a.get(k) for k in ("id", "Description", "IBAN", "Type", "IsDefault", "IsArchived")}
        for a in accounts
    ])
    kas = [a for a in accounts if a.get("Type") == 3 and not a.get("IsArchived")]
    if not kas:
        print("\n⚠️ Geen kas-rekening (Type 3) — die moet eerst in RLZ bestaan.")
    else:
        state["kas_id"] = kas[0]["id"]
        print(f"\nGekozen kas: {kas[0].get('Description')} ({kas[0]['id']})")

    omzet = c.get("Ledgers", search="omzet")["value"]
    _dump("Ledgers ?search=omzet", [
        {k: le.get(k) for k in ("id", "AccountCode", "Description", "Type")} for le in omzet[:15]
    ])
    if omzet:
        state["omzet_account_id"] = omzet[0]["id"]
        state["omzet_account_naam"] = f"{omzet[0].get('AccountCode')} {omzet[0].get('Description')}"

    taxrates = c.get("TaxRates")["value"]
    interessant = [t for t in taxrates
                   if t.get("IsExcempt") or "vrijgesteld" in (t.get("Description") or "").lower()
                   or t.get("id") == TEST_TAXRATE_21_ID]
    _dump("TaxRates (vrijgesteld + 21%)", [
        {k: t.get(k) for k in ("id", "Description", "Percentage", "IsExcempt", "IsRelayed",
                               "TaxKind")} for t in interessant
    ])
    vrijgesteld = [t for t in interessant if t.get("IsExcempt")]
    if vrijgesteld:
        state["taxrate_vrijgesteld_id"] = vrijgesteld[0]["id"]
        state["taxrate_vrijgesteld_naam"] = vrijgesteld[0].get("Description")

    decls = c.get("TaxDeclarations")["value"]
    _dump("TaxDeclarations (alle, kop)", [
        {k: d.get(k) for k in ("id", "Status", "Description", "Reference", "StartDate",
                               "EndDate", "Date", "ReceiptNumber")} for d in decls
    ])
    vandaag = datetime.now(UTC).date().isoformat()
    huidige = [d for d in decls
               if (d.get("StartDate") or "")[:10] <= vandaag <= (d.get("EndDate") or "9999")[:10]]
    if huidige:
        state["decl_id"] = huidige[0]["id"]
        print(f"\nAangifte die vandaag dekt: {huidige[0].get('Description')} ({huidige[0]['id']})")
    _save_state(state)
    print(f"\nState opgeslagen: {STATE_FILE}")


def stap_aangifte(c: PocClient, label: str = "nu") -> None:
    """Read-only: TaxSources van de huidige-periode-aangifte dumpen + in state bewaren
    (snapshot 'voor'/'na' voor de beslissende rubriek-diff)."""
    state = _state()
    decl = state.get("decl_id")
    if not decl:
        raise SystemExit("Geen decl_id in state — eerst `verken` draaien.")
    kop = c.get(f"TaxDeclarations/{decl}")
    _dump("TaxDeclaration kop", {k: kop.get(k) for k in (
        "id", "Status", "Description", "StartDate", "EndDate", "TotalTaxAmount", "PayableAmount")})
    bronnen = c.get(f"TaxDeclarations/{decl}/TaxSources")
    _dump(f"TaxSources ({label})", bronnen)
    state.setdefault("aangifte_snapshots", {})[label] = {"kop": kop, "bronnen": bronnen}
    _save_state(state)


def stap_tx(c: PocClient, bedrag: str = "121.00", suffix: str = "KAS1") -> None:
    """Kas-PaymentTransaction (positief = inkomsten) via PUT + client-GUID."""
    state = _state()
    tx_id = str(uuid.uuid4())
    body = {
        "id": tx_id,
        "PaymentAccount": {"id": state["kas_id"]},
        "BookDate": datetime.now(UTC).date().isoformat(),
        "Amount": float(bedrag),
        "Name": "TEST PoC kasomzet",
        "Reference": f"TEST-KASPOC-{suffix}",
    }
    nieuw = c.put(f"PaymentTransactions/{tx_id}", body)
    _dump(f"Kas-PaymentTransaction {suffix} na PUT", nieuw)
    state.setdefault("tx", {})[suffix] = tx_id
    _save_state(state)


def stap_direct(c: PocClient, suffix: str = "KAS1") -> None:
    """Directboeking op omzet-GB mét TaxRate per regel, GEEN Entity: €100 netto + €21 btw."""
    state = _state()
    tx = state["tx"][suffix]
    db_id = str(uuid.uuid4())
    body = {
        "id": db_id,
        "PaymentTransaction": {"id": tx},
        "Description": f"TEST-KASPOC omzet direct {suffix}",
        "DocumentLineList": [{
            "Account": {"id": state["omzet_account_id"]},
            "TaxRate": {"id": TEST_TAXRATE_21_ID},
            "NetAmount": 100.00,
            "TaxAmount": 21.00,
            "Description": "TEST-KASPOC omzet 21%",
        }],
    }
    nieuw = c.put(f"BankMutationDirectBookings/{db_id}", body)
    _dump("Directboeking na PUT (verwacht Status 3, btw-regel geaccepteerd)", nieuw)
    state.setdefault("directbookings", {})[suffix] = db_id
    _save_state(state)


def stap_gemengd(c: PocClient, suffix: str = "MIX1") -> None:
    """Gemengd rapport: vrijgestelde categorie (€50, btw 0) + 21%-categorie (€100 + €21)
    in één directboeking tegen één kas-transactie van €171."""
    state = _state()
    if "taxrate_vrijgesteld_id" not in state:
        raise SystemExit("Geen vrijgesteld-tarief in state — eerst `verken` draaien.")
    if suffix not in (state.get("tx") or {}):
        stap_tx(c, "171.00", suffix)
        state = _state()
    tx = state["tx"][suffix]
    db_id = str(uuid.uuid4())
    body = {
        "id": db_id,
        "PaymentTransaction": {"id": tx},
        "Description": f"TEST-KASPOC gemengd rapport {suffix}",
        "DocumentLineList": [
            {
                "Account": {"id": state["omzet_account_id"]},
                "TaxRate": {"id": state["taxrate_vrijgesteld_id"]},
                "NetAmount": 50.00,
                "TaxAmount": 0.00,
                "Description": "TEST-KASPOC vrijgestelde categorie",
            },
            {
                "Account": {"id": state["omzet_account_id"]},
                "TaxRate": {"id": TEST_TAXRATE_21_ID},
                "NetAmount": 100.00,
                "TaxAmount": 21.00,
                "Description": "TEST-KASPOC btw-categorie 21%",
            },
        ],
    }
    nieuw = c.put(f"BankMutationDirectBookings/{db_id}", body)
    _dump("Gemengde directboeking na PUT (verwacht Status 3)", nieuw)
    state.setdefault("directbookings", {})[suffix] = db_id
    _save_state(state)


def stap_inspect(c: PocClient) -> None:
    """Actuele staat van alle betrokken objecten (read-only)."""
    state = _state()
    for suffix, db in (state.get("directbookings") or {}).items():
        d = c.get(f"BankMutationDirectBookings/{db}", **{"$expand": "DocumentLineList"})
        _dump(f"Directboeking {suffix}", {k: d.get(k) for k in (
            "id", "Status", "Description", "ReceiptNumber", "DocumentLineList")})
    for suffix, tx in (state.get("tx") or {}).items():
        t = c.get(f"PaymentTransactions/{tx}")
        _dump(f"Kas-transactie {suffix}", {k: t.get(k) for k in (
            "id", "Amount", "OpenAmount", "IsComplete", "Reference")})


def stap_storno(c: PocClient) -> None:
    """Opruimen conform besluit 0005: actie 19 op elke directboeking (nooit delete)."""
    state = _state()
    for suffix, db in (state.get("directbookings") or {}).items():
        try:
            d = c.get(f"BankMutationDirectBookings/{db}")
            if d and d.get("Status") != 1:
                nieuw = c.actie(f"BankMutationDirectBookings/{db}", ACTION_CORRECT)
                _dump(f"Directboeking {suffix} na actie 19 (verwacht Status 1)", {
                    k: (nieuw or {}).get(k) for k in ("id", "Status", "Description")
                })
            else:
                print(f"{suffix}: staat al op concept.")
        except RlzApiError as e:
            print(f"⚠️ Storno {suffix} faalde: {e.status_code}: {e.body[:300]}")
    stap_inspect(c)


STAPPEN = {
    "verken": stap_verken,
    "aangifte": stap_aangifte,
    "tx": stap_tx,
    "direct": stap_direct,
    "gemengd": stap_gemengd,
    "inspect": stap_inspect,
    "storno": stap_storno,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in STAPPEN:
        raise SystemExit(f"Gebruik: poc_kasomzet_direct.py <{'|'.join(STAPPEN)}> [args]")
    client = PocClient()
    STAPPEN[sys.argv[1]](client, *sys.argv[2:])


if __name__ == "__main__":
    main()
