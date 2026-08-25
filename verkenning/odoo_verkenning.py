#!/usr/bin/env python3
"""Odoo JSON-2 STAP-0-verkenning — UITSLUITEND LEZEN, geen enkele schrijfactie.

Leest ODOO_URL / ODOO_DB / ODOO_API_KEY uit verkenning/.env en rapporteert:
versie, gebruiker, bedrijven, journalen, aantallen per documenttype, grootboek,
btw-codes, relaties, analytic (projecten) en een voorbeeld-inkoopfactuur (velden).
De API-key komt nooit in de output. Draaien: python3 verkenning/odoo_verkenning.py
"""
import json
import pathlib
import urllib.error
import urllib.request

HIER = pathlib.Path(__file__).parent
env = {}
for regel in (HIER / ".env").read_text().splitlines():
    regel = regel.strip()
    if "=" in regel and not regel.startswith("#"):
        k, v = regel.split("=", 1)
        env[k.strip()] = v.strip()

URL = env["ODOO_URL"].rstrip("/")
DB = env.get("ODOO_DB", "")
KEY = env["ODOO_API_KEY"]


def call(pad, body=None, method="POST"):
    req = urllib.request.Request(URL + pad, method=method)
    req.add_header("Authorization", "bearer " + KEY)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "rlz-verkenning")
    if DB:
        req.add_header("X-Odoo-Database", DB)
    data = json.dumps(body or {}).encode() if method == "POST" else None
    try:
        with urllib.request.urlopen(req, data, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            fout = json.loads(e.read().decode())
        except Exception:
            fout = {}
        return e.code, {"naam": fout.get("name"), "melding": fout.get("message")}
    except Exception as e:  # noqa: BLE001
        return None, {"fout": str(e)}


def m(model, methode, body):
    return call(f"/json/2/{model}/{methode}", body)


print("== Odoo-verkenning (read-only) ==")
s, v = call("/web/version", method="GET")
print(f"versie: {v.get('version') if s == 200 else (s, v)}")

s, ctx = m("res.users", "context_get", {})
print(f"key geldig: {'JA' if s == 200 else (s, ctx)}")

s, bedrijven = m("res.company", "search_read", {"domain": [], "fields": ["name"]})
if s == 200:
    print(f"bedrijven ({len(bedrijven)}):", ", ".join(b["name"] for b in bedrijven))
else:
    print("bedrijven:", s, bedrijven)

s, jrn = m("account.journal", "search_read", {"domain": [], "fields": ["name", "type", "code"]})
if s == 200:
    print(f"journalen ({len(jrn)}):")
    for j in jrn:
        print(f"   {j['code']:<8} {j['type']:<10} {j['name']}")

s, groepen = m("account.move", "read_group", {
    "domain": [], "fields": ["id"], "groupby": ["move_type"], "lazy": False})
if s == 200:
    print("documenten per type:")
    for g in groepen:
        print(f"   {g['move_type']:<14} {g.get('__count', g.get('move_type_count', '?'))}")
else:
    print("documenten per type:", s, groepen)

for model, oms in [("account.account", "grootboekrekeningen"),
                   ("account.tax", "btw-codes"),
                   ("res.partner", "relaties"),
                   ("account.analytic.account", "analytic-rekeningen (projecten)")]:
    s, n = m(model, "search_count", {"domain": []})
    print(f"{oms}: {n if s == 200 else (s, n)}")

s, btw = m("account.tax", "search_read", {
    "domain": [], "fields": ["name", "amount", "type_tax_use"], "limit": 12})
if s == 200:
    print("btw-codes (eerste 12):")
    for t in btw:
        print(f"   {t['type_tax_use']:<9} {t['amount']:>6}%  {t['name']}")

s, fact = m("account.move", "search_read", {
    "domain": [["move_type", "=", "in_invoice"]],
    "fields": ["name", "partner_id", "invoice_date", "state", "payment_state",
               "amount_untaxed", "amount_tax", "ref"],
    "limit": 3, "order": "id desc"})
if s == 200:
    print(f"voorbeeld-inkoopfacturen ({len(fact)}):")
    for f in fact:
        print("  ", {k: f[k] for k in ("name", "state", "payment_state",
                                        "invoice_date", "amount_untaxed", "ref")})
    if fact:
        s2, regels = m("account.move.line", "search_read", {
            "domain": [["move_id", "=", fact[0]["id"]],
                        ["display_type", "=", "product"]],
            "fields": ["name", "account_id", "tax_ids", "analytic_distribution",
                        "price_subtotal"], "limit": 5})
        if s2 == 200:
            print("   regels van de nieuwste factuur:")
            for r in regels:
                print("     ", {k: r[k] for k in ("name", "account_id",
                                                   "analytic_distribution",
                                                   "price_subtotal")})
print("== klaar — geen schrijfacties uitgevoerd ==")
