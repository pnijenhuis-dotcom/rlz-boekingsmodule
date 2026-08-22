#!/usr/bin/env python3
"""STAP 0 — tegenboek-pad (2026-08-22, vóór de bouw; mockup/tegenboek-mockup.html).

Verifieert live tegen de TEST-administratie hoe een tegenboeking van een geboekte
PurchaseInvoice het zuiverst landt. Verwachting (te toetsen): een NIEUWE PurchaseInvoice
met negatieve regels op dezelfde Entity, zelfde GB/TaxRate per regel, boekdatum vandaag
(open periode). Vragen:

1. `origineel`   (schrijf) — origineel TEST-document boeken mét Date in de ingediende
   periode 2023-Q1 (Status 2, api-verkenning "Actie 19 in een periode met ingediende
   btw-aangifte") — het scenario waarin storno door onze poort geblokkeerd is.
2. `tegenboeking`(schrijf) — nieuwe PurchaseInvoice, zelfde Entity, gespiegelde regels
   (NetAmount/TaxAmount negatief, zelfde Account/TaxRate), Date = vandaag → boek 17.
   Accepteert RLZ dit door de hele flow (Status 2, negatief BaseInvoiceAmount, eigen
   ReceiptNumber)?
3. `btw`         (read-only) — valt de btw van de tegenboeking als NEGATIEVE voorbelasting
   in de eerstvolgende open aangifte-periode? (TaxDeclarations + /TaxSources; best-effort:
   als er geen concept-aangifte bestaat die vandaag dekt, is dat zelf ook een feit.)
4. `openpost`    (read-only) — hoe gedraagt de open post zich: origineel houdt
   BaseRemainingAmount +, de tegenboeking − (open creditpost — mockup-waarschuwing)?
5. `opruimen`    (schrijf) — actie 19 op beide; einde = concept (nooit verwijderen).

Waarborgen identiek aan de andere PoC's: ADMIN-PIN, KILL SWITCH (verkenning/POC_STOP),
TEST-referenties, append-only audit (output/tegenboekpoc_audit.jsonl), NOOIT DELETE.

Gebruik:
    backend/.venv/bin/python verkenning/poc_tegenboeking.py <stap>
Stappen: origineel | tegenboeking | btw | openpost | opruimen | alles
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

ORIG_REFERENTIE = "TEST-TB-ORIG-01"
TEGEN_REFERENTIE = "TB TEST-TB-ORIG-01"
_POC_NS = uuid.UUID("b1a6c9de-4f02-47d3-9b7a-2e8f0c5d1a44")  # zelfde PoC-namespace
ORIG_ID = uuid.uuid5(_POC_NS, f"tegenboek:orig:{ORIG_REFERENTIE}")
TEGEN_ID = uuid.uuid5(_POC_NS, f"tegenboek:tegen:{ORIG_REFERENTIE}")

# In de ingediende periode 2023-Q1 (Status 2 op de test-administratie) — het geblokkeerde
# storno-scenario waarvoor het tegenboek-pad bestaat.
ORIG_DATUM = "2023-02-15"

KILL_SWITCH = HIER / "POC_STOP"
OUTPUT = HIER / "output"
AUDIT_LOG = OUTPUT / "tegenboekpoc_audit.jsonl"

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
    """Zelfde schil als poc_herput_en_aangiftepoort.py: admin-pin, kill switch vóór elke
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


def _vendor_id(c: PocClient) -> str:
    naam_esc = CREDITEUR_NAAM.replace("'", "''")
    vendors = c.get("Vendors", **{"$filter": f"Name eq '{naam_esc}'"}).get("value", [])
    if not vendors:
        raise SystemExit("TEST-crediteur niet gevonden — draai eerst poc_doorbelasting_schrijf.py crediteur")
    return vendors[0]["id"]


def _kostenrekening(c: PocClient) -> dict[str, Any]:
    kandidaten = c.get("Ledgers", search="4302").get("value", [])
    kosten = next((k for k in kandidaten if k.get("AccountType") == 2), None)
    if kosten is None:
        raise SystemExit("Geen kostenrekening (AccountType 2) gevonden")
    return kosten


def _print_doc(c: PocClient, doc_id: uuid.UUID, label: str) -> dict[str, Any]:
    doc = c.get(f"PurchaseInvoices/{doc_id}")
    regels = c.get(f"PurchaseInvoices/{doc_id}/Lines").get("value", [])
    print(
        f"   [{label}] Status={doc.get('Status')} regels={len(regels)} "
        f"Totaal={doc.get('BaseInvoiceAmount')} Open={doc.get('BaseRemainingAmount')} "
        f"Betaald={doc.get('BasePaidAmount')} ReceiptNumber={doc.get('ReceiptNumber')} "
        f"Date={doc.get('Date')} BookDate={doc.get('BookDate')}"
    )
    return doc


def stap_origineel(c: PocClient) -> None:
    print(f"== origineel (schrijf): PurchaseInvoice {ORIG_ID} ({ORIG_REFERENTIE}, Date {ORIG_DATUM})")
    vendor_id = _vendor_id(c)
    kosten = _kostenrekening(c)
    body = {
        "id": str(ORIG_ID),
        "Entity": {"id": vendor_id},
        "DocumentLineList": [
            {
                "Account": {"id": kosten["id"]},
                "TaxRate": {"id": TAXRATE_21_ID},
                "NetAmount": 100.00,
                "TaxAmount": 21.00,
                "Description": f"{ORIG_REFERENTIE} kostenregel",
            }
        ],
        "Reference": ORIG_REFERENTIE,
        "Date": f"{ORIG_DATUM}T00:00:00",
    }
    c.put(f"PurchaseInvoices/{ORIG_ID}", body)
    c.actie(f"PurchaseInvoices/{ORIG_ID}", ACTION_BOOK)
    _print_doc(c, ORIG_ID, "origineel na boek")


def stap_tegenboeking(c: PocClient) -> None:
    print(f"== tegenboeking (schrijf): NIEUWE PurchaseInvoice {TEGEN_ID} ({TEGEN_REFERENTIE}, Date vandaag)")
    vendor_id = _vendor_id(c)
    orig_regels = c.get(f"PurchaseInvoices/{ORIG_ID}/Lines", **{"$expand": "Account,TaxRate"}).get("value", [])
    if not orig_regels:
        raise SystemExit("Origineel heeft geen regels — draai eerst stap `origineel`")
    lines = []
    for r in orig_regels:
        account = (r.get("Account") or {}).get("id")
        taxrate = (r.get("TaxRate") or {}).get("id")
        lines.append(
            {
                "Account": {"id": account},
                "TaxRate": {"id": taxrate},
                "NetAmount": -float(r.get("NetAmount") or 0),
                "TaxAmount": -float(r.get("TaxAmount") or 0),
                "Description": f"TEGENBOEKING {ORIG_REFERENTIE} · {CREDITEUR_NAAM}",
            }
        )
    body = {
        "id": str(TEGEN_ID),
        "Entity": {"id": vendor_id},
        "DocumentLineList": lines,
        "Reference": TEGEN_REFERENTIE,
        "Date": f"{datetime.now(UTC).date().isoformat()}T00:00:00",
    }
    c.put(f"PurchaseInvoices/{TEGEN_ID}", body)
    c.actie(f"PurchaseInvoices/{TEGEN_ID}", ACTION_BOOK)
    _print_doc(c, TEGEN_ID, "tegenboeking na boek")


def stap_btw(c: PocClient) -> None:
    print("== btw (read-only): waar landen de TaxSources van origineel + tegenboeking?")
    rijen = c.get("TaxDeclarations").get("value", [])
    print(f"   {len(rijen)} aangifte-rijen; per rij zoeken in /TaxSources naar onze documenten")
    doelen = {str(ORIG_ID): "origineel", str(TEGEN_ID): "tegenboeking"}
    gevonden = 0
    for rij in sorted(rijen, key=lambda r: str(r.get("StartDate"))):
        try:
            bronnen = c.get(f"TaxDeclarations/{rij['id']}/TaxSources").get("value", [])
        except RlzApiError as e:
            print(f"   ⚠️ TaxSources onleesbaar voor {rij.get('id')} ({e.status_code})")
            continue
        for bron in bronnen:
            doc_id = str((bron.get("Document") or {}).get("id") or bron.get("DocumentId") or "")
            if doc_id in doelen:
                gevonden += 1
                print(
                    f"   → {doelen[doc_id]} in aangifte Status={rij.get('Status')} "
                    f"periode {rij.get('StartDate')} – {rij.get('Date')}: "
                    f"NetAmount={bron.get('NetAmount')} TaxAmount={bron.get('TaxAmount')} "
                    f"categorie={bron.get('VATSourceCategory')}"
                )
    if gevonden == 0:
        print(
            "   geen TaxSources gevonden op onze documenten — mogelijk bestaat er (nog) geen "
            "aangifte-document dat de open periode dekt (TaxSource koppelt dan pas bij aanmaak); "
            "zelf ook een feit om vast te leggen."
        )


def stap_openpost(c: PocClient) -> None:
    print("== openpost (read-only): open-post-gedrag van beide documenten")
    _print_doc(c, ORIG_ID, "origineel")
    _print_doc(c, TEGEN_ID, "tegenboeking")


def stap_opruimen(c: PocClient) -> None:
    print("== opruimen (schrijf): actie 19 op beide — einde = concept, nooit verwijderen")
    for doc_id, label in ((TEGEN_ID, "tegenboeking"), (ORIG_ID, "origineel")):
        try:
            c.actie(f"PurchaseInvoices/{doc_id}", ACTION_CORRECT)
        except RlzApiError as e:
            print(f"   ⚠️ storno {label} faalde ({e.status_code}) — handmatig nakijken")
            continue
        _print_doc(c, doc_id, f"{label} na storno")


STAPPEN = {
    "origineel": stap_origineel,
    "tegenboeking": stap_tegenboeking,
    "btw": stap_btw,
    "openpost": stap_openpost,
    "opruimen": stap_opruimen,
}


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
