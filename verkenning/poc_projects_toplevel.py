#!/usr/bin/env python3
"""STAP-0-HERTEST — klant-loze top-level Projects-schrijfroute (2026-08-14, screencheck Peter).

Aanleiding: Peters live browsercapture in de Universal-administratie bewees dat de RLZ-UI een
project ZONDER klant aanmaakt via `PUT {adminId}/Projects/{guid}?$expand=*($levels=max)` → 200.
De eerdere STAP-0-conclusie "de Customers-route is de enige schrijfvorm" (gebaseerd op de
Help-lijst, die géén top-level PUT kent) is daarmee gefalsifieerd — een geslaagde PoC op route X
bewijst nooit de afwezigheid van route Y. Kanttekening capture: payload onbekend (alleen
method/URL/status), UI draait op sessie-auth — deze hertest beantwoordt of de route óók via
Basic Auth werkt (de API-vorm die de motor gebruikt).

Vragen (opdracht Peter):
a. Werkt `PUT {adminId}/Projects/{client-guid}` zónder Customer via Basic Auth?
b. Minimale veldvorm ({id, Name})? Zo nee: helpt de capture-query ($expand) of een vollere body?
c. IsActive-default bij aanmaak?
d. Create-or-update-gedrag bij tweede PUT zelfde GUID (zelfde body én gewijzigde naam)?
e. Komt het project terug in de top-level collectie, en draagt het een Customer ($expand)?
f. Bruikbaar op een documentregel van een vreemde entiteit (concept + boek + storno — bevestigen
   dat klant-loos niet anders is dan het bewezen anker-gedrag)?

Opruiming (zelfde run, stap `opruim`): dit hertest-project én het route-A-project
`TEST-ROUTE-A Pand Dorpsstraat 1` op IsActive:false (projecten kennen geen actie 19 — de
archief-vlag ís het correctiemechanisme); het regel-PoC-concept blijft als concept staan
(testdata-afspraak v1.3: storno, nooit verwijderen).

Waarborgen identiek aan de andere PoC's: ADMIN-PIN (login mag uitsluitend de
test-administratie zien), KILL SWITCH (verkenning/POC_STOP), TEST-namen, append-only audit
(output/projectstoplevelpoc_audit.jsonl), NOOIT DELETE.

Gebruik:
    backend/.venv/bin/python verkenning/poc_projects_toplevel.py <stap>
Stappen: maak | herhaal | regel | opruim | alles
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

_POC_NS = uuid.UUID("7f1207e6-9f6b-4c58-a6a1-53df0f56b2e1")
PROJECT_NAAM = "TEST-LOSPROJECT-API hertest Dorpsstraat 2"
PROJECT_NAAM_GEWIJZIGD = "TEST-LOSPROJECT-API hertest Dorpsstraat 2 (hernoemd)"
PROJECT_ID = uuid.uuid5(_POC_NS, f"project:{TESTADMIN_ID}:{PROJECT_NAAM.lower()}")

# Bestaande teststand (route-A-run 2026-08-14) — opruimdoelen:
ROUTE_A_PROJECT_NAAM = "TEST-ROUTE-A Pand Dorpsstraat 1"
ANKER_NAAM = "Pandprojecten (systeem)"

# Bewezen geldige boekcombinatie op de test-administratie (zelfde bron als
# poc_project_regelgebruik.py: gekopieerd van een eerder GEBOEKT document).
VENDOR_ID = uuid.UUID("f7a74265-518a-4384-ad6e-214aeee28c27")
LEDGER_ID = uuid.UUID("c1c355aa-3618-4519-ad5e-e19712e13d72")
TAXRATE_ID = uuid.UUID("1e44993a-15f6-419f-87e5-3e31ac3d9383")
REFERENTIE = "TEST-LOSPROJECTPOC-1"
FACTUUR_ID = uuid.uuid5(_POC_NS, f"purchase:{TESTADMIN_ID}:{REFERENTIE.lower()}")

KILL_SWITCH = HIER / "POC_STOP"
OUTPUT = HIER / "output"
AUDIT_LOG = OUTPUT / "projectstoplevelpoc_audit.jsonl"
STATE_FILE = OUTPUT / "projectstoplevelpoc_state.json"


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

    def put(self, path: str, body: dict[str, Any], **params: Any) -> Any:
        self._check_kill_switch()
        try:
            r = self.rlz.put(path, body, params=params or None)
            status: Any = r.status_code
            tekst = r.text[:300]
        except RlzApiError as e:
            status = e.status_code
            tekst = e.body[:300]
        _audit(
            {"actie": "PUT", "pad": path, "params": params, "body": body, "status": status, "respons": tekst}
        )
        print(f"PUT {path} {params or ''} → {status} {tekst!r}")
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


def _toon_project(c: PocClient, project_id: uuid.UUID, label: str) -> dict[str, Any]:
    direct = c.get_or_none(f"Projects/{project_id}", **{"$expand": "Customer"})
    print(f"— GET Projects/{project_id}?$expand=Customer ({label}):")
    print(json.dumps(direct, indent=2, default=str)[:1500])
    _audit({"actie": f"toon_{label}", "project": direct})
    return direct if isinstance(direct, dict) else {}


def stap_maak(c: PocClient) -> None:
    """Vraag a/b/c/e: kale top-level PUT met minimale body; bij falen escaleren naar de
    capture-vorm (mét $expand-query) en een vollere body — pas dan is 'werkt niet' bewezen."""
    pogingen: list[dict[str, Any]] = []

    status = c.put(f"Projects/{PROJECT_ID}", {"id": str(PROJECT_ID), "Name": PROJECT_NAAM})
    pogingen.append({"vorm": "minimaal", "status": status})

    if not (200 <= int(status) < 300):
        # Escalatie 1: exact de capture-query van Peter erbij.
        status = c.put(
            f"Projects/{PROJECT_ID}",
            {"id": str(PROJECT_ID), "Name": PROJECT_NAAM},
            **{"$expand": "*($levels=max)"},
        )
        pogingen.append({"vorm": "capture_query", "status": status})
    if not (200 <= int(status) < 300):
        # Escalatie 2: vollere body (velden die de UI vermoedelijk meestuurt).
        status = c.put(
            f"Projects/{PROJECT_ID}",
            {
                "id": str(PROJECT_ID),
                "Name": PROJECT_NAAM,
                "IsActive": True,
                "IsBillable": False,
                "Description": PROJECT_NAAM,
            },
            **{"$expand": "*($levels=max)"},
        )
        pogingen.append({"vorm": "vollere_body_plus_query", "status": status})

    project = _toon_project(c, PROJECT_ID, "na_maak")
    in_collectie = c.get(
        "Projects", **{"$filter": f"Name eq '{PROJECT_NAAM}'"}
    ).get("value", [])
    print(f"— Treffers in top-level collectie op naam: {len(in_collectie)}")
    state = _state()
    state["maak"] = {
        "pogingen": pogingen,
        "gelukt": bool(project) and "_fout" not in project,
        "is_active_default": project.get("IsActive"),
        "customer_via_expand": project.get("Customer"),
        "in_collectie": len(in_collectie),
        "record": project,
    }
    _save_state(state)


def stap_herhaal(c: PocClient) -> None:
    """Vraag d: idempotentie + create-or-update op de top-level route."""
    print("— Herhaalde PUT, zelfde GUID + zelfde body:")
    status_zelfde = c.put(f"Projects/{PROJECT_ID}", {"id": str(PROJECT_ID), "Name": PROJECT_NAAM})
    aantal = len(
        c.get("Projects", **{"$filter": "startswith(Name, 'TEST-LOSPROJECT-API')"}).get("value", [])
    )
    print(f"— Aantal TEST-LOSPROJECT-API-projecten na herhaal-PUT: {aantal}")
    print("— Herhaalde PUT, zelfde GUID + GEWIJZIGDE naam:")
    status_gewijzigd = c.put(
        f"Projects/{PROJECT_ID}", {"id": str(PROJECT_ID), "Name": PROJECT_NAAM_GEWIJZIGD}
    )
    project = _toon_project(c, PROJECT_ID, "na_herhaal")
    # Terug naar de oorspronkelijke naam zodat de teststand deterministisch blijft.
    c.put(f"Projects/{PROJECT_ID}", {"id": str(PROJECT_ID), "Name": PROJECT_NAAM})
    state = _state()
    state["herhaal"] = {
        "status_zelfde_body": status_zelfde,
        "aantal_na_herhaal": aantal,
        "status_gewijzigde_naam": status_gewijzigd,
        "naam_na_herhaal": project.get("Name"),
    }
    _save_state(state)


def stap_regel(c: PocClient) -> None:
    """Vraag f: klant-loos project op een PurchaseInvoice-regel van een vreemde entiteit,
    door concept → boeken (17) → storno (19) heen — zelfde bewijs als de anker-nazorg-PoC."""
    status_put = c.put(
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
                    "Project": {"id": str(PROJECT_ID)},
                    "Description": "TEST klant-loos project op vreemde documentregel",
                }
            ],
        },
    )

    def _regels(label: str) -> list[dict[str, Any]]:
        regels = c.get_or_none(f"PurchaseInvoices/{FACTUUR_ID}/Lines", **{"$expand": "Project"})
        waarde = regels.get("value", []) if isinstance(regels, dict) else []
        doc = c.get_or_none(f"PurchaseInvoices/{FACTUUR_ID}", **{"$select": "id,Status,Reference"})
        print(f"— Document ({label}): {json.dumps(doc, default=str)[:300]}")
        for r in waarde:
            proj = r.get("Project") or {}
            print(f"— Regel ({label}): Project={proj.get('Name')!r} ({proj.get('id')})")
        _audit({"actie": f"lees_{label}", "document": doc, "regels": waarde})
        return waarde

    na_put = _regels("na_put")
    status_boek = c.actie(f"PurchaseInvoices/{FACTUUR_ID}", 17)
    na_boek = _regels("na_boek")
    status_storno = c.actie(f"PurchaseInvoices/{FACTUUR_ID}", 19)
    na_storno = _regels("na_storno")
    state = _state()
    state["regel"] = {
        "put_status": status_put,
        "project_na_put": (na_put[0].get("Project") or {}).get("id") if na_put else None,
        "boek_status": status_boek,
        "project_na_boek": (na_boek[0].get("Project") or {}).get("id") if na_boek else None,
        "storno_status": status_storno,
        "project_na_storno": (na_storno[0].get("Project") or {}).get("id") if na_storno else None,
    }
    _save_state(state)


def stap_opruim(c: PocClient) -> None:
    """Opruiming teststand: hertest-project + TEST-ROUTE-A op IsActive:false (archief-vlag,
    het enige correctiemechanisme voor projecten); het anker-customer-record alleen TONEN
    (welke velden draagt het — deactiveren gebeurt in de bouwstap, niet hier)."""
    status_eigen = c.put(
        f"Projects/{PROJECT_ID}", {"id": str(PROJECT_ID), "Name": PROJECT_NAAM, "IsActive": False}
    )
    hits = c.get(
        "Projects", **{"$filter": f"Name eq '{ROUTE_A_PROJECT_NAAM}'"}
    ).get("value", [])
    status_route_a: Any = None
    if len(hits) == 1:
        route_a_id = hits[0]["id"]
        status_route_a = c.put(
            f"Projects/{route_a_id}",
            {"id": route_a_id, "Name": ROUTE_A_PROJECT_NAAM, "IsActive": False},
        )
        _toon_project(c, route_a_id, "route_a_na_opruim")
    else:
        print(f"⚠️ Verwacht 1 project '{ROUTE_A_PROJECT_NAAM}', gevonden: {len(hits)} — overgeslagen")
    anker = c.get("Customers", **{"$filter": f"Name eq '{ANKER_NAAM}'"}).get("value", [])
    print("— Anker-customer-record (veldvorm t.b.v. deactivering in de bouwstap):")
    print(json.dumps(anker, indent=2, default=str)[:2000])
    _audit({"actie": "anker_veldvorm", "anker": anker})
    state = _state()
    state["opruim"] = {
        "eigen_project_inactief_status": status_eigen,
        "route_a_inactief_status": status_route_a,
        "anker_record": anker,
    }
    _save_state(state)


STAPPEN = {"maak": stap_maak, "herhaal": stap_herhaal, "regel": stap_regel, "opruim": stap_opruim}


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {*STAPPEN, "alles"}:
        raise SystemExit(f"Gebruik: poc_projects_toplevel.py {{{' | '.join([*STAPPEN, 'alles'])}}}")
    c = PocClient()
    if sys.argv[1] == "alles":
        for naam, fn in STAPPEN.items():
            print(f"\n===== STAP: {naam} =====")
            fn(c)
    else:
        STAPPEN[sys.argv[1]](c)


if __name__ == "__main__":
    main()
