from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.extractie.controle import (
    TaxRateKandidaat,
    VendorKandidaat,
    bouw_veldvoorstel,
    is_verlegd_vermelding,
    leid_btw_af,
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
        omschrijving=omschrijving,
        netto_bedrag=netto,
        btw_bedrag=btw,
        hoeveelheid=hoeveelheid,
        zekerheid=zekerheid,
    )


def _extractie(
    kop_overrides: dict | None = None, regels: list[AiRegel] | None = None, volledig: bool = True
) -> AiFactuurExtractie:
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
    return AiFactuurExtractie(
        kop=kop, regels=regels if regels is not None else [_regel()], bsn_verwijderd=0, volledig=volledig
    )


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
        assert voorstel["regel_zekerheid"] == [0.95]
        assert voorstel["zekerheid_drempel"] == 0.8
        assert voorstel["controle"]["regelsom_wijkt_af"] is False
        assert voorstel["controle"]["onparseerbaar"] == []
        assert voorstel["controle"]["lage_zekerheid"] == []
        assert voorstel["controle"]["onvolledig"] is False

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

    def test_lage_regelzekerheid_wordt_gemarkeerd(self) -> None:
        extractie = _extractie(regels=[_regel(zekerheid=0.95), _regel("Vage regel", zekerheid=0.4)])
        voorstel = bouw_veldvoorstel(extractie, vendors=[], taxrates=[], zekerheid_drempel=0.8)
        assert voorstel["regel_zekerheid"] == [0.95, 0.4]
        assert "regel 2" in voorstel["controle"]["lage_zekerheid"]
        assert "regel 1" not in voorstel["controle"]["lage_zekerheid"]

    def test_onvolledige_extractie_wordt_gesignaleerd(self) -> None:
        # Alleen relevant voor niet-projectplicht-administraties: bij projectplicht komt dit
        # voorstel er überhaupt niet (documenten/service blokkeert naar handmatig_afmaken).
        voorstel = bouw_veldvoorstel(_extractie(volledig=False), vendors=[], taxrates=[], zekerheid_drempel=0.8)
        assert voorstel["controle"]["onvolledig"] is True

    def test_grootboek_wordt_nooit_gesuggereerd(self) -> None:
        # Boekingsgeheugen is sessie 2 — tot die tijd geen enkele GB-suggestie (geen gok).
        voorstel = bouw_veldvoorstel(_extractie(), vendors=[], taxrates=[], zekerheid_drempel=0.8)
        assert all("ledger_id" not in regel for regel in voorstel["regels"])


class TestLeidBtwAf:
    """Btw-code vooraf invullen uit de scan (feedbackronde 26-08 punt 3): CODE leidt per regel
    het tarief af uit btw ÷ netto tegen de gesyncte TaxRates; 0/onbepaalbaar/meerduidig = leeg."""

    def _tarieven(self) -> dict[str, TaxRateKandidaat]:
        return {
            "hoog": TaxRateKandidaat(id=uuid.uuid4(), percentage=Decimal("0.21"), is_favoriet=True),
            "hoog_vooruit": TaxRateKandidaat(id=uuid.uuid4(), percentage=Decimal("0.21")),
            "laag": TaxRateKandidaat(id=uuid.uuid4(), percentage=Decimal("0.09"), is_favoriet=True),
            "laag_vooruit": TaxRateKandidaat(id=uuid.uuid4(), percentage=Decimal("0.09")),
            "verlegd": TaxRateKandidaat(id=uuid.uuid4(), percentage=Decimal("0"), is_verlegd=True),
            "vrijgesteld": TaxRateKandidaat(id=uuid.uuid4(), percentage=Decimal("0"), is_vrijgesteld=True),
            "nul": TaxRateKandidaat(id=uuid.uuid4(), percentage=Decimal("0")),
            "gemengd": TaxRateKandidaat(id=uuid.uuid4(), percentage=Decimal("0"), is_gemengd=True),
        }

    def test_21_en_9_procent_worden_afgeleid_met_bron_factuur(self) -> None:
        t = self._tarieven()
        kandidaten = list(t.values())
        hoog = leid_btw_af(Decimal("100.00"), Decimal("21.00"), kandidaten)
        assert (hoog.taxrate_id, hoog.bron, hoog.percentage) == (t["hoog"].id, "factuur", Decimal("0.21"))
        laag = leid_btw_af(Decimal("250.00"), Decimal("22.50"), kandidaten)
        assert (laag.taxrate_id, laag.bron) == (t["laag"].id, "factuur")

    def test_dubbel_percentage_kiest_de_rlz_favoriet(self) -> None:
        """De echte RLZ-situatie (dev-DB 26-08, 14 administraties): "NL, Hoog Tarief" én
        "NL, Hoog Tarief (vooruit)" zijn beide 21% — vóór deze fix bleef het veld daardoor leeg."""
        t = self._tarieven()
        afleiding = leid_btw_af(Decimal("100.00"), Decimal("21.00"), [t["hoog_vooruit"], t["hoog"]])
        assert afleiding.taxrate_id == t["hoog"].id

    def test_dubbel_percentage_zonder_eenduidige_favoriet_blijft_leeg(self) -> None:
        a = TaxRateKandidaat(id=uuid.uuid4(), percentage=Decimal("0.21"))
        b = TaxRateKandidaat(id=uuid.uuid4(), percentage=Decimal("0.21"))
        assert leid_btw_af(Decimal("100.00"), Decimal("21.00"), [a, b]).taxrate_id is None
        assert leid_btw_af(Decimal("100.00"), Decimal("21.00"), [a, b]).reden == "meerduidig"
        twee_favorieten = [
            TaxRateKandidaat(id=uuid.uuid4(), percentage=Decimal("0.21"), is_favoriet=True),
            TaxRateKandidaat(id=uuid.uuid4(), percentage=Decimal("0.21"), is_favoriet=True),
        ]
        assert leid_btw_af(Decimal("100.00"), Decimal("21.00"), twee_favorieten).taxrate_id is None

    def test_centafronding_binnen_1_cent_matcht(self) -> None:
        t = self._tarieven()
        kandidaten = list(t.values())
        # 33.33 × 0.21 = 6.9993 → factuur toont 7.00 (afgerond) én 6.99 (afgekapt): beide matchen.
        assert leid_btw_af(Decimal("33.33"), Decimal("7.00"), kandidaten).taxrate_id == t["hoog"].id
        assert leid_btw_af(Decimal("33.33"), Decimal("6.99"), kandidaten).taxrate_id == t["hoog"].id
        # Meer dan 1 cent ernaast = geen match (geen gok).
        assert leid_btw_af(Decimal("33.33"), Decimal("7.02"), kandidaten).taxrate_id is None

    def test_nul_btw_blijft_leeg_ook_met_verlegd_vrijgesteld_en_nultarief_in_de_cache(self) -> None:
        """0% is ambigu (0%-tarief/vrijgesteld/verlegd — bouwketen-norm verlegd): nooit invullen
        vanuit de afleiding; boekingsgeheugen per leverancier wint, anders kiest de mens."""
        t = self._tarieven()
        afleiding = leid_btw_af(Decimal("100.00"), Decimal("0"), list(t.values()))
        assert afleiding.taxrate_id is None and afleiding.bron is None and afleiding.reden == "btw_nul"
        assert leid_btw_af(Decimal("100.00"), Decimal("0.00"), [t["verlegd"]]).taxrate_id is None

    def test_meerdere_tarieven_in_een_factuur_per_regel(self) -> None:
        t = self._tarieven()
        kandidaten = list(t.values())
        regels = [(Decimal("100.00"), Decimal("21.00")), (Decimal("50.00"), Decimal("4.50")), (Decimal("10.00"), Decimal("0"))]
        uitkomsten = [leid_btw_af(n, b, kandidaten).taxrate_id for n, b in regels]
        assert uitkomsten == [t["hoog"].id, t["laag"].id, None]

    def test_negatieve_regel_creditnota(self) -> None:
        t = self._tarieven()
        kandidaten = list(t.values())
        assert leid_btw_af(Decimal("-100.00"), Decimal("-21.00"), kandidaten).taxrate_id == t["hoog"].id
        assert leid_btw_af(Decimal("-100.00"), Decimal("-9.00"), kandidaten).taxrate_id == t["laag"].id
        # Tekenfout op de factuur (netto negatief, btw positief) matcht niets — geen gok.
        assert leid_btw_af(Decimal("-100.00"), Decimal("21.00"), kandidaten).taxrate_id is None

    def test_onbepaalbaar_zonder_bedragen(self) -> None:
        t = self._tarieven()
        assert leid_btw_af(None, Decimal("21.00"), list(t.values())).reden == "onbepaalbaar"
        assert leid_btw_af(Decimal("100.00"), None, list(t.values())).reden == "onbepaalbaar"
        assert leid_btw_af(Decimal("0"), Decimal("0"), list(t.values())).taxrate_id is None

    def test_afwijkend_percentage_matcht_niets(self) -> None:
        t = self._tarieven()
        assert leid_btw_af(Decimal("100.00"), Decimal("15.00"), list(t.values())).reden == "geen_match"

    def test_veldvoorstel_draagt_btw_bron_en_verlegd_hint(self) -> None:
        t = self._tarieven()
        extractie = AiFactuurExtractie(
            kop={
                "leverancier_naam": _veld("Onderaannemer X"),
                "totaal_excl": _veld("110.00"),
                "totaal_incl": _veld("131.00"),
                "btw_verlegd_vermelding": _veld("BTW verlegd naar afnemer art. 12 lid 5"),
            },
            regels=[_regel(netto="100.00", btw="21.00"), _regel(omschrijving="Arbeid", netto="10.00", btw="0")],
            bsn_verwijderd=0,
        )
        voorstel = bouw_veldvoorstel(extractie, vendors=[], taxrates=list(t.values()), zekerheid_drempel=0.8)
        assert voorstel["regels"][0]["taxrate_id"] == str(t["hoog"].id)
        assert voorstel["regels"][0]["btw_bron"] == "factuur"
        assert voorstel["regels"][1]["taxrate_id"] is None
        assert voorstel["regels"][1]["btw_bron"] is None
        assert voorstel["regels"][1]["btw_afleiding_reden"] == "btw_nul"
        # De verlegd-vermelding is een hint (tekst), geen ingevulde code.
        assert voorstel["btw_verlegd_vermelding"] == "BTW verlegd naar afnemer art. 12 lid 5"

    def test_verlegd_vermelding_alleen_bij_echte_verleggingstekst(self) -> None:
        assert is_verlegd_vermelding("BTW verlegd") is True
        assert is_verlegd_vermelding("Verleggingsregeling van toepassing") is True
        assert is_verlegd_vermelding("VAT reverse charge") is True
        assert is_verlegd_vermelding("Betaling binnen 30 dagen") is False
        assert is_verlegd_vermelding(None) is False
