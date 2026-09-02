#!/usr/bin/env python3
"""Odoo STAP-0 deel 1 — VERBINDING & INVENTARIS, strikt read-only (02-09-2026).

Rapporteert versie, API-gebruiker + rechten, geïnstalleerde modules, bedrijf + lock-dates,
rekeningschema, btw-codes mét aangifte-tags, dagboeken, partners, analytic plans/accounts,
nummerreeksen, veldenlijsten van account.move/account.move.line, foutsemantiek en een
rate-observatie. Uitvoer: verkenning/output/odoo_stap0_inventaris.json (gitignored) + samenvatting.
Draaien: backend/.venv/bin/python verkenning/odoo_stap0_inventaris.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from odoo_stap0_client import OdooFout, OdooJson2, bewaar  # noqa: E402

c = OdooJson2()
R: dict = {}


def sectie(naam: str):
    print(f"\n== {naam} ==")


# 1. versie + gebruiker
sectie("versie + gebruiker")
R["versie"] = c.versie()
print("server:", R["versie"]["server_version"])
ctx = c.call("res.users", "context_get")
uid = ctx["uid"]
uf = c.fields_get("res.users")
groep_veld = "group_ids" if "group_ids" in uf else "groups_id"
gebruiker = c.read("res.users", [uid], ["name", "login", "share", "active", groep_veld, "company_id", "company_ids"])[0]
groepen = c.read("res.groups", gebruiker[groep_veld], ["full_name" if "full_name" in c.fields_get("res.groups") else "name"])
R["gebruiker"] = {"uid": uid, "login_gemaskeerd": gebruiker["login"][:3] + "…", "naam": gebruiker["name"],
                  "share": gebruiker["share"], "groepen": sorted(g.get("full_name") or g.get("name") for g in groepen),
                  "context": ctx, "groep_veld": groep_veld}
print("uid", uid, "| groepen:", len(groepen))
for g in R["gebruiker"]["groepen"]:
    print("   ", g)

# rechten-probe per model (has_access = Odoo ≥ 18)
sectie("rechten (has_access)")
rechten = {}
for model in ["account.move", "account.move.line", "res.partner", "account.account", "account.tax", "account.journal",
              "account.analytic.account", "account.analytic.plan", "account.analytic.line", "ir.attachment",
              "account.move.reversal", "ir.model.data", "res.company", "account.payment", "account.bank.statement.line"]:
    rechten[model] = {}
    for op in ["read", "create", "write", "unlink"]:
        try:
            rechten[model][op] = bool(c.call(model, "has_access", operation=op))
        except OdooFout as f:
            rechten[model][op] = f"FOUT {f.status} {f.naam}"
    print(f"   {model:<32}", " ".join(f"{op}={'✓' if v is True else ('✗' if v is False else v)}" for op, v in rechten[model].items()))
R["rechten"] = rechten
for xmlid in ["analytic.group_analytic_accounting", "account.group_account_manager", "account.group_account_user",
              "account.group_account_invoice", "base.group_system", "base.group_erp_manager", "account.group_account_readonly"]:
    try:
        R.setdefault("has_group", {})[xmlid] = c.call("res.users", "has_group", ids=[uid], group_ext_id=xmlid)
    except OdooFout as f:
        R.setdefault("has_group", {})[xmlid] = f"FOUT {f.status} {f.naam}: {(f.melding or '')[:120]}"
print("has_group:", R["has_group"])

# 2. modules
sectie("modules")
mods = c.search_read("ir.module.module", [["state", "=", "installed"]], ["name", "shortdesc", "latest_version"], order="name")
R["modules_geinstalleerd"] = [m["name"] for m in mods]
relevant = [m for m in mods if any(k in m["name"] for k in ("account", "analytic", "project", "l10n_nl", "documents", "invoice", "purchase", "sale", "stock", "hr_timesheet", "base_vat", "peppol", "edi"))]
print(f"{len(mods)} geïnstalleerd; relevant:")
for m in relevant:
    print(f"   {m['name']:<40} {m['shortdesc']}")
R["modules_relevant"] = [(m["name"], m["shortdesc"]) for m in relevant]

# 3. bedrijf + lock dates + instellingen
sectie("bedrijf")
cf = c.fields_get("res.company")
wens = ["name", "vat", "company_registry", "currency_id", "country_id", "fiscalyear_lock_date", "tax_lock_date",
        "sale_lock_date", "purchase_lock_date", "hard_lock_date", "period_lock_date", "tax_calculation_rounding_method",
        "anglo_saxon_accounting", "account_purchase_tax_id", "account_sale_tax_id", "chart_template", "vat_check_vies",
        "extract_in_invoice_digitalization_mode", "extract_out_invoice_digitalization_mode", "account_fiscal_country_id",
        "analytic_plan_id", "fiscalyear_last_day", "fiscalyear_last_month", "quick_edit_mode", "account_storno",
        "account_default_credit_limit", "invoice_is_email", "invoice_is_print", "account_journal_suspense_account_id",
        "transfer_account_id", "account_opening_move_id", "expects_chart_of_accounts", "autopost_bills"]
velden = [v for v in wens if v in cf]
bedrijf = c.search_read("res.company", [], velden)
R["bedrijf"] = bedrijf
R["bedrijf_velden_ontbrekend"] = [v for v in wens if v not in cf]
for b in bedrijf:
    for k, v in b.items():
        print(f"   {k:<44} {v}")
print("   (niet-bestaande velden:", R["bedrijf_velden_ontbrekend"], ")")
# lock-uitzonderingen (Odoo 18+)
try:
    R["lock_exceptions"] = c.search_read("account.lock_exception", [], ["company_id", "lock_date_field", "lock_date", "end_datetime", "state"])
except OdooFout as f:
    R["lock_exceptions"] = f"n.v.t. ({f.naam})"
print("   lock_exceptions:", R["lock_exceptions"])

# 4. rekeningschema
sectie("rekeningschema (account.account)")
af = c.fields_get("account.account")
acc_velden = [v for v in ["code", "name", "account_type", "reconcile", "deprecated", "tax_ids", "tag_ids", "company_ids", "active", "internal_group", "non_trade"] if v in af]
accounts = c.search_read("account.account", [], acc_velden, order="code")
R["accounts"] = accounts
R["accounts_velden"] = sorted(af)
print(f"{len(accounts)} rekeningen; per type:")
per_type: dict[str, int] = {}
for a in accounts:
    per_type[a["account_type"]] = per_type.get(a["account_type"], 0) + 1
for t, n in sorted(per_type.items()):
    print(f"   {t:<32} {n}")
print("   voorbeelden:", [(a["code"], a["name"]) for a in accounts[:6]])
kosten = [a for a in accounts if a["account_type"] == "expense"]
print("   kosten-rekeningen (eerste 8):", [(a["code"], a["name"]) for a in kosten[:8]])
print("   payable:", [(a["code"], a["name"]) for a in accounts if a["account_type"] == "liability_payable"])
print("   receivable:", [(a["code"], a["name"]) for a in accounts if a["account_type"] == "asset_receivable"])

# 5. btw-codes mét aangifte-mapping (repartition lines → tags)
sectie("btw-codes (account.tax)")
tf = c.fields_get("account.tax")
tax_velden = [v for v in ["name", "description", "invoice_label", "amount", "amount_type", "type_tax_use", "tax_scope", "tax_group_id", "active",
                          "price_include", "price_include_override", "include_base_amount", "is_base_affected", "country_id",
                          "invoice_repartition_line_ids", "refund_repartition_line_ids", "repartition_line_ids", "sequence", "tax_exigibility"] if v in tf]
taxes = c.search_read("account.tax", [["active", "in", [True, False]], ["company_id", "=", 1]], tax_velden, order="type_tax_use,sequence,amount")
rep_ids = sorted({i for t in taxes for k in ("invoice_repartition_line_ids", "repartition_line_ids") for i in (t.get(k) or [])})
rf = c.fields_get("account.tax.repartition.line")
rep_velden = [v for v in ["repartition_type", "factor_percent", "account_id", "tag_ids", "document_type", "use_in_tax_closing", "tax_id"] if v in rf]
reps = {r["id"]: r for r in c.read("account.tax.repartition.line", rep_ids, rep_velden)} if rep_ids else {}
tag_ids = sorted({i for r in reps.values() for i in (r.get("tag_ids") or [])})
tags = {t["id"]: t for t in c.read("account.account.tag", tag_ids, ["name", "applicability", "country_id", "balance_negate"])} if tag_ids else {}
R["taxes"] = taxes
R["tax_repartition"] = reps
R["tax_tags"] = tags
R["tax_velden"] = sorted(tf)
print(f"{len(taxes)} btw-codes:")
for t in taxes:
    regels = [reps[i] for i in (t.get("invoice_repartition_line_ids") or t.get("repartition_line_ids") or []) if i in reps]
    regels = [r for r in regels if r.get("document_type", "invoice") == "invoice"]
    tagnamen = []
    for r in regels:
        for tid in r.get("tag_ids") or []:
            tagnamen.append(f"{r['repartition_type'][:4]}:{tags[tid]['name']}")
    acc = [r["account_id"][1] if r.get("account_id") else "-" for r in regels if r["repartition_type"] == "tax"]
    print(f"   [{t['id']:>3}] {t['type_tax_use']:<8} {t['amount']:>6} {t['amount_type']:<8} {'act' if t['active'] else 'INACT'} {t['name']:<45} label={t.get('invoice_label') or t.get('description')!s:<12} tags={tagnamen} btw-rek={acc}")

# 6. dagboeken
sectie("dagboeken (account.journal)")
jf = c.fields_get("account.journal")
j_velden = [v for v in ["name", "code", "type", "default_account_id", "sequence", "refund_sequence", "active", "bank_account_id",
                        "suspense_account_id", "restrict_mode_hash_table", "alias_id", "invoice_reference_type", "invoice_reference_model",
                        "sequence_override_regex", "payment_sequence", "company_id"] if v in jf]
journals = c.search_read("account.journal", [["active", "in", [True, False]], ["company_id", "=", 1]], j_velden, order="sequence")
R["journals"] = journals
for j in journals:
    print(f"   [{j['id']:>2}] {j['code']:<6} {j['type']:<9} {j['name']:<32} default={j.get('default_account_id')} refund_seq={j.get('refund_sequence')} hash={j.get('restrict_mode_hash_table')}")

# 7. partners
sectie("partners (res.partner)")
pf = c.fields_get("res.partner")
R["partner_velden_relevant"] = {k: pf[k] for k in ["vat", "company_registry", "supplier_rank", "customer_rank", "property_payment_term_id",
                                                      "property_supplier_payment_term_id", "property_account_payable_id", "property_account_receivable_id",
                                                      "bank_ids", "peppol_eas", "peppol_endpoint", "is_company", "ref", "email", "invoice_sending_method",
                                                      "invoice_edi_format", "country_id", "l10n_nl_kvk", "l10n_nl_oin"] if k in pf}
partners = c.search_read("res.partner", [["active", "in", [True, False]]], [v for v in ["name", "is_company", "vat", "company_registry", "supplier_rank", "customer_rank", "parent_id", "active", "type", "country_id"] if v in pf], order="id")
R["partners"] = partners
print(f"{len(partners)} partners:")
for p in partners:
    print(f"   [{p['id']:>3}] {p['name']:<40} bedrijf={p['is_company']} vat={p.get('vat')} kvk={p.get('company_registry')} sup={p.get('supplier_rank')} cust={p.get('customer_rank')} type={p.get('type')} act={p['active']}")
print("   relevante partnervelden aanwezig:", sorted(R["partner_velden_relevant"]))
print("   ontbrekend:", [k for k in ["l10n_nl_kvk", "peppol_eas", "company_registry"] if k not in pf])

# 8. analytic
sectie("analytic plans/accounts (projecten)")
try:
    plf = c.fields_get("account.analytic.plan")
    plans = c.search_read("account.analytic.plan", [], [v for v in ["name", "parent_id", "default_applicability", "color", "complete_name"] if v in plf])
    R["analytic_plans"] = plans
    for p in plans:
        print("   plan:", p)
    aaf = c.fields_get("account.analytic.account")
    R["analytic_account_velden"] = sorted(aaf)
    aas = c.search_read("account.analytic.account", [["active", "in", [True, False]]], [v for v in ["name", "code", "plan_id", "root_plan_id", "company_id", "partner_id", "active"] if v in aaf])
    R["analytic_accounts"] = aas
    print(f"   {len(aas)} analytic accounts:", aas[:10])
    # welke Json-kolommen kent account.move.line voor de distributie (x_plan…_id-velden)
    mlf = c.fields_get("account.move.line")
    R["move_line_velden"] = {k: {kk: vv for kk, vv in v.items() if kk in ("type", "string", "relation", "readonly")} for k, v in mlf.items()}
    print("   analytic-velden op account.move.line:", sorted(k for k in mlf if "analytic" in k or k.startswith("x_plan")))
except OdooFout as f:
    R["analytic_fout"] = str(f)
    print("   analytic fout:", f)
R["project_project"] = None
if "project" in R["modules_geinstalleerd"]:
    R["project_project"] = c.search_read("project.project", [], ["name", "analytic_account_id" if "analytic_account_id" in c.fields_get("project.project") else "name"])
    print("   project.project:", R["project_project"])
else:
    print("   module 'project' NIET geïnstalleerd → geen project.project; analytic accounts zijn het projectanker")

# 9. nummerreeksen + moves
sectie("nummering + documenten")
mf = c.fields_get("account.move")
R["move_velden"] = {k: {kk: vv for kk, vv in v.items() if kk in ("type", "string", "relation", "readonly", "required")} for k, v in mf.items()}
kern = ["name", "ref", "payment_reference", "invoice_date", "date", "invoice_date_due", "invoice_payment_term_id", "state", "move_type",
        "partner_id", "journal_id", "invoice_line_ids", "line_ids", "amount_untaxed", "amount_tax", "amount_total", "amount_residual",
        "payment_state", "reversed_entry_id", "reversal_move_ids", "reversal_move_id", "duplicated_ref_ids", "message_main_attachment_id",
        "auto_post", "sequence_prefix", "sequence_number", "tax_totals", "invoice_origin", "narration", "posted_before", "inalterable_hash",
        "secure_sequence_number", "to_check", "checked", "invoice_vendor_bill_id", "extract_state", "fiscal_position_id", "currency_id",
        "invoice_incoterm_id", "partner_bank_id", "always_tax_exigible", "is_move_sent", "tax_cash_basis_origin_move_id", "quick_edit_total_amount",
        "l10n_nl_reports_sbr_attachment_ids", "purchase_id", "attachment_ids", "invoice_pdf_report_id", "restrict_mode_hash_table", "made_sequence_gap"]
print("   account.move kernvelden aanwezig:", [k for k in kern if k in mf])
print("   account.move kernvelden ONTBREKEND:", [k for k in kern if k not in mf])
groepen = c.call("account.move", "read_group", domain=[], fields=["id"], groupby=["move_type", "state"], lazy=False)
R["moves_per_type_state"] = groepen
print("   documenten per type/state:", [(g["move_type"], g["state"], g["__count"]) for g in groepen])
seqs = c.search_read("ir.sequence", [], ["name", "code", "prefix", "padding", "number_next_actual", "implementation", "use_date_range"])
R["ir_sequence"] = seqs
print(f"   ir.sequence ({len(seqs)}):", [(s["code"], s["prefix"]) for s in seqs][:20])
pt = c.search_read("account.payment.term", [], ["name", "line_ids"])
R["payment_terms"] = pt
print("   betaaltermijnen:", [(p["id"], p["name"]) for p in pt])
fp = c.search_read("account.fiscal.position", [], ["name", "auto_apply", "country_id", "vat_required"])
R["fiscal_positions"] = fp
print("   fiscale posities:", [(f["id"], f["name"], f.get("country_id")) for f in fp])
ic = c.search_read("res.config.settings", [], ["id"], limit=1) if False else None  # res.config.settings is transient — niet lezen

# 10. foutsemantiek (read-only)
sectie("foutsemantiek")
fouten = {}
for oms, (model, meth, kw) in {
    "MissingError (read onbekend id)": ("account.move", "read", {"ids": [999999999], "fields": ["name"]}),
    "ValueError (onbekend veld)": ("account.move", "search_read", {"domain": [], "fields": ["bestaat_niet"]}),
    "AccessError/onbekend model": ("model.bestaat.niet", "search_read", {"domain": [], "fields": ["id"]}),
    "verkeerde methode": ("account.move", "methode_bestaat_niet", {}),
    "private methode": ("account.move", "_compute_amount", {}),
}.items():
    try:
        c.call(model, meth, **kw)
        fouten[oms] = "GEEN FOUT (?)"
    except OdooFout as f:
        fouten[oms] = {"http": f.status, "name": f.naam, "message": (f.melding or "")[:200]}
    print(f"   {oms:<36} → {fouten[oms]}")
R["foutsemantiek"] = fouten

# 11. rate-observatie: 40 lichte reads achter elkaar
sectie("rate-observatie (40 × search_count)")
t0 = time.monotonic()
statussen = []
for _ in range(40):
    try:
        c.call("res.partner", "search_count", domain=[])
        statussen.append(200)
    except OdooFout as f:
        statussen.append(f.status)
duur = time.monotonic() - t0
ms = [a["ms"] for a in c.aanroepen[-40:]]
R["rate_observatie"] = {"n": 40, "totaal_s": round(duur, 2), "statussen": sorted(set(statussen)), "ms_min": min(ms), "ms_med": sorted(ms)[20], "ms_max": max(ms)}
print("  ", R["rate_observatie"])

p = bewaar("odoo_stap0_inventaris.json", R)
print("\nbewaard:", p)
