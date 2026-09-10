"""Blok D2 (bundel 10-09): deterministische afleiding pandenregister — pure functies, parametrisch.

Adressen (NL straat + nummer + toevoeging + postcode/plaats; meerduidig = None), dossiernummers (notaris-vorm,
"dossier …", nooit een datum), notaris-herkenning (Ouwerkerk/Ouwekerk, Buma Algera, generiek), classificatie
(aankoop/verkoop/kosten × hoog/midden/laag; geen signaal = None)."""

from __future__ import annotations

import pytest

from app.panden.afleiding import (
    AdresVoorstel,
    BoekingsFeit,
    adres_uit_tekst,
    adressen_uit_tekst,
    classificeer,
    dossiernummer_uit_tekst,
    dossiernummers_uit_tekst,
    notaris_herkenning,
)


class TestAdres:
    @pytest.mark.parametrize(
        ("tekst", "straat", "nummer", "toevoeging", "plaats", "postcode", "code"),
        [
            ("Goeverneurlaan 310, Den Haag", "Goeverneurlaan", "310", None, "Den Haag", None, "goeverneurlaan-310"),
            (
                "Betreft: aankoop Bleijeheiderstraat 1 te Kerkrade",
                "Bleijeheiderstraat",
                "1",
                None,
                "Kerkrade",
                None,
                "bleijeheiderstraat-1",
            ),
            ("Homekeur 95514 keuring Kerkstraat 44 BV", "Kerkstraat", "44", None, None, None, "kerkstraat-44"),
            (
                "Gustaaf Gelderstraat 12 Rotterdam",
                "Gustaaf Gelderstraat",
                "12",
                None,
                None,
                None,
                "gustaaf-gelderstraat-12",
            ),
            (
                "Jan Collongstraat 8, 6821 AB Arnhem",
                "Jan Collongstraat",
                "8",
                None,
                "Arnhem",
                "6821AB",
                "jan-collongstraat-8",
            ),
            ("dossier 2025/058870 Kerkstraat 44a, Ede", "Kerkstraat", "44", "a", "Ede", None, "kerkstraat-44-a"),
            ("Hoofdweg 12-3 Amsterdam", "Hoofdweg", "12", "-3", None, None, "hoofdweg-12-3"),
            ("Van der Kunstraat 5 A, Utrecht", "Van der Kunstraat", "5", "A", "Utrecht", None, "van-der-kunstraat-5-a"),
            ("kosten van Kerkstraat 44", "Kerkstraat", "44", None, None, None, "kerkstraat-44"),
            (
                "verkoop Goeverneurlaan 310 dd 2026-01-09",
                "Goeverneurlaan",
                "310",
                None,
                None,
                None,
                "goeverneurlaan-310",
            ),
            (
                "1e Jan van der Heijdenstraat 20 hs",
                "Jan van der Heijdenstraat",
                "20",
                "hs",
                None,
                None,
                "jan-van-der-heijdenstraat-20-hs",
            ),
        ],
    )
    def test_herkent_adres(
        self,
        tekst: str,
        straat: str,
        nummer: str,
        toevoeging: str | None,
        plaats: str | None,
        postcode: str | None,
        code: str,
    ) -> None:
        a = adres_uit_tekst(tekst)
        assert a is not None, tekst
        assert (a.straat, a.huisnummer, a.toevoeging, a.plaats, a.postcode) == (
            straat,
            nummer,
            toevoeging,
            plaats,
            postcode,
        )
        assert a.code == code

    @pytest.mark.parametrize(
        "tekst",
        [
            "factuur 2026047",
            "Overige kosten — bank-direct",
            "Rente lening Q3 2026",
            "Aanbetaling pand 15-08",
            "",
            None,
            "RLZ-06-00000012",
        ],
    )
    def test_geen_adres(self, tekst: str | None) -> None:
        assert adres_uit_tekst(tekst) is None
        assert adressen_uit_tekst(tekst) == []

    def test_meerdere_adressen_is_meerduidig(self) -> None:
        assert [a.code for a in adressen_uit_tekst("Kerkstraat 44 en Kerkstraat 46")] == [
            "kerkstraat-44",
            "kerkstraat-46",
        ]
        assert adres_uit_tekst("Kerkstraat 44 en Kerkstraat 46") is None

    def test_zelfde_adres_twee_keer_is_een_adres(self) -> None:
        assert adres_uit_tekst("Kerkstraat 44", "nota Kerkstraat 44, Ede") is not None

    def test_code_zonder_diacritics_en_plaats(self) -> None:
        assert AdresVoorstel(straat="Élysée-laan", huisnummer="7", plaats="Ede").code == "elysee-laan-7"
        assert AdresVoorstel(straat="Kerkstraat", huisnummer="44", toevoeging="a").weergave == "Kerkstraat 44a"
        assert (
            AdresVoorstel(straat="Kerkstraat", huisnummer="44", toevoeging="bis", plaats="Ede").weergave
            == "Kerkstraat 44 bis, Ede"
        )


class TestDossier:
    @pytest.mark.parametrize(
        ("tekst", "verwacht"),
        [
            ("dossier 2025.058870.01 · Ouwerkerk", ("2025.058870.01",)),
            ("Afrekening 2026.014221.01 Bleijeheiderstraat 1", ("2026.014221.01",)),
            ("Dossiernr: 2025/061112 verkoop", ("2025/061112",)),
            ("dossier 2025.058870.01 en 2025.058870", ("2025.058870.01",)),  # kort = zelfde dossier
            ("factuur 2026047 dd 2026-08-15", ()),  # datum is geen dossier
            ("Kerkstraat 44 2026.08.15", ()),
            ("", ()),
        ],
    )
    def test_dossiernummers(self, tekst: str, verwacht: tuple[str, ...]) -> None:
        assert dossiernummers_uit_tekst(tekst) == verwacht

    def test_een_dossier_of_none(self) -> None:
        assert dossiernummer_uit_tekst("dossier 2025.058870.01") == "2025.058870.01"
        assert dossiernummer_uit_tekst("2025.058870.01 en 2026.014221.01") is None


class TestNotaris:
    @pytest.mark.parametrize(
        ("naam", "weergave", "bekend"),
        [
            ("Ouwerkerk Notariaat B.V.", "Ouwerkerk", True),
            ("Notariskantoor Ouwekerk", "Ouwerkerk", True),  # spelling uit de opdracht
            ("Buma Algera Notarissen", "Buma Algera", True),
            ("BUMA-ALGERA", "Buma Algera", True),
            ("Notariskantoor De Vries", "Notariskantoor De Vries", False),
            ("Van Dijk notarissen", "Van Dijk notarissen", False),
        ],
    )
    def test_herkent(self, naam: str, weergave: str, bekend: bool) -> None:
        h = notaris_herkenning(naam)
        assert h is not None and (h.naam, h.bekend) == (weergave, bekend)

    @pytest.mark.parametrize("naam", ["Homekeur B.V.", "Administratiekantoor Nijenhuis C.V.", None, "", "  "])
    def test_geen_notaris(self, naam: str | None) -> None:
        assert notaris_herkenning(naam) is None


def _feit(
    collectie: str,
    tekst: str,
    *,
    entity: str | None = None,
    boekstuk: str | None = None,
    bijlage: bool | None = None,
    dagboek: str | None = None,
) -> BoekingsFeit:
    if boekstuk is None:
        boekstuk = {
            "ManualJournals": "RLZ-06-00000012",
            "SalesInvoices": "RLZ-01-00000007",
            "PurchaseInvoices": "RLZ-04-00000846",
        }.get(collectie, "RLZ-99-1")
    return BoekingsFeit(
        collectie=collectie, boekstuk=boekstuk, entity_naam=entity, tekst=tekst, heeft_bijlage=bijlage, dagboek=dagboek
    )


class TestClassificatie:
    @pytest.mark.parametrize(
        ("feit", "soort", "zekerheid"),
        [
            (_feit("ManualJournals", "Aankoop Kerkstraat 44 Ede", bijlage=True), "aankoop", "hoog"),
            (_feit("ManualJournals", "Aankoop Kerkstraat 44 dossier 2025.058870.01", bijlage=False), "aankoop", "hoog"),
            (_feit("ManualJournals", "Aankoop Kerkstraat 44", bijlage=False), "aankoop", "midden"),
            (_feit("ManualJournals", "Aankoop Kerkstraat 44", bijlage=None), "aankoop", "midden"),
            (_feit("ManualJournals", "Notarisafrekening 2025.058870.01"), "aankoop", "laag"),
            (_feit("SalesInvoices", "Verkoop Kerkstraat 44, Ede", entity="Ouwerkerk Notariaat"), "verkoop", "hoog"),
            (_feit("SalesInvoices", "Verkoop Kerkstraat 44, Ede", entity="Jansen Beheer B.V."), "verkoop", "midden"),
            (_feit("SalesInvoices", "dossier 2025.058870.01", entity="Buma Algera Notarissen"), "verkoop", "laag"),
            (_feit("PurchaseInvoices", "keuring Kerkstraat 44", entity="Homekeur B.V."), "kosten", "midden"),
            (
                _feit(
                    "PurchaseInvoices", "nota 37863 Kerkstraat 44 dossier 2025.058870.01", entity="Ouwerkerk Notariaat"
                ),
                "kosten",
                "hoog",
            ),
            (
                _feit("PurchaseInvoices", "honorarium dossier 2025.058870.01", entity="Ouwerkerk Notariaat"),
                "kosten",
                "laag",
            ),
        ],
    )
    def test_soort_en_zekerheid(self, feit: BoekingsFeit, soort: str, zekerheid: str) -> None:
        c = classificeer(feit)
        assert c is not None and (c.soort, c.zekerheid) == (soort, zekerheid), c

    @pytest.mark.parametrize(
        "feit",
        [
            _feit(
                "PurchaseInvoices",
                "Administratiekantoor Nijenhuis 2026047",
                entity="Administratiekantoor Nijenhuis C.V.",
            ),
            _feit("ManualJournals", "Overige kosten — bank-direct"),
            _feit("SalesInvoices", "Rente", entity="Ouwerkerk Notariaat"),  # notaris zonder adres/dossier = geen pand
            _feit(
                "ManualJournals", "Aankoop Kerkstraat 44", boekstuk="RLZ-09-00000001", dagboek="Bank"
            ),  # geen memoriaal
            _feit("BankMutationDirectBookings", "Aankoop Kerkstraat 44"),
        ],
    )
    def test_geen_signaal(self, feit: BoekingsFeit) -> None:
        assert classificeer(feit) is None

    def test_memoriaal_op_dagboeknaam_zonder_boekstuk(self) -> None:
        c = classificeer(
            _feit("ManualJournals", "Aankoop Kerkstraat 44", boekstuk="X-1", dagboek="Memoriaal", bijlage=True)
        )
        assert c is not None and c.soort == "aankoop"

    def test_meerduidig_adres_wordt_niet_ingevuld(self) -> None:
        c = classificeer(_feit("ManualJournals", "Kerkstraat 44 en Kerkstraat 46 dossier 2025.058870.01", bijlage=True))
        assert c is not None and c.adres is None and c.zekerheid == "laag" and "meerdere adressen" in c.reden

    def test_classificatie_draagt_dossiers_en_notaris(self) -> None:
        c = classificeer(
            _feit("SalesInvoices", "Verkoop Kerkstraat 44 dossier 2025.058870.01", entity="Ouwerkerk Notariaat")
        )
        assert (
            c is not None
            and c.dossiers == ("2025.058870.01",)
            and c.notaris is not None
            and c.notaris.naam == "Ouwerkerk"
        )
