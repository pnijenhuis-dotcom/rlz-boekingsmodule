#!/usr/bin/env python3
"""STAP 0 — Uploads-semantiek bij een herstart-boekcyclus (2026-08-16).

Aanleiding: kliktest 2 van TEST-ONB-KLIKTEST-01 faalde per doelentiteit op
`PUT SalesInvoices/{id}/Uploads/{upload_id}` → 404 `_NotFound`. Het document zelf was net
via her-PUT op het deterministische GUID herschapen (Peter had de storno-concepten in de
RLZ-UI verwijderd); het deterministische upload-GUID was in cyclus 1 al verbruikt. De
aanname in `app/documenten/rlz_ids.py::rlz_upload_id` ("een retry ... overschrijft (PUT)
dezelfde") is daarmee in het geding — maar het productie-geval bewijst alleen het
verwijderd-document-pad. Deze PoC beslist de rest van de semantiek op de TEST-administratie,
op het bestaande TEST-HERPUT-01-concept (PurchaseInvoice; het /Uploads-mechanisme is per
api-verkenning identiek voor SalesInvoices en ManualJournals):

1. `GET .../Uploads` op een concept — is de leesroute bruikbaar als aanwezigheids-check?
2. upload GUID-A (vers) → verwacht 204;
3. HER-PUT van GUID-A (zelfde body) — overschrijft RLZ, of 404 (zoals productie deed op een
   verbruikt GUID)?
4. upload GUID-B (vers, naast A) → tweede bijlage of fout?
5. boek (17) → storno (19) → her-PUT document — overleeft de bijlage storno én her-PUT?
   (Bepaalt of de skip-op-aanwezigheid in de motor volstaat voor het spiegel-herstartpad.)

Einde = concept mét bijlagen, conform testdata-afspraak (nooit verwijderen). Waarborgen
identiek aan de andere PoC's: ADMIN-PIN, KILL SWITCH (verkenning/POC_STOP), audit-log
(output/uploadpoc_audit.jsonl), NOOIT DELETE.

Gebruik:
    backend/.venv/bin/python verkenning/poc_upload_herstart.py
"""

from __future__ import annotations

import base64
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
HERPUT_REFERENTIE = "TEST-HERPUT-01"
_POC_NS = uuid.UUID("b1a6c9de-4f02-47d3-9b7a-2e8f0c5d1a44")  # zelfde PoC-namespace
HERPUT_ID = uuid.uuid5(_POC_NS, f"herput:{HERPUT_REFERENTIE}")
UPLOAD_A = uuid.uuid5(_POC_NS, "uploadpoc:A")
UPLOAD_B = uuid.uuid5(_POC_NS, "uploadpoc:B")
TAXRATE_21_ID = "1e44993a-15f6-419f-87e5-3e31ac3d9383"

KILL_SWITCH = HIER / "POC_STOP"
OUTPUT = HIER / "output"
AUDIT_LOG = OUTPUT / "uploadpoc_audit.jsonl"

ACTION_BOOK = 17
ACTION_CORRECT = 19

# minimale geldige PDF (één lege pagina) — alleen voor de bijlage-mechaniek
_MINI_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f \ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF\n"
)


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

    def put(self, path: str, body: dict[str, Any]) -> str:
        self._check_kill_switch()
        try:
            r = self.rlz.put(path, body)
            status = str(r.status_code)
        except RlzApiError as e:
            status = f"{e.status_code}: {e.body[:300]}"
        _audit(
            {
                "actie": "PUT",
                "login": self._login_naam,
                "pad": path,
                "payload": {k: (v if k != "Content" else f"<{len(v)} b64>") for k, v in body.items()},
                "status": status,
            }
        )
        return status

    def actie(self, doc_pad: str, actie_type: int) -> Any:
        self._check_kill_switch()
        r = self.rlz.post_action(doc_pad, actie_type)
        nieuw = self.get(doc_pad)
        _audit(
            {
                "actie": f"POST Actions {actie_type}",
                "login": self._login_naam,
                "pad": doc_pad,
                "status": r.status_code,
                "nieuw_status": nieuw.get("Status"),
            }
        )
        return nieuw


def _uploads(c: PocClient) -> list[dict[str, Any]]:
    r = c.get(f"PurchaseInvoices/{HERPUT_ID}/Uploads")
    return r.get("value", []) if isinstance(r, dict) else r


def _print_uploads(c: PocClient, label: str) -> list[dict[str, Any]]:
    rijen = _uploads(c)
    print(f"   [{label}] Uploads: {len(rijen)}")
    for rij in rijen:
        print(f"      id={rij.get('id')} FileName={rij.get('FileName')} CreateDate={rij.get('CreateDate')}")
    return rijen


def _upload_body(upload_id: uuid.UUID, naam: str) -> dict[str, Any]:
    return {"id": str(upload_id), "FileName": naam, "Content": base64.b64encode(_MINI_PDF).decode()}


def main() -> None:
    alleen_herput = "--alleen-herput" in sys.argv
    c = PocClient()
    doc = c.get(f"PurchaseInvoices/{HERPUT_ID}")
    print(f"== TEST-HERPUT-01 ({HERPUT_ID}) Status={doc.get('Status')} (verwacht 1 = concept)")
    if doc.get("Status") != 1:
        raise SystemExit("Uitgangspunt klopt niet (geen concept) — stop.")

    if not alleen_herput:
        print("1) leesroute op concept")
        _print_uploads(c, "start")

        print(f"2) upload GUID-A vers ({UPLOAD_A})")
        s = c.put(f"PurchaseInvoices/{HERPUT_ID}/Uploads/{UPLOAD_A}", _upload_body(UPLOAD_A, "poc-upload-a.pdf"))
        print(f"   PUT -> {s}")
        _print_uploads(c, "na A")

        print("3) HER-PUT GUID-A (zelfde GUID, zelfde body) — overschrijven of 404?")
        s = c.put(f"PurchaseInvoices/{HERPUT_ID}/Uploads/{UPLOAD_A}", _upload_body(UPLOAD_A, "poc-upload-a2.pdf"))
        print(f"   PUT -> {s}")
        _print_uploads(c, "na her-PUT A")

        print(f"4) upload GUID-B vers naast A ({UPLOAD_B})")
        s = c.put(f"PurchaseInvoices/{HERPUT_ID}/Uploads/{UPLOAD_B}", _upload_body(UPLOAD_B, "poc-upload-b.pdf"))
        print(f"   PUT -> {s}")
        _print_uploads(c, "na B")

        print("5) boek (17) → storno (19) → her-PUT document → overleeft de bijlage?")
        c.actie(f"PurchaseInvoices/{HERPUT_ID}", ACTION_BOOK)
        _print_uploads(c, "na boek 17")
        c.actie(f"PurchaseInvoices/{HERPUT_ID}", ACTION_CORRECT)
        _print_uploads(c, "na storno 19")
    else:
        print("(--alleen-herput: stappen 1–4 en boek/storno overgeslagen — al gedraaid)")
    regels = c.get(f"PurchaseInvoices/{HERPUT_ID}/Lines", **{"$expand": "Account,TaxRate"}).get("value", [])
    if not regels:
        raise SystemExit("Geen regels op het concept — her-PUT-stap overgeslagen.")
    body = {
        "id": str(HERPUT_ID),
        "Entity": {"id": doc.get("Entity", {}).get("id")} if doc.get("Entity") else None,
        "DocumentLineList": [
            {
                "Account": {"id": r["Account"]["id"] if isinstance(r.get("Account"), dict) else r["Account"]},
                "TaxRate": {"id": TAXRATE_21_ID},
                "NetAmount": r.get("NetAmount"),
                "TaxAmount": r.get("TaxAmount"),
                "Description": r.get("Description"),
            }
            for r in regels
        ],
        "Reference": HERPUT_REFERENTIE,
        "Date": f"{datetime.now(UTC).date().isoformat()}T00:00:00",
    }
    if body["Entity"] is None:
        # Entity zit mogelijk alleen achter $expand — haal 'm expliciet op
        doc2 = c.get(f"PurchaseInvoices/{HERPUT_ID}", **{"$expand": "Entity"})
        body["Entity"] = {"id": doc2["Entity"]["id"]}
    s = c.put(f"PurchaseInvoices/{HERPUT_ID}", body)
    print(f"   her-PUT document -> {s}")
    _print_uploads(c, "na her-PUT document")
    print("Einde: concept blijft staan (testdata-afspraak — nooit verwijderen).")


if __name__ == "__main__":
    main()
