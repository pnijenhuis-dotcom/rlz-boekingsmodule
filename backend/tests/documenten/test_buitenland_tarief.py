"""Blok A verzamelrun 31-08 (casus Labo Derva): EU-/buitenland-tarief × crediteurkaart —
het onvoorwaardelijke oranje pre-check-signaal (land/btw-nummer van de crediteur is via de
RLZ-API niet leesbaar, dus niet toetsbaar) én de foutvertaling van RLZ's 400
"ongeldig belastingtarief" op de boekpaden. Pure unit-tests, geen DB/RLZ."""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.documenten.boeken import vertaal_rlz_boekfout
from app.documenten.checks import (
    CheckRegel,
    check_buitenland_tarief_crediteurkaart,
    is_buitenland_tarief,
)
from app.rlz.client import RlzApiError


def _regel(taxrate_id: uuid.UUID | None) -> CheckRegel:
    return CheckRegel(
        ledger_id=uuid.uuid4(),
        taxrate_id=taxrate_id,
        netto_bedrag=Decimal("100.00"),
        btw_bedrag=Decimal("0.00"),
    )


class TestIsBuitenlandTarief:
    def test_nl_tarieven_zijn_geen_buitenland(self) -> None:
        # Alle NL-varianten uit de gesyncte taxrate_cache (probe 31-08), incl. verlegd.
        for naam in ("NL, Hoog Tarief", "NL, BTW verlegd (hoog)", "NL, Nul tarief", "NL, Geen BTW (Vrijgesteld)"):
            assert not is_buitenland_tarief(naam)

    def test_eu_en_ex_eu_varianten_zijn_buitenland(self) -> None:
        # Letterlijke namen uit de cache — let op de casing-varianten "Ex Eu"/"Ex EU".
        for naam in (
            "EU, Producten Hoog tarief",
            "EU, Diensten Laag tarief (vanaf 2010)",
            "Ex Eu, Producten Hoog tarief",
            "Ex EU, Diensten Laag tarief (vanaf 2010)",
            "EU + Ex-EU, Diensten Hoog Tarief (t/m 2009)",
            "DE, Hoog tarief",  # landcode-variant (casus: tarief 'DE')
        ):
            assert is_buitenland_tarief(naam), naam

    def test_zonder_komma_prefix_geen_uitspraak(self) -> None:
        assert not is_buitenland_tarief(None)
        assert not is_buitenland_tarief("")
        assert not is_buitenland_tarief("Eigen tarief zonder prefix")


class TestCheckBuitenlandTariefCrediteurkaart:
    def test_geen_buitenland_tarief_geen_signaal(self) -> None:
        tid = uuid.uuid4()
        resultaat = check_buitenland_tarief_crediteurkaart(
            regels=[_regel(tid)], taxrate_namen={tid: "NL, Hoog Tarief"}, factuur_btw_nummer=None
        )
        assert resultaat.ok and not resultaat.signaal

    def test_buitenland_tarief_geeft_signaal_geen_blokkade(self) -> None:
        nl, de = uuid.uuid4(), uuid.uuid4()
        resultaat = check_buitenland_tarief_crediteurkaart(
            regels=[_regel(nl), _regel(de)],
            taxrate_namen={nl: "NL, Hoog Tarief", de: "EU, Producten Hoog tarief"},
            factuur_btw_nummer="BE0403052253",
        )
        assert resultaat.ok  # signaal, nooit blokkade
        assert resultaat.signaal
        assert "regel 2" in resultaat.melding
        assert "EU, Producten Hoog tarief" in resultaat.melding
        assert "land én btw-nummer" in resultaat.melding
        assert "BE0403052253" in resultaat.melding  # handelingshulp: zo overtikken in RLZ

    def test_onbekende_taxrate_id_geen_vals_signaal(self) -> None:
        resultaat = check_buitenland_tarief_crediteurkaart(
            regels=[_regel(uuid.uuid4())], taxrate_namen={}, factuur_btw_nummer=None
        )
        assert resultaat.ok and not resultaat.signaal


class TestVertaalRlzBoekfout:
    def test_ongeldig_belastingtarief_wordt_leesbaar(self) -> None:
        # Letterlijke casus-tekst 31-08 (Labo Derva, tarief 'DE' op regel 1).
        exc = RlzApiError(
            400, "POST", "https://apps.reeleezee.nl/api/v1/x/PurchaseInvoices/y/Actions",
            "Inkoopfactuur 26100033 heeft een ongeldig belastingtarief 'DE' op regel 1",
        )
        melding = vertaal_rlz_boekfout(exc)
        assert "RLZ weigert het btw-tarief ('DE') op regel 1" in melding
        assert "controleer land en btw-nummer van de crediteur in RLZ" in melding
        assert "ongeldig belastingtarief" in melding  # de rauwe RLZ-tekst blijft meereizen

    def test_onbekende_fout_blijft_rauw(self) -> None:
        exc = RlzApiError(400, "POST", "https://x", "De credit- en debetbedragen zijn niet gelijk")
        assert vertaal_rlz_boekfout(exc) == str(exc)

    def test_zelfde_tekst_op_andere_status_blijft_rauw(self) -> None:
        exc = RlzApiError(500, "POST", "https://x", "ongeldig belastingtarief 'DE' op regel 1")
        assert vertaal_rlz_boekfout(exc) == str(exc)
