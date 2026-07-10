from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.extractie.controle import (
    TaxRateKandidaat,
    VendorKandidaat,
    bouw_veldvoorstel,
    match_taxrate,
    match_vendor,
    parse_bedrag,
    parse_datum,
)
from app.extractie.service import AiFactuurExtractie, AiRegel, AiVeld


def _veld(waarde: str | None, zekerheid: float = 0.95) -> AiVeld:
    return AiVeld(waarde=waarde, zekerheid=zekerheid)


def _regel(
    omschrijving: str | None = "Materiaal",
    netto: str | None = "100.00",
    btw: str | None = "21.00",
    hoeveelheid: str | None = None,
    zekerheid: float = 0.95,
) -> AiRegel:
    return AiRegel(
        omschrijving=_veld(omschrijving, zekerheid),
        netto_bedrag=_veld(netto, zekerheid),
        btw_bedrag=_veld(btw, zekerheid),
        hoeveelheid=_veld(hoeveelheid, zekerheid),
    )


def _extractie(kop_overrides: dict | None = None, regels: list[AiRegel] | None = None) -> AiFactuurExtractie:
    kop = {
        "leverancier_naam": _veld("Bouwmaat Nederland B.V."),
        "factuurnummer": _veld("F-2026-001"),
        "factuurdatum": _veld("2026-07-01"),
        "vervaldatum": _veld("2026-07-31"),
        "valuta": _veld("EUR"),
        "totaal_excl": _veld("100.00"),
        "totaal_incl": _veld("121.00"),
        "btw_bedrag": _veld("21.00"),
    }
    kop.update(kop_overrides or {})
    return AiFactuurExtractie(kop=kop, regels=regels if regels is not None else [_regel()], bsn_verwijderd=0)


class TestParseBedrag:
    def test_punt_decimaal(self) -> None:
        assert parse_bedrag("1234.56") == Decimal("1234.56")

    def test_nl_notatie_met_komma(self) -> None:
        assert parse_bedrag("1.234,56") == Decimal("1234.56")

    def test_valutateken_en_spaties(self) -> None:
        assert parse_bedrag("€ 25,00") == Decimal("25.00")

    def test_negatief_creditbedrag(self) -> None:
        assert parse_bedrag("-25.00") == Decimal("-25.00")

    def test_rommel_is_none(self) -> None:
        assert parse_bedrag("abc") is None
        assert parse_bedrag("") is None
        assert parse_bedrag(None) is None

    def test_meer_dan_twee_decimalen_is_leesfout(self) -> None:
        assert parse_bedrag("12.345") is None

    def test_absurde_grootte_is_leesfout(self) -> None:
        assert parse_bedrag("123456789.00") is None


class TestParseDatum:
    def test_iso(self) -> None:
        assert parse_datum("2026-07-01") == date(2026, 7, 1)

    def test_nl_notatie_is_none(self) -> None:
        assert parse_datum("01-07-2026") is None

    def test_buiten_plausibiliteitsvenster(self) -> None:
        assert parse_datum("1926-07-01") is None
        assert parse_datum("2126-07-01") is None

    def test_leeg(self) -> None:
        assert parse_datum(None) is None
        assert parse_datum("") is None


class TestMatchVendor:
    def test_exacte_match(self) -> None:
        vendor = VendorKandidaat(id=uuid.uuid4(), naam="Bouwmaat Nederland B.V.")
        vendor_id, soort = match_vendor("bouwmaat nederland b.v.", [vendor])
        assert vendor_id == vendor.id
        assert soort == "exact"

    def test_fuzzy_match_op_rechtsvorm_verschil(self) -> None:
        vendor = VendorKandidaat(id=uuid.uuid4(), naam="Bouwmaat Nederland B.V.")
        vendor_id, soort = match_vendor("Bouwmaat Nederland BV", [vendor])
        assert vendor_id == vendor.id
        assert soort == "fuzzy"

    def test_geen_gok_bij_meerdere_kandidaten(self) -> None:
        kandidaten = [
            VendorKandidaat(id=uuid.uuid4(), naam="Bouwmaat Nederland B.V."),
            VendorKandidaat(id=uuid.uuid4(), naam="bouwmaat nederland b.v."),
        ]
        assert match_vendor("Bouwmaat Nederland B.V.", kandidaten) == (None, None)

    def test_geen_match_onder_drempel(self) -> None:
        vendor = VendorKandidaat(id=uuid.uuid4(), naam="Jansen Installatietechniek")
        assert match_vendor("Pietersen Dakwerken", [vendor]) == (None, None)

    def test_lege_naam(self) -> None:
        assert match_vendor(None, [VendorKandidaat(id=uuid.uuid4(), naam="X")]) == (None, None)


class TestMatchTaxrate:
    def test_uniek_percentage(self) -> None:
        hoog = TaxRateKandidaat(id=uuid.uuid4(), percentage=Decimal("0.21"))
        laag = TaxRateKandidaat(id=uuid.uuid4(), percentage=Decimal("0.09"))
        assert match_taxrate(Decimal("100.00"), Decimal("21.00"), [hoog, laag]) == hoog.id

    def test_geen_gok_bij_twee_codes_met_zelfde_percentage(self) -> None:
        kandidaten = [
            TaxRateKandidaat(id=uuid.uuid4(), percentage=Decimal("0.21")),
            TaxRateKandidaat(id=uuid.uuid4(), percentage=Decimal("0.21")),
        ]
        assert match_taxrate(Decimal("100.00"), Decimal("21.00"), kandidaten) is None

    def test_btw_nul_krijgt_geen_suggestie(self) -> None:
        # 0% kan verlegd/vrijgesteld/0%-tarief zijn — aangifte-kritisch onderscheid, nooit gokken.
        kandidaat = TaxRateKandidaat(id=uuid.uuid4(), percentage=Decimal("0"))
        assert match_taxrate(Decimal("100.00"), Decimal("0"), [kandidaat]) is None

    def test_geen_passend_percentage(self) -> None:
        kandidaat = TaxRateKandidaat(id=uuid.uuid4(), percentage=Decimal("0.21"))
        assert match_taxrate(Decimal("100.00"), Decimal("15.00"), [kandidaat]) is None


class TestBouwVeldvoorstel:
    def test_compleet_voorstel(self) -> None:
        vendor = VendorKandidaat(id=uuid.uuid4(), naam="Bouwmaat Nederland B.V.")
        taxrate = TaxRateKandidaat(id=uuid.uuid4(), percentage=Decimal("0.21"))
        voorstel = bouw_veldvoorstel(_extractie(), vendors=[vendor], taxrates=[taxrate], zekerheid_drempel=0.8)

        assert voorstel["bron"] == "ai"
        assert voorstel["factuurnummer"] == "F-2026-001"
        assert voorstel["factuurdatum"] == "2026-07-01"
        assert voorstel["totaal_incl"] == "121.00"
        assert voorstel["vendor_suggestie"] == {"vendor_id": str(vendor.id), "match": "exact"}
        assert voorstel["regels"][0]["taxrate_id"] == str(taxrate.id)
        assert voorstel["zekerheid"]["factuurnummer"] == 0.95
        assert voorstel["zekerheid_drempel"] == 0.8
        assert voorstel["controle"]["regelsom_wijkt_af"] is False
        assert voorstel["controle"]["onparseerbaar"] == []
        assert voorstel["controle"]["lage_zekerheid"] == []

    def test_onparseerbaar_veld_blijft_leeg_en_wordt_benoemd(self) -> None:
        extractie = _extractie({"totaal_incl": _veld("honderd euro")})
        voorstel = bouw_veldvoorstel(extractie, vendors=[], taxrates=[], zekerheid_drempel=0.8)
        assert voorstel["totaal_incl"] is None
        assert "totaal_incl" in voorstel["controle"]["onparseerbaar"]

    def test_lage_zekerheid_wordt_gemarkeerd(self) -> None:
        extractie = _extractie({"vervaldatum": _veld("2026-07-31", zekerheid=0.4)})
        voorstel = bouw_veldvoorstel(extractie, vendors=[], taxrates=[], zekerheid_drempel=0.8)
        # Waarde blijft een voorstel (parsebaar), maar staat gemarkeerd als laag — oranje in de UI.
        assert voorstel["vervaldatum"] == "2026-07-31"
        assert "vervaldatum" in voorstel["controle"]["lage_zekerheid"]

    def test_regelsom_afwijking_wordt_gesignaleerd(self) -> None:
        extractie = _extractie(regels=[_regel(netto="50.00", btw="10.50")])  # som 60.50 vs totaal 121.00
        voorstel = bouw_veldvoorstel(extractie, vendors=[], taxrates=[], zekerheid_drempel=0.8)
        assert voorstel["controle"]["regelsom"] == "60.50"
        assert voorstel["controle"]["regelsom_wijkt_af"] is True

    def test_regelsom_niet_getoetst_bij_onparseerbare_regel(self) -> None:
        extractie = _extractie(regels=[_regel(netto="honderd")])
        voorstel = bouw_veldvoorstel(extractie, vendors=[], taxrates=[], zekerheid_drempel=0.8)
        assert voorstel["controle"]["regelsom"] is None
        assert voorstel["controle"]["regelsom_wijkt_af"] is None
        assert "netto_bedrag (regel 1)" in voorstel["controle"]["onparseerbaar"]

    def test_grootboek_wordt_nooit_gesuggereerd(self) -> None:
        # Boekingsgeheugen is sessie 2 — tot die tijd geen enkele GB-suggestie (geen gok).
        voorstel = bouw_veldvoorstel(_extractie(), vendors=[], taxrates=[], zekerheid_drempel=0.8)
        assert all("ledger_id" not in regel for regel in voorstel["regels"])
