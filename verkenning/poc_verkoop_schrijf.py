#!/usr/bin/env python3
"""STAP 0 — verkoopfactuur-boekpad (blok 1e, 2026-08-09): wat de motor NIEUW doet, live
geverifieerd tegen de test-administratie vóór het eerste echte gebruik:

1. `debiteur`  — idempotente debiteur-aanmaak: ziet de Customers-collectie API-aangemaakte
   debiteuren (`$filter=Name eq …`)? PUT met deterministisch client-GUID + herhaal-PUT.
2. `maak`      — SalesInvoice MÉT Entity (huurder) + regels, deterministische Description
   ("VASTLY-VERKOOP TEST-…").
3. `boek`      — actie 17; daarna: ziet de Receipts-collectie deze entity-factuur óók
   (Description-filter = onze duplicaatcheck-op-afstand voor de verkoopkant)?
4. `credit`    — de creditvariant: SalesInvoice met NEGATIEVE regelbedragen op dezelfde
   debiteur (verkoopcreditnota = negatieve SalesInvoice, api-verkenning "Inkoopcreditnota" +
   PaymentRecommendationCreditSalesinvoicesFilters) → PUT + boeken, bedragen vóór/ná.
5. `storno`    — actie 19 op alles wat geboekt is (besluit 0005: nooit verwijderen).

Waarborgen identiek aan de andere PoC's: ADMIN-PIN (login mag uitsluitend de
test-administratie zien), KILL SWITCH (verkenning/POC_STOP), TEST-referenties, append-only
audit (output/verkooppoc_audit.jsonl), NOOIT DELETE.

Gebruik:
    backend/.venv/bin/python verkenning/poc_verkoop_schrijf.py <stap>
Stappen: debiteur | maak | boek | credit | storno | alles
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

TESTADMIN_ID = "8dbfb856-d75b-4ec3-9124-c8b739fe3bc5"
OMZET1_ACCOUNT_ID = "330e4771-a63a-43cc-b050-5e7b0476209c"  # 8000 Omzet 1
TAXRATE_21_ID = "1e44993a-15f6-419f-87e5-3e31ac3d9383"  # 21% NL

DEBITEUR_NAAM = "TEST-VERKOOPPOC Huurder"
# Deterministisch client-GUID, zelfde principe als rlz_customer_id maar met eigen PoC-namespace
# (de app-namespace blijft gereserveerd voor echte boekingen).
_POC_NS = uuid.UUID("7f1207e6-9f6b-4c58-a6a1-53df0f56b2e1")
DEBITEUR_ID = uuid.uuid5(_POC_NS, f"customer:{TESTADMIN_ID}:{DEBITEUR_NAAM.lower()}")

KILL_SWITCH = HIER / "POC_STOP"
OUTPUT = HIER / "output"
AUDIT_LOG = OUTPUT / "verkooppoc_audit.jsonl"
STATE_FILE = OUTPUT / "verkooppoc_state.json"

ACTION_BOOK = 17
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

    def put(self, path: str, body: dict[str, Any]) -> Any:
        self._check_kill_switch()
        oud = self._snapshot(path)
        try:
            r = self.rlz.put(path, body)
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

    def actie(self, doc_pad: str, actie_type: int) -> Any:
        self._check_kill_switch()
        oud = self._snapshot(doc_pad)
        try:
            r = self.rlz.post_action(doc_pad, actie_type)
            status: Any = r.status_code
        except RlzApiError as e:
            status = f"{e.status_code}: {e.body[:300]}"
            _audit({"actie": f"POST Actions {actie_type}", "login": self._login_naam,
                    "pad": doc_pad, "status": status, "oud": oud})
            raise
        nieuw = self._snapshot(doc_pad)
        _audit({"actie": f"POST Actions {actie_type}", "login": self._login_naam, "pad": doc_pad,
                "status": status, "oud": oud, "nieuw": nieuw})
        return nieuw

    def _snapshot(self, path: str) -> Any:
        try:
            return self.rlz.get(path)
        except RlzApiError:
            return None


def _dump(label: str, data: Any) -> None:
    print(f"\n=== {label} ===")
    print(json.dumps(data, indent=2, default=str, ensure_ascii=False))


def _kern(doc: dict | None) -> dict:
    return {
        k: (doc or {}).get(k)
        for k in ("id", "Status", "Reference", "InvoiceNumber", "ReceiptNumber",
                  "BaseInvoiceAmount", "BaseRemainingAmount", "Entity", "Description")
    }


def _regels(*, netto: float, credit: bool = False) -> list[dict[str, Any]]:
    teken = -1 if credit else 1
    return [
        {
            "Account": {"id": OMZET1_ACCOUNT_ID},
            "TaxRate": {"id": TAXRATE_21_ID},
            "NetAmount": teken * netto,
            "TaxAmount": round(teken * netto * 0.21, 2),
            "Description": "TEST-VERKOOPPOC huurregel" + (" CREDIT" if credit else ""),
        }
    ]


# --------------------------------------------------------------------------- stappen


def stap_debiteur(c: PocClient) -> None:
    """Idempotente debiteur-aanmaak: (a) lookup vóór PUT, (b) PUT met client-GUID,
    (c) lookup ná PUT — ziet de Customers-collectie de API-debiteur? (d) herhaal-PUT = no-op."""
    vooraf = c.get("Customers", **{"$filter": f"Name eq '{DEBITEUR_NAAM}'"}).get("value", [])
    _dump("Lookup vóór PUT (bestaande naamgenoten)", vooraf)

    c.put(f"Customers/{DEBITEUR_ID}", {"id": str(DEBITEUR_ID), "Name": DEBITEUR_NAAM})
    achteraf = c.get("Customers", **{"$filter": f"Name eq '{DEBITEUR_NAAM}'"}).get("value", [])
    _dump("Lookup ná PUT — ziet de collectie de API-debiteur?", achteraf)

    c.put(f"Customers/{DEBITEUR_ID}", {"id": str(DEBITEUR_ID), "Name": DEBITEUR_NAAM})
    print("\nHerhaal-PUT met zelfde GUID: geen fout = idempotent bevestigd.")

    state = _state()
    state["debiteur_id"] = str(DEBITEUR_ID)
    _save_state(state)


def stap_maak(c: PocClient) -> None:
    """SalesInvoice MÉT Entity (de huurder-debiteur) + deterministische Description."""
    state = _state()
    doc_id = state.get("factuur_id") or str(uuid.uuid4())
    nieuw = c.put(
        f"SalesInvoices/{doc_id}",
        {
            "id": doc_id,
            "Entity": {"id": str(DEBITEUR_ID)},
            "Description": "VASTLY-VERKOOP TEST-VF-POC-1",
            "Date": f"{datetime.now(UTC).date().isoformat()}T00:00:00",
            "DocumentLineList": _regels(netto=100.00),
        },
    )
    _dump("Concept mét Entity na PUT", _kern(nieuw))
    state["factuur_id"] = doc_id
    _save_state(state)


def stap_boek(c: PocClient) -> None:
    """Actie 17 + de beslissende leescheck: ziet de Receipts-collectie deze ENTITY-factuur via
    het Description-filter (duplicaatbewaking-op-afstand verkoopkant)?"""
    state = _state()
    doc_id = state.get("factuur_id")
    if not doc_id:
        raise SystemExit("Geen concept in state — eerst `maak`.")
    try:
        na = c.actie(f"SalesInvoices/{doc_id}", ACTION_BOOK)
    except RlzApiError as e:
        if "factuurnummer" in e.body.lower():
            hoogste = c.get("SalesInvoices", **{"$orderby": "InvoiceNumber desc", "$top": "1"})
            vrij = int((hoogste.get("value") or [{}])[0].get("InvoiceNumber") or 0) + 1
            print(f"Nummer-botsing — herstel met expliciet InvoiceNumber {vrij}.")
            c.put(f"SalesInvoices/{doc_id}", {"id": doc_id, "InvoiceNumber": vrij})
            na = c.actie(f"SalesInvoices/{doc_id}", ACTION_BOOK)
        else:
            raise
    _dump("Ná boeken (verwacht Status 2)", _kern(na))

    hits = c.get("Receipts", **{"$filter": "Description eq 'VASTLY-VERKOOP TEST-VF-POC-1'"}).get("value", [])
    _dump("Receipts-collectie op Description (entity-factuur zichtbaar?)", [
        {k: h.get(k) for k in ("id", "Description", "InvoiceNumber", "Status")} for h in hits
    ])
    state["factuur_geboekt"] = True
    _save_state(state)


def stap_credit(c: PocClient) -> None:
    """Creditvariant: negatieve regelbedragen op dezelfde debiteur → PUT + actie 17.
    Verwachting (creditnota = negatieve SalesInvoice): BaseInvoiceAmount negatief."""
    state = _state()
    doc_id = state.get("credit_id") or str(uuid.uuid4())
    nieuw = c.put(
        f"SalesInvoices/{doc_id}",
        {
            "id": doc_id,
            "Entity": {"id": str(DEBITEUR_ID)},
            "Description": "VASTLY-VERKOOP TEST-VF-POC-1-C1 CREDIT",
            "Date": f"{datetime.now(UTC).date().isoformat()}T00:00:00",
            "DocumentLineList": _regels(netto=100.00, credit=True),
        },
    )
    _dump("Credit-concept na PUT (verwacht negatief bedrag)", _kern(nieuw))
    state["credit_id"] = doc_id
    _save_state(state)
    try:
        na = c.actie(f"SalesInvoices/{doc_id}", ACTION_BOOK)
    except RlzApiError as e:
        if "factuurnummer" in e.body.lower():
            hoogste = c.get("SalesInvoices", **{"$orderby": "InvoiceNumber desc", "$top": "1"})
            vrij = int((hoogste.get("value") or [{}])[0].get("InvoiceNumber") or 0) + 1
            print(f"Nummer-botsing — herstel met expliciet InvoiceNumber {vrij}.")
            c.put(f"SalesInvoices/{doc_id}", {"id": doc_id, "InvoiceNumber": vrij})
            na = c.actie(f"SalesInvoices/{doc_id}", ACTION_BOOK)
        else:
            raise
    _dump("Credit ná boeken (verwacht Status 2/3, negatief bedrag)", _kern(na))
    state["credit_geboekt"] = True
    _save_state(state)


def stap_storno(c: PocClient) -> None:
    """Actie 19 op alles wat geboekt is; concepten blijven staan (besluit 0005)."""
    state = _state()
    for sleutel in ("factuur_id", "credit_id"):
        doc = state.get(sleutel)
        if not doc:
            continue
        try:
            d = c.get(f"SalesInvoices/{doc}")
        except RlzApiError as e:
            print(f"{sleutel}: {e.status_code}")
            continue
        if d.get("Status") == 1:
            print(f"{sleutel} ({doc}): concept — blijft staan (opdracht).")
            continue
        na = c.actie(f"SalesInvoices/{doc}", ACTION_CORRECT)
        _dump(f"{sleutel} na actie 19 (verwacht Status 1)", _kern(na))


def stap_alles(c: PocClient) -> None:
    stap_debiteur(c)
    stap_maak(c)
    stap_boek(c)
    stap_credit(c)
    stap_storno(c)


STAPPEN = {
    "debiteur": stap_debiteur,
    "maak": stap_maak,
    "boek": stap_boek,
    "credit": stap_credit,
    "storno": stap_storno,
    "alles": stap_alles,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in STAPPEN:
        raise SystemExit(f"Gebruik: poc_verkoop_schrijf.py <{'|'.join(STAPPEN)}>")
    client = PocClient()
    STAPPEN[sys.argv[1]](client)


if __name__ == "__main__":
    main()
