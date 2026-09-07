#!/usr/bin/env python3
"""STAP 0 — `Description` op PurchaseInvoices (blok 4a herstelrun 07-09; vervolg op blok 9 "kop-omschrijving
automatisch": de boekmotor geeft de kop-omschrijving mee als document-`Description`).

Vraag 1: bewaart RLZ de document-`Description` van een PurchaseInvoice en komt die terug via
         GET PurchaseInvoices/{id} — in concept (Status 1) én ná boeken (17)?
Vraag 2: blijft de regel-`Description` (DocumentLineList) apart bewaard (GET .../Lines)?
Vraag 3: (bijvangst 1b) ziet `find_purchase_invoices_by_reference` een CONCEPT (Status 1) al — of pas ná boeken?
Vraag 4: zónder document-Description: leidt RLZ 'm af uit de eerste regel (zoals op SalesInvoices)?

Stappen (TEST-administratie, TEST-referenties, actie 19 = terugweg, NOOIT DELETE):
    concept   (schrijf)   PUT TEST-DESC-01 mét Description + regel-Description; GET doc + Lines; collectie-filter
    boek      (schrijf)   actie 17 op TEST-DESC-01; GET doc + Lines; collectie-filter
    zonder    (schrijf)   PUT TEST-DESC-02 zónder document-Description (alleen regel); GET doc
    header    (schrijf)   her-PUT TEST-DESC-02 mét `Header` + lange regel-Description (kandidaat-kopveld, afkap)
    opruimen  (schrijf)   actie 19 op geboekte exemplaren (concept, nooit verwijderen)
    alles     = concept → boek → zonder → opruimen
Gebruik: backend/.venv/bin/python verkenning/poc_description.py <stap>
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
KOP = "TEST-DESC kop-omschrijving 07-09 — Latour vergoeding per boeking"
REGEL = "TEST-DESC regelomschrijving (regel 1)"
DOCS = {
    "TEST-DESC-01": (uuid.uuid5(_POC_NS, "description:TEST-DESC-01"), 100.00, 21.00, KOP),
    "TEST-DESC-02": (uuid.uuid5(_POC_NS, "description:TEST-DESC-02"), 10.00, 2.10, None),
}
KILL_SWITCH = HIER / "POC_STOP"
OUTPUT = HIER / "output"
AUDIT_LOG = OUTPUT / "descriptionpoc_audit.jsonl"
VANDAAG = datetime.now(UTC).date().isoformat()


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
    print(f"   [{label}] Status={d.get('Status')} Receipt={d.get('ReceiptNumber')} Totaal={d.get('BaseInvoiceAmount')} "
          f"Reference={d.get('Reference')!r}\n      Description={d.get('Description')!r}")
    return d


def _lines(c: PocClient, doc_id: uuid.UUID, label: str) -> list[dict]:
    rijen = c.get(f"PurchaseInvoices/{doc_id}/Lines", **{"$expand": "Account"}).get("value", [])
    for r in rijen:
        print(f"   [{label} regel] Description={r.get('Description')!r} Net={r.get('NetAmount')} Tax={r.get('TaxAmount')} "
              f"Account={(r.get('Account') or {}).get('Code')}")
    return rijen


def _collectie(c: PocClient, ref: str, vendor: str, bedrag: float, label: str) -> None:
    """Bijvangst 1b: ziet het collectie-filter (de duplicaatcheck) dit document in zijn huidige status?"""
    treffers = c.rlz.find_purchase_invoices_by_reference(vendor_id=vendor, reference=ref, total_amount=bedrag)
    print(f"   [{label}] find_purchase_invoices_by_reference → {len(treffers)} treffer(s): "
          + json.dumps([{k: t.get(k) for k in ('id', 'Status', 'Reference', 'BaseInvoiceAmount', 'Description')} for t in treffers], default=str))
    # Expliciet Status-predicaat: RLZ's DocumentStatus is een enum-type — `Status eq 1` geeft 400 ("incompatible
    # types … DocumentStatus / Edm.Int32", geverifieerd 07-09); de enum-literal-vorm proberen we ter documentatie.
    for vorm in ("Status eq Reeleezee.DTO.DocumentStatus'1'", "Status eq 'Tentative'", "Status eq '1'"):
        try:
            rijen = c.get("PurchaseInvoices", **{"$filter": f"Entity/id eq {vendor} and Reference eq '{ref}' and {vorm}"}).get("value", [])
            print(f"      expliciet {vorm}: {len(rijen)} → statussen {[r.get('Status') for r in rijen]}")
        except RlzApiError as e:
            print(f"      expliciet {vorm}: {e.status_code} {e.body[:120]}")
    _audit({"actie": "collectie-filter", "ref": ref, "label": label, "treffers": treffers})


def _put(c: PocClient, ref: str) -> None:
    doc_id, net, btw, kop = DOCS[ref]
    body: dict[str, Any] = {
        "id": str(doc_id),
        "Entity": {"id": _vendor_id(c)},
        "DocumentLineList": [{"Account": {"id": _kosten(c)}, "TaxRate": {"id": TAXRATE_21_ID},
                              "NetAmount": net, "TaxAmount": btw, "Description": REGEL}],
        "Reference": ref,
        "Date": f"{VANDAAG}T00:00:00",
        "BookDate": f"{VANDAAG}T00:00:00",
    }
    if kop is not None:
        body["Description"] = kop
    print(f"== PUT {ref}: Description={kop!r}, regel-Description={REGEL!r}")
    c.put(f"PurchaseInvoices/{doc_id}", body)


def stap_concept(c: PocClient) -> None:
    ref = "TEST-DESC-01"
    doc_id, net, btw, _ = DOCS[ref]
    _put(c, ref)
    _doc(c, doc_id, f"{ref} concept")
    _lines(c, doc_id, f"{ref} concept")
    _collectie(c, ref, _vendor_id(c), round(net + btw, 2), f"{ref} concept (Status 1)")


def stap_boek(c: PocClient) -> None:
    ref = "TEST-DESC-01"
    doc_id, net, btw, _ = DOCS[ref]
    print(f"== boek {ref} (actie 17)")
    c.actie(f"PurchaseInvoices/{doc_id}", 17)
    d = _doc(c, doc_id, f"{ref} geboekt")
    print("   alle kopvelden:", json.dumps({k: v for k, v in d.items() if not isinstance(v, (list, dict))}, default=str))
    _lines(c, doc_id, f"{ref} geboekt")
    _collectie(c, ref, _vendor_id(c), round(net + btw, 2), f"{ref} geboekt")


def stap_zonder(c: PocClient) -> None:
    ref = "TEST-DESC-02"
    doc_id, *_ = DOCS[ref]
    _put(c, ref)
    _doc(c, doc_id, f"{ref} concept zonder document-Description")
    _lines(c, doc_id, f"{ref} concept")


LANG = ("TEST-DESC lange kop " + "x" * 230)[:250]


def stap_header(c: PocClient) -> None:
    """Kandidaat-velden voor een kop-tekst die RLZ wél bewaart: `Header` (leeg kopveld in de GET) + een lange
    regel-Description (afkap-grens?). Her-PUT op het concept TEST-DESC-02 vervangt de DocumentLineList (geverifieerd)."""
    ref = "TEST-DESC-02"
    doc_id, net, btw, _ = DOCS[ref]
    body: dict[str, Any] = {
        "id": str(doc_id),
        "Entity": {"id": _vendor_id(c)},
        "DocumentLineList": [{"Account": {"id": _kosten(c)}, "TaxRate": {"id": TAXRATE_21_ID},
                              "NetAmount": net, "TaxAmount": btw, "Description": LANG}],
        "Reference": ref,
        "Date": f"{VANDAAG}T00:00:00",
        "BookDate": f"{VANDAAG}T00:00:00",
        "Header": KOP,
        "Description": KOP,
    }
    print(f"== her-PUT {ref}: Header={KOP!r}, regel-Description {len(LANG)} tekens")
    c.put(f"PurchaseInvoices/{doc_id}", body)
    d = _doc(c, doc_id, f"{ref} met Header")
    print(f"      Header={d.get('Header')!r}  Description-lengte={len(d.get('Description') or '')}")
    rijen = _lines(c, doc_id, f"{ref} lang")
    for r in rijen:
        print(f"      regel-Description-lengte={len(r.get('Description') or '')}")


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


STAPPEN = {"concept": stap_concept, "boek": stap_boek, "zonder": stap_zonder, "header": stap_header, "opruimen": stap_opruimen}

if __name__ == "__main__":
    stap = sys.argv[1] if len(sys.argv) > 1 else "alles"
    c = PocClient()
    if stap == "alles":
        for s in ("concept", "boek", "zonder", "header", "opruimen"):
            STAPPEN[s](c)
    else:
        STAPPEN[stap](c)
