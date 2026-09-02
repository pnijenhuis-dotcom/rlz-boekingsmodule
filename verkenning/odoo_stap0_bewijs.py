#!/usr/bin/env python3
"""Odoo STAP-0 deel 2 — de TWEE toegestane bewijs-cycli (besluit Peter 02-09-2026).

    a         cyclus A (inkoop): crediteur + project-analytic aanmaken (indien nodig), vendor bill
              "TEST-ODOO-STAP0-A" met twee regels (2 GB's, 21 % + 9 %, analytic per regel), vervaldatum,
              boekdatum-test, btw-cent-override, duplicaat-signaal (tweede CONCEPT, nooit gepost,
              geannuleerd), posten, PDF-bijlage, alles terug-lezen, reversal (creditnota) + afletteren.
    b         cyclus B (memoriaal): eerst een ONGEBALANCEERDE create (verwacht: fout, niets bewaard),
              dan "TEST-ODOO-STAP0-B" saldo-0 → posten → reversal.
    opruimen  TEST-crediteur + TEST-analytic archiveren (active=False — nooit verwijderen).
    status    read-only stand van alle TEST-ODOO-STAP0-documenten.

Elke stap is idempotent (zoek-vóór-create op referentie/naam) — een herstart maakt nooit een tweede
document. Alles gescope'd op company 1 (Universal Steigerbouw B.V.) via context + expliciet company_id;
de database is multi-company (10 bedrijven, Universal Verkoop draait er al live in).
Gebruik: backend/.venv/bin/python verkenning/odoo_stap0_bewijs.py <a|b|opruimen|status>
"""

from __future__ import annotations

import base64
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from odoo_stap0_client import OdooFout, OdooJson2, bewaar  # noqa: E402

COMPANY = 1
CTX = {"allowed_company_ids": [COMPANY]}
JOURNAL_BILL, JOURNAL_MISC = 9, 10
TAX_21, TAX_9 = 14, 13
ACC_TOOLS, ACC_MACHINE, ACC_PAYABLE, ACC_KOSTPRIJS, ACC_VOORRAAD = 258, 252, 131, 336, 208
LAND_NL = 165
PARTNER_NAAM = "TEST-ODOO-STAP0 Crediteur B.V."
PARTNER_VAT = "NL123456782B01"  # elfproef-geldig, fictief
PARTNER_KVK = "12345678"
ANALYTIC_NAAM = "TEST-ODOO-STAP0 Project"
REF_A, REF_B = "TEST-ODOO-STAP0-A", "TEST-ODOO-STAP0-B"
FACTUURDATUM, VERVALDATUM = "2026-08-15", "2026-09-14"
VANDAAG = date.today().isoformat()
PDF_BYTES = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 60>>stream\nBT /F1 12 Tf 10 50 Td (TEST-ODOO-STAP0-A bijlage) Tj ET\nendstream\nendobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
)

c = OdooJson2()
R: dict = {"vandaag": VANDAAG, "company": COMPANY}
MOVE_VELDEN = ["name", "ref", "payment_reference", "state", "move_type", "partner_id", "journal_id", "company_id",
               "invoice_date", "date", "invoice_date_due", "invoice_payment_term_id", "amount_untaxed", "amount_tax",
               "amount_total", "amount_residual", "payment_state", "duplicated_ref_ids", "reversed_entry_id",
               "reversal_move_ids", "message_main_attachment_id", "attachment_ids", "extract_state", "posted_before",
               "sequence_prefix", "sequence_number", "inalterable_hash", "auto_post", "checked", "narration", "line_ids"]
LINE_VELDEN = ["name", "display_type", "account_id", "quantity", "price_unit", "tax_ids", "tax_line_id",
               "analytic_distribution", "debit", "credit", "balance", "amount_currency", "price_subtotal", "price_total",
               "tax_tag_ids", "tax_base_amount", "date_maturity", "partner_id", "reconciled", "full_reconcile_id"]


def log(*a):
    print(*a, flush=True)


def move_lezen(move_id: int) -> dict:
    m = c.read("account.move", [move_id], MOVE_VELDEN)[0]
    m["regels"] = c.search_read("account.move.line", [["move_id", "=", move_id]], LINE_VELDEN, order="id", context=CTX)
    return m


def analytic_lines(move_id: int) -> list[dict]:
    return c.search_read("account.analytic.line", [["move_line_id.move_id", "=", move_id]],
                         ["name", "account_id", "amount", "date", "general_account_id", "move_line_id", "partner_id", "company_id", "ref"],
                         order="id", context=CTX)


def zoek_move(ref: str, move_type: str) -> list[dict]:
    return c.search_read("account.move", [["ref", "=", ref], ["move_type", "=", move_type], ["company_id", "=", COMPANY]],
                         ["id", "name", "state", "amount_total"], order="id", context=CTX)


def toon_move(m: dict, kop: str) -> None:
    log(f"--- {kop}: id={m['id']} name={m['name']!r} state={m['state']} type={m['move_type']} ref={m['ref']!r} "
        f"invoice_date={m['invoice_date']} date={m['date']} due={m['invoice_date_due']} term={m['invoice_payment_term_id']} "
        f"untaxed={m['amount_untaxed']} tax={m['amount_tax']} total={m['amount_total']} residual={m['amount_residual']} "
        f"pay={m['payment_state']} dup={m['duplicated_ref_ids']} rev_of={m['reversed_entry_id']} revs={m['reversal_move_ids']} "
        f"main_att={m['message_main_attachment_id']} extract={m['extract_state']} seq={m['sequence_prefix']}/{m['sequence_number']} hash={m['inalterable_hash']}")
    for r in m["regels"]:
        log(f"      [{r['id']}] {r['display_type']:<13} {str(r['account_id'][1])[:34]:<34} q={r['quantity']} pu={r['price_unit']} "
            f"tax={r['tax_ids']} taxline={r['tax_line_id'] and r['tax_line_id'][0]} an={r['analytic_distribution']} "
            f"D={r['debit']} C={r['credit']} bal={r['balance']} sub={r['price_subtotal']} tot={r['price_total']} tags={r['tax_tag_ids']} "
            f"mat={r['date_maturity']} rec={r['reconciled']} name={r['name']!r}")


# ----------------------------------------------------------------------------- cyclus A
def cyclus_a() -> None:
    # 1. crediteur — zoek-vóór-create (op btw-nummer, dan naam)
    partner = c.search_read("res.partner", ["|", ["vat", "=", PARTNER_VAT], ["name", "=", PARTNER_NAAM], ["active", "in", [True, False]]],
                            ["name", "vat", "company_registry", "active", "company_id", "supplier_rank"], context=CTX)
    if partner:
        pid = partner[0]["id"]
        log("crediteur bestaat al:", partner[0])
    else:
        pid = c.schrijf("res.partner", "create", reden="cyclus A: TEST-crediteur", vals_list=[{
            "name": PARTNER_NAAM, "is_company": True, "company_id": COMPANY, "vat": PARTNER_VAT,
            "company_registry": PARTNER_KVK, "country_id": LAND_NL, "supplier_rank": 1,
        }], context=CTX)[0]
        log("crediteur aangemaakt id", pid)
    R["partner"] = c.read("res.partner", [pid], ["name", "vat", "company_registry", "country_id", "company_id", "supplier_rank",
                                                   "property_account_payable_id", "property_supplier_payment_term_id", "autopost_bills",
                                                   "peppol_eas", "peppol_endpoint", "active"])[0]
    log("crediteur terug-gelezen:", R["partner"])

    # 2. project = analytic account in plan 'Project' (id 1), company 1
    an = c.search_read("account.analytic.account", [["name", "=", ANALYTIC_NAAM], ["active", "in", [True, False]]],
                       ["name", "code", "plan_id", "company_id", "active"], context=CTX)
    if an:
        aid = an[0]["id"]
        log("analytic bestaat al:", an[0])
    else:
        aid = c.schrijf("account.analytic.account", "create", reden="cyclus A: TEST-project (analytic)", vals_list=[{
            "name": ANALYTIC_NAAM, "code": "TEST-STAP0", "plan_id": 1, "company_id": COMPANY}], context=CTX)[0]
        log("analytic aangemaakt id", aid)
    R["analytic"] = c.read("account.analytic.account", [aid], ["name", "code", "plan_id", "root_plan_id", "company_id", "active"])[0]

    # 3. vendor bill — idempotentie: zoek op ref + partner + type + company vóór create
    bestaand = c.search_read("account.move", [["ref", "=", REF_A], ["move_type", "=", "in_invoice"], ["partner_id", "=", pid],
                                              ["company_id", "=", COMPANY], ["state", "!=", "cancel"]], ["id", "name", "state"], order="id", context=CTX)
    if bestaand:
        mid = bestaand[0]["id"]
        log("bill bestaat al (idempotentie-zoekpad):", bestaand)
        R["idempotentie_zoekpad"] = "bestaand gevonden op ref+partner+type+company — geen tweede create"
    else:
        vals = {
            "move_type": "in_invoice", "company_id": COMPANY, "journal_id": JOURNAL_BILL, "partner_id": pid,
            "ref": REF_A, "payment_reference": "TEST-STAP0-A-KENMERK",
            "invoice_date": FACTUURDATUM,  # bewust GEEN `date`: wat wordt de boekdatum-default?
            "invoice_payment_term_id": False, "invoice_date_due": VERVALDATUM,
            "narration": "STAP-0-verkenning Administratiekantoor Nijenhuis — testdocument, wordt tegengeboekt",
            "invoice_line_ids": [
                [0, 0, {"name": "Regel 1 — gereedschap (21%)", "account_id": ACC_TOOLS, "quantity": 1, "price_unit": 100.00,
                        "tax_ids": [[6, 0, [TAX_21]]], "analytic_distribution": {str(aid): 100}}],
                [0, 0, {"name": "Regel 2 — machinehuur (9%)", "account_id": ACC_MACHINE, "quantity": 1, "price_unit": 10.00,
                        "tax_ids": [[6, 0, [TAX_9]]], "analytic_distribution": {str(aid): 100}}],
            ],
        }
        mid = c.schrijf("account.move", "create", reden="cyclus A: vendor bill TEST-ODOO-STAP0-A", vals_list=[vals], context=CTX)[0]
        log("bill aangemaakt id", mid)
    m = move_lezen(mid)
    toon_move(m, "A ná create (concept)")
    R["a_concept"] = m
    R["boekdatum_default"] = {"invoice_date": m["invoice_date"], "date_zonder_opgave": m["date"]}

    if m["state"] == "draft":
        # 4. boekdatum-test: `date` los van `invoice_date` schrijfbaar? (BookDate-les)
        c.schrijf("account.move", "write", reden="cyclus A: boekdatum-test date=2026-08-20", ids=[mid], vals={"date": "2026-08-20"}, context=CTX)
        d1 = c.read("account.move", [mid], ["invoice_date", "date"])[0]
        c.schrijf("account.move", "write", reden="cyclus A: boekdatum terug = factuurdatum", ids=[mid], vals={"date": FACTUURDATUM}, context=CTX)
        d2 = c.read("account.move", [mid], ["invoice_date", "date", "invoice_date_due"])[0]
        R["boekdatum_test"] = {"na_write_20": d1, "na_terugzetten": d2}
        log("boekdatum-test:", R["boekdatum_test"])

        # 5. btw-cent-override: factuur zegt 21,01 i.p.v. Odoo's 21,00 op de 21 %-regel
        taxlines = [r for r in m["regels"] if r["display_type"] == "tax" and r["tax_line_id"] and r["tax_line_id"][0] == TAX_21]
        R["btw_override"] = {"voor": {"amount_tax": m["amount_tax"], "amount_total": m["amount_total"], "taxline": taxlines[0] if taxlines else None}}
        try:
            c.schrijf("account.move.line", "write", reden="cyclus A: btw-regel 21% → 21,01 (cent-exactheid)", ids=[taxlines[0]["id"]],
                      vals={"balance": 21.01}, context=CTX)
            R["btw_override"]["methode"] = "write balance op de tax-regel"
        except OdooFout as f:
            R["btw_override"]["write_balance_fout"] = str(f)
            try:
                c.schrijf("account.move.line", "write", reden="cyclus A: btw-regel amount_currency → 21,01", ids=[taxlines[0]["id"]],
                          vals={"amount_currency": 21.01}, context=CTX)
                R["btw_override"]["methode"] = "write amount_currency op de tax-regel"
            except OdooFout as f2:
                R["btw_override"]["write_amount_currency_fout"] = str(f2)
        m = move_lezen(mid)
        R["btw_override"]["na"] = {"amount_tax": m["amount_tax"], "amount_total": m["amount_total"],
                                   "regels": [(r["display_type"], r["balance"]) for r in m["regels"]]}
        toon_move(m, "A ná btw-override (concept)")

        # 6. duplicaat-signaal: tweede CONCEPT met dezelfde ref+partner (wordt NOOIT gepost; daarna geannuleerd)
        dup = c.search_read("account.move", [["ref", "=", REF_A], ["move_type", "=", "in_invoice"], ["company_id", "=", COMPANY], ["id", "!=", mid]],
                            ["id", "state", "duplicated_ref_ids"], context=CTX)
        if not dup:
            did = c.schrijf("account.move", "create", reden="cyclus A: dubbele create (concept) voor duplicaat-signaal", vals_list=[{
                "move_type": "in_invoice", "company_id": COMPANY, "journal_id": JOURNAL_BILL, "partner_id": pid, "ref": REF_A,
                "invoice_date": FACTUURDATUM, "invoice_payment_term_id": False, "invoice_date_due": VERVALDATUM,
                "invoice_line_ids": [[0, 0, {"name": "duplicaat-test", "account_id": ACC_TOOLS, "quantity": 1, "price_unit": 1.00, "tax_ids": [[6, 0, []]]}]],
            }], context=CTX)[0]
        else:
            did = dup[0]["id"]
        R["duplicaat"] = {"dup_id": did, "dup_signaal_op_dup": c.read("account.move", [did], ["duplicated_ref_ids", "state", "name"])[0],
                          "dup_signaal_op_origineel": c.read("account.move", [mid], ["duplicated_ref_ids"])[0]}
        log("duplicaat:", R["duplicaat"])
        if R["duplicaat"]["dup_signaal_op_dup"]["state"] == "draft":
            c.schrijf("account.move", "button_cancel", reden="cyclus A: duplicaat-concept annuleren (nooit gepost, niet verwijderd)", ids=[did], context=CTX)
        R["duplicaat"]["dup_na_cancel"] = c.read("account.move", [did], ["state", "name", "ref"])[0]
        log("duplicaat ná cancel:", R["duplicaat"]["dup_na_cancel"])

        # 7. posten
        c.schrijf("account.move", "action_post", reden="cyclus A: posten", ids=[mid], context=CTX)
        m = move_lezen(mid)
    toon_move(m, "A ná action_post")
    R["a_geboekt"] = m
    R["a_analytic_lines"] = analytic_lines(mid)
    log("analytic lines:", R["a_analytic_lines"])

    # 8. PDF-bijlage — ná het posten (extract_in_invoice_digitalization_mode = auto_send op concepten!)
    atts = c.search_read("ir.attachment", [["res_model", "=", "account.move"], ["res_id", "=", mid]],
                         ["name", "mimetype", "file_size", "checksum", "res_field", "type"], context=CTX)
    if not atts:
        att_id = c.schrijf("ir.attachment", "create", reden="cyclus A: PDF-bijlage", vals_list=[{
            "name": "TEST-ODOO-STAP0-A.pdf", "res_model": "account.move", "res_id": mid, "mimetype": "application/pdf",
            "datas": base64.b64encode(PDF_BYTES).decode()}], context=CTX)[0]
    else:
        att_id = atts[0]["id"]
    m2 = c.read("account.move", [mid], ["message_main_attachment_id", "attachment_ids", "extract_state"])[0]
    R["bijlage"] = {"attachment_id": att_id, "move_na_attach": m2}
    if not m2["message_main_attachment_id"]:
        c.schrijf("ir.attachment", "register_as_main_attachment", reden="cyclus A: bijlage als hoofdbijlage", ids=[att_id], force=True, context=CTX)
        R["bijlage"]["na_register_main"] = c.read("account.move", [mid], ["message_main_attachment_id", "extract_state"])[0]
    R["bijlage"]["attachment"] = c.read("ir.attachment", [att_id], ["name", "mimetype", "file_size", "checksum", "res_model", "res_id", "res_field", "type"])[0]
    terug = c.read("ir.attachment", [att_id], ["datas"])[0]["datas"]
    R["bijlage"]["bytes_identiek"] = base64.b64decode(terug) == PDF_BYTES
    log("bijlage:", {k: v for k, v in R["bijlage"].items()})

    # 9. terugdraaien = reversal (creditnota als APART document) via de wizard
    m = move_lezen(mid)
    if not m["reversal_move_ids"]:
        wiz = c.schrijf("account.move.reversal", "create", reden="cyclus A: reversal-wizard", vals_list=[{
            "move_ids": [[6, 0, [mid]]], "reason": "STAP-0 storno TEST-ODOO-STAP0-A", "journal_id": JOURNAL_BILL,
            "date": VANDAAG, "company_id": COMPANY}], context={**CTX, "active_model": "account.move", "active_ids": [mid]})[0]
        actie = c.schrijf("account.move.reversal", "reverse_moves", reden="cyclus A: reverse_moves", ids=[wiz], context=CTX)
        R["reversal_actie"] = actie
        log("reverse_moves →", {k: actie.get(k) for k in ("res_model", "res_id", "domain", "view_mode")} if isinstance(actie, dict) else actie)
        m = move_lezen(mid)
    rev_ids = m["reversal_move_ids"]
    rev = move_lezen(rev_ids[0])
    toon_move(rev, "A reversal (creditnota) direct ná wizard")
    if rev["state"] == "draft":
        c.schrijf("account.move", "action_post", reden="cyclus A: reversal posten", ids=[rev["id"]], context=CTX)
        rev = move_lezen(rev["id"])
        toon_move(rev, "A reversal ná action_post")
    # afletteren origineel ↔ creditnota op de crediteurenrekening
    pay_o = [r["id"] for r in move_lezen(mid)["regels"] if r["display_type"] == "payment_term"]
    pay_r = [r["id"] for r in rev["regels"] if r["display_type"] == "payment_term"]
    m = move_lezen(mid)
    if m["payment_state"] not in ("reversed", "paid") and pay_o and pay_r:
        c.schrijf("account.move.line", "reconcile", reden="cyclus A: afletteren origineel ↔ creditnota", ids=pay_o + pay_r, context=CTX)
        m = move_lezen(mid)
        rev = move_lezen(rev["id"])
    toon_move(m, "A origineel EINDSTAND")
    toon_move(rev, "A reversal EINDSTAND")
    R["a_eind"] = m
    R["a_reversal_eind"] = rev
    R["a_reversal_analytic_lines"] = analytic_lines(rev["id"])
    log("reversal analytic lines:", R["a_reversal_analytic_lines"])
    bewaar("odoo_stap0_bewijs_a.json", R)


# ----------------------------------------------------------------------------- cyclus B
def cyclus_b() -> None:
    bestaand = zoek_move(REF_B, "entry")
    if not bestaand:
        # 1. saldo-0-afdwinging: ongebalanceerde create → verwacht fout, niets bewaard
        try:
            c.schrijf("account.move", "create", reden="cyclus B: ONGEBALANCEERDE create (verwacht: fout)", vals_list=[{
                "move_type": "entry", "company_id": COMPANY, "journal_id": JOURNAL_MISC, "date": FACTUURDATUM, "ref": REF_B,
                "line_ids": [[0, 0, {"account_id": ACC_KOSTPRIJS, "name": "onbalans-test", "debit": 250.00, "credit": 0}],
                             [0, 0, {"account_id": ACC_VOORRAAD, "name": "onbalans-test", "debit": 0, "credit": 240.00}]]}], context=CTX)
            R["onbalans"] = "GEEN FOUT — concept met onbalans is aangemaakt (!)"
        except OdooFout as f:
            R["onbalans"] = {"http": f.status, "name": f.naam, "message": (f.melding or "")[:400]}
        R["onbalans_bewaard"] = zoek_move(REF_B, "entry")
        log("onbalans:", R["onbalans"], "| bewaard:", R["onbalans_bewaard"])
        if R["onbalans_bewaard"]:
            log("!! onbalans-concept bestaat — wordt niet gepost; handmatig beoordelen")
            return
        # 2. saldo-0 memoriaal
        mid = c.schrijf("account.move", "create", reden="cyclus B: memoriaal TEST-ODOO-STAP0-B", vals_list=[{
            "move_type": "entry", "company_id": COMPANY, "journal_id": JOURNAL_MISC, "date": FACTUURDATUM, "ref": REF_B,
            "narration": "STAP-0-verkenning — kostprijsmemoriaal-test, wordt teruggedraaid",
            "line_ids": [[0, 0, {"account_id": ACC_KOSTPRIJS, "name": "Kostprijs testperiode", "debit": 250.00, "credit": 0}],
                         [0, 0, {"account_id": ACC_VOORRAAD, "name": "Aan voorraad (kostprijs testperiode)", "debit": 0, "credit": 250.00}]]}], context=CTX)[0]
    else:
        mid = bestaand[0]["id"]
        log("memoriaal bestaat al:", bestaand)
    m = move_lezen(mid)
    toon_move(m, "B ná create")
    R["b_concept"] = m
    if m["state"] == "draft":
        c.schrijf("account.move", "action_post", reden="cyclus B: posten", ids=[mid], context=CTX)
        m = move_lezen(mid)
    toon_move(m, "B ná action_post")
    R["b_geboekt"] = m
    if not m["reversal_move_ids"]:
        wiz = c.schrijf("account.move.reversal", "create", reden="cyclus B: reversal-wizard", vals_list=[{
            "move_ids": [[6, 0, [mid]]], "reason": "STAP-0 storno TEST-ODOO-STAP0-B", "journal_id": JOURNAL_MISC,
            "date": VANDAAG, "company_id": COMPANY}], context={**CTX, "active_model": "account.move", "active_ids": [mid]})[0]
        R["b_reversal_actie"] = c.schrijf("account.move.reversal", "reverse_moves", reden="cyclus B: reverse_moves", ids=[wiz], context=CTX)
        m = move_lezen(mid)
    rev = move_lezen(m["reversal_move_ids"][0])
    toon_move(rev, "B reversal direct ná wizard")
    if rev["state"] == "draft":
        c.schrijf("account.move", "action_post", reden="cyclus B: reversal posten", ids=[rev["id"]], context=CTX)
        rev = move_lezen(rev["id"])
    toon_move(move_lezen(mid), "B origineel EINDSTAND")
    toon_move(rev, "B reversal EINDSTAND")
    R["b_eind"] = move_lezen(mid)
    R["b_reversal_eind"] = rev
    bewaar("odoo_stap0_bewijs_b.json", R)


def opruimen() -> None:
    for model, dom in [("res.partner", [["name", "=", PARTNER_NAAM]]), ("account.analytic.account", [["name", "=", ANALYTIC_NAAM]])]:
        rijen = c.search_read(model, dom + [["active", "=", True]], ["name"], context=CTX)
        for r in rijen:
            c.schrijf(model, "write", reden=f"opruimen: {model} archiveren (active=False, nooit verwijderen)", ids=[r["id"]], vals={"active": False}, context=CTX)
            log("gearchiveerd:", model, r)
    status()


def status() -> None:
    for ref, t in [(REF_A, "in_invoice"), (REF_A, "in_refund"), (REF_B, "entry")]:
        for m in c.search_read("account.move", [["ref", "ilike", "TEST-ODOO-STAP0"], ["move_type", "=", t], ["company_id", "=", COMPANY]],
                               ["name", "ref", "state", "amount_total", "payment_state", "reversed_entry_id", "reversal_move_ids", "date"], order="id", context=CTX):
            log(t, m)
    log("reversals (ref bevat 'Reversal'):", c.search_read("account.move", [["ref", "ilike", "STAP0"], ["company_id", "=", COMPANY], ["reversed_entry_id", "!=", False]],
                                                          ["name", "ref", "state", "move_type", "amount_total", "reversed_entry_id"], context=CTX))
    log("partner:", c.search_read("res.partner", [["name", "=", PARTNER_NAAM], ["active", "in", [True, False]]], ["name", "active", "vat"], context=CTX))
    log("analytic:", c.search_read("account.analytic.account", [["name", "=", ANALYTIC_NAAM], ["active", "in", [True, False]]], ["name", "active"], context=CTX))
    log("alle moves company 1:", c.call("account.move", "search_count", domain=[["company_id", "=", COMPANY]], context=CTX))


if __name__ == "__main__":
    stap = sys.argv[1] if len(sys.argv) > 1 else "status"
    if stap != "a2":
        {"a": cyclus_a, "b": cyclus_b, "opruimen": opruimen, "status": status}[stap]()


def cyclus_a2() -> None:
    """Cent-herstel op de creditnota (ontdekt in cyclus A): de reversal-wizard herberekent de btw uit de
    regels (21,00) en neemt de handmatige tax-override (21,01) van het origineel NIET mee → origineel
    bleef `partial` met € 0,01 open. Herstel = Odoo's actie-19-analoog `button_draft` op de creditnota
    (zelfde document terug naar concept — kan alleen zonder hash-lock/lock-date), tax-regel gelijktrekken,
    opnieuw posten → volledige afletterng. Idempotent."""
    orig = zoek_move(REF_A, "in_invoice")
    orig = [o for o in orig if o["state"] == "posted"]
    if not orig:
        log("geen gepost origineel")
        return
    m = move_lezen(orig[0]["id"])
    if not m["reversal_move_ids"]:
        log("geen reversal")
        return
    rev = move_lezen(m["reversal_move_ids"][0])
    R["a2_voor"] = {"orig": (m["payment_state"], m["amount_residual"]), "rev": (rev["state"], rev["amount_tax"], rev["amount_total"])}
    log("a2 vóór:", R["a2_voor"])
    if m["amount_residual"] != 0 and rev["state"] == "posted":
        c.schrijf("account.move", "button_draft", reden="cyclus A2: creditnota terug naar concept (actie-19-analoog) voor cent-herstel", ids=[rev["id"]], context=CTX)
        rev = move_lezen(rev["id"])
        R["a2_na_button_draft"] = {"state": rev["state"], "name": rev["name"], "orig_payment_state": move_lezen(m["id"])["payment_state"],
                                   "orig_residual": move_lezen(m["id"])["amount_residual"]}
        log("a2 ná button_draft:", R["a2_na_button_draft"])
    if rev["state"] == "draft":
        tl = [r for r in rev["regels"] if r["display_type"] == "tax" and r["tax_line_id"] and r["tax_line_id"][0] == TAX_21][0]
        c.schrijf("account.move.line", "write", reden="cyclus A2: creditnota-btw 21% → -21,01 (spiegel van de override)", ids=[tl["id"]], vals={"balance": -21.01}, context=CTX)
        c.schrijf("account.move", "action_post", reden="cyclus A2: creditnota opnieuw posten", ids=[rev["id"]], context=CTX)
        rev = move_lezen(rev["id"])
    m = move_lezen(m["id"])
    pay_o = [r["id"] for r in m["regels"] if r["display_type"] == "payment_term"]
    pay_r = [r["id"] for r in rev["regels"] if r["display_type"] == "payment_term"]
    if m["amount_residual"] != 0:
        c.schrijf("account.move.line", "reconcile", reden="cyclus A2: afletteren origineel ↔ creditnota", ids=pay_o + pay_r, context=CTX)
        m = move_lezen(m["id"])
        rev = move_lezen(rev["id"])
    toon_move(m, "A2 origineel EINDSTAND")
    toon_move(rev, "A2 creditnota EINDSTAND")
    R["a2_eind"] = {"orig": m, "rev": rev, "rev_analytic": analytic_lines(rev["id"])}
    bewaar("odoo_stap0_bewijs_a2.json", R)


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "a2":
    cyclus_a2()
