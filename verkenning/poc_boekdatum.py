#!/usr/bin/env python3
"""STAP 0 — boekingsdatum = factuurdatum (opruimrun 28-08, punt 15; besluit Peter 27-08).

Vraag 1: welk RLZ-veld stuurt de BOEKINGSDATUM (de datum van de journaalpost/grootboekmutatie)
         — `Date` (door ons gezet) of `BookDate` (systeemdatum bij actie 17)?
Vraag 2: gedrag bij een `Date` in een INGEDIENDE btw-periode (verwachting: RLZ verschuift de
         TaxSource zelf naar de eerstvolgende open periode — consistent met actie-19-gedrag,
         api-verkenning "Actie 19 in een periode met ingediende btw-aangifte").

Stappen (TEST-administratie, TEST-referenties, actie 19 = terugweg, NOOIT DELETE):
    boek      (schrijf)   PurchaseInvoice TEST-BD-01 mét Date 2026-06-15, boeken (17), Date/BookDate lezen
    journaal  (read-only) JournalEntries/JournalEntryLines rond het document: welke datum draagt de post?
    aangifte  (schrijf)   PurchaseInvoice TEST-BD-02 mét Date 2023-02-15 (Q1-2023 ingediend), boeken,
                          Date/BookDate + journaalpost-datum + TaxSource-periode
    opruimen  (schrijf)   actie 19 op beide (concept, nooit verwijderen)
    alles     = boek → journaal → aangifte → opruimen
Gebruik: backend/.venv/bin/python verkenning/poc_boekdatum.py <stap>
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
TAXRATE_21_ID = "1e44993a-15f6-419f-87e5-3e31ac3d9383"
CREDITEUR_NAAM = "TEST-DOORB Kempen Facilities B.V."
_POC_NS = uuid.UUID("b1a6c9de-4f02-47d3-9b7a-2e8f0c5d1a44")
DOCS = {
    "TEST-BD-01": (uuid.uuid5(_POC_NS, "boekdatum:TEST-BD-01"), "2026-06-15", 100.00, 21.00),
    "TEST-BD-02": (uuid.uuid5(_POC_NS, "boekdatum:TEST-BD-02"), "2023-02-15", 10.00, 2.10),
}
KILL_SWITCH = HIER / "POC_STOP"
OUTPUT = HIER / "output"
AUDIT_LOG = OUTPUT / "boekdatumpoc_audit.jsonl"


def _audit(entry: dict[str, Any]) -> None:
    OUTPUT.mkdir(exist_ok=True)
    with AUDIT_LOG.open("a") as f:
        f.write(json.dumps({"ts": datetime.now(UTC).isoformat(), "admin": TESTADMIN_ID, **entry}, default=str) + "\n")


class PocClient:
    def __init__(self) -> None:
        user, pw = resolve_credentials(TESTADMIN_ID)
        login = RlzClient(username=user, password=pw)
        ids = [a["id"] for a in login.list_administrations()]
        if ids != [TESTADMIN_ID]:
            raise SystemExit(f"FAILSAFE: login ziet {ids}, verwacht alleen {TESTADMIN_ID}")
        self.rlz = login.for_administration(TESTADMIN_ID)

    def get(self, path: str, **params: Any) -> Any:
        return self.rlz.get(path, params=params or None)

    def put(self, path: str, body: dict[str, Any]) -> None:
        if KILL_SWITCH.exists():
            raise SystemExit("KILL SWITCH actief")
        try:
            r = self.rlz.put(path, body)
            _audit({"actie": "PUT", "pad": path, "payload": body, "status": r.status_code})
        except RlzApiError as e:
            _audit({"actie": "PUT", "pad": path, "payload": body, "status": f"{e.status_code}: {e.body[:300]}"})
            raise

    def actie(self, pad: str, t: int) -> Any:
        if KILL_SWITCH.exists():
            raise SystemExit("KILL SWITCH actief")
        r = self.rlz.post_action(pad, t)
        nieuw = self.get(pad)
        _audit({"actie": f"POST Actions {t}", "pad": pad, "status": r.status_code, "nieuw": nieuw})
        return nieuw


def _vendor_id(c: PocClient) -> str:
    v = c.get("Vendors", **{"$filter": f"Name eq '{CREDITEUR_NAAM.replace(chr(39), chr(39) * 2)}'"}).get("value", [])
    if not v:
        raise SystemExit("TEST-crediteur ontbreekt")
    return v[0]["id"]


def _kosten(c: PocClient) -> str:
    k = next((x for x in c.get("Ledgers", search="4302").get("value", []) if x.get("AccountType") == 2), None)
    if k is None:
        raise SystemExit("Geen kostenrekening 4302")
    return k["id"]


def _doc(c: PocClient, doc_id: uuid.UUID, label: str) -> dict:
    d = c.get(f"PurchaseInvoices/{doc_id}")
    print(f"   [{label}] Status={d.get('Status')} Date={d.get('Date')} BookDate={d.get('BookDate')} "
          f"DueDate={d.get('DueDate')} Receipt={d.get('ReceiptNumber')} Totaal={d.get('BaseInvoiceAmount')}")
    return d


def _boek(c: PocClient, ref: str) -> dict:
    doc_id, datum, net, btw = DOCS[ref]
    body = {
        "id": str(doc_id),
        "Entity": {"id": _vendor_id(c)},
        "DocumentLineList": [{"Account": {"id": _kosten(c)}, "TaxRate": {"id": TAXRATE_21_ID},
                              "NetAmount": net, "TaxAmount": btw, "Description": f"{ref} boekdatum-test"}],
        "Reference": ref,
        "Date": f"{datum}T00:00:00",
    }
    print(f"== boek {ref}: Date={datum}")
    c.put(f"PurchaseInvoices/{doc_id}", body)
    c.actie(f"PurchaseInvoices/{doc_id}", 17)
    return _doc(c, doc_id, f"{ref} na boek")


def _journaal(c: PocClient, ref: str) -> None:
    doc_id, datum, *_ = DOCS[ref]
    print(f"== journaal {ref}: welke datum draagt de journaalpost?")
    treffers: list[dict] = []
    # Poging 1: JournalEntries op Reference / Description.
    for veld in ("Reference", "Description"):
        try:
            rijen = c.get("JournalEntries", **{"$filter": f"{veld} eq '{ref}'"}).get("value", [])
            print(f"   JournalEntries ${veld} eq '{ref}': {len(rijen)} rij(en)")
            treffers += rijen
        except RlzApiError as e:
            print(f"   JournalEntries filter {veld}: {e.status_code} {e.body[:120]}")
    # Poging 2: JournalEntries in het datumvenster van Date én van vandaag (BookDate).
    vandaag = datetime.now(UTC).date().isoformat()
    for label, dag in (("Date-venster", datum), ("vandaag-venster", vandaag)):
        for veld in ("Date", "BookDate", "EntryDate"):
            try:
                rijen = c.get("JournalEntries", **{"$filter": f"{veld} ge {dag} and {veld} le {dag}", "$top": "50"}).get("value", [])
                eigen = [r for r in rijen if ref in json.dumps(r)]
                print(f"   JournalEntries {veld} = {dag} ({label}): {len(rijen)} rijen, waarvan {len(eigen)} met '{ref}'")
                treffers += eigen
            except RlzApiError as e:
                print(f"   JournalEntries {veld} = {dag}: {e.status_code} {e.body[:100]}")
    # Poging 3: JournalEntryLines met expand.
    try:
        rijen = c.get("JournalEntryLines", **{"$filter": f"Description eq '{ref} boekdatum-test'", "$expand": "JournalEntry"}).get("value", [])
        print(f"   JournalEntryLines Description-match: {len(rijen)}")
        for r in rijen[:3]:
            print("   LINE:", json.dumps(r, default=str)[:700])
    except RlzApiError as e:
        print(f"   JournalEntryLines: {e.status_code} {e.body[:120]}")
    gezien = set()
    for r in treffers:
        if r.get("id") in gezien:
            continue
        gezien.add(r.get("id"))
        print("   ENTRY:", json.dumps({k: v for k, v in r.items() if "Date" in k or k in ("id", "Reference", "Description", "Number", "Period", "Year")}, default=str))
    _audit({"actie": "journaal", "ref": ref, "treffers": treffers})


def _taxsource(c: PocClient, ref: str) -> None:
    print(f"== aangifte-periode van {ref}")
    try:
        decls = c.get("TaxDeclarations", **{"$top": "60"}).get("value", [])
    except RlzApiError as e:
        print(f"   TaxDeclarations: {e.status_code}")
        return
    for d in decls:
        try:
            src = c.get(f"TaxDeclarations/{d['id']}/TaxSources").get("value", [])
        except RlzApiError:
            continue
        eigen = [s for s in src if ref in json.dumps(s)]
        if eigen:
            print(f"   → TaxSource in aangifte {d.get('StartDate')}..{d.get('EndDate')} Status={d.get('Status')}: {json.dumps(eigen[0], default=str)[:300]}")


def stap_boek(c: PocClient) -> None:
    _boek(c, "TEST-BD-01")


def stap_journaal(c: PocClient) -> None:
    _journaal(c, "TEST-BD-01")


def stap_aangifte(c: PocClient) -> None:
    _boek(c, "TEST-BD-02")
    _journaal(c, "TEST-BD-02")
    _taxsource(c, "TEST-BD-02")


def stap_opruimen(c: PocClient) -> None:
    for ref, (doc_id, *_) in DOCS.items():
        try:
            d = c.get(f"PurchaseInvoices/{doc_id}")
        except RlzApiError:
            print(f"   {ref}: bestaat niet")
            continue
        if d.get("Status") != 1:
            c.actie(f"PurchaseInvoices/{doc_id}", 19)
        _doc(c, doc_id, f"{ref} na opruimen")


STAPPEN = {"boek": stap_boek, "journaal": stap_journaal, "aangifte": stap_aangifte, "opruimen": stap_opruimen}

if __name__ == "__main__":
    stap = sys.argv[1] if len(sys.argv) > 1 else "alles"
    c = PocClient()
    if stap == "alles":
        for s in ("boek", "journaal", "aangifte", "opruimen"):
            STAPPEN[s](c)
    else:
        STAPPEN[stap](c)
