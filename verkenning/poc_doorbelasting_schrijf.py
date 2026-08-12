#!/usr/bin/env python3
"""STAP 0 — doorbelasting-boekpad (BLOK 0b, 2026-08-13): de tweezijdige motor gesimuleerd
tegen de TEST-administratie, vóór de eerste regel motorcode. Facilities-productie wordt in
deze stap NIET beschreven (alleen read-only verkend, zie 16_DOORBELASTING_KEMPEN.md).

Wat hier nieuw geverifieerd wordt (de rest is al bewezen door eerdere PoC's):
1. `debiteur`  — idempotente debiteur-aanmaak voor de doelentiteit-als-klant in de bron
   (patroon zorg_voor_debiteur, met PoC-namespace).
2. `crediteur` — idempotente CREDITEUR-aanmaak (put_vendor + herhaal-PUT + lookup):
   is een vers aangemaakte vendor direct bruikbaar als Entity van een PurchaseInvoice
   in dezelfde run? (De motor moet dit bij de eerste spiegel per doelentiteit doen.)
3. `verkoop`   — de bron-kant: SalesInvoice MÉT Entity + exact het Kempen-patroon
   (kostenregel met bron-referentie in de omschrijving + losse provisieregel, beide
   GB 8000 / 21% hoog) → boeken (17) → InvoiceNumber/ReceiptNumber teruglezen.
4. `inkoop`    — de spiegel-kant: PurchaseInvoice met Reference = het verkoopnummer van
   stap 3 (zoals Rubicon de Facilities-nummers draagt, §2c), kostenregel + provisieregel
   op een kostenrekening → boeken (17) → duplicaatquery vindt 'm terug.
5. `storno`    — actie 19 op beide kanten (besluit 0005: nooit verwijderen), in de
   volgorde die de motor ook gebruikt: spiegel eerst, dan de bron.

Waarborgen identiek aan de andere PoC's: ADMIN-PIN (credentials mogen uitsluitend de
test-administratie zien), KILL SWITCH (verkenning/POC_STOP), TEST-referenties, append-only
audit (output/doorbpoc_audit.jsonl), NOOIT DELETE.

Gebruik:
    backend/.venv/bin/python verkenning/poc_doorbelasting_schrijf.py <stap>
Stappen: debiteur | crediteur | verkoop | inkoop | storno | alles
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
from app.rlz.credentials import resolve_credentials  # noqa: E402

load_dotenv(HIER / ".env")

TESTADMIN_ID = "8dbfb856-d75b-4ec3-9124-c8b739fe3bc5"
OMZET1_ACCOUNT_ID = "330e4771-a63a-43cc-b050-5e7b0476209c"  # 8000 Omzet 1
TAXRATE_21_ID = "1e44993a-15f6-419f-87e5-3e31ac3d9383"  # 21% NL hoog (vaste systeem-GUID)

DEBITEUR_NAAM = "TEST-DOORB Doelentiteit B.V."
CREDITEUR_NAAM = "TEST-DOORB Kempen Facilities B.V."
BRON_REFERENTIE = "TEST-DOORB-BRON-0001"  # de fictieve originele inkoopfactuur in de bron

# Eigen PoC-namespace — de app-namespace blijft gereserveerd voor echte boekingen.
_POC_NS = uuid.UUID("b1a6c9de-4f02-47d3-9b7a-2e8f0c5d1a44")
DEBITEUR_ID = uuid.uuid5(_POC_NS, f"customer:{TESTADMIN_ID}:{DEBITEUR_NAAM.lower()}")
CREDITEUR_ID = uuid.uuid5(_POC_NS, f"vendor:{TESTADMIN_ID}:{CREDITEUR_NAAM.lower()}")
VERKOOP_ID = uuid.uuid5(_POC_NS, f"doorbelasting-verkoop:{BRON_REFERENTIE}:doel1")
INKOOP_ID = uuid.uuid5(_POC_NS, f"doorbelasting-inkoop:{BRON_REFERENTIE}:doel1")

KILL_SWITCH = HIER / "POC_STOP"
OUTPUT = HIER / "output"
AUDIT_LOG = OUTPUT / "doorbpoc_audit.jsonl"
STATE_FILE = OUTPUT / "doorbpoc_state.json"

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
    """Dunne schil om RlzClient: admin-pin, kill switch vóór elke write, audit per actie.
    Credentials store-first (platform.rlz_credential) met .env-fallback — zelfde route als
    de app zelf (app/rlz/credentials.py)."""

    def __init__(self) -> None:
        user, pw = resolve_credentials(TESTADMIN_ID)
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


def stap_debiteur(c: PocClient) -> None:
    print(f"== debiteur: {DEBITEUR_NAAM} ({DEBITEUR_ID})")
    naam_esc = DEBITEUR_NAAM.replace("'", "''")
    bestaand = c.get("Customers", **{"$filter": f"Name eq '{naam_esc}'"}).get("value", [])
    if bestaand:
        print(f"   bestaat al ({bestaand[0]['id']}) — lookup-vóór-PUT werkt, geen PUT nodig")
    else:
        c.put(f"Customers/{DEBITEUR_ID}", {"id": str(DEBITEUR_ID), "Name": DEBITEUR_NAAM})
        print("   aangemaakt via PUT met deterministisch client-GUID")
    # herhaal-PUT moet idempotent zijn
    c.put(f"Customers/{DEBITEUR_ID}", {"id": str(DEBITEUR_ID), "Name": DEBITEUR_NAAM})
    print("   herhaal-PUT: OK (idempotent)")
    _save_state({**_state(), "debiteur_id": str(DEBITEUR_ID)})


def stap_crediteur(c: PocClient) -> None:
    print(f"== crediteur: {CREDITEUR_NAAM} ({CREDITEUR_ID})")
    naam_esc = CREDITEUR_NAAM.replace("'", "''")
    bestaand = c.get("Vendors", **{"$filter": f"Name eq '{naam_esc}'"}).get("value", [])
    print(f"   lookup vóór PUT (Vendors $filter Name eq): {len(bestaand)} treffer(s)")
    if not bestaand:
        c.put(f"Vendors/{CREDITEUR_ID}", {"id": str(CREDITEUR_ID), "Name": CREDITEUR_NAAM})
        print("   aangemaakt via PUT met deterministisch client-GUID")
    c.put(f"Vendors/{CREDITEUR_ID}", {"id": str(CREDITEUR_ID), "Name": CREDITEUR_NAAM})
    print("   herhaal-PUT: OK (idempotent)")
    # direct-na-aanmaak zichtbaar in de collectie? (motor-voorwaarde)
    terug = c.get("Vendors", **{"$filter": f"Name eq '{naam_esc}'"}).get("value", [])
    print(f"   direct terugleesbaar via $filter: {len(terug)} treffer(s) — {'OK' if terug else 'NIET (⚠️ vertraging)'}")
    _save_state({**_state(), "crediteur_id": str(CREDITEUR_ID)})


def stap_verkoop(c: PocClient) -> None:
    print(f"== verkoop (bron-kant): SalesInvoice {VERKOOP_ID}")
    lines = [
        {
            "Account": {"id": OMZET1_ACCOUNT_ID},
            "TaxRate": {"id": TAXRATE_21_ID},
            "NetAmount": 100.00,
            "TaxAmount": 21.00,
            # Kempen-patroon: bron-referentie in de omschrijving van regel 1 (RLZ leidt de
            # document-Description hieruit af — bewezen verkoop-STAP-0 2026-08-09)
            "Description": f"TEST-DOORB {BRON_REFERENTIE} Doelentiteit",
        },
        {
            "Account": {"id": OMZET1_ACCOUNT_ID},
            "TaxRate": {"id": TAXRATE_21_ID},
            "NetAmount": 5.00,
            "TaxAmount": 1.05,
            "Description": "Provisie 5% over nettobedrag",
        },
    ]
    body = {
        "id": str(VERKOOP_ID),
        "Entity": {"id": str(DEBITEUR_ID)},
        "DocumentLineList": lines,
        "Date": "2026-08-13T00:00:00",
    }
    c.put(f"SalesInvoices/{VERKOOP_ID}", body)
    doc = c.actie(f"SalesInvoices/{VERKOOP_ID}", ACTION_BOOK)
    print(f"   geboekt: Status={doc.get('Status')} InvoiceNumber={doc.get('InvoiceNumber')} "
          f"Reference={doc.get('Reference')} ReceiptNumber={doc.get('ReceiptNumber')} "
          f"Totaal={doc.get('BaseInvoiceAmount')}")
    verwacht = 126.05
    if doc.get("BaseInvoiceAmount") != verwacht:
        print(f"   ⚠️ totaal wijkt af van verwacht {verwacht}")
    _save_state({**_state(), "verkoop_id": str(VERKOOP_ID),
                 "verkoop_reference": doc.get("Reference"),
                 "verkoop_invoice_number": doc.get("InvoiceNumber"),
                 "verkoop_status": doc.get("Status")})


def stap_inkoop(c: PocClient) -> None:
    state = _state()
    spiegel_ref = state.get("verkoop_reference") or f"RLZ-{state.get('verkoop_invoice_number')}"
    print(f"== inkoop (spiegel-kant): PurchaseInvoice {INKOOP_ID}, Reference={spiegel_ref}")
    # kostenrekening in de test-administratie opzoeken (zoals de motor per doel-administratie doet)
    kandidaten = c.get("Ledgers", search="Administratiekosten").get("value", [])
    if not kandidaten:
        kandidaten = c.get("Ledgers", search="4604").get("value", [])
    kosten = next((k for k in kandidaten if k.get("AccountType") == 2), None)
    if kosten is None:
        raise SystemExit("Geen kostenrekening (AccountType 2) gevonden in de test-administratie")
    print(f"   kostenrekening: {kosten.get('AccountNumber')} {kosten.get('Description')}")
    lines = [
        {
            "Account": {"id": kosten["id"]},
            "TaxRate": {"id": TAXRATE_21_ID},
            "NetAmount": 100.00,
            "TaxAmount": 21.00,
            "Description": f"TEST-DOORB {BRON_REFERENTIE} Doelentiteit",
        },
        {
            "Account": {"id": kosten["id"]},
            "TaxRate": {"id": TAXRATE_21_ID},
            "NetAmount": 5.00,
            "TaxAmount": 1.05,
            "Description": "Provisie 5% over nettobedrag",
        },
    ]
    body = {
        "id": str(INKOOP_ID),
        "Entity": {"id": str(CREDITEUR_ID)},
        "DocumentLineList": lines,
        "Reference": spiegel_ref,
        "Date": "2026-08-13T00:00:00",
    }
    c.put(f"PurchaseInvoices/{INKOOP_ID}", body)
    doc = c.actie(f"PurchaseInvoices/{INKOOP_ID}", ACTION_BOOK)
    print(f"   geboekt: Status={doc.get('Status')} Reference={doc.get('Reference')} "
          f"ReceiptNumber={doc.get('ReceiptNumber')} Totaal={doc.get('BaseInvoiceAmount')}")
    # duplicaatquery zoals de motor die vóór elke PUT doet
    esc = (spiegel_ref or "")[:30].replace("'", "''")
    dupl = c.get("PurchaseInvoices",
                 **{"$filter": f"Entity/id eq {CREDITEUR_ID} and Reference eq '{esc}'"}).get("value", [])
    print(f"   duplicaatquery (Entity+Reference): {len(dupl)} treffer(s) — {'OK' if len(dupl) == 1 else '⚠️'}")
    _save_state({**_state(), "inkoop_id": str(INKOOP_ID), "inkoop_status": doc.get("Status"),
                 "inkoop_reference": doc.get("Reference"), "kosten_gb": kosten.get("AccountNumber")})


def stap_storno(c: PocClient) -> None:
    state = _state()
    # motor-volgorde: spiegel eerst terugdraaien, dan de bron
    for label, pad_soort, sleutel in (
        ("spiegel-inkoop", "PurchaseInvoices", "inkoop_id"),
        ("bron-verkoop", "SalesInvoices", "verkoop_id"),
    ):
        doc_id = state.get(sleutel)
        if not doc_id:
            print(f"== storno {label}: overgeslagen (niet in state)")
            continue
        pad = f"{pad_soort}/{doc_id}"
        huidig = c.get(pad)
        if huidig is None or huidig.get("Status") == 1:
            print(f"== storno {label}: al concept/onbekend — overgeslagen")
            continue
        doc = c.actie(pad, ACTION_CORRECT)
        print(f"== storno {label}: Status {huidig.get('Status')} → {doc.get('Status')} "
              f"({'OK terug naar concept' if doc.get('Status') == 1 else '⚠️ onverwacht'})")
    _save_state({**state, "gestorneerd_op": _nu()})


STAPPEN = {
    "debiteur": stap_debiteur,
    "crediteur": stap_crediteur,
    "verkoop": stap_verkoop,
    "inkoop": stap_inkoop,
    "storno": stap_storno,
}


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {*STAPPEN, "alles"}:
        raise SystemExit(f"Gebruik: {sys.argv[0]} <{' | '.join([*STAPPEN, 'alles'])}>")
    c = PocClient()
    if sys.argv[1] == "alles":
        for naam in ("debiteur", "crediteur", "verkoop", "inkoop", "storno"):
            STAPPEN[naam](c)
    else:
        STAPPEN[sys.argv[1]](c)


if __name__ == "__main__":
    main()
