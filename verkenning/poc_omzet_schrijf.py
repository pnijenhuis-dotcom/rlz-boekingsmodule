#!/usr/bin/env python3
"""Omzetboekingen STAP 0 — write-path-PoC (fase 2), uitsluitend tegen de RLZ-test-administratie.

Te verifiëren vóór de bouw van de omzetmodule (grote opdracht 2026-08-07):
1. SalesInvoice: PUT met client-GUID + Entity (debiteur) + DocumentLineList → /Uploads (PDF-
   bijlage) → actie 17 (boeken). Welke velden zijn verplicht, wat is de status na boeken,
   komt ReceiptNumber terug?
2. ManualJournal: PUT met JournalEntryDiary + regels (CreditOrDebit/DebitAmount/CreditAmount),
   saldo 0 → /Uploads → actie 17. (PoC 2 van 2 juli bewees dit tegen BLOW; hier her-verifiëren
   tegen de test-administratie mét bijlage, want het dagboek-GUID is per administratie.)
3. Saldo≠0-gedrag: wat doet RLZ met een niet-sluitend memoriaal (PUT autoCorrect=false, daarna
   actie 17)? → bepaalt of onze harde check memoriaal-saldo-0 de enige poort is of een
   dubbele waarborg.
4. Systeemdebiteur "Kasomzet": bestaat die per administratie, en zo niet — kan hij via
   PUT Customers/{client-guid} aangemaakt worden (zelfde vorm als crediteur-aanmaken)?
5. Storneren: actie 19 op beide documenten → Status 1, geen apart creditdocument (bekend
   gedrag, hier bevestigen voor SalesInvoice + ManualJournal).

"Als één transactie boeken" hoeft niet geverifieerd: RLZ kent geen cross-call-atomiciteit
(elke PUT/actie is een losse HTTP-call) — de één-transactie-garantie is per definitie ónze
verantwoordelijkheid (idempotente GUID's + half-geboekt-failsafe in de app).

Waarborgen (identiek aan poc_bank_schrijf.py, besluit 0005 + kernprincipes):
- ADMIN-PIN: weigert te starten als de login iets anders ziet dan de test-administratie.
- KILL SWITCH: bestaat `verkenning/POC_STOP`, dan weigert elke schrijfactie.
- TOGGLE: draait alleen met een expliciet subcommando.
- TEST-referenties: alles herkenbaar aan `TEST-OMZETPOC-`.
- AUDIT: append-only JSONL per actie (output/omzetpoc_audit.jsonl).
- NOOIT DELETE: opruimen = actie 19 (storneren); de testdebiteur blijft bewust staan.

Gebruik:
    backend/.venv/bin/python verkenning/poc_omzet_schrijf.py <stap>
Stappen: verken | klant | verkoop | memoriaal | saldo | storno | alles
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

# Platform/registers/entiteiten.md — RLZ-test-administratie "Administratiekantoor Nijenhuis".
TESTADMIN_ID = "8dbfb856-d75b-4ec3-9124-c8b739fe3bc5"
# Vaste testrekeningen (zelfde als tests/integration + poc_bank_schrijf.py):
# 4699 Diverse algemene kosten / 21% NL.
TEST_KOSTEN_ACCOUNT_ID = "79b6f64a-dad9-4683-9e47-9c182ebae1c1"
TEST_TAXRATE_21_ID = "1e44993a-15f6-419f-87e5-3e31ac3d9383"

KILL_SWITCH = HIER / "POC_STOP"
OUTPUT = HIER / "output"
AUDIT_LOG = OUTPUT / "omzetpoc_audit.jsonl"
STATE_FILE = OUTPUT / "omzetpoc_state.json"

ACTION_BOOK = 17
ACTION_CORRECT = 19

# Minimale geldige PDF (één lege pagina) — genoeg om het /Uploads-mechanisme te verifiëren.
MINI_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000052 00000 n \n"
    b"0000000101 00000 n \ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n164\n%%EOF\n"
)


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

    def put(self, path: str, body: dict[str, Any], *, params: dict[str, Any] | None = None) -> Any:
        self._check_kill_switch()
        oud = self._snapshot(path)
        try:
            r = self.rlz.put(path, body, params=params)
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

    def actie(self, doc_pad: str, actie_type: int, **extra: Any) -> Any:
        self._check_kill_switch()
        oud = self._snapshot(doc_pad)
        try:
            r = self.rlz.post_action(doc_pad, actie_type, **extra)
            status: Any = r.status_code
        except RlzApiError as e:
            status = f"{e.status_code}: {e.body[:300]}"
            _audit({"actie": f"POST Actions {actie_type}", "login": self._login_naam,
                    "pad": doc_pad, "extra_body": extra, "status": status, "oud": oud})
            raise
        nieuw = self._snapshot(doc_pad)
        _audit({"actie": f"POST Actions {actie_type}", "login": self._login_naam, "pad": doc_pad,
                "extra_body": extra, "status": status, "oud": oud, "nieuw": nieuw})
        return nieuw

    def upload(self, entity_pad: str, entity_id: str, *, upload_id: str, filename: str) -> Any:
        self._check_kill_switch()
        import base64

        try:
            r = self.rlz.upload_bijlage(
                entity_pad, uuid.UUID(entity_id), upload_id=uuid.UUID(upload_id),
                filename=filename, content_base64=base64.b64encode(MINI_PDF).decode(),
            )
            status: Any = r.status_code
        except RlzApiError as e:
            status = f"{e.status_code}: {e.body[:300]}"
            _audit({"actie": "PUT Uploads", "login": self._login_naam,
                    "pad": f"{entity_pad}/{entity_id}", "status": status})
            raise
        _audit({"actie": "PUT Uploads", "login": self._login_naam,
                "pad": f"{entity_pad}/{entity_id}", "upload_id": upload_id, "status": status})
        return status

    def _snapshot(self, path: str) -> Any:
        try:
            return self.rlz.get(path)
        except RlzApiError:
            return None


def _dump(label: str, data: Any) -> None:
    print(f"\n=== {label} ===")
    print(json.dumps(data, indent=2, default=str, ensure_ascii=False))


# --------------------------------------------------------------------------- stappen


def stap_verken(c: PocClient) -> None:
    """Read-only: dagboeken, bestaande Kasomzet-debiteur, omzet-GB's, btw-tarieven."""
    state = _state()

    diaries = c.get("JournalEntryDiaries")["value"]
    _dump("JournalEntryDiaries", [
        {k: d.get(k) for k in ("id", "Description", "Type", "IsSystemDiary")} for d in diaries
    ])
    memoriaal = [d for d in diaries if "memoriaal" in (d.get("Description") or "").lower()]
    if memoriaal:
        state["diary_id"] = memoriaal[0]["id"]
        print(f"\nGekozen memoriaal-dagboek: {memoriaal[0]['Description']} ({memoriaal[0]['id']})")

    kasomzet = c.get("Customers", **{"$filter": "contains(Name,'asomzet')"})["value"]
    _dump("Customers met 'asomzet' in de naam", [
        {k: k_.get(k) for k in ("id", "Name", "SearchName")} for k_ in kasomzet
    ])

    omzet = c.get("Ledgers", search="omzet")["value"]
    _dump("Ledgers ?search=omzet", [
        {k: le.get(k) for k in ("id", "AccountCode", "Description", "Type")} for le in omzet[:15]
    ])
    if omzet:
        state["omzet_account_id"] = omzet[0]["id"]
        state["omzet_account_naam"] = f"{omzet[0].get('AccountCode')} {omzet[0].get('Description')}"

    voorraad = c.get("Ledgers", search="voorraad")["value"]
    _dump("Ledgers ?search=voorraad", [
        {k: le.get(k) for k in ("id", "AccountCode", "Description", "Type")} for le in voorraad[:15]
    ])
    if voorraad:
        state["voorraad_account_id"] = voorraad[0]["id"]
        state["voorraad_account_naam"] = (
            f"{voorraad[0].get('AccountCode')} {voorraad[0].get('Description')}"
        )

    taxrates = c.get("TaxRates")["value"]
    _dump("TaxRates (eerste 20)", [
        {k: t.get(k) for k in ("id", "Description", "Percentage", "TaxRateType")} for t in taxrates[:20]
    ])
    _save_state(state)
    print(f"\nState opgeslagen: {STATE_FILE}")


def stap_klant(c: PocClient) -> None:
    """Systeemdebiteur-aanmaak verifiëren: PUT Customers/{client-guid} met minimale payload —
    zelfde vorm als crediteur-aanmaken (Vendors). Deterministische her-run raakt dezelfde rij."""
    state = _state()
    klant_id = state.get("klant_id") or str(uuid.uuid4())
    nieuw = c.put(f"Customers/{klant_id}", {"id": klant_id, "Name": "TEST-OMZETPOC Kasomzet"})
    _dump("Customer na PUT", nieuw)
    state["klant_id"] = klant_id
    _save_state(state)


def stap_verkoop(c: PocClient) -> None:
    """SalesInvoice: PUT + bijlage + actie 17. Regel op een omzet-GB, 21% NL (vrijgesteld-tarief
    is administratie-specifiek — mapping is per administratie, hier verifiëren we het mechanisme)."""
    state = _state()
    if "klant_id" not in state:
        raise SystemExit("Eerst `klant` draaien.")
    account = state.get("omzet_account_id") or TEST_KOSTEN_ACCOUNT_ID
    invoice_id = state.get("verkoop_id") or str(uuid.uuid4())
    body = {
        "id": invoice_id,
        "Entity": {"id": state["klant_id"]},
        "Reference": "TEST-OMZETPOC-SI1",
        "Date": f"{datetime.now(UTC).date().isoformat()}T00:00:00",
        "DocumentLineList": [
            {
                "Account": {"id": account},
                "TaxRate": {"id": TEST_TAXRATE_21_ID},
                "NetAmount": 100.00,
                "TaxAmount": 21.00,
                "Description": "TEST omzet categorie A",
            },
            {
                "Account": {"id": account},
                "TaxRate": {"id": TEST_TAXRATE_21_ID},
                "NetAmount": 50.00,
                "TaxAmount": 10.50,
                "Description": "TEST omzet categorie B",
            },
        ],
    }
    nieuw = c.put(f"SalesInvoices/{invoice_id}", body)
    _dump("SalesInvoice na PUT (verwacht Status 1 + ReceiptNumber)", {
        k: (nieuw or {}).get(k)
        for k in ("id", "Status", "Reference", "ReceiptNumber", "BaseInvoiceAmount", "Date")
    })
    state["verkoop_id"] = invoice_id
    _save_state(state)

    upload_id = str(uuid.uuid4())
    upload_status = c.upload("SalesInvoices", invoice_id, upload_id=upload_id, filename="TEST-omzetpoc.pdf")
    print(f"\nUpload bijlage op SalesInvoice: HTTP {upload_status}")

    geboekt = c.actie(f"SalesInvoices/{invoice_id}", ACTION_BOOK)
    _dump("SalesInvoice na actie 17 (verwacht Status 2)", {
        k: (geboekt or {}).get(k)
        for k in ("id", "Status", "Reference", "ReceiptNumber", "BaseInvoiceAmount",
                  "BaseRemainingAmount")
    })


def stap_memoriaal(c: PocClient) -> None:
    """ManualJournal: PUT (JournalEntryDiary + CreditOrDebit-regels, saldo 0) + bijlage +
    actie 17 — her-verificatie van PoC 2 tegen de test-administratie, nu mét /Uploads."""
    state = _state()
    if "diary_id" not in state:
        raise SystemExit("Eerst `verken` draaien (dagboek-id).")
    debet_account = TEST_KOSTEN_ACCOUNT_ID
    credit_account = state.get("voorraad_account_id") or state.get("omzet_account_id")
    if not credit_account:
        raise SystemExit("Geen credit-tegenrekening in state — eerst `verken` draaien.")

    journal_id = state.get("memoriaal_id") or str(uuid.uuid4())
    body = {
        "id": journal_id,
        "JournalEntryDiary": {"id": state["diary_id"]},
        "Reference": "TEST-OMZETPOC-MEM1",
        "Date": f"{datetime.now(UTC).date().isoformat()}T00:00:00",
        "DocumentLineList": [
            {
                "Account": {"id": debet_account},
                "CreditOrDebit": 1,
                "DebitAmount": 75.00,
                "Description": "TEST kostprijs groep A",
            },
            {
                "Account": {"id": credit_account},
                "CreditOrDebit": 2,
                "CreditAmount": 75.00,
                "Description": "TEST aan voorraad",
            },
        ],
    }
    nieuw = c.put(f"ManualJournals/{journal_id}", body, params={"autoCorrect": "false"})
    _dump("ManualJournal na PUT (verwacht BalanceAmount 0, Status 1)", {
        k: (nieuw or {}).get(k)
        for k in ("id", "Status", "Reference", "ReceiptNumber", "BalanceAmount", "Date")
    })
    state["memoriaal_id"] = journal_id
    _save_state(state)

    upload_id = str(uuid.uuid4())
    upload_status = c.upload("ManualJournals", journal_id, upload_id=upload_id, filename="TEST-omzetpoc.pdf")
    print(f"\nUpload bijlage op ManualJournal: HTTP {upload_status}")

    geboekt = c.actie(f"ManualJournals/{journal_id}", ACTION_BOOK)
    _dump("ManualJournal na actie 17 (verwacht Status 3 — saldo 0, niets open)", {
        k: (geboekt or {}).get(k) for k in ("id", "Status", "Reference", "ReceiptNumber", "BalanceAmount")
    })


def stap_saldo(c: PocClient) -> None:
    """Saldo≠0-experiment: accepteert RLZ een niet-sluitend memoriaal (PUT autoCorrect=false)?
    En zo ja — weigert actie 17 dan? Bepaalt of onze memoriaal-saldo-0-check de enige poort is."""
    state = _state()
    if "diary_id" not in state:
        raise SystemExit("Eerst `verken` draaien (dagboek-id).")
    journal_id = state.get("saldo_id") or str(uuid.uuid4())
    body = {
        "id": journal_id,
        "JournalEntryDiary": {"id": state["diary_id"]},
        "Reference": "TEST-OMZETPOC-SALDO",
        "Date": f"{datetime.now(UTC).date().isoformat()}T00:00:00",
        "DocumentLineList": [
            {
                "Account": {"id": TEST_KOSTEN_ACCOUNT_ID},
                "CreditOrDebit": 1,
                "DebitAmount": 10.00,
                "Description": "TEST saldo-experiment debet 10",
            },
            {
                "Account": {"id": state.get("voorraad_account_id") or state.get("omzet_account_id")},
                "CreditOrDebit": 2,
                "CreditAmount": 7.00,
                "Description": "TEST saldo-experiment credit 7",
            },
        ],
    }
    try:
        nieuw = c.put(f"ManualJournals/{journal_id}", body, params={"autoCorrect": "false"})
        _dump("Niet-sluitend memoriaal na PUT (BalanceAmount verwacht 3.00)", {
            k: (nieuw or {}).get(k) for k in ("id", "Status", "BalanceAmount", "Reference")
        })
        state["saldo_id"] = journal_id
        _save_state(state)
    except RlzApiError as e:
        print(f"\nPUT niet-sluitend memoriaal geweigerd: {e.status_code}: {e.body[:300]}")
        return
    try:
        geboekt = c.actie(f"ManualJournals/{journal_id}", ACTION_BOOK)
        _dump("Niet-sluitend memoriaal na actie 17 (⚠️ als dit lukt is onze check de enige poort)", {
            k: (geboekt or {}).get(k) for k in ("id", "Status", "BalanceAmount")
        })
    except RlzApiError as e:
        print(f"\nActie 17 op niet-sluitend memoriaal geweigerd: {e.status_code}: {e.body[:300]}")


def stap_storno(c: PocClient) -> None:
    """Opruimen conform besluit 0005: actie 19 op alles wat geboekt is (nooit delete)."""
    state = _state()
    for label, pad_prefix, sleutel in (
        ("SalesInvoice", "SalesInvoices", "verkoop_id"),
        ("ManualJournal", "ManualJournals", "memoriaal_id"),
        ("Saldo-experiment", "ManualJournals", "saldo_id"),
    ):
        doc_id = state.get(sleutel)
        if not doc_id:
            continue
        huidig = c.get(f"{pad_prefix}/{doc_id}")
        if huidig.get("Status") == 1:
            print(f"{label} {doc_id} staat al op concept (Status 1) — geen storno nodig.")
            continue
        try:
            nieuw = c.actie(f"{pad_prefix}/{doc_id}", ACTION_CORRECT)
            _dump(f"{label} na actie 19 (verwacht Status 1)", {
                k: (nieuw or {}).get(k) for k in ("id", "Status", "Reference")
            })
        except RlzApiError as e:
            print(f"⚠️ Storno {label} {doc_id} faalde: {e.status_code}: {e.body[:300]}")


STAPPEN = {
    "verken": stap_verken,
    "klant": stap_klant,
    "verkoop": stap_verkoop,
    "memoriaal": stap_memoriaal,
    "saldo": stap_saldo,
    "storno": stap_storno,
}


def main() -> None:
    if len(sys.argv) < 2 or (sys.argv[1] not in STAPPEN and sys.argv[1] != "alles"):
        raise SystemExit(f"Gebruik: poc_omzet_schrijf.py <{'|'.join(STAPPEN)}|alles>")
    c = PocClient()
    if sys.argv[1] == "alles":
        for naam in ("verken", "klant", "verkoop", "memoriaal", "saldo", "storno"):
            print(f"\n########## STAP: {naam} ##########")
            STAPPEN[naam](c)
    else:
        STAPPEN[sys.argv[1]](c)


if __name__ == "__main__":
    main()
