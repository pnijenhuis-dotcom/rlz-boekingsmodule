#!/usr/bin/env python3
"""STAP 0 — storno-blokkade ná ingediende btw-aangifte + kliktest-herstart (2026-08-16).

Drie verificaties tegen de TEST-administratie, vóór de bouw van de aangifte-poort en vóór
we Peter melden dat hij TEST-ONB-KLIKTEST-01 opnieuw kan doorbelasten:

1. `aangifte`  (read-only) — de leesroute van de poort: GET TaxDeclarations levert per rij
   Status (1 concept / 2 ingediend / 3 afgehandeld) + StartDate/Date als periode-grenzen,
   machineleesbaar genoeg voor een deterministische datum-in-periode-toets.
2. `bankdatum` (read-only) — draagt een BankMutationDirectBookings-document een bruikbaar
   `Date`-veld? (De bank-storno-poort toetst dáárop; fail-closed als het ontbreekt.)
3. `herput`    (schrijf) — HET kliktest-risico: de spiegels van TEST-ONB-KLIKTEST-01 staan
   ná Peters storno nog als concept (Status 1) in RLZ; een nieuwe doorbelasting-run doet
   een her-PUT op hetzelfde deterministische GUID mét DocumentLineList. Vervángt RLZ dan
   de regels, of stápelt hij ze (dubbele bedragen)? Cyclus: PUT → boek 17 → storno 19 →
   her-PUT (zelfde GUID, zelfde regels) → regels tellen → boek 17 → controle → storno 19.
   Einde = concept, conform testdata-afspraak (nooit verwijderen).

Waarborgen identiek aan de andere PoC's: ADMIN-PIN, KILL SWITCH (verkenning/POC_STOP),
TEST-referenties, append-only audit (output/herputpoc_audit.jsonl), NOOIT DELETE.

Gebruik:
    backend/.venv/bin/python verkenning/poc_herput_en_aangiftepoort.py <stap>
Stappen: aangifte | bankdatum | herput | alles
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
TAXRATE_21_ID = "1e44993a-15f6-419f-87e5-3e31ac3d9383"  # 21% NL hoog (vaste systeem-GUID)
CREDITEUR_NAAM = "TEST-DOORB Kempen Facilities B.V."  # bestaat al (doorbelasting-PoC)

HERPUT_REFERENTIE = "TEST-HERPUT-01"
_POC_NS = uuid.UUID("b1a6c9de-4f02-47d3-9b7a-2e8f0c5d1a44")  # zelfde PoC-namespace
HERPUT_ID = uuid.uuid5(_POC_NS, f"herput:{HERPUT_REFERENTIE}")

KILL_SWITCH = HIER / "POC_STOP"
OUTPUT = HIER / "output"
AUDIT_LOG = OUTPUT / "herputpoc_audit.jsonl"

ACTION_BOOK = 17
ACTION_CORRECT = 19


def _nu() -> str:
    return datetime.now(UTC).isoformat()


def _audit(entry: dict[str, Any]) -> None:
    OUTPUT.mkdir(exist_ok=True)
    entry = {"ts": _nu(), "admin": TESTADMIN_ID, **entry}
    with AUDIT_LOG.open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


class PocClient:
    """Zelfde schil als poc_doorbelasting_schrijf.py: admin-pin, kill switch vóór elke
    write, audit per actie."""

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
        try:
            r = self.rlz.put(path, body)
            status: Any = r.status_code
        except RlzApiError as e:
            status = f"{e.status_code}: {e.body[:300]}"
            _audit({"actie": "PUT", "login": self._login_naam, "pad": path, "payload": body, "status": status})
            raise
        _audit({"actie": "PUT", "login": self._login_naam, "pad": path, "payload": body, "status": status})

    def actie(self, doc_pad: str, actie_type: int) -> Any:
        self._check_kill_switch()
        try:
            r = self.rlz.post_action(doc_pad, actie_type)
            status: Any = r.status_code
        except RlzApiError as e:
            status = f"{e.status_code}: {e.body[:300]}"
            _audit({"actie": f"POST Actions {actie_type}", "login": self._login_naam, "pad": doc_pad, "status": status})
            raise
        nieuw = self.get(doc_pad)
        _audit({"actie": f"POST Actions {actie_type}", "login": self._login_naam, "pad": doc_pad,
                "status": status, "nieuw": nieuw})
        return nieuw


def stap_aangifte(c: PocClient) -> None:
    print("== aangifte (read-only): GET TaxDeclarations — velden voor de poort")
    rijen = c.get("TaxDeclarations").get("value", [])
    print(f"   {len(rijen)} aangifte-rijen")
    for rij in sorted(rijen, key=lambda r: str(r.get("StartDate")))[-8:]:
        print(
            f"   Status={rij.get('Status')} StartDate={rij.get('StartDate')} "
            f"Date={rij.get('Date')} id={rij.get('id')}"
        )
    onbruikbaar = [r for r in rijen if r.get("Status") in (2, 3) and not (r.get("StartDate") and r.get("Date"))]
    print(f"   ingediende rijen zonder leesbare periode: {len(onbruikbaar)} (verwacht 0)")


def stap_bankdatum(c: PocClient) -> None:
    print("== bankdatum (read-only): BankMutationDirectBookings — Date/Status-velden")
    rijen = c.get("BankMutationDirectBookings", **{"$top": "5"}).get("value", [])
    if not rijen:
        print("   collectie leeg — geen uitspraak mogelijk")
        return
    for rij in rijen:
        print(f"   id={rij.get('id')} Status={rij.get('Status')} Date={rij.get('Date')} "
              f"DocumentType={rij.get('DocumentType')}")


def _lines(c: PocClient) -> list[dict[str, Any]]:
    return c.get(f"PurchaseInvoices/{HERPUT_ID}/Lines").get("value", [])


def _print_staat(c: PocClient, label: str) -> tuple[int, Any]:
    doc = c.get(f"PurchaseInvoices/{HERPUT_ID}")
    regels = _lines(c)
    print(f"   [{label}] Status={doc.get('Status')} regels={len(regels)} "
          f"Totaal={doc.get('BaseInvoiceAmount')} ReceiptNumber={doc.get('ReceiptNumber')}")
    return len(regels), doc.get("BaseInvoiceAmount")


def stap_herput(c: PocClient) -> None:
    print(f"== herput (schrijf): PurchaseInvoice {HERPUT_ID} ({HERPUT_REFERENTIE})")
    naam_esc = CREDITEUR_NAAM.replace("'", "''")
    vendors = c.get("Vendors", **{"$filter": f"Name eq '{naam_esc}'"}).get("value", [])
    if not vendors:
        raise SystemExit("TEST-crediteur niet gevonden — draai eerst poc_doorbelasting_schrijf.py crediteur")
    vendor_id = vendors[0]["id"]
    kandidaten = c.get("Ledgers", search="4302").get("value", [])
    kosten = next((k for k in kandidaten if k.get("AccountType") == 2), None)
    if kosten is None:
        raise SystemExit("Geen kostenrekening (AccountType 2) gevonden")
    lines = [
        {
            "Account": {"id": kosten["id"]},
            "TaxRate": {"id": TAXRATE_21_ID},
            "NetAmount": 10.00,
            "TaxAmount": 2.10,
            "Description": f"{HERPUT_REFERENTIE} kostenregel",
        },
        {
            "Account": {"id": kosten["id"]},
            "TaxRate": {"id": TAXRATE_21_ID},
            "NetAmount": 0.50,
            "TaxAmount": 0.11,
            "Description": f"{HERPUT_REFERENTIE} provisieregel",
        },
    ]
    body = {
        "id": str(HERPUT_ID),
        "Entity": {"id": vendor_id},
        "DocumentLineList": lines,
        "Reference": HERPUT_REFERENTIE,
        "Date": f"{datetime.now(UTC).date().isoformat()}T00:00:00",
    }
    print("   1) eerste PUT + boek (17)")
    c.put(f"PurchaseInvoices/{HERPUT_ID}", body)
    c.actie(f"PurchaseInvoices/{HERPUT_ID}", ACTION_BOOK)
    n1, _ = _print_staat(c, "na 1e boek")
    print("   2) storno (19) — het kliktest-uitgangspunt: concept mét regels")
    c.actie(f"PurchaseInvoices/{HERPUT_ID}", ACTION_CORRECT)
    n2, _ = _print_staat(c, "na storno")
    print("   3) her-PUT op hetzelfde GUID met dezelfde DocumentLineList (motor-pad)")
    c.put(f"PurchaseInvoices/{HERPUT_ID}", body)
    n3, tot3 = _print_staat(c, "na her-PUT")
    print("   4) boek (17) opnieuw")
    c.actie(f"PurchaseInvoices/{HERPUT_ID}", ACTION_BOOK)
    n4, tot4 = _print_staat(c, "na 2e boek")
    print("   5) opruimen: storno (19), blijft als concept staan (testdata-afspraak)")
    c.actie(f"PurchaseInvoices/{HERPUT_ID}", ACTION_CORRECT)
    _print_staat(c, "eind")
    if n3 == n1 and n4 == n1:
        print(f"   CONCLUSIE: her-PUT VERVANGT de regels (blijft {n1}) — geen stapeling. ✅")
    else:
        print(f"   CONCLUSIE: ⚠️ REGELSTAPELING ({n1} → {n3}/{n4} regels, totaal {tot3}/{tot4}) — "
              "motor-fix nodig vóór de kliktest!")


STAPPEN = {"aangifte": stap_aangifte, "bankdatum": stap_bankdatum, "herput": stap_herput}


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in (*STAPPEN, "alles"):
        raise SystemExit(f"Gebruik: {sys.argv[0]} {' | '.join([*STAPPEN, 'alles'])}")
    c = PocClient()
    if sys.argv[1] == "alles":
        for fn in STAPPEN.values():
            fn(c)
            print()
    else:
        STAPPEN[sys.argv[1]](c)


if __name__ == "__main__":
    main()
