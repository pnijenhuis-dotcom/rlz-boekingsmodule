#!/usr/bin/env python3
"""Odoo STAP-0 (blok 3c bundel 08-09, B3): bestaat er in Odoo 19 een NIET-afsluitend equivalent van RLZ's
"Betaling"-veld (QuickPaymentSelection: post blijft open, verdwijnt uit de betaallijst)?

`account.payment.register` sluit de post (betaling + reconciliatie) en is dus GEEN equivalent. Kandidaten die een
vendor bill markeren zonder 'm af te letteren:
  - account.move.preferred_payment_method_line_id  ("Payment Method" op de factuur; stuurt betaalbatches/SDD)
  - account.move.payment_state                      (computed: not_paid/in_payment/paid/… — niet handmatig zetbaar)
  - velden met 'payment'/'direct_debit'/'sdd'/'mandate' in de naam (account_sepa_direct_debit geïnstalleerd?)

ALLEEN LEZEN: fields_get + search_read op de dev-company (company 1). Geen write — dit is een inventaris; een
schrijftest volgt pas als er een kandidaat is (dan op een TEST-bill, met audit via odoo_stap0_client.schrijf).
Gebruik: backend/.venv/bin/python verkenning/odoo_stap0_betaalstatus.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))

from odoo_stap0_client import OdooFout, OdooJson2, bewaar  # noqa: E402

ZOEK = ("payment", "direct_debit", "sdd", "mandate", "incasso", "paid", "to_pay", "in_payment")


def main() -> int:
    c = OdooJson2()
    print("Odoo-versie:", json.dumps(c.versie(), default=str)[:200])
    velden = c.fields_get("account.move", ["string", "type", "readonly", "store", "relation", "selection", "help"])
    kandidaten = {
        naam: v for naam, v in velden.items() if any(z in naam.lower() or z in (v.get("string") or "").lower() for z in ZOEK)
    }
    print(f"\n== account.move: {len(kandidaten)} velden met betaal-achtige naam/label:")
    for naam, v in sorted(kandidaten.items()):
        print(
            f"   {naam:45s} type={v.get('type'):10s} readonly={v.get('readonly')!s:5s} store={v.get('store')!s:5s} "
            f"rel={v.get('relation') or '-'} — {v.get('string')}"
        )
        if v.get("selection"):
            print(f"      selection: {v['selection']}")
    # Betaalmethoden (account.payment.method.line) die op een leveranciersjournaal beschikbaar zijn.
    try:
        methoden = c.search_read(
            "account.payment.method.line",
            [["payment_type", "=", "outbound"]],
            ["name", "code", "payment_method_id", "journal_id", "company_id"],
        )
        print(f"\n== account.payment.method.line (outbound): {len(methoden)}")
        for m in methoden:
            print("   ", json.dumps(m, default=str)[:200])
    except OdooFout as e:
        methoden = []
        print("\n== account.payment.method.line:", e)
    # Geïnstalleerde modules rond SEPA/direct debit.
    try:
        modules = c.search_read(
            "ir.module.module",
            [["name", "ilike", "sepa"], ["state", "=", "installed"]],
            ["name", "shortdesc", "state"],
        )
        print(f"\n== geïnstalleerde modules met 'sepa': {[m['name'] for m in modules]}")
    except OdooFout as e:
        modules = []
        print("\n== ir.module.module:", e)
    # Eén geposte leveranciersfactuur lezen om de huidige waarden van de kandidaatvelden te zien.
    kandidaat_velden = [n for n in ("preferred_payment_method_line_id", "payment_state", "payment_reference", "amount_residual") if n in velden]
    try:
        bills = c.search_read(
            "account.move",
            [["move_type", "=", "in_invoice"], ["state", "=", "posted"]],
            ["name", "partner_id", *kandidaat_velden],
            limit=3,
            order="id desc",
        )
        print(f"\n== laatste geposte vendor bills ({len(bills)}), kandidaatvelden:")
        for b in bills:
            print("   ", json.dumps(b, default=str)[:300])
    except OdooFout as e:
        bills = []
        print("\n== account.move search_read:", e)
    pad = bewaar(
        "betaalstatus_stap0",
        {"kandidaten": kandidaten, "methoden": methoden, "modules": modules, "bills": bills},
    )
    print("\nrapport →", pad)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
