#!/usr/bin/env python3
"""
Reeleezee API-verkenning — stap 1 van de RLZ boekingsmodule.

Doel: met een geldige webservice-login vaststellen welke entiteiten de API
biedt (inkoopfacturen, verkoopfacturen, dagboeken, administraties, btw-codes,
grootboek) zodat we het datamodel niet op aannames bouwen.

Gebruik:
    1. Kopieer .env.example naar .env en vul de credentials in
    2. pip install requests python-dotenv
    3. python explore_api.py

Output: ./output/ met JSON/XML-dumps per endpoint + samenvatting in console.
"""

import base64
import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE = "https://apps.reeleezee.nl/api/v1"
OUTPUT = Path(__file__).parent / "output"

# Kandidaat-endpoints; het service document (BASE zelf) is leidend.
CANDIDATES = [
    "",                      # OData service document: lijst van entity sets
    "$metadata",             # Volledig schema (XML)
    "administrations",
    "Administrations",
    "purchaseinvoices",
    "salesinvoices",
    "documents",
    "suppliers",
    "customers",
    "taxrates",
    "ledgeraccounts",
    "journals",
]


def main() -> None:
    load_dotenv(Path(__file__).parent / ".env")
    user = os.getenv("RLZ_USERNAME")
    pw = os.getenv("RLZ_PASSWORD")
    if not user or not pw:
        raise SystemExit("Vul eerst RLZ_USERNAME en RLZ_PASSWORD in .env in.")

    token = base64.b64encode(f"{user}:{pw}".encode()).decode()
    headers = {
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
    }

    OUTPUT.mkdir(exist_ok=True)
    session = requests.Session()
    session.headers.update(headers)

    print(f"{'endpoint':<28} {'status':<8} bytes")
    print("-" * 50)
    for ep in CANDIDATES:
        url = f"{BASE}/{ep}" if ep else BASE
        try:
            r = session.get(url, timeout=30)
        except requests.RequestException as e:
            print(f"{ep or '(service root)':<28} FOUT     {e}")
            continue

        name = (ep or "service_root").replace("$", "").replace("/", "_")
        ext = "xml" if "metadata" in ep else "json"
        (OUTPUT / f"{name}.{ext}").write_bytes(r.content)
        print(f"{ep or '(service root)':<28} {r.status_code:<8} {len(r.content)}")

    # Samenvatting van het service document, als dat JSON is
    sd = OUTPUT / "service_root.json"
    if sd.exists():
        try:
            data = json.loads(sd.read_text())
            sets = [v.get("name") or v.get("url") for v in data.get("value", [])]
            if sets:
                print("\nBeschikbare entity sets volgens service document:")
                for s in sorted(filter(None, sets)):
                    print(f"  - {s}")
        except (json.JSONDecodeError, AttributeError):
            pass

    print(f"\nDumps opgeslagen in: {OUTPUT}")
    print("Stuur deze map (of de console-output) terug de chat in.")


if __name__ == "__main__":
    main()
