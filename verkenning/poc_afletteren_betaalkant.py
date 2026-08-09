#!/usr/bin/env python3
"""STAP-0 PoC: afletteren via de BETAAL-kant — POST PaymentTransactions/{id}/Actions.

Aanleiding: UI-walkthrough 2026-08-08 (api-verkenning.md "Afletteren via de betaal-kant"):
de RLZ-UI lettert een matchsuggestie af via POST /api/v1/{adminId}/PaymentTransactions/
{txId}/actions → 204. De exacte action-body is onbekend (interceptor geblokkeerd). De
schrijf-PoC van 2026-08-02 kreeg op deze route met {Type: 15/16} altijd 400 _InvalidData —
de hypothese is dus een ánder Type-nummer of een andere body-vorm.

Verifiëren, niet bouwen. Uitsluitend tegen de RLZ-test-administratie; alles herkenbaar aan
TEST-referenties; terugdraaien = actie 16 (unlink) of actie 19 (Correct) — nooit DELETE.

Waarborgen (identiek aan poc_bank_schrijf.py):
- ADMIN-PIN: weigert te starten als de login iets anders ziet dan de test-administratie.
- KILL SWITCH: bestand verkenning/POC_STOP aanwezig → elke schrijfactie geweigerd.
- TOGGLE: draait alleen met expliciet subcommando.
- AUDIT: append-only JSONL per actie in output/afletterpoc_audit.jsonl.
- STOP-BIJ-SUCCES: de probe stopt zodra één poging OpenAmount naar 0 brengt.

Gebruik:
    backend/.venv/bin/python verkenning/poc_afletteren_betaalkant.py <stap> [args]
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
TEST_ACCOUNT_ID = "79b6f64a-dad9-4683-9e47-9c182ebae1c1"  # 4699 Diverse algemene kosten
TEST_TAXRATE_ID = "1e44993a-15f6-419f-87e5-3e31ac3d9383"  # 21% NL

KILL_SWITCH = HIER / "POC_STOP"
OUTPUT = HIER / "output"
AUDIT_LOG = OUTPUT / "afletterpoc_audit.jsonl"
STATE_FILE = OUTPUT / "afletterpoc_state.json"
BANKPOC_STATE = OUTPUT / "bankpoc_state.json"

ACTION_BOOK = 17
ACTION_CORRECT = 19

TX_EXPAND = "MatchedPaymentItem,PaymentReferenceList($expand=Document)"


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


def _dump(label: str, data: Any) -> None:
    print(f"\n=== {label} ===")
    print(json.dumps(data, indent=2, default=str, ensure_ascii=False))


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

    def put(self, path: str, body: dict[str, Any]) -> Any:
        self._check_kill_switch()
        try:
            r = self.rlz.put(path, body)
            status: Any = r.status_code
        except RlzApiError as e:
            status = f"{e.status_code}: {e.body[:300]}"
            _audit({"actie": "PUT", "login": self._login_naam, "pad": path,
                    "payload": body, "status": status})
            raise
        _audit({"actie": "PUT", "login": self._login_naam, "pad": path,
                "payload": body, "status": status})
        return self.rlz.get(path)

    def actie(self, doc_pad: str, actie_type: int, **extra: Any) -> Any:
        self._check_kill_switch()
        try:
            r = self.rlz.post_action(doc_pad, actie_type, **extra)
            status: Any = r.status_code
        except RlzApiError as e:
            status = f"{e.status_code}: {e.body[:300]}"
            _audit({"actie": f"POST Actions {actie_type}", "login": self._login_naam,
                    "pad": doc_pad, "extra_body": extra, "status": status})
            raise
        _audit({"actie": f"POST Actions {actie_type}", "login": self._login_naam,
                "pad": doc_pad, "extra_body": extra, "status": status})
        return status

    def post_raw_actions(self, doc_pad: str, body: Any) -> Any:
        """POST .../Actions met een VOLLEDIG vrije body (ook leeg/geen Type) — voor de probe."""
        self._check_kill_switch()
        try:
            r = self.rlz.request_raw("POST", f"{doc_pad.rstrip('/')}/Actions", json=body)
            status: Any = r.status_code
        except RlzApiError as e:
            status = f"{e.status_code}: {e.body[:300]}"
            _audit({"actie": "POST Actions (raw)", "login": self._login_naam, "pad": doc_pad,
                    "payload": body, "status": status})
            return status
        _audit({"actie": "POST Actions (raw)", "login": self._login_naam, "pad": doc_pad,
                "payload": body, "status": status})
        return status


def _tx_staat(c: PocClient, tx_id: str) -> dict[str, Any]:
    t = c.get(f"PaymentTransactions/{tx_id}", **{"$expand": TX_EXPAND})
    return {
        "id": t.get("id"),
        "Amount": t.get("Amount"),
        "OpenAmount": t.get("OpenAmount"),
        "IsComplete (stale na terugdraaien!)": t.get("IsComplete"),
        "MatchedPaymentItem": t.get("MatchedPaymentItem"),
        "PaymentReferenceList": t.get("PaymentReferenceList"),
        "Reference": t.get("Reference"),
    }


# --------------------------------------------------------------------------- stappen


def stap_inspect(c: PocClient) -> None:
    """Read-only: huidige staat van factuur + alle bekende TX'en + hun actielijsten."""
    bankstate = json.loads(BANKPOC_STATE.read_text()) if BANKPOC_STATE.exists() else {}
    state = _state()

    if inv := (state.get("invoice_id") or bankstate.get("invoice_id")):
        f = c.get(f"PurchaseInvoices/{inv}")
        _dump("Factuur (bankpoc TEST-BANKPOC-INV1)", {k: f.get(k) for k in (
            "id", "Status", "Reference", "BaseInvoiceAmount", "BaseRemainingAmount",
            "BasePaidAmount", "ReceiptNumber")})
        items = c.get("PaymentItems", **{"$filter": f"Document/id eq {inv}"})["value"]
        _dump("PaymentItems bij de factuur", items)

    alle_tx = dict(bankstate.get("tx") or {})
    alle_tx.update(state.get("tx") or {})
    for suffix, tx in alle_tx.items():
        _dump(f"PaymentTransaction {suffix}", _tx_staat(c, tx))
        try:
            acties = c.get(f"PaymentTransactions/{tx}/Actions")
            _dump(f"Beschikbare acties op {suffix}", acties)
        except RlzApiError as e:
            _dump(f"Beschikbare acties op {suffix}", f"{e.status_code}: {e.body[:300]}")


def stap_actionkinds(c: PocClient) -> None:
    """Read-only: de volledige ActionKinds-catalogus dumpen (nummer → naam/omschrijving)."""
    kinds = c.get("ActionKinds")
    waarden = kinds.get("value", kinds)
    _dump("ActionKinds (volledig)", waarden)
    OUTPUT.mkdir(exist_ok=True)
    (OUTPUT / "actionkinds.json").write_text(json.dumps(waarden, indent=2, ensure_ascii=False))
    print(f"\nOpgeslagen: {OUTPUT / 'actionkinds.json'}")


def stap_setup(c: PocClient) -> None:
    """Vers af te letteren paar met een UNIEK bedrag (€153,67): nieuwe factuur + nieuwe TX,
    zodat het matchvoorstel eenduidig auto-vult. De oude TEST-BANKPOC-INV1 is vervuild:
    herboeken gaf direct Status 3 zonder open PaymentItem (oud betaalspoor overleeft de
    concept-rondgang)."""
    bankstate = json.loads(BANKPOC_STATE.read_text()) if BANKPOC_STATE.exists() else {}
    state = _state()

    vendor = state.get("vendor_id") or bankstate.get("vendor_id")
    if not vendor:
        raise SystemExit("Geen vendor_id in bankpoc_state.json — eerst poc_bank_schrijf.py setup.")

    inv = state.get("invoice_id") or str(uuid.uuid4())
    if not state.get("invoice_id"):
        c.put(f"PurchaseInvoices/{inv}", {
            "id": inv,
            "Entity": {"id": vendor},
            "Reference": "TEST-AFLETTERPOC-INV1",
            "DocumentLineList": [{
                "Account": {"id": TEST_ACCOUNT_ID},
                "TaxRate": {"id": TEST_TAXRATE_ID},
                "NetAmount": 127.00,
                "TaxAmount": 26.67,
            }],
        })
        state["invoice_id"] = inv
        _save_state(state)
    f = c.get(f"PurchaseInvoices/{inv}")
    if f.get("Status") == 1:
        c.actie(f"PurchaseInvoices/{inv}", ACTION_BOOK)
        f = c.get(f"PurchaseInvoices/{inv}")
    _dump("Factuur", {k: f.get(k) for k in (
        "id", "Status", "Reference", "BaseInvoiceAmount", "BaseRemainingAmount",
        "BasePaidAmount", "ReceiptNumber")})

    items = c.get("PaymentItems", **{"$filter": f"Document/id eq {inv}"})["value"]
    _dump("PaymentItems bij de factuur", items)
    if not items:
        raise SystemExit("Geen open PaymentItem bij de geboekte factuur — onverwacht, stop.")
    state["item_id"] = items[0]["id"]

    tx_id = state.get("probe_tx")
    if not tx_id:
        rekening = state.get("rekening_id") or bankstate.get("rekening_id")
        tx_id = str(uuid.uuid4())
        c.put(f"PaymentTransactions/{tx_id}", {
            "id": tx_id,
            "PaymentAccount": {"id": rekening},
            "BookDate": datetime.now(UTC).date().isoformat(),
            "Amount": -153.67,
            "Name": "TEST PoC afletteren betaal-kant",
            "Reference": "TEST-AFLETTERPOC-TX5",
        })
        state.setdefault("tx", {})["TX5"] = tx_id
        state["probe_tx"] = tx_id
    _dump("Probe-TX (TX5)", _tx_staat(c, tx_id))
    _save_state(state)
    print(f"\nState opgeslagen: {STATE_FILE}")


def _pogingen(state: dict[str, Any], tx_staat: dict[str, Any]) -> list[tuple[str, Any]]:
    """De systematische probelijst. Volgorde: eerst de vormen die de UI-waarneming het
    dichtst benaderen en die de PoC van 2026-08-02 NIET al heeft uitgesloten."""
    matched = tx_staat.get("MatchedPaymentItem") or {}
    matched_id = matched.get("id")
    item_id = state.get("item_id")
    pogingen: list[tuple[str, Any]] = [
        # 1) Lege body — misschien accepteert de actie-route het reeds-gezette matchvoorstel
        #    zonder expliciet Type (netwerklog toonde geen body).
        ("lege body {}", {}),
        # 2) Type 15 met id = MatchedPaymentItem-id (kan afwijken van het PaymentItem-id).
        ("Type 15 + id=MatchedPaymentItem", {"Type": 15, "id": matched_id}),
    ]
    # 3) Alle acties die RLZ zélf aanbiedt op deze TX (uit stap inspect), kaal —
    #    behalve 15/16 kaal (bewezen _InvalidData, 2026-08-02) en 19 (storno, geen link).
    for t in state.get("aangeboden_acties", []):
        if t in (15, 16, 19):
            continue
        pogingen.append((f"Type {t} kaal (aangeboden door RLZ)", {"Type": t}))
    # 4) Type 15-varianten die 2026-08-02 net niet dekte.
    pogingen += [
        ("Type 15 + MatchedPaymentItem-object", {"Type": 15, "MatchedPaymentItem": {"id": matched_id}}),
        ("Type 15 + PaymentItem-object", {"Type": 15, "PaymentItem": {"id": item_id}}),
        ("lijst [ApiAction 15]", [{"Type": 15, "id": item_id}]),
    ]
    return pogingen


def stap_probe(c: PocClient) -> None:
    """Systematisch POST PaymentTransactions/{tx}/Actions proberen; log status +
    OpenAmount-effect per poging; STOP zodra OpenAmount 0 wordt."""
    state = _state()
    tx = state.get("probe_tx")
    if not tx:
        raise SystemExit("Geen probe_tx in state — eerst stap setup draaien.")

    voor = _tx_staat(c, tx)
    _dump("TX vóór probe", voor)
    if not voor["MatchedPaymentItem"]:
        raise SystemExit("MatchedPaymentItem is niet gevuld — probe zinloos, eerst setup nalopen.")
    if (voor["OpenAmount"] or 0) == 0:
        raise SystemExit("OpenAmount is al 0 — niets te proberen; eerst terugdraaien.")

    try:
        aangeboden = c.get(f"PaymentTransactions/{tx}/Actions")
        lijst = aangeboden.get("value", aangeboden) if isinstance(aangeboden, dict) else aangeboden
        _dump("Door RLZ aangeboden acties op de probe-TX", lijst)
        state["aangeboden_acties"] = sorted({
            a.get("Type") for a in lijst if isinstance(a, dict) and isinstance(a.get("Type"), int)
        })
        _save_state(state)
    except RlzApiError as e:
        print(f"GET Actions faalt: {e.status_code} — probe gaat door met de vaste lijst.")

    resultaten = []
    for label, body in _pogingen(state, voor):
        status = c.post_raw_actions(f"PaymentTransactions/{tx}", body)
        na = _tx_staat(c, tx)
        effect = {
            "poging": label, "body": body, "status": status,
            "OpenAmount voor": voor["OpenAmount"], "OpenAmount na": na["OpenAmount"],
            "PaymentReferenceList na": bool(na["PaymentReferenceList"]),
        }
        resultaten.append(effect)
        print(f"\n→ {label}: status {status}, OpenAmount {voor['OpenAmount']} → {na['OpenAmount']}")
        if (na["OpenAmount"] or 0) == 0:
            _dump("SUCCES — TX na de werkende poging", na)
            state["werkende_body"] = {"label": label, "body": body}
            _save_state(state)
            _dump("Alle pogingen tot en met succes", resultaten)
            print("\nSTOP: OpenAmount is 0 — deze body is canoniek. Nu stap verify + terugdraaien.")
            return
        voor = na
    _dump("Alle pogingen (geen enkele bracht OpenAmount naar 0)", resultaten)


def stap_verify(c: PocClient) -> None:
    """Leesspoor bevestigen + terugdraaien (16-varianten, anders actie 19 op de factuur)."""
    state = _state()
    tx = state["probe_tx"]
    _dump("TX (leesspoor)", _tx_staat(c, tx))

    for label, body in [
        ("Type 16 kaal", {"Type": 16}),
        ("lege body {} (nogmaals, als toggle?)", None),  # None = niet proberen, placeholder
    ]:
        if body is None:
            continue
        status = c.post_raw_actions(f"PaymentTransactions/{tx}", body)
        na = _tx_staat(c, tx)
        print(f"\n→ terugdraai-poging {label}: status {status}, OpenAmount → {na['OpenAmount']}")
        if (na["OpenAmount"] or 0) != 0:
            _dump("Teruggedraaid — TX weer open", na)
            state["terugdraai_body"] = {"label": label, "body": body}
            _save_state(state)
            return
    print("\nType 16 draaide niet terug — val terug op actie 19 (Correct) op de factuur (cleanup).")


def stap_cleanup(c: PocClient) -> None:
    """Alles terugdraaien: factuur storneren (actie 19) → betaling/koppeling ongedaan.
    Kale test-TX'en blijven bewust staan (geen storno mogelijk, DELETE verboden)."""
    state = _state()
    bankstate = json.loads(BANKPOC_STATE.read_text()) if BANKPOC_STATE.exists() else {}
    inv = state.get("invoice_id") or bankstate.get("invoice_id")
    if inv:
        f = c.get(f"PurchaseInvoices/{inv}")
        if f.get("Status") != 1:
            c.actie(f"PurchaseInvoices/{inv}", ACTION_CORRECT)
            print("Factuur gestorneerd (actie 19) → concept")
        else:
            print("Factuur staat al op concept.")
    if tx := state.get("probe_tx"):
        _dump("Probe-TX na cleanup", _tx_staat(c, tx))


def _koppel_body(
    *, item_id: str, linked_amount: float, is_completely_paid: bool = False,
    correction_method: int = 1, actie_type: int = 15,
) -> dict[str, Any]:
    """Exact de door Peter gevangen UI-body (DevTools-capture 2026-08-09, api-verkenning
    "Afletteren betaal-kant — BODY GEVANGEN"): actie 15 op de PAYMENTTRANSACTION met
    PaymentItemList + LinkedAmount (teken van de mutatie) + IsCompletelyPaid +
    PaymentCorrectionMethod."""
    return {
        "Type": actie_type,
        "PaymentItemList": [{"id": item_id}],
        "LinkedAmount": linked_amount,
        "IsCompletelyPaid": is_completely_paid,
        "PaymentCorrectionMethod": correction_method,
    }


def _item_staat(c: PocClient, item_id: str) -> dict[str, Any]:
    items = c.get("PaymentItems", **{"$filter": f"id eq {item_id}"})["value"]
    if not items:
        return {"id": item_id, "status": "NIET GEVONDEN"}
    i = items[0]
    return {k: i.get(k) for k in ("id", "OpenAmount", "Amount", "PaymentStatus", "Description")}


def stap_replay(c: PocClient) -> None:
    """DEEL 1b (vervolgopdracht 2026-08-09): replay van de gevangen body op het verse paar uit
    `setup` — verwacht 204 + OpenAmount 0 op mutatie én post + PaymentReferenceList-leesspoor."""
    state = _state()
    tx = state.get("probe_tx")
    item = state.get("item_id")
    if not tx or not item:
        raise SystemExit("Geen probe_tx/item_id in state — eerst stap setup draaien.")
    voor = _tx_staat(c, tx)
    _dump("TX vóór replay", voor)
    _dump("PaymentItem vóór replay", _item_staat(c, item))
    if (voor["OpenAmount"] or 0) == 0:
        raise SystemExit("OpenAmount is al 0 — eerst terugdraaien (stap ontkoppel of cleanup).")

    body = _koppel_body(item_id=item, linked_amount=voor["OpenAmount"])
    status = c.post_raw_actions(f"PaymentTransactions/{tx}", body)
    na = _tx_staat(c, tx)
    print(f"\n→ replay gevangen body: status {status}, OpenAmount {voor['OpenAmount']} → {na['OpenAmount']}")
    _dump("TX ná replay", na)
    _dump("PaymentItem ná replay", _item_staat(c, item))
    if (na["OpenAmount"] or 0) == 0:
        state["werkende_body"] = {"label": "capture-replay Type 15 + PaymentItemList", "body": body}
        _save_state(state)
        print("\nSUCCES: OpenAmount 0 — body canoniek bevestigd met Basic Auth. Nu stap ontkoppel/deel.")
    else:
        print("\nGEEN effect — rapporteren en stoppen (deel 2 vervalt).")


def stap_ontkoppel(c: PocClient) -> None:
    """DEEL 1c-4: de tegenhanger — Type 16 in dezelfde vorm; verwacht: OpenAmount komt terug
    op mutatie én post."""
    state = _state()
    tx = state["probe_tx"]
    item = state["item_id"]
    voor = _tx_staat(c, tx)
    _dump("TX vóór ontkoppelen", voor)
    body = _koppel_body(item_id=item, linked_amount=voor.get("Amount") or 0, actie_type=16)
    status = c.post_raw_actions(f"PaymentTransactions/{tx}", body)
    na = _tx_staat(c, tx)
    print(f"\n→ ontkoppel (Type 16, zelfde vorm): status {status}, OpenAmount {voor['OpenAmount']} → {na['OpenAmount']}")
    _dump("TX ná ontkoppelen", na)
    _dump("PaymentItem ná ontkoppelen", _item_staat(c, item))
    if (na["OpenAmount"] or 0) != 0:
        state["ontkoppel_body"] = {"label": "Type 16 + PaymentItemList", "body": body}
        _save_state(state)
        print("\nSUCCES: mutatie weer open — ontkoppel-vorm canoniek.")
    else:
        # Variant: kaal Type 16 zonder lijst, of met LinkedAmount 0 — één alternatieve poging.
        alt = {"Type": 16, "PaymentItemList": [{"id": item}]}
        status = c.post_raw_actions(f"PaymentTransactions/{tx}", alt)
        na = _tx_staat(c, tx)
        print(f"\n→ ontkoppel-variant zonder LinkedAmount: status {status}, OpenAmount → {na['OpenAmount']}")
        if (na["OpenAmount"] or 0) != 0:
            state["ontkoppel_body"] = {"label": "Type 16 + PaymentItemList (zonder LinkedAmount)", "body": alt}
            _save_state(state)


def stap_deel(c: PocClient) -> None:
    """DEEL 1c-1: deelbetaling — LinkedAmount kleiner dan het openstaande bedrag; verwacht:
    OpenAmount daalt met precies dat deel op mutatie én post (G-rekening-case)."""
    state = _state()
    tx = state["probe_tx"]
    item = state["item_id"]
    voor = _tx_staat(c, tx)
    _dump("TX vóór deelkoppeling", voor)
    if (voor["OpenAmount"] or 0) == 0:
        raise SystemExit("OpenAmount is al 0 — eerst ontkoppelen.")
    deel = round((voor["OpenAmount"] or 0) / 2, 2)
    body = _koppel_body(item_id=item, linked_amount=deel)
    status = c.post_raw_actions(f"PaymentTransactions/{tx}", body)
    na = _tx_staat(c, tx)
    print(f"\n→ deelkoppeling {deel}: status {status}, OpenAmount {voor['OpenAmount']} → {na['OpenAmount']}")
    _dump("TX ná deelkoppeling", na)
    _dump("PaymentItem ná deelkoppeling", _item_staat(c, item))


def stap_dicht(c: PocClient) -> None:
    """DEEL 1c-2: IsCompletelyPaid=true bij een DEEL-koppeling — sluit RLZ de post ondanks het
    restant (betalingsverschil-afboeking)? Draaien vanaf een volledig open paar: LinkedAmount =
    de helft, IsCompletelyPaid=true → verwacht óf post dicht (verschil afgeboekt) óf gewoon
    deel. Daarna terugdraaien (stap ontkoppel + evt. storno)."""
    state = _state()
    tx = state["probe_tx"]
    item = state["item_id"]
    voor = _tx_staat(c, tx)
    _dump("TX vóór dicht-poging", voor)
    _dump("PaymentItem vóór dicht-poging", _item_staat(c, item))
    if (voor["OpenAmount"] or 0) == 0:
        raise SystemExit("Mutatie is dicht — deze stap vereist een open paar (eerst ontkoppel).")
    deel = round((voor["OpenAmount"] or 0) / 2, 2)
    body = _koppel_body(item_id=item, linked_amount=deel, is_completely_paid=True)
    status = c.post_raw_actions(f"PaymentTransactions/{tx}", body)
    na = _tx_staat(c, tx)
    print(f"\n→ IsCompletelyPaid=true bij deel {deel}: status {status}, "
          f"OpenAmount {voor['OpenAmount']} → {na['OpenAmount']}")
    _dump("TX ná dicht-poging", na)
    _dump("PaymentItem ná dicht-poging (post dicht ondanks restant = verschil afgeboekt?)", _item_staat(c, item))
    inv = state.get("invoice_id")
    if inv:
        f = c.get(f"PurchaseInvoices/{inv}")
        _dump("Factuur ná dicht-poging", {k: f.get(k) for k in (
            "Status", "BaseInvoiceAmount", "BaseRemainingAmount", "BasePaidAmount")})


STAPPEN = {
    "inspect": stap_inspect,
    "actionkinds": stap_actionkinds,
    "setup": stap_setup,
    "probe": stap_probe,
    "replay": stap_replay,
    "deel": stap_deel,
    "dicht": stap_dicht,
    "ontkoppel": stap_ontkoppel,
    "verify": stap_verify,
    "cleanup": stap_cleanup,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in STAPPEN:
        raise SystemExit(f"Gebruik: poc_afletteren_betaalkant.py <{'|'.join(STAPPEN)}> [args]")
    client = PocClient()
    STAPPEN[sys.argv[1]](client, *sys.argv[2:])


if __name__ == "__main__":
    main()
