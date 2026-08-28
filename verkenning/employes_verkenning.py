#!/usr/bin/env python3
"""Employes API-verkenning — STRIKT READ-ONLY (alleen GET).

Doel (26-08, besluit Peter: alle 25 salarisadministraties draaien op
Employes; wens = salarisafhandeling zonder menswerk via de module):
1. Dekt één bearer-token (accountant-account) alle companies? → aantal vs 25.
2. Payrun-model: statusveld (concept/definitief?), periode/maand, kan
   "welke maand is gedraaid" hieruit gelezen worden? (werkvoorraad-signaal)
3. Journaalpost-veldvorm: payrun entries — looncomponenten, bedragen,
   grootboek-info? → basis voor het RLZ-memoriaal-boekpad.
4. Loonstroken-metadata + rate-limit-headers.

Gebruik:
  1. Token genereren: app.employes.nl → linksonder op je naam →
     token genereren (1 jaar geldig).
  2. In verkenning/.env:  EMPLOYES_API_TOKEN=<token>
  3. python3 verkenning/employes_verkenning.py

Token verschijnt NOOIT in output. Geen enkele POST/PUT/PATCH/DELETE.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error

BASE = "https://connect.employes.nl/v4"
ENV_PAD = os.path.join(os.path.dirname(__file__), ".env")


def lees_token() -> str:
    token = ""
    if os.path.exists(ENV_PAD):
        for regel in open(ENV_PAD, encoding="utf-8"):
            regel = regel.strip()
            if regel.startswith("EMPLOYES_API_TOKEN="):
                token = regel.split("=", 1)[1].strip().strip('"').strip("'")
    if not token:
        sys.exit("EMPLOYES_API_TOKEN ontbreekt in verkenning/.env — zie docstring.")
    return token


def get(pad: str, token: str):
    """GET met nette foutafhandeling; retourneert (status, json|tekst, headers)."""
    req = urllib.request.Request(
        f"{BASE}{pad}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            # Cloudflare op connect.employes.nl weigert de standaard
            # Python-urllib-signatuur (error 1010) — normale UA meesturen.
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/126.0.0.0 Safari/537.36",
            "Accept-Language": "nl-NL,nl;q=0.9",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            headers = dict(resp.headers)
            try:
                return resp.status, json.loads(body), headers
            except json.JSONDecodeError:
                return resp.status, body[:500], headers
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        return e.code, body, dict(e.headers or {})
    except urllib.error.URLError as e:
        sys.exit(f"Verbindingsfout: {e.reason}")


def kop(titel: str):
    print(f"\n{'=' * 72}\n== {titel}\n{'=' * 72}")


def toon(obj, limiet: int = 3000):
    tekst = json.dumps(obj, indent=2, ensure_ascii=False, default=str)
    print(tekst[:limiet] + ("\n… [afgekapt]" if len(tekst) > limiet else ""))


def rate_headers(headers: dict):
    relevant = {k: v for k, v in headers.items() if "rate" in k.lower() or "limit" in k.lower()}
    if relevant:
        print(f"   rate-limit-headers: {relevant}")


def main():
    token = lees_token()

    kop("1. Companies — dekt één token alle administraties?")
    status, data, headers = get("/companies?page=1&per_page=100", token)
    print(f"   HTTP {status}")
    rate_headers(headers)
    if status != 200:
        toon(data)
        sys.exit("Companies-call faalde — controleer het token.")
    print("   Ruwe respons (envelope-vorm):")
    toon(data, limiet=2000)
    companies = data if isinstance(data, list) else data.get("data", data)
    if isinstance(companies, list):
        print(f"   Aantal companies zichtbaar met dit token: {len(companies)} (verwacht: ~25)")
        for c in companies[:30]:
            if isinstance(c, dict):
                print(f"   - {c.get('id', '?')} · {c.get('name') or c.get('company_name') or '?'}")
        eerste = companies[0] if companies and isinstance(companies[0], dict) else None
    else:
        toon(data)
        eerste = None
    if not eerste:
        sys.exit("Geen companies gevonden — verder verkennen kan niet.")

    cid = eerste.get("id")
    print(f"\n   → verder met company: {eerste.get('name') or cid}")
    kop("1b. Volledige veldvorm van één company")
    toon(eerste)

    kop("2. Payruns — status/periode-model (signaal 'welke maand gedraaid')")
    status, data, headers = get(f"/{cid}/payruns", token)
    print(f"   HTTP {status}")
    rate_headers(headers)
    payruns = data if isinstance(data, list) else (data.get("data", data) if isinstance(data, dict) else data)
    if isinstance(payruns, list) and payruns:
        print(f"   Aantal payruns: {len(payruns)} — veldvorm van de meest recente:")
        toon(payruns[0])
        run_id = payruns[0].get("id") if isinstance(payruns[0], dict) else None
    else:
        toon(data)
        run_id = None

    if run_id:
        kop("3. Payrun-detail")
        status, data, _ = get(f"/{cid}/payruns/{run_id}", token)
        print(f"   HTTP {status}")
        toon(data)

        kop("4. Payrun ENTRIES — de journaalpost-veldvorm (kern voor het RLZ-boekpad)")
        status, data, _ = get(f"/{cid}/payruns/{run_id}/entries", token)
        print(f"   HTTP {status}")
        toon(data, limiet=6000)

        kop("5. Payslips-metadata (alleen lijst, geen download)")
        status, data, _ = get(f"/{cid}/payruns/{run_id}/payslips", token)
        print(f"   HTTP {status}")
        toon(data, limiet=1500)

    kop("6. Regulations (looncomponenten-definities)")
    status, data, _ = get("/regulations", token)
    print(f"   HTTP {status}")
    toon(data, limiet=1500)

    print("\nKlaar — read-only verkenning afgerond. Geen enkele schrijfactie gedaan.")


if __name__ == "__main__":
    main()
