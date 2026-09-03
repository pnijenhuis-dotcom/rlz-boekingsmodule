#!/usr/bin/env python3
"""STAP 0 — Vendor archiveren via de RLZ-API (design-ronde 03-09, blok 0; mockup crediteuren-dubbelen-v2 ④).

Vraag: kan een Vendor via de API op inactief/gearchiveerd? (Customers konden dat NIET — hertest 14-08,
api-verkenning "Systeemanker route A": IsArchived/RecordStatus geven 204 zonder effect.)

Stappen (TEST-administratie, eigen TEST-vendor, NOOIT DELETE, alles teruggezet):
    inspecteer  (read-only) GET Vendors/{id}?fields=all van de TEST-vendor + Help-routes rond Vendors
    aanmaken    (schrijf)   PUT Vendors/{guid} "TEST-ARCHIEF-STAP0 crediteur" (client-GUID, idempotent)
    probeer     (schrijf)   PUT-varianten IsArchived / RecordStatus / IsActive / Status → readback per variant,
                            plus $filter-zichtbaarheid; ná elke variant terugzetten
    herstel     (schrijf)   alle kandidaat-velden terug op de actieve stand
    alles       = inspecteer → aanmaken → probeer → herstel
Gebruik: backend/.venv/bin/python verkenning/poc_vendor_archiveren.py <stap>
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
_POC_NS = uuid.UUID("b1a6c9de-4f02-47d3-9b7a-2e8f0c5d1a44")
VENDOR_ID = uuid.uuid5(_POC_NS, "vendor-archiveren:TEST-ARCHIEF-STAP0")
VENDOR_NAAM = "TEST-ARCHIEF-STAP0 crediteur"
KILL_SWITCH = HIER / "POC_STOP"
OUTPUT = HIER / "output"
AUDIT_LOG = OUTPUT / "vendor_archiveren_audit.jsonl"


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

    def put(self, path: str, body: dict[str, Any]) -> int | str:
        if KILL_SWITCH.exists():
            raise SystemExit("KILL SWITCH actief")
        try:
            r = self.rlz.put(path, body)
            _audit({"actie": "PUT", "pad": path, "payload": body, "status": r.status_code})
            return r.status_code
        except RlzApiError as e:
            _audit({"actie": "PUT", "pad": path, "payload": body, "status": f"{e.status_code}: {e.body[:300]}"})
            return f"{e.status_code}: {e.body[:200]}"


def _vendor(c: PocClient, label: str) -> dict:
    v = c.get(f"Vendors/{VENDOR_ID}", fields="all")
    kandidaat = {k: v.get(k) for k in ("IsArchived", "RecordStatus", "IsActive", "Status", "IsBlocked", "Archived", "IsDeleted")
                 if k in v}
    print(f"   [{label}] {kandidaat}")
    return v


def inspecteer(c: PocClient) -> None:
    print("== inspecteer: velden op een bestaande vendor (fields=all)")
    lijst = c.get("Vendors", **{"$top": 1}).get("value", [])
    if lijst:
        v = c.get(f"Vendors/{lijst[0]['id']}", fields="all")
        print("   velden:", sorted(v.keys()))
        print("   kandidaat-velden:", {k: v.get(k) for k in v if any(s in k.lower() for s in ("archiv", "active", "status", "block", "delet"))})
    print("== inspecteer: Help-routes rond Vendors")
    try:
        help_ = c.get("Help")
        routes = [r for r in json.dumps(help_).split('"') if "Vendor" in r and ("/" in r)]
        for r in sorted(set(routes))[:60]:
            print("   ", r)
    except RlzApiError as e:
        print("   Help niet leesbaar:", e.status_code)
    print("== inspecteer: filter-zichtbaarheid (telling actief/gearchiveerd)")
    alle = c.get("Vendors", **{"$top": 1000, "fields": "all"}).get("value", [])
    from collections import Counter
    print("   RecordStatus-verdeling over alle vendors:", Counter(v.get("RecordStatus") for v in alle))
    print("   IsArchived-verdeling:", Counter(v.get("IsArchived") for v in alle))
    for flt in ("IsArchived eq true", "IsArchived eq false", "RecordStatus eq Reeleezee.DTO.RecordStatus'Archived'", "RecordStatus eq 'Active'"):
        try:
            n = len(c.get("Vendors", **{"$filter": flt, "$top": 500}).get("value", []))
            print(f"   $filter={flt!r}: {n} rijen")
        except RlzApiError as e:
            print(f"   $filter={flt!r}: {e.status_code} {e.body[:120]}")


def aanmaken(c: PocClient) -> None:
    print(f"== aanmaken {VENDOR_NAAM} ({VENDOR_ID})")
    print("   PUT:", c.put(f"Vendors/{VENDOR_ID}", {"id": str(VENDOR_ID), "Name": VENDOR_NAAM}))
    _vendor(c, "na aanmaak")


def _zichtbaar_in_lijst(c: PocClient) -> dict[str, bool]:
    uit: dict[str, bool] = {}
    for label, params in (
        ("default", {"$top": 1000}),
        ("fields=all", {"$top": 1000, "fields": "all"}),
    ):
        ids = {x["id"] for x in c.get("Vendors", **params).get("value", [])}
        uit[label] = str(VENDOR_ID) in ids
    return uit


def probeer(c: PocClient) -> None:
    basis = {"id": str(VENDOR_ID), "Name": VENDOR_NAAM}
    varianten: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
        ("IsArchived:true", {"IsArchived": True}, {"IsArchived": False}),
        ("RecordStatus:1", {"RecordStatus": 1}, {"RecordStatus": 2}),
        ("RecordStatus:3", {"RecordStatus": 3}, {"RecordStatus": 2}),
        ("RecordStatus:0", {"RecordStatus": 0}, {"RecordStatus": 2}),
        ("IsArchived:true+RecordStatus:1", {"IsArchived": True, "RecordStatus": 1}, {"IsArchived": False, "RecordStatus": 2}),
    ]
    voor = _vendor(c, "voor")
    for naam, zet, terug in varianten:
        print(f"== variant {naam}")
        st = c.put(f"Vendors/{VENDOR_ID}", {**basis, **zet})
        print("   PUT:", st)
        na = _vendor(c, f"na {naam}")
        veld = next(iter(zet))
        gewijzigd = na.get(veld) != voor.get(veld)
        print(f"   effect op {veld}: {voor.get(veld)!r} → {na.get(veld)!r} ({'GEWIJZIGD' if gewijzigd else 'geen effect'})")
        print("   zichtbaar in lijst:", _zichtbaar_in_lijst(c))
        _audit({"actie": "variant", "naam": naam, "put": st, "voor": voor.get(veld), "na": na.get(veld),
                "zichtbaar": _zichtbaar_in_lijst(c)})
        if gewijzigd:
            print("   terugzetten:", c.put(f"Vendors/{VENDOR_ID}", {**basis, **terug}))
            _vendor(c, "na terugzetten")


def herstel(c: PocClient) -> None:
    print("== herstel: actieve stand")
    print("   PUT:", c.put(f"Vendors/{VENDOR_ID}", {"id": str(VENDOR_ID), "Name": VENDOR_NAAM,
                                                    "IsArchived": False, "RecordStatus": 2}))
    _vendor(c, "eindstand")
    print("   zichtbaar in lijst:", _zichtbaar_in_lijst(c))


if __name__ == "__main__":
    stap = sys.argv[1] if len(sys.argv) > 1 else "inspecteer"
    c = PocClient()
    stappen = {"inspecteer": [inspecteer], "aanmaken": [aanmaken], "probeer": [probeer], "herstel": [herstel],
               "alles": [inspecteer, aanmaken, probeer, herstel]}
    for fn in stappen[stap]:
        fn(c)
