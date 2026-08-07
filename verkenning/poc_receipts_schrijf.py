#!/usr/bin/env python3
"""STAP 0 — "losse inkomstenboeking" via Receipts (UI-walkthrough 2026-08-07).

CONTEXT: RLZ-UI "Verkopen → Boekingen" = documenttype Receipts; de UI schrijft via
POST /api/v1/{adminId}/Receipts/actions. Rosetta-steen: concept RLZ-01-00000395
(Reference RLZ-11, € 12,10 incl., 21%, GB 8000 "Omzet 1", GEEN relatie).

Al geverifieerd (read-only, 2026-08-07):
- Er is GÉÉN Receipts/{id}-route; wel {adminId}/Receipts (collectie), Receipts/Actions
  (collectie-niveau) en Receipts/Totals. Het document zelf is via SalesInvoices/{id}
  leesbaar mét DocumentLineList/TaxSummaryList/PaymentTermList — het "Receipt" ís een
  SalesInvoice zonder Entity (Entity: null, DocumentCategory "Verkoopfactuur (Omzet)",
  DocumentBinder "Inkomsten"/invoice).
- De Receipts-COLLECTIE ziet óók API-aangemaakte SalesInvoices (getest met de
  TEST-KASPOC-vergelijkingsfactuur) — anders dan de SalesInvoices-collectie zelf
  (omzet-STAP-0-blinde-vlek).

Waarborgen (identiek aan de andere PoC's, besluit 0005): ADMIN-PIN, KILL SWITCH
(verkenning/POC_STOP), TOGGLE (subcommando), TEST-referenties, append-only audit
(output/receiptspoc_audit.jsonl), NOOIT DELETE (concepten laten staan, geboekt = actie 19).

Gebruik:
    backend/.venv/bin/python verkenning/poc_receipts_schrijf.py <stap>
Stappen: lees | maak | boek | aangifte | gemengd | betaling | storno
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
ROSETTA_ID = "ff0cddbd-b14b-4d97-897f-ad113cfb95bb"  # RLZ-01-00000395, concept, blijft staan
OMZET1_ACCOUNT_ID = "330e4771-a63a-43cc-b050-5e7b0476209c"  # 8000 Omzet 1
TAXRATE_21_ID = "1e44993a-15f6-419f-87e5-3e31ac3d9383"  # 21% NL
TAXRATE_VRIJGESTELD_ID = "4c8a31dd-d20b-4335-b4e3-9dd623589d62"  # NL, Geen BTW (Vrijgesteld)
CATEGORIE_VERKOOP_OMZET_ID = "9138fa50-d8be-4b6f-9d39-ce5bb2e67f86"  # "Verkoopfactuur (Omzet)"
DECL_ID = "1d7b1fa1-2f01-4028-a02c-34269259a8a7"  # concept-btw-aangifte vanaf 2026-07-01
KAS_ID = "211b9038-b4b5-4a3d-ae2e-5c73b3c38b3f"  # PaymentAccount Type 3 "Kas"

KILL_SWITCH = HIER / "POC_STOP"
OUTPUT = HIER / "output"
AUDIT_LOG = OUTPUT / "receiptspoc_audit.jsonl"
STATE_FILE = OUTPUT / "receiptspoc_state.json"

ACTION_BOOK = 17
ACTION_CORRECT = 19


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

    def post_raw(self, path: str, body: Any) -> Any:
        """POST met exacte status/response-registratie — voor de Receipts/Actions-experimenten.
        Geeft (status_code, response-tekst-of-json) terug, gooit NIET bij 4xx/5xx."""
        self._check_kill_switch()
        try:
            r = self.rlz.request_raw("POST", path, json=body)
            status = r.status_code
            try:
                payload: Any = r.json()
            except Exception:  # noqa: BLE001
                payload = r.text[:800]
        except RlzApiError as e:
            status = e.status_code
            payload = e.body[:800]
        _audit({"actie": "POST", "login": self._login_naam, "pad": path, "payload": body,
                "status": status, "response": payload})
        return status, payload

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

    def _snapshot(self, path: str) -> Any:
        try:
            return self.rlz.get(path)
        except RlzApiError:
            return None


def _dump(label: str, data: Any) -> None:
    print(f"\n=== {label} ===")
    print(json.dumps(data, indent=2, default=str, ensure_ascii=False))


def _document_body(doc_id: str, *, omschrijving: str, regels: list[dict[str, Any]]) -> dict[str, Any]:
    """Payload gespiegeld aan de rosetta-steen: DocumentCategory + regels, GEEN Entity."""
    return {
        "id": doc_id,
        "Description": omschrijving,
        "Date": f"{datetime.now(UTC).date().isoformat()}T00:00:00",
        "DocumentCategory": {"id": CATEGORIE_VERKOOP_OMZET_ID},
        "DocumentLineList": regels,
    }


def _regel_21(bedrag_net: float = 10.00) -> dict[str, Any]:
    return {
        "Account": {"id": OMZET1_ACCOUNT_ID},
        "TaxRate": {"id": TAXRATE_21_ID},
        "NetAmount": bedrag_net,
        "TaxAmount": round(bedrag_net * 0.21, 2),
        "Description": "TEST-RECPOC omzet 21%",
    }


# --------------------------------------------------------------------------- stappen


def stap_lees(c: PocClient) -> None:
    """Rosetta-steen volledig teruglezen (read-only): via de Receipts-collectie én via
    SalesInvoices/{id} (de enige route met regels)."""
    r = c.get("Receipts", **{"$filter": f"id eq {ROSETTA_ID}"})
    _dump("Rosetta via Receipts-collectie (kop)", r.get("value"))
    d = c.get(f"SalesInvoices/{ROSETTA_ID}", **{
        "$expand": "DocumentLineList($expand=Account,TaxRate),TaxSummaryList,PaymentTermList,DocumentCategory",
    })
    _dump("Rosetta via SalesInvoices/{id} (volledig)", d)


def stap_maak(c: PocClient) -> None:
    """Schrijfvorm vinden: POST Receipts/Actions in de plausibele vormen, exact rapporteren.
    Fallback (óók documenteren): PUT SalesInvoices/{client-guid} ZONDER Entity."""
    state = _state()

    # Vorm A: het document zelf als action-body.
    doc_a = str(uuid.uuid4())
    body_a = _document_body(doc_a, omschrijving="TEST-RECPOC vorm A (document als body)",
                            regels=[_regel_21()])
    status, resp = c.post_raw("Receipts/Actions", body_a)
    _dump(f"Vorm A — POST Receipts/Actions met document-body → HTTP {status}", resp)
    if status < 300:
        state["vorm_a_id"] = doc_a

    # Vorm B: {Type: n, ...} — action-envelop (n=1 als gok voor 'create/save').
    doc_b = str(uuid.uuid4())
    body_b = {"Type": 1, **_document_body(doc_b, omschrijving="TEST-RECPOC vorm B (Type-envelop)",
                                          regels=[_regel_21()])}
    status, resp = c.post_raw("Receipts/Actions", body_b)
    _dump(f"Vorm B — POST Receipts/Actions met Type-envelop → HTTP {status}", resp)
    if status < 300:
        state["vorm_b_id"] = doc_b

    # Vorm C (fallback + eigen natuurlijke mechaniek): PUT SalesInvoices ZONDER Entity.
    doc_c = state.get("vorm_c_id") or str(uuid.uuid4())
    try:
        nieuw = c.put(f"SalesInvoices/{doc_c}", _document_body(
            doc_c, omschrijving="TEST-RECPOC vorm C (PUT SalesInvoices zonder Entity)",
            regels=[_regel_21()]))
        _dump("Vorm C — PUT SalesInvoices/{guid} zonder Entity", {
            k: (nieuw or {}).get(k) for k in ("id", "Status", "Reference", "InvoiceNumber",
                                              "ReceiptNumber", "BaseInvoiceAmount", "Entity")})
        state["vorm_c_id"] = doc_c
    except RlzApiError as e:
        print(f"\nVorm C geweigerd: {e.status_code}: {e.body[:300]}")

    _save_state(state)


def stap_boek(c: PocClient) -> None:
    """Boeken van het gelukte concept (actie 17 op SalesInvoices/{id} — de UI-Boek loopt via
    Receipts/actions maar per document bestaat alleen de SalesInvoices-route). Status vóór/ná;
    bekende nummer-botsing documenteren + herstel-pad."""
    state = _state()
    doc = state.get("vorm_a_id") or state.get("vorm_b_id") or state.get("vorm_c_id")
    if not doc:
        raise SystemExit("Geen gelukt concept in state — eerst `maak`.")
    voor = c.get(f"SalesInvoices/{doc}")
    _dump("Vóór boeken", {k: voor.get(k) for k in ("id", "Status", "Reference", "InvoiceNumber",
                                                   "ReceiptNumber")})
    try:
        na = c.actie(f"SalesInvoices/{doc}", ACTION_BOOK)
    except RlzApiError as e:
        print(f"\nBoeken geweigerd: {e.status_code}: {e.body[:300]}")
        if "factuurnummer" in e.body.lower():
            # Bekende botsing (omzet-STAP-0): RLZ's volgende InvoiceNumber botst met een
            # bestaand nummer → expliciet vrij nummer zetten en opnieuw (deterministisch herstel).
            hoogste = c.get("Receipts", **{"$orderby": "InvoiceNumber desc", "$top": "1"})
            vrij = int(hoogste["value"][0]["InvoiceNumber"]) + 1
            print(f"Herstel-pad: InvoiceNumber expliciet op {vrij} en opnieuw boeken.")
            c.put(f"SalesInvoices/{doc}", {"id": doc, "InvoiceNumber": vrij})
            na = c.actie(f"SalesInvoices/{doc}", ACTION_BOOK)
        else:
            raise
    _dump("Ná boeken", {k: (na or {}).get(k) for k in ("id", "Status", "Reference",
                                                       "InvoiceNumber", "ReceiptNumber",
                                                       "BaseInvoiceAmount", "BaseRemainingAmount")})
    state["geboekt_id"] = doc
    _save_state(state)


def stap_aangifte(c: PocClient, label: str = "nu") -> None:
    """TaxSources van de concept-aangifte (beslissende check, zelfde meting als de kas-PoC)."""
    bronnen = c.get(f"TaxDeclarations/{DECL_ID}/TaxSources")
    _dump(f"TaxSources ({label})", bronnen)


def stap_gemengd(c: PocClient) -> None:
    """BLOW-case: vrijgestelde regel + 21%-regel in één Receipt-boeking (multi-regel is bij
    SalesInvoices wél bewezen, anders dan bij BankMutationDirectBookings)."""
    state = _state()
    doc = state.get("gemengd_id") or str(uuid.uuid4())
    regels = [
        {
            "Account": {"id": OMZET1_ACCOUNT_ID},
            "TaxRate": {"id": TAXRATE_VRIJGESTELD_ID},
            "NetAmount": 50.00,
            "TaxAmount": 0.00,
            "Description": "TEST-RECPOC vrijgestelde categorie",
        },
        _regel_21(100.00),
    ]
    nieuw = c.put(f"SalesInvoices/{doc}", _document_body(
        doc, omschrijving="TEST-RECPOC gemengd (vrijgesteld + 21%)", regels=regels))
    _dump("Gemengd concept na PUT", {k: (nieuw or {}).get(k) for k in (
        "id", "Status", "BaseInvoiceAmount", "InvoiceNumber", "ReceiptNumber")})
    state["gemengd_id"] = doc
    _save_state(state)
    d = c.get(f"SalesInvoices/{doc}", **{"$expand": "DocumentLineList($expand=TaxRate),TaxSummaryList"})
    _dump("Gemengd regels + TaxSummary", {"DocumentLineList": d.get("DocumentLineList"),
                                          "TaxSummaryList": d.get("TaxSummaryList")})
    geboekt = c.actie(f"SalesInvoices/{doc}", ACTION_BOOK)
    _dump("Gemengd ná boeken", {k: (geboekt or {}).get(k) for k in (
        "id", "Status", "BaseInvoiceAmount", "InvoiceNumber", "ReceiptNumber")})


def stap_betaling(c: PocClient) -> None:
    """Betaling-veld: kan de boeking bij aanmaak direct aan de KAS gekoppeld worden?
    Experimenten met PaymentAccount/QuickPaymentSelection-achtige velden in de payload."""
    state = _state()
    doc = str(uuid.uuid4())
    body = _document_body(doc, omschrijving="TEST-RECPOC betaling-kas-experiment",
                          regels=[_regel_21(20.00)])
    body["PaymentAccount"] = {"id": KAS_ID}
    try:
        nieuw = c.put(f"SalesInvoices/{doc}", body)
        _dump("Concept met PaymentAccount=Kas in payload", {k: (nieuw or {}).get(k) for k in (
            "id", "Status", "BaseInvoiceAmount")})
        state["betaling_id"] = doc
        _save_state(state)
        d = c.get(f"SalesInvoices/{doc}", **{"$expand": "PaymentTermList"})
        _dump("PaymentTermList na PUT (is er een kas-koppeling?)", d.get("PaymentTermList"))
    except RlzApiError as e:
        print(f"\nPUT met PaymentAccount geweigerd: {e.status_code}: {e.body[:300]}")


def stap_storno(c: PocClient) -> None:
    """Definitief geboekte testdocumenten storneren (actie 19); concepten laten staan."""
    state = _state()
    for sleutel in ("geboekt_id", "gemengd_id", "betaling_id"):
        doc = state.get(sleutel)
        if not doc:
            continue
        try:
            d = c.get(f"SalesInvoices/{doc}")
        except RlzApiError as e:
            print(f"{sleutel}: {e.status_code}")
            continue
        if d.get("Status") == 1:
            print(f"{sleutel} ({doc}): concept — blijft staan (opdracht).")
            continue
        nieuw = c.actie(f"SalesInvoices/{doc}", ACTION_CORRECT)
        _dump(f"{sleutel} na actie 19 (verwacht Status 1)", {
            k: (nieuw or {}).get(k) for k in ("id", "Status", "InvoiceNumber")})
    stap_aangifte(c, "na storno")


STAPPEN = {
    "lees": stap_lees,
    "maak": stap_maak,
    "boek": stap_boek,
    "aangifte": stap_aangifte,
    "gemengd": stap_gemengd,
    "betaling": stap_betaling,
    "storno": stap_storno,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in STAPPEN:
        raise SystemExit(f"Gebruik: poc_receipts_schrijf.py <{'|'.join(STAPPEN)}> [args]")
    client = PocClient()
    STAPPEN[sys.argv[1]](client, *sys.argv[2:])


if __name__ == "__main__":
    main()
