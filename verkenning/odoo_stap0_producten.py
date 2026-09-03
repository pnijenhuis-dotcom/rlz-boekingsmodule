#!/usr/bin/env python3
"""Odoo blok B (fase 1, 03-09-2026) — product-semantiek-verificatie, STAP-0-stijl, live op company 1.

Vragen (odoo-verkenning.md §6 legt de antwoorden vast):
 P1. Hoe boekt een regel MÉT product zónder expliciete account_id: rekening uit product/categorie
     (property_account_expense_(categ_)id) of — anglo-saxon + voorraadwaardering — een tussenrekening?
 P2. Blijft een EXPLICIETE account_id op een productregel staan (onze regel: het boekvoorstel bepaalt de rekening)?
 P3. quantity × price_unit → price_subtotal cent-exact; product_uom; supplier_taxes_id wordt NIET automatisch
     gezet als wij tax_ids expliciet meegeven (leeg = leeg)?
 P4. analytic_distribution op een productregel → account.analytic.line mét product_id?
 P5. Kostprijs-consequentie: ontstaan er stock.move/valuation-regels bij het posten van een leveranciersfactuur
     zonder inkooporder (anglo_saxon_accounting True, categorie periodic/standard)?
 P6. Een door ons aangemaakt product.template (type consu, default_code AKN-…, categorie uit de catalogus) — welke
     rekening leidt Odoo daarvan af op een factuurregel?
Alles mét TEST-referentie; tegengeboekt via reversal; TEST-partner/-product gearchiveerd (nooit unlink).
Gebruik: python verkenning/odoo_stap0_producten.py [run|opruimen|status]
"""

from __future__ import annotations

import json
import sys
from datetime import date

from odoo_stap0_client import OdooJson2, bewaar

COMPANY = 1
CTX = {"allowed_company_ids": [COMPANY]}
REF = "TEST-ODOO-FASE1-PRODUCTEN"
PARTNER_NAAM = "TEST-ODOO-FASE1 Leverancier (niet gebruiken)"
PRODUCT_CODE = "AKN-TEST0001"
PRODUCT_NAAM = "TEST-ODOO-FASE1 Steigerplank 3 m"
MOVE_VELDEN = ["name", "state", "company_id", "amount_untaxed", "amount_tax", "amount_total", "date", "invoice_date",
               "ref", "invoice_origin", "payment_state", "amount_residual", "reversal_move_ids"]
LINE_VELDEN = ["name", "display_type", "product_id", "product_uom_id", "quantity", "price_unit", "price_subtotal",
               "account_id", "tax_ids", "analytic_distribution", "balance", "debit", "credit"]


def _m2o(v):
    return v[0] if isinstance(v, list) else v


def status(c: OdooJson2) -> dict:
    moves = c.search_read("account.move", [["company_id", "=", COMPANY], ["ref", "ilike", "TEST-ODOO-FASE1"]],
                          MOVE_VELDEN, context=CTX)
    partners = c.search_read("res.partner", [["name", "=", PARTNER_NAAM], ["active", "in", [True, False]]],
                             ["id", "active", "company_id"], context=CTX)
    producten = c.search_read("product.product", [["default_code", "=", PRODUCT_CODE], ["active", "in", [True, False]]],
                              ["id", "name", "active", "product_tmpl_id", "categ_id", "type", "is_storable",
                               "standard_price", "property_account_expense_id", "company_id"], context=CTX)
    return {"moves": moves, "partners": partners, "producten": producten}


def run(c: OdooJson2) -> None:
    uit: dict = {"datum": date.today().isoformat()}
    st = status(c)
    # --- partner (lookup-vóór-create, groepsgedeeld = company_id False, besluit Peter 02-09) ---
    if st["partners"]:
        partner_id = st["partners"][0]["id"]
        if not st["partners"][0]["active"]:
            c.schrijf("res.partner", "write", reden="TEST-partner heractiveren voor fase-1-bewijs", ids=[partner_id],
                      vals={"active": True})
    else:
        partner_id = c.schrijf("res.partner", "create", reden="TEST-partner fase 1 (groepsgedeeld)",
                               vals_list=[{"name": PARTNER_NAAM, "is_company": True, "supplier_rank": 1,
                                           "company_id": False, "country_id": 165}], context=CTX)[0]
    uit["partner_id"] = partner_id

    # --- bestaand product uit de Odoo-catalogus (categorie Betonbewerking, expense 700100) ---
    bestaand = c.search_read("product.product", [["company_id", "in", [COMPANY, False]], ["purchase_ok", "=", True]],
                             ["id", "name", "categ_id", "type", "is_storable", "standard_price", "uom_id",
                              "property_account_expense_id", "supplier_taxes_id", "default_code"],
                             limit=3, order="id", context=CTX)
    uit["bestaande_producten_voorbeeld"] = bestaand
    bestaand_product = bestaand[0] if bestaand else None
    categ_id = _m2o(bestaand_product["categ_id"]) if bestaand_product else None
    categ = c.read("product.category", [categ_id], ["complete_name", "property_account_expense_categ_id",
                                                    "property_valuation", "property_cost_method",
                                                    "property_stock_valuation_account_id"])[0] if categ_id else None
    uit["categorie_bestaand"] = categ

    # --- eigen product (brug-vorm): template consu + default_code + categorie ---
    if st["producten"]:
        eigen_product_id = st["producten"][0]["id"]
        if not st["producten"][0]["active"]:
            c.schrijf("product.product", "write", reden="TEST-product heractiveren", ids=[eigen_product_id],
                      vals={"active": True}, context=CTX)
    else:
        tmpl_vals = {"name": PRODUCT_NAAM, "default_code": PRODUCT_CODE, "type": "consu", "purchase_ok": True,
                     "sale_ok": False, "company_id": COMPANY, "description_purchase": "TEST fase 1 — brugvorm"}
        if categ_id:
            tmpl_vals["categ_id"] = categ_id
        tmpl_id = c.schrijf("product.template", "create", reden="TEST-product (brugvorm) fase 1",
                            vals_list=[tmpl_vals], context=CTX)[0]
        eigen_product_id = c.search_read("product.product", [["product_tmpl_id", "=", tmpl_id]], ["id"], context=CTX)[0]["id"]
    eigen = c.read("product.product", [eigen_product_id], ["name", "categ_id", "type", "is_storable", "standard_price",
                                                          "uom_id", "property_account_expense_id", "supplier_taxes_id",
                                                          "default_code", "company_id"])[0]
    uit["eigen_product"] = eigen

    # --- analytic account (Internal, company 1) ---
    analytic = c.search_read("account.analytic.account", [["plan_id", "=", 1], ["company_id", "in", [COMPANY, False]],
                                                          ["name", "=", "Internal"]], ["id", "name"], context=CTX)
    analytic_id = analytic[0]["id"] if analytic else None
    uit["analytic_id"] = analytic_id

    # --- factuur: 4 regels, elk een vraag ---
    regels = [
        # P1: bestaand product, GEEN account_id → wat leidt Odoo af?
        {"name": "P1 bestaand product zonder rekening", "product_id": bestaand_product["id"], "quantity": 2,
         "price_unit": 10.0, "tax_ids": [[6, 0, [14]]]},
        # P2: bestaand product MÉT expliciete account_id 424000 (id 258) → blijft die staan?
        {"name": "P2 bestaand product met expliciete rekening 424000", "product_id": bestaand_product["id"],
         "account_id": 258, "quantity": 3, "price_unit": 10.0, "tax_ids": [[6, 0, [14]]]},
        # P3/P4/P6: eigen product, expliciete rekening 420100 (id 252), analytic, geen tax (0 %-inkoop = géén tax_ids)
        {"name": "P3 eigen product 4 x 12,34 zonder btw + project", "product_id": eigen_product_id, "account_id": 252,
         "quantity": 4, "price_unit": 12.34, "tax_ids": [],
         **({"analytic_distribution": {str(analytic_id): 100}} if analytic_id else {})},
        # P6: eigen product ZONDER account_id → afleiding uit categorie?
        {"name": "P6 eigen product zonder rekening", "product_id": eigen_product_id, "quantity": 1, "price_unit": 5.0,
         "tax_ids": [[6, 0, [14]]]},
    ]
    if analytic_id:
        regels[1]["analytic_distribution"] = {str(analytic_id): 100}
    bestaande_move = c.search_read("account.move", [["company_id", "=", COMPANY], ["ref", "=", REF],
                                                    ["move_type", "=", "in_invoice"], ["state", "!=", "cancel"]],
                                   ["id"], context=CTX)
    if bestaande_move:
        move_id = bestaande_move[0]["id"]
    else:
        move_id = c.schrijf("account.move", "create", reden="TEST-inkoopfactuur fase 1 product-semantiek",
                            vals_list=[{"move_type": "in_invoice", "company_id": COMPANY, "journal_id": 9,
                                        "partner_id": partner_id, "ref": REF, "invoice_origin": "AKN:TEST:fase1",
                                        "invoice_date": "2026-09-01", "date": "2026-09-01",
                                        "invoice_date_due": "2026-10-01", "invoice_payment_term_id": False,
                                        "payment_reference": "TEST-FASE1-KENMERK",
                                        "invoice_line_ids": [[0, 0, r] for r in regels]}], context=CTX)[0]
    uit["move_id"] = move_id
    concept = c.read("account.move", [move_id], MOVE_VELDEN)[0]
    uit["concept"] = concept
    lines = c.search_read("account.move.line", [["move_id", "=", move_id]], LINE_VELDEN, order="id", context=CTX)
    uit["concept_regels"] = lines

    # Posten (P5: stock/valuation-effect?)
    stock_voor = c.call("stock.move", "search_count", domain=[["company_id", "=", COMPANY]], context=CTX)
    if concept["state"] == "draft":
        c.schrijf("account.move", "action_post", reden="TEST-factuur posten (fase 1 P5)", ids=[move_id], context=CTX)
    geboekt = c.read("account.move", [move_id], MOVE_VELDEN)[0]
    uit["geboekt"] = geboekt
    uit["geboekt_regels"] = c.search_read("account.move.line", [["move_id", "=", move_id]], LINE_VELDEN, order="id", context=CTX)
    stock_na = c.call("stock.move", "search_count", domain=[["company_id", "=", COMPANY]], context=CTX)
    uit["stock_moves_voor_na"] = [stock_voor, stock_na]
    uit["analytic_lines"] = c.search_read("account.analytic.line", [["move_line_id.move_id", "=", move_id]],
                                          ["name", "amount", "account_id", "general_account_id", "product_id",
                                           "unit_amount", "date", "ref"], context=CTX)
    # Bijlage ná posten
    att = c.search_read("ir.attachment", [["res_model", "=", "account.move"], ["res_id", "=", move_id]], ["id", "name"],
                        context=CTX)
    if not att:
        import base64
        pdf = b"%PDF-1.4\n%TEST fase 1 producten\n%%EOF\n"
        att_id = c.schrijf("ir.attachment", "create", reden="TEST-bijlage ná posten",
                           vals_list=[{"name": "TEST-fase1.pdf", "res_model": "account.move", "res_id": move_id,
                                       "datas": base64.b64encode(pdf).decode(), "mimetype": "application/pdf"}],
                           context=CTX)[0]
        c.schrijf("ir.attachment", "register_as_main_attachment", reden="hoofdbijlage", ids=[att_id], force=True,
                  context=CTX)
    uit["bijlage"] = c.search_read("ir.attachment", [["res_model", "=", "account.move"], ["res_id", "=", move_id]],
                                   ["id", "name", "checksum"], context=CTX)

    # Reversal (storno-norm) + posten + verificatie
    if not geboekt.get("reversal_move_ids"):
        wiz = c.schrijf("account.move.reversal", "create", reden="TEST reversal fase 1",
                        vals_list=[{"move_ids": [[6, 0, [move_id]]], "reason": "fase-1-bewijs, tegengeboekt",
                                    "journal_id": 9, "date": date.today().isoformat(), "company_id": COMPANY}],
                        context=CTX)[0]
        actie = c.schrijf("account.move.reversal", "reverse_moves", reden="reversal uitvoeren", ids=[wiz], context=CTX)
        uit["reversal_actie"] = actie
        refund_id = actie.get("res_id") if isinstance(actie, dict) else None
    else:
        refund_id = geboekt["reversal_move_ids"][-1]
    refund = c.read("account.move", [refund_id], MOVE_VELDEN)[0]
    if refund["state"] == "draft":
        c.schrijf("account.move", "action_post", reden="creditnota posten", ids=[refund_id], context=CTX)
        refund = c.read("account.move", [refund_id], MOVE_VELDEN)[0]
    uit["refund"] = refund
    uit["refund_regels"] = c.search_read("account.move.line", [["move_id", "=", refund_id]], LINE_VELDEN, order="id", context=CTX)
    uit["origineel_na_reversal"] = c.read("account.move", [move_id], MOVE_VELDEN)[0]
    bewaar("odoo_fase1_producten.json", uit)
    samenvatting(uit)


def samenvatting(uit: dict) -> None:
    print("company:", uit["geboekt"]["company_id"], "| state:", uit["geboekt"]["state"], "| naam:", uit["geboekt"]["name"],
          "| date:", uit["geboekt"]["date"], "| totaal:", uit["geboekt"]["amount_total"])
    print("categorie bestaand:", json.dumps(uit.get("categorie_bestaand"), default=str))
    print("eigen product:", {k: uit["eigen_product"].get(k) for k in ("type", "is_storable", "categ_id", "property_account_expense_id", "uom_id", "standard_price")})
    for r in uit["geboekt_regels"]:
        if r["display_type"] == "product":
            print(f"  regel {r['name'][:45]:45} product={_m2o(r['product_id'])} qty={r['quantity']} pu={r['price_unit']} "
                  f"subtotal={r['price_subtotal']} account={r['account_id']} tax={r['tax_ids']} analytic={r['analytic_distribution']}")
        else:
            print(f"  {r['display_type']:8} {str(r['name'])[:40]:40} account={r['account_id']} debit={r['debit']} credit={r['credit']}")
    print("stock moves voor/na:", uit["stock_moves_voor_na"])
    print("analytic lines:", [(a["amount"], a["general_account_id"], a["product_id"], a["unit_amount"]) for a in uit["analytic_lines"]])
    print("bijlage:", uit["bijlage"])
    print("refund:", uit["refund"]["name"], uit["refund"]["state"], uit["refund"]["amount_total"])
    print("origineel na reversal:", uit["origineel_na_reversal"]["payment_state"], uit["origineel_na_reversal"]["amount_residual"])


def opruimen(c: OdooJson2) -> None:
    st = status(c)
    for p in st["partners"]:
        if p["active"]:
            c.schrijf("res.partner", "write", reden="TEST-partner archiveren", ids=[p["id"]], vals={"active": False})
    for p in st["producten"]:
        if p["active"]:
            c.schrijf("product.product", "write", reden="TEST-product archiveren", ids=[p["id"]], vals={"active": False},
                      context=CTX)
    print("opgeruimd (gearchiveerd, niets verwijderd)")


if __name__ == "__main__":
    c = OdooJson2()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "run":
        run(c)
    elif cmd == "opruimen":
        opruimen(c)
    else:
        print(json.dumps(status(c), default=str, indent=1)[:4000])
