"""READ-ONLY integratietests tegen de echte BLOW- en Universal Steigerbouw-administraties.

Hard: geen enkele schrijfactie in dit bestand. Schrijf-integratietests staan apart in
test_write_integration.py en draaien uitsluitend tegen de RLZ-test-administratie.

read_integration-marker (2026-07-08, zelfde reden als write_integration): dit leest live
productiedata van échte klanten (BLOw/Universal) — dat hoort niet in een kale pytest-run te
zitten, zelfs niet als alleen-lezend en zelfs niet als hij zonder credentials toch al skipt.
"""

from __future__ import annotations

import time

import pytest

from app.rlz.client import RlzClient

pytestmark = pytest.mark.read_integration


def test_administrations_bereikbaar_blow(blow_login: RlzClient) -> None:
    administraties = blow_login.list_administrations()
    assert administraties


def test_administrations_bereikbaar_universal(universal_login: RlzClient) -> None:
    administraties = universal_login.list_administrations()
    assert administraties


def test_ledgers_blow(blow_client: RlzClient) -> None:
    ledgers = blow_client.get("Ledgers").get("value", [])
    assert ledgers


def test_taxrates_blow(blow_client: RlzClient) -> None:
    taxrates = blow_client.get("TaxRates").get("value", [])
    assert taxrates


def test_vendors_blow(blow_client: RlzClient) -> None:
    vendors = blow_client.get("Vendors").get("value", [])
    assert isinstance(vendors, list)


def test_purchase_invoices_met_expand_lines_blow(blow_client: RlzClient) -> None:
    invoices = blow_client.get("PurchaseInvoices", params={"$top": 5}).get("value", [])
    if not invoices:
        pytest.skip("Geen inkoopfacturen in BLOw om Lines-$expand op te testen")
    lines = blow_client.get_lines("PurchaseInvoices", invoices[0]["id"], expand="Account,Project")
    assert isinstance(lines, list)


def test_ledgers_universal(universal_client: RlzClient) -> None:
    ledgers = universal_client.get("Ledgers").get("value", [])
    assert ledgers


def test_taxrates_universal(universal_client: RlzClient) -> None:
    taxrates = universal_client.get("TaxRates").get("value", [])
    assert taxrates


def test_vendors_universal(universal_client: RlzClient) -> None:
    vendors = universal_client.get("Vendors").get("value", [])
    assert isinstance(vendors, list)


def test_projects_universal_rond_145(universal_client: RlzClient) -> None:
    """verkenning/api-verkenning.md (2 juli 2026): 145 projecten (60 actief). Ondergrens i.p.v.
    een exact getal — de administratie leeft door en krijgt tussentijds nieuwe projecten."""
    projects = universal_client.get("Projects").get("value", [])
    assert len(projects) >= 100, f"Verwachtte >=100 projecten (referentie: 145), kreeg {len(projects)}"


def test_purchase_invoices_met_expand_lines_universal(universal_client: RlzClient) -> None:
    invoices = universal_client.get("PurchaseInvoices", params={"$top": 5}).get("value", [])
    if not invoices:
        pytest.skip("Geen inkoopfacturen in Universal om Lines-$expand op te testen")
    lines = universal_client.get_lines("PurchaseInvoices", invoices[0]["id"], expand="Account,Project")
    assert isinstance(lines, list)


def test_rate_limit_gedrag_observatie(blow_client: RlzClient) -> None:
    """Geen harde assertie op een concreet limiet-getal (nog niet gedocumenteerd door RLZ) — dit
    observeert en print het gedrag zodat het overgenomen kan worden in api-verkenning.md. Draai
    met `pytest -s` om de output te zien."""
    n_requests = 20
    statuses: list[int] = []
    rate_limit_headers: dict[str, str] = {}
    start = time.monotonic()
    for _ in range(n_requests):
        response = blow_client.request_raw("GET", "Ledgers")
        statuses.append(response.status_code)
        rate_limit_headers.update(
            {k: v for k, v in response.headers.items() if "ratelimit" in k.lower() or k.lower() == "retry-after"}
        )
    elapsed = time.monotonic() - start

    print(f"\n[rate-limit-observatie] {n_requests} GET Ledgers in {elapsed:.2f}s ({n_requests / elapsed:.1f} req/s)")
    print(f"[rate-limit-observatie] statuscodes: {sorted(set(statuses))}")
    print(f"[rate-limit-observatie] rate-limit/retry-after headers gezien: {rate_limit_headers or '(geen)'}")

    assert all(s == 200 for s in statuses), f"Onverwachte statuscodes tijdens burst: {statuses}"
