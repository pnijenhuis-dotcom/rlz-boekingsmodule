#!/usr/bin/env python3
"""Route-A-nazorg PoC (2026-08-14): is een pand-project dat onder het SYSTEEMANKER
"Pandprojecten (systeem)" hangt, bruikbaar op documentregels van VREEMDE entiteiten?

Waarom dit moet: route A hangt elk pand-project noodgedwongen onder één anker-customer
(de schrijfroute `PUT Customers/{baseId}/Projects/{id}` dwingt een customer af — STAP-0
"Projects-schrijfroute"). Het hele doel van die projecten is echter kostenregistratie op
INKOOPfacturen van willekeurige leveranciers (kostenflow-omkering §3a: pand = project_id
per regel). Als RLZ een project regel-technisch aan zijn customer zou binden, is route A
een doodlopende straat — dat willen we nú bewijzen, niet bij S2.

Stappen (tegen de TEST-administratie, testdata-afspraak v1.3 — storno, nooit verwijderen):
1. `vind`   — zoek het route-A-testproject `TEST-ROUTE-A Pand Dorpsstraat 1` + bewijs via
              $expand=Customer dat het onder het anker hangt.
2. `regel`  — PUT PurchaseInvoice (concept) op de bewezen PoC-vendor met het project op de
              regel → teruglezen via Lines?$expand=Account,Project: blijft de Project-ref
              staan op een document van een ándere entiteit?
3. `boek`   — actie 17 (Book) → documentstatus + regel-herlees (overleeft de ref het boeken?).
4. `storno` — actie 19 (Correct, terug naar concept) — teststand blijft herkenbaar staan.

Waarborgen identiek aan de andere PoC's: ADMIN-PIN (login mag uitsluitend de
test-administratie zien), KILL SWITCH (verkenning/POC_STOP), TEST-referentie, append-only
audit (output/projectregelpoc_audit.jsonl), NOOIT DELETE.

Gebruik:
    backend/.venv/bin/python verkenning/poc_project_regelgebruik.py <stap>
Stappen: vind | regel | boek | storno | alles
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

PROJECT_NAAM = "TEST-ROUTE-A Pand Dorpsstraat 1"
ANKER_NAAM = "Pandprojecten (systeem)"

# Bewezen geldige boekcombinatie op de test-administratie (zelfde bron als
# scripts/kliktest_accordeur_seed.py: gekopieerd van een eerder GEBOEKT document).
VENDOR_ID = uuid.UUID("f7a74265-518a-4384-ad6e-214aeee28c27")
LEDGER_ID = uuid.UUID("c1c355aa-3618-4519-ad5e-e19712e13d72")
TAXRATE_ID = uuid.UUID("1e44993a-15f6-419f-87e5-3e31ac3d9383")

_POC_NS = uuid.UUID("7f1207e6-9f6b-4c58-a6a1-53df0f56b2e1")
REFERENTIE = "TEST-PROJECTREGELPOC-1"
FACTUUR_ID = uuid.uuid5(_POC_NS, f"purchase:{TESTADMIN_ID}:{REFERENTIE.lower()}")

KILL_SWITCH = HIER / "POC_STOP"
OUTPUT = HIER / "output"
AUDIT_LOG = OUTPUT / "projectregelpoc_audit.jsonl"
STATE_FILE = OUTPUT / "projectregelpoc_state.json"


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

    def get_or_none(self, path: str, **params: Any) -> Any:
        try:
            return self.get(path, **params)
        except RlzApiError as e:
            return {"_fout": f"{e.status_code}: {e.body[:300]}"}

    def put(self, path: str, body: dict[str, Any]) -> Any:
        self._check_kill_switch()
        try:
            r = self.rlz.put(path, body)
            status: Any = r.status_code
            tekst = r.text[:300]
        except RlzApiError as e:
            status = e.status_code
            tekst = e.body[:300]
        _audit({"actie": "PUT", "pad": path, "body": body, "status": status, "respons": tekst})
        print(f"PUT {path} → {status} {tekst!r}")
        return status

    def actie(self, path: str, action_type: int) -> Any:
        self._check_kill_switch()
        try:
            r = self.rlz.post_action(path, action_type)
            status: Any = r.status_code
            tekst = r.text[:300]
        except RlzApiError as e:
            status = e.status_code
            tekst = e.body[:300]
        _audit({"actie": "POST_Actions", "pad": path, "type": action_type, "status": status, "respons": tekst})
        print(f"POST {path}/Actions Type:{action_type} → {status} {tekst!r}")
        return status


def _vind_project(c: PocClient) -> dict[str, Any]:
    hits = c.get(
        "Projects", **{"$filter": f"Name eq '{PROJECT_NAAM}'", "$expand": "Customer"}
    ).get("value", [])
    if len(hits) != 1:
        raise SystemExit(f"Verwacht precies 1 project '{PROJECT_NAAM}', gevonden: {len(hits)}")
    return hits[0]


def stap_vind(c: PocClient) -> None:
    project = _vind_project(c)
    customer = project.get("Customer") or {}
    print(json.dumps(project, indent=2, default=str)[:1500])
    print(f"— Project hangt onder customer: {customer.get('Name')!r} ({customer.get('id')})")
    _audit({"actie": "vind", "project": project.get("id"), "customer": customer})
    state = _state()
    state["vind"] = {
        "project_id": project.get("id"),
        "customer_naam": customer.get("Name"),
        "onder_anker": customer.get("Name") == ANKER_NAAM,
    }
    _save_state(state)


def _lees_regels(c: PocClient, label: str) -> list[dict[str, Any]]:
    regels = c.get_or_none(
        f"PurchaseInvoices/{FACTUUR_ID}/Lines", **{"$expand": "Account,Project"}
    )
    waarde = regels.get("value", []) if isinstance(regels, dict) else []
    doc = c.get_or_none(f"PurchaseInvoices/{FACTUUR_ID}", **{"$select": "id,Status,Reference"})
    print(f"— Document ({label}): {json.dumps(doc, default=str)[:300]}")
    for r in waarde:
        proj = r.get("Project") or {}
        print(
            f"— Regel ({label}): Net={r.get('NetAmount')} Project={proj.get('Name')!r} "
            f"({proj.get('id')})"
        )
    _audit({"actie": f"lees_{label}", "document": doc, "regels": waarde})
    return waarde


def stap_regel(c: PocClient) -> None:
    project = _vind_project(c)
    project_id = project["id"]
    status = c.put(
        f"PurchaseInvoices/{FACTUUR_ID}",
        {
            "id": str(FACTUUR_ID),
            "Entity": {"id": str(VENDOR_ID)},
            "Reference": REFERENTIE,
            "DocumentLineList": [
                {
                    "Account": {"id": str(LEDGER_ID)},
                    "TaxRate": {"id": str(TAXRATE_ID)},
                    "NetAmount": 100.00,
                    "TaxAmount": 21.00,
                    "Project": {"id": project_id},
                    "Description": "TEST route-A projectgebruik op vreemde documentregel",
                }
            ],
        },
    )
    regels = _lees_regels(c, "na_put")
    state = _state()
    state["regel"] = {
        "put_status": status,
        "project_op_regel": (regels[0].get("Project") or {}).get("id") if regels else None,
        "verwacht_project": project_id,
    }
    _save_state(state)


def stap_boek(c: PocClient) -> None:
    status = c.actie(f"PurchaseInvoices/{FACTUUR_ID}", 17)
    regels = _lees_regels(c, "na_boek")
    state = _state()
    state["boek"] = {
        "actie17_status": status,
        "project_op_regel_na_boeken": (regels[0].get("Project") or {}).get("id") if regels else None,
    }
    _save_state(state)


def stap_storno(c: PocClient) -> None:
    status = c.actie(f"PurchaseInvoices/{FACTUUR_ID}", 19)
    _lees_regels(c, "na_storno")
    state = _state()
    state["storno"] = {"actie19_status": status}
    _save_state(state)


STAPPEN = {"vind": stap_vind, "regel": stap_regel, "boek": stap_boek, "storno": stap_storno}


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {*STAPPEN, "alles"}:
        raise SystemExit(f"Gebruik: poc_project_regelgebruik.py {{{' | '.join([*STAPPEN, 'alles'])}}}")
    c = PocClient()
    if sys.argv[1] == "alles":
        for naam, fn in STAPPEN.items():
            print(f"\n===== STAP: {naam} =====")
            fn(c)
    else:
        STAPPEN[sys.argv[1]](c)


if __name__ == "__main__":
    main()
