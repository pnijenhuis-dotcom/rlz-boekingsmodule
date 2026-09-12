"""Blok D2 (bundel 10-09) + run 2 VGG blok 3 (12-09): deterministische afleiding pandenregister — pure functies,
parametrisch op de LETTERLIJKE omschrijvingen uit de nametingen 11-09 (panden 214 voorstellen + schoonlijst), in
RLZ-vorm mét de 32-tekens-knip (`\\n`) en ontknipt via `app/rlz/tekst.py`. Persoonsnamen = initialen.

Adressen (knip-reparatie, vulwoorden, plaats-/postcode-restanten, herhaalde straatnaam), dossiers (alleen notarisformaat
als sleutel; onvolledig apart; factuurnummers nooit), notaris-herkenning, classificatie (aankoop/verkoop/kosten/
aanbetaling/vaste_lasten/balans × hoog/midden/laag; 31-12 = balans; bank-direct = teken; Ouwerkerk-ontvangsten =
verkoop)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.panden.afleiding import (
    AdresVoorstel,
    BoekingsFeit,
    adres_uit_tekst,
    adressen_uit_tekst,
    classificeer,
    classificeer_bankmutatie,
    dossiernummer_uit_tekst,
    dossiernummers_uit_tekst,
    dossiers_uit_tekst,
    is_bank_direct,
    notaris_herkenning,
)
from app.rlz.tekst import ontknip


def rlz_vorm(tekst: str) -> str:
    """De RLZ-opslagvorm: regels van exact 32 tekens gescheiden door `\\n`, een spatie op de regelgrens gestript
    (blok 0 STAP-0 12-09). Zo wordt "Aanbetaling volgens afspraak: Oosterdiepswal 7 te Kollum" weer
    "Aanbetaling volgens afspraak: Oo\\nsterdiepswal 7 te Kollum"."""
    regels: list[str] = []
    rest = tekst
    while len(rest) > 32:
        regel, rest = rest[:32], rest[32:]
        if rest.startswith(" "):
            rest = rest[1:]
        regels.append(regel.rstrip())
    regels.append(rest)
    return "\n".join(regels)


def test_rlz_vorm_reproduceert_de_knip() -> None:
    assert rlz_vorm("Aanbetaling volgens afspraak: Oosterdiepswal 7 te Kollum") == (
        "Aanbetaling volgens afspraak: Oo\nsterdiepswal 7 te Kollum"
    )
    assert ontknip(rlz_vorm("Aanbetaling volgens afspraak: Oosterdiepswal 7 te Kollum")) == (
        "Aanbetaling volgens afspraak: Oosterdiepswal 7 te Kollum"
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
            # plaats zonder komma/te wordt nu herkend als het een bekende plaatsnaam is (run 2)
            (
                "Gustaaf Gelderstraat 12 Rotterdam",
                "Gustaaf Gelderstraat",
                "12",
                None,
                "Rotterdam",
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
            ("Hoofdweg 12-3 Amsterdam", "Hoofdweg", "12", "-3", "Amsterdam", None, "hoofdweg-12-3"),
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
            # ---- run 2: letterlijke nameting-omschrijvingen (ontknipt)
            (
                "Aanbetaling volgens afspraak: Oosterdiepswal 7 te Kollum",
                "Oosterdiepswal",
                "7",
                None,
                "Kollum",
                None,
                "oosterdiepswal-7",
            ),
            ("Aanbetaling Azielaan 334 Utrecht", "Azielaan", "334", None, "Utrecht", None, "azielaan-334"),
            (
                "Overdracht Azielaan 334 te Utrecht, ons dossier: 2025.078804.01",
                "Azielaan",
                "334",
                None,
                "Utrecht",
                None,
                "azielaan-334",
            ),
            (
                "Vaste lasten volgens afspraak: Azielaan 334 te Utrecht",
                "Azielaan",
                "334",
                None,
                "Utrecht",
                None,
                "azielaan-334",
            ),
            (
                "Aanbetaling volgens afspraak: Bleijeheiderstraat 123B, te Kerkrade",
                "Bleijeheiderstraat",
                "123",
                "B",
                "Kerkrade",
                None,
                "bleijeheiderstraat-123-b",
            ),
            (
                "betreft: Bleijerheiderstraat 123B te Kerkrade, ons dossier:2025.079527.01",
                "Bleijerheiderstraat",
                "123",
                "B",
                "Kerkrade",
                None,
                "bleijerheiderstraat-123-b",
            ),
            (
                "Overdracht Koraalerf 45 te Heerlen, ons dossier: 2025.079469.01",
                "Koraalerf",
                "45",
                None,
                "Heerlen",
                None,
                "koraalerf-45",
            ),
            ("Vaste lasten Molenstraat 13, Brunssum", "Molenstraat", "13", None, "Brunssum", None, "molenstraat-13"),
            (
                "Burgemeester Norbrui Burgemeester Norbruislaan 422",
                "Burgemeester Norbruislaan",
                "422",
                None,
                None,
                None,
                "burgemeester-norbruislaan-422",
            ),
            (
                "Gustaaf Gelderstraat Gustaaf Gelderstraat 60",
                "Gustaaf Gelderstraat",
                "60",
                None,
                None,
                None,
                "gustaaf-gelderstraat-60",
            ),
            (
                "Kasteel Hillenraedst Kasteel Hillenraedstraat 152",
                "Kasteel Hillenraedstraat",
                "152",
                None,
                None,
                None,
                "kasteel-hillenraedstraat-152",
            ),
            (
                "Henri Dunantstraat Henri Dunantstraat 301",
                "Henri Dunantstraat",
                "301",
                None,
                None,
                None,
                "henri-dunantstraat-301",
            ),
            ("HL Arnhem Papaverstraat 44", "Papaverstraat", "44", None, None, None, "papaverstraat-44"),
            ("Verhuizing Rotterdam Tapuitstraat 52A", "Tapuitstraat", "52", "A", None, None, "tapuitstraat-52-a"),
            ("Kouvenderstraat34b Hoensbroek", "Kouvenderstraat", "34", "b", "Hoensbroek", None, "kouvenderstraat-34-b"),
            (
                "Terugbetaling Kasteel Hillenraedtstraat 152, Roermond",
                "Kasteel Hillenraedtstraat",
                "152",
                None,
                "Roermond",
                None,
                "kasteel-hillenraedtstraat-152",
            ),
            ("Vastelasten Hilledijk 87D Rotterdam", "Hilledijk", "87", "D", "Rotterdam", None, "hilledijk-87-d"),
            ("F2026-0083 Lidwinahof 47", "Lidwinahof", "47", None, None, None, "lidwinahof-47"),
            (
                "Belasting verkoop Verschoorstraat 70-2",
                "Verschoorstraat",
                "70",
                "-2",
                None,
                None,
                "verschoorstraat-70-2",
            ),
            ("Aanbetaling Heidebeemd 3 Weert", "Heidebeemd", "3", None, "Weert", None, "heidebeemd-3"),
            (
                "Overdracht hogevecht 123 te Amsterdam, ons dossier: 2026.080369.01",
                "Hogevecht",
                "123",
                None,
                "Amsterdam",
                None,
                "hogevecht-123",
            ),
            (
                "Overdracht van de Spiegelstraat 42 te Bergen op Zoom, ons dossier: 2026.080912.01",
                "Van de Spiegelstraat",
                "42",
                None,
                "Bergen op Zoom",
                None,
                "van-de-spiegelstraat-42",
            ),
            (
                "Overdracht Apollolaan 644 te Leiden, ons dossier: 2026.081052.01",
                "Apollolaan",
                "644",
                None,
                "Leiden",
                None,
                "apollolaan-644",
            ),
            (
                "Overdracht Duifhuis 11 te Berlicum, ons dossier: 2026.080906.01",
                "Duifhuis",
                "11",
                None,
                "Berlicum",
                None,
                "duifhuis-11",
            ),
            (
                "Overdracht Sportlaan 180 te Purmerend, ons dossier: 2026.080301.01",
                "Sportlaan",
                "180",
                None,
                "Purmerend",
                None,
                "sportlaan-180",
            ),
            (
                "Overdracht Knopkruid 45, ons dossier 2025.079458.01",
                "Knopkruid",
                "45",
                None,
                None,
                None,
                "knopkruid-45",
            ),
            (
                "Overdracht Heelsumstraat 75 te 's-Gravenhage, ons dossier:2026.080234.01",
                "Heelsumstraat",
                "75",
                None,
                "'s-Gravenhage",
                None,
                "heelsumstraat-75",
            ),
            (
                "Maandelijkse aanbetaling: 2500 euro Nachtegaallaan 47, Goes",
                "Nachtegaallaan",
                "47",
                None,
                "Goes",
                None,
                "nachtegaallaan-47",
            ),
            (
                "Extra aanbetaling volgens afspraak: Mgr. Hanssenlaan 38, Hoensbroek",
                "Mgr. Hanssenlaan",
                "38",
                None,
                "Hoensbroek",
                None,
                "mgr-hanssenlaan-38",
            ),
            (
                "Vaste lasten volgens afspraak: Groningerstraatweg 203, Leeuwarden",
                "Groningerstraatweg",
                "203",
                None,
                "Leeuwarden",
                None,
                "groningerstraatweg-203",
            ),
            ("Laatste vaste lasten: Duifhuis 11, Berlicum", "Duifhuis", "11", None, "Berlicum", None, "duifhuis-11"),
            (
                "Vaste lasten maand september: Meekrapstraat 34A Rotterdam",
                "Meekrapstraat",
                "34",
                "A",
                "Rotterdam",
                None,
                "meekrapstraat-34-a",
            ),
            (
                "Aanbetaling volgens afspraak: Korenstraat 28, Olst",
                "Korenstraat",
                "28",
                None,
                "Olst",
                None,
                "korenstraat-28",
            ),
            (
                "extra aanbetaling volgens afspraak Merwede 43, Heerhugowaard",
                "Merwede",
                "43",
                None,
                "Heerhugowaard",
                None,
                "merwede-43",
            ),
            ("Vaste lasten augustus: Knopkruid 45, Venray", "Knopkruid", "45", None, "Venray", None, "knopkruid-45"),
            (
                "Aanbetaling volgens afspraak: Wadden 66, Zwijndrecht",
                "Wadden",
                "66",
                None,
                "Zwijndrecht",
                None,
                "wadden-66",
            ),
            (
                "Vaste lasten maand september: Oosterduinplein 18, IJmuiden",
                "Oosterduinplein",
                "18",
                None,
                "IJmuiden",
                None,
                "oosterduinplein-18",
            ),
            (
                "Haringvlietstraat 44 Dordrecht Rente",
                "Haringvlietstraat",
                "44",
                None,
                "Dordrecht",
                None,
                "haringvlietstraat-44",
            ),
            (
                "Vaste lasten t/m 17 september Spaakstraat 13, Zevenaar",
                "Spaakstraat",
                "13",
                None,
                "Zevenaar",
                None,
                "spaakstraat-13",
            ),
            (
                "Aanbetaling volgens afspraak: Archipel 15-17, Lelystad",
                "Archipel",
                "15",
                "-17",
                "Lelystad",
                None,
                "archipel-15-17",
            ),
            (
                "Fazantstraat 79a Rotterdam Vve kosten",
                "Fazantstraat",
                "79",
                "a",
                "Rotterdam",
                None,
                "fazantstraat-79-a",
            ),
            (
                "Vaste lasten: Papaverstraat 44, Utrecht",
                "Papaverstraat",
                "44",
                None,
                "Utrecht",
                None,
                "papaverstraat-44",
            ),
            (
                "2/2 aanbetaling Bornholmstraat 49, Almere",
                "Bornholmstraat",
                "49",
                None,
                "Almere",
                None,
                "bornholmstraat-49",
            ),
            (
                "Aanbetaling volgens afspraak: Stadhoudersring 374, Zoetermeer",
                "Stadhoudersring",
                "374",
                None,
                "Zoetermeer",
                None,
                "stadhoudersring-374",
            ),
            (
                "Aanbetaling volgens afspraak Allard Piersonlaan 20, Den Haag",
                "Allard Piersonlaan",
                "20",
                None,
                "Den Haag",
                None,
                "allard-piersonlaan-20",
            ),
            (
                "Aanbetaling volgens afspraal: Klinkenbergerweg 84D Ede",
                "Klinkenbergerweg",
                "84",
                "D",
                "Ede",
                None,
                "klinkenbergerweg-84-d",
            ),
            (
                "Aanbetaling volgens afspraak Goudreinetgaard 59, Arnhem",
                "Goudreinetgaard",
                "59",
                None,
                "Arnhem",
                None,
                "goudreinetgaard-59",
            ),
            (
                "aanbetaling volgens: Bovenpolder 49, de Meern",
                "Bovenpolder",
                "49",
                None,
                "de Meern",
                None,
                "bovenpolder-49",
            ),
            ("Vaste lasten: Dwartsweg 22, Zeist maand mei", "Dwartsweg", "22", None, "Zeist", None, "dwartsweg-22"),
            (
                "Overschiese Kleiweg 667 Rotterdam",
                "Overschiese Kleiweg",
                "667",
                None,
                "Rotterdam",
                None,
                "overschiese-kleiweg-667",
            ),
            (
                "betreft: Kruidenlaan 72 te Venray, ons dossier: 2026.080367.01",
                "Kruidenlaan",
                "72",
                None,
                "Venray",
                None,
                "kruidenlaan-72",
            ),
            ("Chevremontstraat 68 Kerkrade", "Chevremontstraat", "68", None, "Kerkrade", None, "chevremontstraat-68"),
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
        # Via de RLZ-vorm (32-tekens-knip) en ontknip — de knip mag het adres nooit meer breken.
        a = adres_uit_tekst(ontknip(rlz_vorm(tekst)))
        assert a is not None, tekst
        assert (a.straat, a.huisnummer, a.toevoeging, a.plaats, a.postcode) == (
            straat,
            nummer,
            toevoeging,
            plaats,
            postcode,
        )
        assert a.code == code
        assert adres_uit_tekst(tekst) == a  # en identiek zonder knip

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
            # run 2: schoonlijst-ruis mag geen adres worden
            "Maandelijkse aanbetaling: maand mei 2026",
            "Dossiernummer: 118261",
            "GJLDDTPWV9KGLMZ32GKII 7180895093 482084 trnsnr:797062166",
            "3774900 8030664778822344 Kadaster webwinkel producten",
            "Cafe In The City Amsterdam 7R-4729303687348224-NGZMC",
            "Cafe Restaurant Meyer Amsterdam 04-09-2026 18:03TERMINALID: 47464443 PASVOLGNR: 001",
            "TEVEELBET. NR. 868049025L015100 LOONH. OKT. 2025 (VASTGOEDGROE)",
            "25010051 RLZ-04-00000216 1-11-2025",
            "Full House Meubelverhuur 2620822",
            "lening volgens afspraak",
            "hypotheekgelden dossier 2026.080038.01",
            "ADWORDS:5600916770:GG104IN2RL",
            "Kadastralekaart.com - Enterprise abonnement. Maandelijks betalen. Vastgoedgroep Nederland B.V.",
            "W Begunstigde: 00000025316563490 101Betaaldatum: 24-08-2026 Kenmerk aanlevering:",
            "2026-0050",
            "F2026-0083",
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

    def test_fazantstraat_77_en_79_is_een_adres(self) -> None:
        # "77 en 79" — het tweede nummer heeft geen straat: één adres, niet meerduidig (Verhagen VvE-casus)
        assert adres_uit_tekst("Fazantstraat 77 en 79") == AdresVoorstel(straat="Fazantstraat", huisnummer="77")

    def test_zelfde_adres_twee_keer_is_een_adres(self) -> None:
        assert adres_uit_tekst("Kerkstraat 44", "nota Kerkstraat 44, Ede") is not None
        # Reference "Kleiweg 667" + Description "Overschiese Kleiweg 667" = één pand binnen één tekst
        assert adres_uit_tekst("Kleiweg 667 Overschiese Kleiweg 667 Rotterdam") is not None

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
            ("dossier 2025.058870.01 en 2025.058870", ("2025.058870.01",)),  # kort = zelfde dossier
            ("factuur 2026047 dd 2026-08-15", ()),  # datum is geen dossier
            ("Kerkstraat 44 2026.08.15", ()),
            ("", ()),
            # run 2: alleen het notarisformaat is een sleutel
            ("Dossiernr: 2025/061112 verkoop", ()),
            ("Dossiernummer: 118261", ()),
            ("2026-0050", ()),
            ("dossier 2026-0050", ()),
            ("F2026-0083 Lidwinahof 47", ()),
            ("2026-00084", ()),
            ("2025-02494", ()),
            ("2026-021018", ()),
            (
                "Overdracht Goeverneurlaan 310, Den Haag, ons dossier: 2025.079",
                (),
            ),  # afgekapt: onvolledig, geen sleutel
            ("ons dossier: 2026.0", ()),
            ("dossier 2025.079507", ()),
            ("betreft: Vondelstraat 14 te Roermond, ons dossier: 2026.079949.0", ()),
            ("betreft: Gustaaf Gelderstraat 60 te Almere, ons dossier: 2025.078957.01", ("2025.078957.01",)),
        ],
    )
    def test_dossiernummers(self, tekst: str, verwacht: tuple[str, ...]) -> None:
        assert dossiernummers_uit_tekst(ontknip(rlz_vorm(tekst)) if tekst else tekst) == verwacht

    @pytest.mark.parametrize(
        ("tekst", "onvolledig", "overig", "woord"),
        [
            ("Overdracht Goeverneurlaan 310, Den Haag, ons dossier: 2025.079", ("2025.079",), (), True),
            ("ons dossier: 2026.0", ("2026.0",), (), True),
            ("dossier 2025.079507", ("2025.079507",), (), True),
            ("betreft: Vondelstraat 14, ons dossier: 2026.079949.0", ("2026.079949.0",), (), True),
            ("Dossiernummer: 118261", (), ("118261",), True),
            ("Dossiernr: 2025/061112 verkoop", (), ("2025/061112",), True),
            ("dossier 2026-0050", (), (), True),  # factuurnummer-vorm: nooit een dossier, ook niet 'overig'
            ("SaaSIT 2026-0050", (), (), False),
            ("Notarisafrekening 2025.058870.01", (), (), False),
        ],
    )
    def test_onvolledig_en_overig(
        self, tekst: str, onvolledig: tuple[str, ...], overig: tuple[str, ...], woord: bool
    ) -> None:
        d = dossiers_uit_tekst(tekst)
        assert (d.onvolledig, d.overig, d.dossierwoord) == (onvolledig, overig, woord)

    def test_een_dossier_of_none(self) -> None:
        assert dossiernummer_uit_tekst("dossier 2025.058870.01") == "2025.058870.01"
        assert dossiernummer_uit_tekst("2025.058870.01 en 2026.014221.01") is None


class TestNotaris:
    @pytest.mark.parametrize(
        ("naam", "weergave", "bekend"),
        [
            ("Ouwerkerk Notariaat B.V.", "Ouwerkerk", True),
            ("Ouwerkerk Notariaat", "Ouwerkerk", True),  # tegenpartij-naam op de bankregel (schoonlijst)
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

    @pytest.mark.parametrize("naam", ["Homekeur B.V.", "Administratiekantoor Nijenhuis C.V.", None, "", "  ", "M.A.B."])
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
    bedrag: str | None = None,
    datum: str | None = None,
) -> BoekingsFeit:
    if boekstuk is None:
        boekstuk = {
            "ManualJournals": "RLZ-06-00000012",
            "SalesInvoices": "RLZ-01-00000007",
            "PurchaseInvoices": "RLZ-04-00000846",
            "Receipts": "RLZ-09-00001056",
            "PaymentTransactions": "00112",
        }.get(collectie, "RLZ-99-1")
    return BoekingsFeit(
        collectie=collectie,
        boekstuk=boekstuk,
        entity_naam=entity,
        tekst=ontknip(rlz_vorm(tekst)) or "",
        heeft_bijlage=bijlage,
        dagboek=dagboek,
        bedrag=Decimal(bedrag) if bedrag is not None else None,
        datum=date.fromisoformat(datum) if datum else None,
    )


OUWERKERK = "Ouwerkerk Notariaat"


class TestClassificatie:
    @pytest.mark.parametrize(
        ("feit", "soort", "zekerheid"),
        [
            # ---- run 1-gedrag dat blijft
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
            # ---- run 2: de zeven "Overdracht …"-memorialen zijn notaris-afrekeningen bij AANKOOP (bijlage = PDF)
            (
                _feit(
                    "ManualJournals",
                    "Overdracht Azielaan 334 te Utrecht, ons dossier: 2025.078804.01",
                    bijlage=True,
                    datum="2026-01-12",
                ),
                "aankoop",
                "hoog",
            ),
            (
                _feit(
                    "ManualJournals",
                    "Overdracht Goeverneurlaan 310, Den Haag, ons dossier: 2025.079",
                    datum="2026-01-12",
                ),
                "aankoop",
                "hoog",  # onvolledig dossier telt als tweede signaal, niet als sleutel
            ),
            # aanbetalingen — alle varianten, alle collecties (RLZ-04 bank-geïmporteerde inkoopfactuur, RLZ-06)
            (
                _feit(
                    "PurchaseInvoices",
                    "Aanbetaling volgens afspraak: Oosterdiepswal 7 te Kollum",
                    boekstuk="RLZ-04-00000062",
                ),
                "aanbetaling",
                "hoog",
            ),
            (
                _feit("ManualJournals", "Aanbetaling Heidebeemd 3 Weert", bedrag="-20000", datum="2025-09-02"),
                "aanbetaling",
                "hoog",
            ),
            (_feit("ManualJournals", "Aanbetaling Kapershoek 34 Rotterdam", bedrag="-20000"), "aanbetaling", "hoog"),
            (
                _feit("PurchaseInvoices", "Maandelijkse aanbetaling: 2500 euro Nachtegaallaan 47, Goes"),
                "aanbetaling",
                "hoog",
            ),
            (_feit("PurchaseInvoices", "2/2 aanbetaling Bornholmstraat 49, Almere"), "aanbetaling", "hoog"),
            (
                _feit("PurchaseInvoices", "Extra aanbetaling volgens afspraak: Rooseveltweg 13, Hulst"),
                "aanbetaling",
                "hoog",
            ),
            (_feit("PurchaseInvoices", "Aanbetaling Azielaan 334"), "aanbetaling", "midden"),
            (
                _feit("ManualJournals", "Dubbel retour aanbetaling Kerkstraat 44", boekstuk="RLZ-06-00000200"),
                "aanbetaling",
                "midden",
            ),
            # vaste lasten — W&V
            (
                _feit("ManualJournals", "Vaste lasten: Dwartsweg 22, Zeist maand mei", boekstuk="RLZ-25-00000568"),
                "vaste_lasten",
                "hoog",
            ),
            (
                _feit("ManualJournals", "Vaste lasten Molenstraat 13, Brunssum", boekstuk="RLZ-25-00000205"),
                "vaste_lasten",
                "hoog",
            ),
            (_feit("PurchaseInvoices", "Vastelasten Hilledijk 87D Rotterdam"), "vaste_lasten", "hoog"),
            (_feit("PurchaseInvoices", "Laatste vaste lasten: Duifhuis 11, Berlicum"), "vaste_lasten", "hoog"),
            (
                _feit("PurchaseInvoices", "Vaste lasten t/m 17 september Spaakstraat 13, Zevenaar"),
                "vaste_lasten",
                "hoog",
            ),
            # verkoop-signaal in de omschrijving (RLZ-28 bankreeks: "Belasting verkoop" = verkoop, midden — Peter 12-09)
            (
                _feit(
                    "ManualJournals",
                    "Belasting verkoop Verschoorstraat 70-2",
                    boekstuk="RLZ-28-00000090",
                    bedrag="-2100",
                ),
                "verkoop",
                "midden",
            ),
            # rente op een verkoopfactuur is geen verkoop
            (
                _feit("SalesInvoices", "Haringvlietstraat 44 Dordrecht Rente", boekstuk="RLZ-01-00000077"),
                "kosten",
                "hoog",
            ),
            # bank-directe boekingen: het teken beslist
            (
                _feit(
                    "Receipts",
                    "Overdracht Knopkruid 45, ons dossier 2025.079458.01",
                    entity=OUWERKERK,
                    bedrag="139834.74",
                ),
                "verkoop",
                "hoog",
            ),
            (
                _feit(
                    "ManualJournals", "Overdracht Kerkstraat 44 te Ede", boekstuk="RLZ-09-00000900", bedrag="-185000"
                ),
                "aankoop",
                "midden",
            ),
            (
                _feit("ManualJournals", "Aankoop Kerkstraat 44", boekstuk="RLZ-09-00000001", dagboek="Bank"),
                "kosten",
                "midden",
            ),
            (_feit("Receipts", "Fazantstraat 79a Rotterdam Vve kosten", bedrag="-56.18"), "kosten", "hoog"),
            # inkoopfacturen met adres zonder dossier = kosten midden (de 214-lijst: Chevremontstraat, Fazantstraat, …)
            (
                _feit("PurchaseInvoices", "Chevremontstraat 68 Kerkrade", entity="Consten Vastgoed B.V."),
                "kosten",
                "midden",
            ),
            (
                _feit("PurchaseInvoices", "Kouvenderstraat34b Hoensbroek", entity="Full House Meubelverhuur"),
                "kosten",
                "midden",
            ),
            (_feit("PurchaseInvoices", "F2026-0083 Lidwinahof 47"), "kosten", "midden"),
            (_feit("PurchaseInvoices", "HL Arnhem Papaverstraat 44"), "kosten", "midden"),
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
            _feit("BankMutationDirectBookings", "Aankoop Kerkstraat 44"),
            # run 2: guards
            _feit("PurchaseInvoices", "Dossiernummer: 118261", boekstuk="RLZ-17-00000464"),
            _feit("PurchaseInvoices", "2026-0050", entity="SaaSIT B.V."),
            _feit("PurchaseInvoices", "F2026-0083"),
            _feit("PurchaseInvoices", "2026-021018"),
            _feit(
                "PurchaseInvoices", "Maandelijkse aanbetaling: maand mei 2026"
            ),  # aanbetaling zonder adres = geen pand
            _feit("ManualJournals", "rc", boekstuk="RLZ-28-00000061", bedrag="135000"),
            _feit("ManualJournals", "Lening", boekstuk="RLZ-46-00000166", bedrag="70000"),
            _feit("Receipts", "", entity=None, bedrag="21388.37"),  # tekstloze RLZ-09-huls
            _feit("PaymentTransactions", "ADWORDS:5600916770:GG104IN2RL", entity="G.I.L.", bedrag="-500"),
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
        assert c.meerduidig is True

    def test_classificatie_draagt_dossiers_en_notaris(self) -> None:
        c = classificeer(
            _feit("SalesInvoices", "Verkoop Kerkstraat 44 dossier 2025.058870.01", entity="Ouwerkerk Notariaat")
        )
        assert (
            c is not None
            and c.dossiers == ("2025.058870.01",)
            and c.notaris is not None
            and c.notaris.naam == "Ouwerkerk"
            and c.dossierwoord is True
        )

    @pytest.mark.parametrize(
        ("tekst", "bedrag"),
        [
            ("Chevremontstraat 68 Kerkrade", "290000"),
            ("Loevesteinsingel 9 Rotterdam", "290000"),
            ("Bleijeheiderstraat 1", "190000"),
            ("Gustaaf Gelderstraat Gustaaf Gelderstraat 60", "200000"),
            ("Overdracht Azielaan 334 te Utrecht, ons dossier: 2025.078804.01", "250000"),
        ],
    )
    def test_31_12_memoriaal_is_balans_nooit_aankoop(self, tekst: str, bedrag: str) -> None:
        c = classificeer(_feit("ManualJournals", tekst, bedrag=bedrag, datum="2025-12-31", bijlage=True))
        assert c is not None and c.soort == "balans" and c.zekerheid == "midden"
        assert c.adres is not None
        # dezelfde tekst op een gewone dag blijft aankoop
        c2 = classificeer(_feit("ManualJournals", tekst, bedrag=bedrag, datum="2025-09-30", bijlage=True))
        assert c2 is not None and c2.soort == "aankoop"

    def test_31_12_zonder_adres_is_balans_laag(self) -> None:
        c = classificeer(_feit("ManualJournals", "jaareinde dossier 2025.058870.01", datum="2025-12-31"))
        assert c is not None and (c.soort, c.zekerheid) == ("balans", "laag")

    def test_31_12_in_bankreeks_is_geen_balans(self) -> None:
        c = classificeer(
            _feit(
                "ManualJournals",
                "Vaste lasten Molenstraat 13, Brunssum",
                boekstuk="RLZ-25-00000300",
                datum="2025-12-31",
            )
        )
        assert c is not None and c.soort == "vaste_lasten"


#: De zes open Ouwerkerk-ontvangsten (schoonlijst 11-09, open bankregels) — letterlijk, in RLZ-vorm mét knip.
OUWERKERK_ONTVANGSTEN: tuple[tuple[str, str, str], ...] = (
    ("Overdracht hogevecht 123 te Amst\nerdam, ons dossier: 2026.080369.\n01", "21388.37", "hogevecht-123"),
    (
        "Overdracht van de Spiegelstraat \n42 te Bergen op Zoom, ons dossie\nr: 2026.080912.01",
        "89023.39",
        "van-de-spiegelstraat-42",
    ),
    ("Overdracht Apollolaan 644 te Lei\nden, ons dossier: 2026.081052.01", "38423.39", "apollolaan-644"),
    ("Overdracht Duifhuis 11 te Berlic\num, ons dossier: 2026.080906.01", "56153.28", "duifhuis-11"),
    ("Overdracht Sportlaan 180 te Purm\nerend, ons dossier: 2026.080301.\n01", "30831.89", "sportlaan-180"),
    ("Overdracht Knopkruid 45, ons dos\nsier 2025.079458.01", "139834.74", "knopkruid-45"),
)


class TestBankmutatie:
    @pytest.mark.parametrize(("reference", "bedrag", "code"), OUWERKERK_ONTVANGSTEN)
    def test_ouwerkerk_ontvangst_is_verkoop_kandidaat(self, reference: str, bedrag: str, code: str) -> None:
        feit = BoekingsFeit(
            collectie="PaymentTransactions",
            boekstuk="00112",
            entity_naam=OUWERKERK,
            tekst=ontknip(reference) or "",
            bedrag=Decimal(bedrag),
            datum=date(2026, 8, 5),
        )
        c = classificeer_bankmutatie(feit)
        assert c is not None, feit.tekst
        assert (c.soort, c.zekerheid) == ("verkoop", "hoog")
        assert c.adres is not None and c.adres.code == code
        assert len(c.dossiers) == 1 and c.notaris is not None and c.notaris.naam == "Ouwerkerk"

    def test_betaling_aan_notaris_met_overdracht_is_aankoop(self) -> None:
        feit = BoekingsFeit(
            collectie="PaymentTransactions",
            boekstuk="00100",
            entity_naam=OUWERKERK,
            tekst="Overdracht Kerkstraat 44 te Ede, ons dossier: 2026.081000.01",
            bedrag=Decimal("-187144.23"),
        )
        c = classificeer_bankmutatie(feit)
        assert c is not None and (c.soort, c.zekerheid) == ("aankoop", "hoog")

    def test_hypotheekgelden_aan_notaris_is_verkoop_signaal_zonder_adres(self) -> None:
        # schoonlijst: "hypotheekgelden dossier 2026.080038.01" −187.144,23 op Ouwerkerk — verkoop-woord, alleen dossier
        feit = BoekingsFeit(
            collectie="PaymentTransactions",
            boekstuk="00100",
            entity_naam=OUWERKERK,
            tekst=ontknip("hypotheekgelden dossier 2026.080\n038.01") or "",
            bedrag=Decimal("-187144.23"),
        )
        c = classificeer_bankmutatie(feit)
        assert c is not None and (c.soort, c.zekerheid, c.dossiers) == ("verkoop", "laag", ("2026.080038.01",))

    @pytest.mark.parametrize(
        ("reference", "naam", "bedrag", "soort"),
        [
            ("Maandelijkse aanbetaling: Nachte\ngaallaan 47, Goes", "M.A.B.", "-2500", "aanbetaling"),
            ("Extra aanbetaling volgens afspra\nak: Mgr. Hanssenlaan 38, Hoensbr\noek", "J.J.", "-2500", "aanbetaling"),
            (
                "Vaste lasten volgens afspraak: G\nroningerstraatweg 203, Leeuwarde\nn",
                "G.K.",
                "-330.10",
                "vaste_lasten",
            ),
            ("Laatste vaste lasten: Duifhuis 1\n1, Berlicum", "T.J.", "-345", "vaste_lasten"),
            ("Vaste lasten maand september: Me\nekrapstraat 34A Rotterdam", "R.S.A.", "-1141", "vaste_lasten"),
            ("Aanbetaling volgens afspraak: Ko\nrenstraat 28, Olst", "J.E.", "-20000", "aanbetaling"),
            ("Vaste lasten augustus: Knopkruid\n45, Venray", "A.J.", "-800", "vaste_lasten"),
            ("2/2 aanbetaling Bornholmstraat 4\n9, Almere", "M.O.", "-10000", "aanbetaling"),
            ("Aanbetaling volgens afspraak All\nard Piersonlaan 20, Den Haag", "K.V.", "-20000", "aanbetaling"),
            ("Fazantstraat 79a Rotterdam Vve k\nosten", "VvE Fazantstraat", "-56.18", "kosten"),
        ],
    )
    def test_bankregels_schoonlijst(self, reference: str, naam: str, bedrag: str, soort: str) -> None:
        feit = BoekingsFeit(
            collectie="PaymentTransactions",
            boekstuk="00112",
            entity_naam=naam,
            tekst=ontknip(reference) or "",
            bedrag=Decimal(bedrag),
        )
        c = classificeer_bankmutatie(feit)
        assert c is not None and c.soort == soort and c.adres is not None, (reference, c)

    def test_alleen_paymenttransactions(self) -> None:
        assert classificeer_bankmutatie(_feit("PurchaseInvoices", "Aanbetaling Kerkstraat 44")) is None

    def test_is_bank_direct(self) -> None:
        assert is_bank_direct(_feit("Receipts", "x")) and is_bank_direct(_feit("PaymentTransactions", "x"))
        assert is_bank_direct(_feit("ManualJournals", "x", boekstuk="RLZ-25-00000001"))
        assert not is_bank_direct(_feit("ManualJournals", "x", boekstuk="RLZ-06-00000001"))
        assert not is_bank_direct(_feit("PurchaseInvoices", "x"))
