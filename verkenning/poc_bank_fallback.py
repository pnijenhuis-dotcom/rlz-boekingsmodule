#!/usr/bin/env python3
"""Bankmodule FALLBACK-PoC — afletteren tegen open post ZONDER actie 15/16.

Vraag (vervolg op "Bankmodule schrijf-PoC", api-verkenning.md): kan een bankmutatie tegen
een open inkoopfactuur afgeletterd worden via een ManualJournal op de crediteurenrekening
+ actie 34 (verrekenen)? Inclusief gedeeltelijke betaling (G-rekening-split).

Uitgevoerd 2 augustus 2026 — ANTWOORD: NEE, de fallback bestaat niet. Canoniek verslag in
verkenning/api-verkenning.md ("Bankmodule FALLBACK-PoC"). Kort:
- Actie 34 (Factuur verrekenen): 400 _InvalidData in élke vorm, ook mét exact matchende
  open creditnota-tegenpost — zelfde ongedocumenteerde-payload-muur als 15/16.
- Actie 218 (Betaal een inkoopfactuur, nieuw ontdekt): 500 in élke vorm.
- ManualJournal kan geen crediteurenpost dragen: regelmodel heeft geen relatie-veld
  (regel-Entity stil genegeerd), document-Entity geeft 500. Memoriaal raakt alleen het
  grootboek; factuur en mutatie blijven onberoerd. G-rekening-split daardoor niet toetsbaar.
- Kruisposten is wél een geldig direct-op-grootboek-doel (parkeren kan), maar dat lost de
  open post niet op — geen afletterpad.
- Lees-lessen: CreditOrDebit komt gespiegeld terug op memoriaalregels (op de bedragvelden
  varen); na storno wordt het gestorneerde document zelf de systeemhuls (IsSystemGenerated
  niet als enig onderscheid gebruiken); ManualJournals/{id}/Lines bestaat niet (404),
  regels lezen via $expand=DocumentLineList.

Zelfde waarborgen als poc_bank_schrijf.py (PocClient wordt geïmporteerd): admin-pin op de
test-administratie, kill-switch `verkenning/POC_STOP`, TEST-referenties (`TEST-BANKFB-`),
append-only audit in `output/bankpoc_audit.jsonl`, nooit DELETE — opruimen = actie 19
(besluit 0005). Eigen state in `output/bankfallback_state.json`.

Gebruik:
    backend/.venv/bin/python verkenning/poc_bank_fallback.py <stap> [args]
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
sys.path.insert(0, str(HIER))

from poc_bank_schrijf import OUTPUT, PocClient, _dump  # noqa: E402

from app.rlz.client import RlzApiError  # noqa: E402

STATE_FILE = OUTPUT / "bankfallback_state.json"

ACTION_BOOK = 17
ACTION_CORRECT = 19
ACTION_SETTLE = 34


def _state() -> dict[str, Any]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def _save_state(state: dict[str, Any]) -> None:
    OUTPUT.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


# --------------------------------------------------------------------------- stappen


def stap_setup(c: PocClient) -> None:
    """Testopstelling: bankrekening + crediteur + geboekte inkoopfactuur (€121, open item)
    + bankmutatie −121 (gesimuleerde import). Plus: grootboek-ids opsnorren (crediteuren,
    bank-GB, tussenrekening) en het memoriaal-dagboek."""
    state = _state()

    accounts = c.get("PaymentAccounts")["value"]
    bank = [a for a in accounts if a.get("Type") == 1 and not a.get("IsArchived")]
    rekening = next((a for a in bank if a.get("IsDefault")), bank[0])
    state["rekening_id"] = rekening["id"]
    _dump("Gekozen bankrekening", {k: rekening.get(k) for k in ("id", "Description", "IBAN")})

    diaries = c.get("JournalEntryDiaries")["value"]
    _dump("JournalEntryDiaries", [
        {k: d.get(k) for k in ("id", "Description", "Type", "SystemType")} for d in diaries
    ])
    memo = [d for d in diaries if "emoriaal" in (d.get("Description") or "")]
    if memo:
        state["diary_id"] = memo[0]["id"]

    for zoek, sleutel in (("crediteuren", "gb_crediteuren"), ("kruisposten", "gb_kruisposten"),
                          ("tussenrekening", "gb_tussen"), ("vraagposten", "gb_vraagposten")):
        try:
            hits = c.get("Ledgers", search=zoek)["value"]
        except RlzApiError as e:
            print(f"Ledgers?search={zoek}: {e.status_code}")
            continue
        _dump(f"Ledgers?search={zoek}", [
            {k: g.get(k) for k in ("id", "Description", "Number", "AccountCode")} for g in hits
        ])
        if hits:
            state[sleutel] = hits[0]["id"]

    vendor_id = state.get("vendor_id") or str(uuid.uuid4())
    c.put(f"Vendors/{vendor_id}", {"id": vendor_id, "Name": "TEST PoC bank-fallback — storneren"})
    state["vendor_id"] = vendor_id

    invoice_id = state.get("invoice_id") or str(uuid.uuid4())
    c.put(
        f"PurchaseInvoices/{invoice_id}",
        {
            "id": invoice_id,
            "Entity": {"id": vendor_id},
            "Reference": "TEST-BANKFB-INV1",
            "DocumentLineList": [{
                "Account": {"id": "79b6f64a-dad9-4683-9e47-9c182ebae1c1"},  # 4699 Div. alg. kosten
                "TaxRate": {"id": "1e44993a-15f6-419f-87e5-3e31ac3d9383"},  # 21% NL
                "NetAmount": 100.00,
                "TaxAmount": 21.00,
            }],
        },
    )
    state["invoice_id"] = invoice_id
    na = c.actie(f"PurchaseInvoices/{invoice_id}", ACTION_BOOK)
    _dump("Factuur na boeken (verwacht Status 2)", {k: na.get(k) for k in (
        "id", "Status", "Reference", "BaseInvoiceAmount", "BaseRemainingAmount", "ReceiptNumber")})

    items = c.get("PaymentItems", **{"$filter": f"Document/id eq {invoice_id}"})["value"]
    _dump("PaymentItems bij de factuur", items)
    if items:
        state["invoice_item_id"] = items[0]["id"]

    tx_id = state.get("tx1_id") or str(uuid.uuid4())
    c.put(f"PaymentTransactions/{tx_id}", {
        "id": tx_id,
        "PaymentAccount": {"id": state["rekening_id"]},
        "BookDate": datetime.now(UTC).date().isoformat(),
        "Amount": -121.00,
        "Name": "TEST PoC bank-fallback",
        "Reference": "TEST-BANKFB-TX1",
    })
    state["tx1_id"] = tx_id
    _save_state(state)
    print(f"\nState opgeslagen: {STATE_FILE}")


def stap_acties(c: PocClient) -> None:
    """Read-only: welke acties bieden factuur en (indien aanwezig) memoriaal aan — is 34 erbij?"""
    state = _state()
    for label, pad in (("factuur", f"PurchaseInvoices/{state['invoice_id']}"),
                       ("memoriaal", f"ManualJournals/{state.get('memoriaal_id')}"),
                       ("mutatie TX1", f"PaymentTransactions/{state['tx1_id']}")):
        if "None" in pad:
            continue
        try:
            acties = c.get(f"{pad}/Actions")
            _dump(f"Actions op {label}", acties)
        except RlzApiError as e:
            print(f"Actions op {label}: {e.status_code} {e.body[:200]}")


def stap_memoriaal(c: PocClient, bedrag: str = "121.00", tegen: str = "bank",
                   sleutel: str = "memoriaal_id", ref: str = "TEST-BANKFB-MEM1") -> None:
    """Betaal-memoriaal: debet crediteuren (1600, mét Entity op de regel) / credit tegenrekening
    (`bank` = bank-GB van de rekening, `kruisposten`/`tussen`/`vraagposten` = die ledger)
    + boeken (17). Verwachting om te toetsen: ontstaat er een verrekenbaar open item op de
    crediteur, en doet de bank-GB-regel iets met de bankmutatie (verwacht: niets)?"""
    state = _state()
    if tegen == "bank":
        tegen_id = state.get("gb_bank")
        if not tegen_id:
            raise SystemExit("gb_bank nog onbekend — eerst `vindbankgb` draaien.")
    else:
        tegen_id = state[f"gb_{tegen}"]
    m_id = str(uuid.uuid4())
    body = {
        "id": m_id,
        "Reference": ref,
        # Entity op documentniveau: regelniveau kent geen relatie-veld (ManualJournalLine-model,
        # Help) en een Entity op de regel wordt stil genegeerd (MEM1) — dit is de enige plek
        # waar het model een relatie toestaat.
        "Entity": {"id": state["vendor_id"]},
        "JournalEntryDiary": {"id": state["diary_id"]},
        "DocumentLineList": [
            {
                "Account": {"id": state["gb_crediteuren"]},
                "Entity": {"id": state["vendor_id"]},
                "CreditOrDebit": 1,
                "DebitAmount": float(bedrag),
                "Description": f"{ref} betaling crediteur",
            },
            {
                "Account": {"id": tegen_id},
                "CreditOrDebit": 2,
                "CreditAmount": float(bedrag),
                "Description": f"{ref} tegenboeking {tegen}",
            },
        ],
    }
    nieuw = c.put(f"ManualJournals/{m_id}", body, params={"autoCorrect": "false"})
    state[sleutel] = m_id
    _save_state(state)
    _dump("Memoriaal na PUT", {k: nieuw.get(k) for k in (
        "id", "Status", "Reference", "BalanceAmount", "ReceiptNumber")} if nieuw else nieuw)
    try:  # /Lines bestaat niet op ManualJournals (404) — regels via $expand op het document
        m = c.get(f"ManualJournals/{m_id}",
                  **{"$expand": "DocumentLineList($expand=Account,Entity)"})
        _dump("Memoriaal-regels (check: Entity op de crediteurenregel?)", m.get("DocumentLineList"))
    except RlzApiError as e:
        print(f"Regels lezen: {e.status_code} {e.body[:150]}")
    na = c.actie(f"ManualJournals/{m_id}", ACTION_BOOK)
    _dump("Memoriaal na boeken", {k: na.get(k) for k in ("id", "Status", "ReceiptNumber")})
    items = c.get("PaymentItems", **{"$filter": f"Document/id eq {m_id}"})["value"]
    _dump("PaymentItems bij het memoriaal (verrekenbaar open item?)", items)


def stap_boek(c: PocClient, sleutel: str = "memoriaal_id") -> None:
    """Actie 17 op een eerder aangemaakt memoriaal (herstelstap na een script-crash)."""
    state = _state()
    na = c.actie(f"ManualJournals/{state[sleutel]}", ACTION_BOOK)
    _dump("Memoriaal na boeken", {k: na.get(k) for k in ("id", "Status", "ReceiptNumber")})
    items = c.get("PaymentItems", **{"$filter": f"Document/id eq {state[sleutel]}"})["value"]
    _dump("PaymentItems bij het memoriaal (verrekenbaar open item?)", items)


def stap_vindbankgb(c: PocClient) -> None:
    """Bank-GB-rekening van de gekozen PaymentAccount vinden (probe: $expand=Account op de
    rekening; fallback: Ledgers doorzoeken op de rekeningnaam/'bank')."""
    state = _state()
    for expand in ("Account", "Ledger", "LedgerAccount"):
        try:
            r = c.get(f"PaymentAccounts/{state['rekening_id']}", **{"$expand": expand})
            _dump(f"PaymentAccount $expand={expand}", r.get(expand))
            if r.get(expand):
                state["gb_bank"] = r[expand]["id"]
                break
        except RlzApiError as e:
            print(f"$expand={expand}: {e.status_code} {e.body[:150]}")
    if not state.get("gb_bank"):
        hits = c.get("Ledgers", search="bank")["value"]
        _dump("Ledgers?search=bank", [
            {k: g.get(k) for k in ("id", "Description", "Number", "AccountCode")} for g in hits
        ])
    _save_state(state)


def stap_verreken_probe(c: PocClient, doel: str = "factuur") -> None:
    """Actie 34 (verrekenen) proberen in alle plausibele vormen, stoppen bij de eerste die
    slaagt. Elke poging (ook mislukte) staat in het audit-log. `doel` = factuur | memoriaal."""
    state = _state()
    inv, mem = state["invoice_id"], state.get("memoriaal_id")
    item_inv = state.get("invoice_item_id")
    items_mem = c.get("PaymentItems", **{"$filter": f"Document/id eq {mem}"})["value"] if mem else []
    item_mem = items_mem[0]["id"] if items_mem else None

    if doel == "factuur":
        pad = f"PurchaseInvoices/{inv}"
        vormen: list[dict[str, Any]] = [
            {},
            {"id": mem},
            {"id": item_mem} if item_mem else None,
            {"Description": mem},
        ]
    else:
        pad = f"ManualJournals/{mem}"
        vormen = [
            {},
            {"id": inv},
            {"id": item_inv} if item_inv else None,
            {"Description": inv},
        ]
    for extra in [v for v in vormen if v is not None]:
        try:
            na = c.actie(pad, ACTION_SETTLE, **extra)
            print(f"\n*** GESLAAGD: POST {pad}/Actions Type=34 extra={extra} ***")
            _dump("Document na actie 34", {k: na.get(k) for k in (
                "id", "Status", "BaseRemainingAmount", "BasePaidAmount")} if na else na)
            stap_inspect(c)
            return
        except RlzApiError as e:
            print(f"Type=34 extra={extra} → {e.status_code}: {e.body[:200]}")
    print("\nGeen enkele vorm van actie 34 geslaagd op dit doel.")


def stap_creditnota(c: PocClient, bedrag: str = "-121.00") -> None:
    """Tegenpost die bewezen wél een PaymentItem oplevert: negatieve PurchaseInvoice
    (creditnota) op dezelfde crediteur + boeken. Doel: toetsen of actie 34 werkt zodra er
    een echte open tegenpost op de crediteur staat."""
    state = _state()
    cn_id = str(uuid.uuid4())
    c.put(f"PurchaseInvoices/{cn_id}", {
        "id": cn_id,
        "Entity": {"id": state["vendor_id"]},
        "Reference": "TEST-BANKFB-CN1",
        "DocumentLineList": [{
            "Account": {"id": "79b6f64a-dad9-4683-9e47-9c182ebae1c1"},
            "TaxRate": {"id": "1e44993a-15f6-419f-87e5-3e31ac3d9383"},
            "NetAmount": round(float(bedrag) / 1.21, 2),
            "TaxAmount": round(float(bedrag) - round(float(bedrag) / 1.21, 2), 2),
        }],
    })
    state["creditnota_id"] = cn_id
    _save_state(state)
    na = c.actie(f"PurchaseInvoices/{cn_id}", ACTION_BOOK)
    _dump("Creditnota na boeken", {k: na.get(k) for k in (
        "id", "Status", "Reference", "BaseInvoiceAmount", "BaseRemainingAmount", "ReceiptNumber")})
    items = c.get("PaymentItems", **{"$filter": f"Document/id eq {cn_id}"})["value"]
    _dump("PaymentItems bij de creditnota", items)
    if items:
        state["creditnota_item_id"] = items[0]["id"]
        _save_state(state)


def stap_verreken2(c: PocClient) -> None:
    """Actie 34 opnieuw, nu mét open tegenpost (creditnota) op dezelfde crediteur."""
    state = _state()
    inv, cn = state["invoice_id"], state["creditnota_id"]
    vormen: list[tuple[str, dict[str, Any]]] = [
        (f"PurchaseInvoices/{inv}", {}),
        (f"PurchaseInvoices/{inv}", {"id": cn}),
        (f"PurchaseInvoices/{inv}", {"id": state.get("creditnota_item_id")}),
        (f"PurchaseInvoices/{cn}", {"id": inv}),
        (f"PurchaseInvoices/{cn}", {"id": state.get("invoice_item_id")}),
    ]
    for pad, extra in vormen:
        if None in extra.values():
            continue
        try:
            na = c.actie(pad, ACTION_SETTLE, **extra)
            print(f"\n*** GESLAAGD: POST {pad}/Actions Type=34 extra={extra} ***")
            _dump("Document na actie 34", {k: na.get(k) for k in (
                "id", "Status", "BaseRemainingAmount", "BasePaidAmount")} if na else na)
            stap_inspect(c)
            return
        except RlzApiError as e:
            print(f"{pad} Type=34 extra={extra} → {e.status_code}: {e.body[:200]}")
    print("\nGeen enkele vorm van actie 34 geslaagd, ook niet met open tegenpost.")


def stap_probe218(c: PocClient) -> None:
    """Actie 218 'Betaal een inkoopfactuur' verkennen: accepteert die een bestaande
    bankmutatie (id = PaymentTransaction), een rekening of niets? Elke poging in het audit-log."""
    state = _state()
    inv = state["invoice_id"]
    vormen: list[dict[str, Any]] = [
        {"id": state["tx1_id"]},
        {"id": state["rekening_id"]},
        {"id": state.get("invoice_item_id")},
        {},
    ]
    for extra in vormen:
        if None in extra.values():
            continue
        try:
            na = c.actie(f"PurchaseInvoices/{inv}", 218, **extra)
            print(f"\n*** GESLAAGD: Type=218 extra={extra} ***")
            _dump("Factuur na actie 218", {k: na.get(k) for k in (
                "id", "Status", "BaseRemainingAmount", "BasePaidAmount")} if na else na)
            stap_inspect(c)
            return
        except RlzApiError as e:
            print(f"Type=218 extra={extra} → {e.status_code}: {e.body[:200]}")
    print("\nGeen enkele vorm van actie 218 geslaagd.")


def stap_direct_tussen(c: PocClient, tussen_sleutel: str = "gb_kruisposten",
                       tx_sleutel: str = "tx1_id", db_sleutel: str = "direct_tussen_id") -> None:
    """Variant B, been 1: de bankmutatie via de bewezen direct-op-grootboek-route naar een
    tussenrekening boeken (lettert de mutatie af). Been 2 = memoriaal tussenrekening↔crediteur."""
    state = _state()
    tx = state[tx_sleutel]
    t = c.get(f"PaymentTransactions/{tx}")
    db_id = str(uuid.uuid4())
    nieuw = c.put(f"BankMutationDirectBookings/{db_id}", {
        "id": db_id,
        "PaymentTransaction": {"id": tx},
        "Description": "TEST-BANKFB via tussenrekening",
        "DocumentLineList": [{
            "Account": {"id": state[tussen_sleutel]},
            "NetAmount": t["Amount"],
            "Description": "TEST-BANKFB betaling naar tussenrekening",
        }],
    })
    _dump("Directe boeking op tussenrekening (verwacht Status 3)", {k: nieuw.get(k) for k in (
        "id", "Status", "ReceiptNumber")} if nieuw else nieuw)
    state[db_sleutel] = db_id
    _save_state(state)
    t2 = c.get(f"PaymentTransactions/{tx}")
    _dump("Mutatie daarna", {"OpenAmount": t2.get("OpenAmount"), "IsComplete": t2.get("IsComplete")})


def stap_inspect(c: PocClient) -> None:
    """Actuele staat van alle betrokken objecten (read-only). OpenAmount is leidend."""
    state = _state()
    if inv := state.get("invoice_id"):
        f = c.get(f"PurchaseInvoices/{inv}")
        _dump("Factuur", {k: f.get(k) for k in (
            "id", "Status", "Reference", "BaseInvoiceAmount", "BaseRemainingAmount",
            "BasePaidAmount", "ReceiptNumber")})
        items = c.get("PaymentItems", **{"$filter": f"Document/id eq {inv}"})["value"]
        _dump("PaymentItems factuur", items)
    for sleutel in ("memoriaal_id", "memoriaal2_id", "memoriaal3_id"):
        if mem := state.get(sleutel):
            try:
                m = c.get(f"ManualJournals/{mem}")
            except RlzApiError as e:
                print(f"{sleutel}: {e.status_code}")
                continue
            _dump(f"Memoriaal {sleutel}", {k: m.get(k) for k in ("id", "Status", "Reference", "ReceiptNumber")})
            items = c.get("PaymentItems", **{"$filter": f"Document/id eq {mem}"})["value"]
            _dump(f"PaymentItems {sleutel}", items)
    for sleutel in ("tx1_id", "tx2a_id", "tx2b_id"):
        if tx := state.get(sleutel):
            t = c.get(f"PaymentTransactions/{tx}",
                      **{"$expand": "MatchedPaymentItem,PaymentReferenceList($expand=Document)"})
            _dump(f"Mutatie {sleutel}", {
                "OpenAmount": t.get("OpenAmount"),
                "IsComplete (stale na storno!)": t.get("IsComplete"),
                "MatchedPaymentItem": (t.get("MatchedPaymentItem") or {}).get("id"),
                "PaymentReferenceList": [
                    {"Amount": r.get("Amount"), "Sequence": r.get("Sequence"),
                     "Source": r.get("PaymentReconciliationSource"),
                     "Document": {k: (r.get("Document") or {}).get(k) for k in (
                         "id", "ReceiptNumber", "IsSystemGenerated", "DocumentType", "Status")}}
                    for r in t.get("PaymentReferenceList") or []
                ],
            })


def stap_cleanup(c: PocClient) -> None:
    """Alles storneren met actie 19 (besluit 0005), nooit DELETE. Kale test-bankmutaties
    blijven staan (kennen geen storno). Volgorde: eerst directe boekingen/memoriaals, dan
    de factuur."""
    state = _state()
    for sleutel in ("direct_tussen_id", "direct_tussen2_id", "direct_tussen3_id",
                    "memoriaal_id", "memoriaal2_id", "memoriaal3_id"):
        if not (doc := state.get(sleutel)):
            continue
        pad = ("BankMutationDirectBookings" if sleutel.startswith("direct") else "ManualJournals")
        try:
            d = c.get(f"{pad}/{doc}")
            if d and d.get("Status") != 1:
                c.actie(f"{pad}/{doc}", ACTION_CORRECT)
                print(f"{sleutel}: gestorneerd (19) → concept")
        except RlzApiError as e:
            print(f"{sleutel}: {e.status_code} {e.body[:150]}")
    for sleutel in ("creditnota_id", "invoice_id"):
        if not (doc := state.get(sleutel)):
            continue
        f = c.get(f"PurchaseInvoices/{doc}")
        if f.get("Status") != 1:
            c.actie(f"PurchaseInvoices/{doc}", ACTION_CORRECT)
            print(f"{sleutel}: gestorneerd (19) → concept")
    stap_inspect(c)


STAPPEN = {
    "setup": stap_setup,
    "acties": stap_acties,
    "vindbankgb": stap_vindbankgb,
    "memoriaal": stap_memoriaal,
    "boek": stap_boek,
    "verreken": stap_verreken_probe,
    "creditnota": stap_creditnota,
    "verreken2": stap_verreken2,
    "probe218": stap_probe218,
    "direct_tussen": stap_direct_tussen,
    "inspect": stap_inspect,
    "cleanup": stap_cleanup,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in STAPPEN:
        raise SystemExit(f"Gebruik: poc_bank_fallback.py <{'|'.join(STAPPEN)}> [args]")
    client = PocClient()
    STAPPEN[sys.argv[1]](client, *sys.argv[2:])


if __name__ == "__main__":
    main()
