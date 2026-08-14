#!/usr/bin/env python3
"""STAP 0 — Projects-schrijfroute (route A, 2026-08-14): verificatie #3 uit het BOUWPLAN,
live tegen de test-administratie vóór de projectaanmaak-motor gebouwd wordt.

Help-lijst-feit (verkenning/output/help.html): PUT bestaat UITSLUITEND als
`Customers/{baseId}/Projects/{id}` — er is géén top-level `PUT Projects/{id}`. De PoC moet
daarom ook beantwoorden wélke rol de customer (baseId) speelt: is het project daarna
top-level zichtbaar (`GET {adminId}/Projects`), en draagt het record een Customer-referentie?

Stappen:
1. `lees`    — GET Projects top-level (veldvorm bestaande projecten) + GET
               Customers/{baseId}/Projects voor de PoC-debiteur (bestaat de subcollectie?).
2. `maak`    — PUT Customers/{baseId}/Projects/{client-guid} met {id, Name "TEST-PROJECTPOC …"}
               → status + respons; daarna GET {adminId}/Projects/{id} en de subcollectie:
               veldvorm van het aangemaakte project (zit er een Customer-ref op?).
3. `herhaal` — exact dezelfde PUT nogmaals (zelfde GUID, zelfde body) → idempotentie-gedrag;
               daarna zelfde GUID met een GEWIJZIGDE naam → is PUT ook update?
4. `archief` — kan IsActive via PUT op false/true (archief-vlag i.p.v. verwijderen — een
               project kent geen actie 19)?

Realisme: een project kent GEEN storno — het testproject krijgt een TEST-prefix in de naam
en BLIJFT STAAN (nooit verwijderen, hard principe). `archief` zet IsActive aan het eind
terug op true zodat de teststand herkenbaar en onschadelijk is.

Waarborgen identiek aan de andere PoC's: ADMIN-PIN (login mag uitsluitend de
test-administratie zien), KILL SWITCH (verkenning/POC_STOP), TEST-namen, append-only audit
(output/projectspoc_audit.jsonl), NOOIT DELETE.

Gebruik:
    backend/.venv/bin/python verkenning/poc_projects_schrijf.py <stap>
Stappen: lees | maak | herhaal | archief | alles
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

# Zelfde PoC-namespace + debiteur als poc_verkoop_schrijf.py: die debiteur bestaat al in de
# test-administratie (verkoop-PoC 2026-08-09) — we hangen het testproject dáár onder.
_POC_NS = uuid.UUID("7f1207e6-9f6b-4c58-a6a1-53df0f56b2e1")
DEBITEUR_NAAM = "TEST-VERKOOPPOC Huurder"
DEBITEUR_ID = uuid.uuid5(_POC_NS, f"customer:{TESTADMIN_ID}:{DEBITEUR_NAAM.lower()}")

PROJECT_NAAM = "TEST-PROJECTPOC Pand Dorpsstraat 1"
PROJECT_NAAM_GEWIJZIGD = "TEST-PROJECTPOC Pand Dorpsstraat 1 (hernoemd)"
PROJECT_ID = uuid.uuid5(_POC_NS, f"project:{TESTADMIN_ID}:{PROJECT_NAAM.lower()}")

KILL_SWITCH = HIER / "POC_STOP"
OUTPUT = HIER / "output"
AUDIT_LOG = OUTPUT / "projectspoc_audit.jsonl"
STATE_FILE = OUTPUT / "projectspoc_state.json"


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


def stap_lees(c: PocClient) -> None:
    top = c.get("Projects", **{"$top": 3})
    print("— Top-level Projects (eerste 3):")
    print(json.dumps(top, indent=2, default=str)[:2000])
    sub = c.get_or_none(f"Customers/{DEBITEUR_ID}/Projects")
    print(f"— Customers/{DEBITEUR_ID}/Projects:")
    print(json.dumps(sub, indent=2, default=str)[:2000])
    _audit({"actie": "lees", "top_level_aantal": len(top.get("value", [])), "subcollectie": sub})


def _toon_project(c: PocClient, label: str) -> dict[str, Any]:
    direct = c.get_or_none(f"Projects/{PROJECT_ID}")
    print(f"— GET Projects/{PROJECT_ID} ({label}):")
    print(json.dumps(direct, indent=2, default=str)[:2000])
    sub = c.get_or_none(f"Customers/{DEBITEUR_ID}/Projects/{PROJECT_ID}")
    print(f"— GET Customers/{{baseId}}/Projects/{{id}} ({label}):")
    print(json.dumps(sub, indent=2, default=str)[:2000])
    _audit({"actie": f"toon_{label}", "top_level": direct, "subcollectie": sub})
    return direct if isinstance(direct, dict) else {}


def stap_maak(c: PocClient) -> None:
    # Controle vooraf: bestaat de PoC-debiteur (aangemaakt door de verkoop-PoC)?
    deb = c.get_or_none(f"Customers/{DEBITEUR_ID}")
    if "_fout" in deb:
        print(f"PoC-debiteur ontbreekt — eerst aanmaken: {deb['_fout']}")
        c.put(f"Customers/{DEBITEUR_ID}", {"id": str(DEBITEUR_ID), "Name": DEBITEUR_NAAM})
    status = c.put(
        f"Customers/{DEBITEUR_ID}/Projects/{PROJECT_ID}",
        {"id": str(PROJECT_ID), "Name": PROJECT_NAAM},
    )
    project = _toon_project(c, "na_maak")
    state = _state()
    state["maak"] = {"status": status, "project_id": str(PROJECT_ID), "respons_top_level": project}
    _save_state(state)


def stap_herhaal(c: PocClient) -> None:
    print("— Herhaalde PUT, zelfde GUID + zelfde body:")
    status_zelfde = c.put(
        f"Customers/{DEBITEUR_ID}/Projects/{PROJECT_ID}",
        {"id": str(PROJECT_ID), "Name": PROJECT_NAAM},
    )
    aantal = len(
        c.get("Projects", **{"$filter": "startswith(Name, 'TEST-PROJECTPOC')"}).get("value", [])
    )
    print(f"— Aantal TEST-PROJECTPOC-projecten in de top-level collectie: {aantal}")
    print("— Herhaalde PUT, zelfde GUID + GEWIJZIGDE naam:")
    status_gewijzigd = c.put(
        f"Customers/{DEBITEUR_ID}/Projects/{PROJECT_ID}",
        {"id": str(PROJECT_ID), "Name": PROJECT_NAAM_GEWIJZIGD},
    )
    project = _toon_project(c, "na_herhaal")
    # Terug naar de oorspronkelijke naam zodat de teststand deterministisch blijft.
    c.put(
        f"Customers/{DEBITEUR_ID}/Projects/{PROJECT_ID}",
        {"id": str(PROJECT_ID), "Name": PROJECT_NAAM},
    )
    state = _state()
    state["herhaal"] = {
        "status_zelfde_body": status_zelfde,
        "aantal_na_herhaal": aantal,
        "status_gewijzigde_naam": status_gewijzigd,
        "naam_na_herhaal": project.get("Name"),
    }
    _save_state(state)


def stap_archief(c: PocClient) -> None:
    print("— IsActive:false via PUT (archief-vlag i.p.v. verwijderen):")
    status_uit = c.put(
        f"Customers/{DEBITEUR_ID}/Projects/{PROJECT_ID}",
        {"id": str(PROJECT_ID), "Name": PROJECT_NAAM, "IsActive": False},
    )
    na_uit = _toon_project(c, "na_archief_uit")
    print("— IsActive:true terug (teststand herkenbaar laten staan):")
    status_aan = c.put(
        f"Customers/{DEBITEUR_ID}/Projects/{PROJECT_ID}",
        {"id": str(PROJECT_ID), "Name": PROJECT_NAAM, "IsActive": True},
    )
    na_aan = _toon_project(c, "na_archief_aan")
    state = _state()
    state["archief"] = {
        "status_uit": status_uit,
        "is_active_na_uit": na_uit.get("IsActive"),
        "status_aan": status_aan,
        "is_active_na_aan": na_aan.get("IsActive"),
    }
    _save_state(state)


STAPPEN = {"lees": stap_lees, "maak": stap_maak, "herhaal": stap_herhaal, "archief": stap_archief}


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {*STAPPEN, "alles"}:
        raise SystemExit(f"Gebruik: poc_projects_schrijf.py {{{' | '.join([*STAPPEN, 'alles'])}}}")
    c = PocClient()
    if sys.argv[1] == "alles":
        for naam, fn in STAPPEN.items():
            print(f"\n===== STAP: {naam} =====")
            fn(c)
    else:
        STAPPEN[sys.argv[1]](c)


if __name__ == "__main__":
    main()
