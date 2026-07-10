from __future__ import annotations

from app.extractie.bsn import MASKER, is_bsn, verwijder_bsns

# 111222333 doorstaat de elfproef (1·9+1·8+1·7+2·6+2·5+2·4+3·3+3·2−3 = 66, deelbaar door 11);
# 123456789 niet (147 % 11 = 4). "10000008" is een geldig 8-cijferig BSN (voorloopnul).
GELDIG_BSN = "111222333"
GEEN_BSN = "123456789"
GELDIG_BSN_8 = "10000008"


class TestElfproef:
    def test_geldig_negencijferig(self) -> None:
        assert is_bsn(GELDIG_BSN)

    def test_ongeldig_negencijferig(self) -> None:
        assert not is_bsn(GEEN_BSN)

    def test_achtcijferig_met_voorloopnul(self) -> None:
        assert is_bsn(GELDIG_BSN_8)

    def test_nul_en_nietcijfers_zijn_geen_bsn(self) -> None:
        assert not is_bsn("000000000")
        assert not is_bsn("11122233a")
        assert not is_bsn("1112223334")  # 10 cijfers
        assert not is_bsn("1112223")  # 7 cijfers


class TestVerwijderBsnsInContext:
    """Maskeren gebeurt alléén bij elfproef + echte BSN-context (fix 2026-07-10: de elfproef
    alleen maskeerde een echt factuurnummer — fout-positieven vernielen juist de data die de
    controleur nodig heeft)."""

    def test_bsn_met_label_wordt_gemaskeerd(self) -> None:
        schoon, aantal = verwijder_bsns(f"BSN {GELDIG_BSN} van medewerker Jansen")
        assert aantal == 1
        assert GELDIG_BSN not in schoon
        assert MASKER in schoon

    def test_bsn_met_scheidingstekens_wordt_gemaskeerd(self) -> None:
        schoon, aantal = verwijder_bsns("BSN: 111.222.333 (WKA-verklaring)")
        assert aantal == 1
        assert "111.222.333" not in schoon

    def test_voluit_geschreven_labels(self) -> None:
        for label in ("burgerservicenummer", "Burger-servicenummer", "sofinummer", "sofi-nummer"):
            schoon, aantal = verwijder_bsns(f"{label}: {GELDIG_BSN}")
            assert aantal == 1, label
            assert GELDIG_BSN not in schoon, label

    def test_bsn_label_direct_erachter(self) -> None:
        schoon, aantal = verwijder_bsns(f"{GELDIG_BSN} (BSN) J. Jansen")
        assert aantal == 1
        assert GELDIG_BSN not in schoon

    def test_achtcijferig_bsn_in_context(self) -> None:
        schoon, aantal = verwijder_bsns(f"BSN {GELDIG_BSN_8} urenstaat week 27")
        assert aantal == 1
        assert GELDIG_BSN_8 not in schoon


class TestGeenValsPositief:
    def test_factuurnummer_dat_elfproef_doorstaat_blijft_ongemoeid(self) -> None:
        # De kernfout uit Peters controle (20260064.pdf): een 9-cijferig factuurnummer dat
        # toevallig de elfproef doorstaat is géén BSN — er is geen BSN-context.
        tekst = f"Factuurnummer: {GELDIG_BSN}"
        schoon, aantal = verwijder_bsns(tekst)
        assert aantal == 0
        assert schoon == tekst

    def test_los_getal_zonder_context_blijft_staan(self) -> None:
        tekst = f"Ordernr {GELDIG_BSN} — steigerhuur week 27"
        schoon, aantal = verwijder_bsns(tekst)
        assert aantal == 0
        assert schoon == tekst

    def test_dichterbijstaand_ander_label_wint_van_bsn_woord(self) -> None:
        # "BSN" komt eerder in de zin voor, maar het getal hoort bij het factuurnummer-label.
        tekst = f"BSN-verklaring aanwezig, factuurnummer {GELDIG_BSN}"
        schoon, aantal = verwijder_bsns(tekst)
        assert aantal == 0
        assert schoon == tekst

    def test_bsn_woord_buiten_venster_telt_niet(self) -> None:
        tekst = (
            "BSN geregistreerd bij aanvang van het werk conform de WKA-administratie. "
            f"Weeknummer 27, staat {GELDIG_BSN}"
        )
        schoon, aantal = verwijder_bsns(tekst)
        assert aantal == 0
        assert schoon == tekst

    def test_getal_dat_elfproef_niet_doorstaat_blijft_ook_in_context_staan(self) -> None:
        tekst = f"BSN {GEEN_BSN}"
        schoon, aantal = verwijder_bsns(tekst)
        assert aantal == 0
        assert schoon == tekst

    def test_bedragen_en_datums_blijven_staan(self) -> None:
        tekst = "Totaal 1234.56 op 2026-07-10, te betalen vóór 2026-08-10"
        schoon, aantal = verwijder_bsns(tekst)
        assert aantal == 0
        assert schoon == tekst

    def test_lange_cijferreeksen_worden_niet_stukgeknipt(self) -> None:
        # Een BSN-patroon als substring van een langere cijferreeks (IBAN, EAN) telt niet —
        # alleen losse groepen van 8/9 cijfers, ook niet als staart van een alfanumeriek kenmerk.
        tekst = f"IBAN NL91ABNA0{GELDIG_BSN}9 rekening, kenmerk F{GELDIG_BSN} — BSN bekend"
        schoon, aantal = verwijder_bsns(tekst)
        assert aantal == 0
        assert schoon == tekst


class TestMeerdereBsns:
    def test_meerdere_bsns_in_context(self) -> None:
        schoon, aantal = verwijder_bsns(f"BSN {GELDIG_BSN} en BSN {GELDIG_BSN_8}")
        assert aantal == 2
        assert GELDIG_BSN not in schoon
        assert GELDIG_BSN_8 not in schoon
