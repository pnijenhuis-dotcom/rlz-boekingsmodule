"""Run 2 VGG blok 3 (12-09): pandenlijst-seam (Protocol + CSV), matchdrempel en clustering — pure functies, geen DB."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.panden.afleiding import AdresVoorstel, adres_uit_tekst
from app.panden.pandenlijst import (
    CsvPandenlijst,
    PandenlijstFout,
    PandenlijstPand,
    cluster_adressen,
    normaliseer_toevoeging,
    straat_gelijk,
    zelfde_pand,
    zoek_in_lijst,
)


class TestDrempel:
    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("Koekoekstraat", "Koekoestraat"),
            ("Dwarsweg", "Dwartsweg"),
            ("Bleijeheiderstraat", "Bleijerheiderstraat"),
            ("Goeverneurlaan", "Goevernourlaan"),
            ("Goeverneurlaan", "Goeveneurlaan"),
            ("Kleiweg", "Overschiese Kleiweg"),  # suffix ≥ 6 (weggevallen voorvoegsel)
            ("Gelderstraat", "Gustaaf Gelderstraat"),
            ("Hanssenlaan", "Mgr. Hanssenlaan"),
            ("MGR. Hanssenlaan", "Mgr. Hanssenlaan"),
            ("Nachtegaallaan", "Nachtegaallaan"),
            ("Ruyghweg", "Ruygweg"),
            ("Appollolaan", "Apollolaan"),
            ("Kasteel Hillenraedstraat", "Kasteel Hillenraedtstraat"),
            ("Spiegelstraat", "Van de Spiegelstraat"),
        ],
    )
    def test_gelijk(self, a: str, b: str) -> None:
        assert straat_gelijk(a, b) and straat_gelijk(b, a)

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("Kerkstraat", "Kerklaan"),
            ("Rooseveltstraat", "Rooseveltweg"),  # ratio 0,69 — bewuste grens, apart gemeld in het rapport
            ("Tapuitstraat", "Fazantstraat"),
            ("Brinklaan", "Kruidenlaan"),
            ("Weg", "Laan"),  # korte namen nooit via prefix
        ],
    )
    def test_ongelijk(self, a: str, b: str) -> None:
        assert not straat_gelijk(a, b)

    def test_toevoeging_normalisatie(self) -> None:
        assert normaliseer_toevoeging("-02") == normaliseer_toevoeging("-2") == "2"
        assert normaliseer_toevoeging("b") == normaliseer_toevoeging("B") == "b"
        assert normaliseer_toevoeging(None) == ""

    def test_zelfde_pand_toevoeging_leeg_is_verenigbaar(self) -> None:
        a = AdresVoorstel(straat="Goeverneurlaan", huisnummer="310")
        b = AdresVoorstel(straat="Goevernourlaan", huisnummer="310", toevoeging="D")
        c = AdresVoorstel(straat="Goeverneurlaan", huisnummer="310", toevoeging="A")
        assert zelfde_pand(a, b) and not zelfde_pand(b, c)
        assert not zelfde_pand(a, AdresVoorstel(straat="Goeverneurlaan", huisnummer="311"))


class TestCluster:
    def test_nameting_varianten_worden_een_pand(self) -> None:
        teksten = [
            "Chevremontstraat 68 Kerkrade",
            "C hevremontstraat 68 Kerkrade",  # pre-ontknip-restanten mogen óók samenvallen (ratio)
            "Chevr emontstraat 68 Kerkrade",
            "Bleijeheiderstraat 123B Kerkrade",
            "Bleijerheiderstraat 123B te Kerkrade",
            "Goeverneurlaan 310, Den Haag",
            "Goevernourlaan 310D",
            "Goeveneurlaan 310",
            "Overschiese Kleiweg 667 Rotterdam",
            "Kleiweg 667",
            "Gustaaf Gelderstraat 60, Almere",
            "Gelderstraat 60 Almere",
            "Kouvenderstraat34b Hoensbroek",
            "Kouvenderstraat 43b",  # ander nummer: apart (tikfout in de bron, bewust niet geraden)
            "Fazantstraat 77",
            "Fazantstraat 79a Rotterdam",
        ]
        adressen = [a for t in teksten if (a := adres_uit_tekst(t)) is not None]
        assert len(adressen) == len(teksten)
        clusters = cluster_adressen(adressen)
        per_code = {c.representant.code: c for c in clusters}
        assert len(clusters) == 9, sorted(per_code)  # Kouvender 34b/43b en Fazant 77/79a bewust apart
        chev = next(c for c in clusters if c.representant.huisnummer == "68")
        assert chev.representant.straat == "Chevremontstraat" and len(chev.leden) == 3
        assert chev.varianten[0] == "Chevremontstraat" and len(chev.varianten) == 3
        goev = next(c for c in clusters if c.representant.huisnummer == "310")
        assert len(goev.leden) == 3 and goev.representant.toevoeging == "D" and goev.representant.plaats == "Den Haag"
        klei = next(c for c in clusters if c.representant.huisnummer == "667")
        assert klei.representant.straat == "Overschiese Kleiweg"  # tie → langste naam
        assert klei.codes == ["overschiese-kleiweg-667", "kleiweg-667"]

    def test_meest_voorkomende_variant_wint(self) -> None:
        adressen = [
            AdresVoorstel(straat="Bleijeheiderstraat", huisnummer="123", toevoeging="B"),
            AdresVoorstel(straat="Bleijeheiderstraat", huisnummer="123", toevoeging="B"),
            AdresVoorstel(straat="Bleijerheiderstraat", huisnummer="123", toevoeging="B", plaats="Kerkrade"),
        ]
        (cl,) = cluster_adressen(adressen)
        assert cl.representant.straat == "Bleijeheiderstraat" and cl.representant.plaats == "Kerkrade"
        assert cl.varianten == ["Bleijeheiderstraat", "Bleijerheiderstraat"]

    def test_leeg(self) -> None:
        assert cluster_adressen([]) == []


LIJST = [
    PandenlijstPand("Chevremontstraat", "68", None, "6461 XT", "Kerkrade", "a0X1"),
    PandenlijstPand("Bleijerheiderstraat", "123", "B", None, "Kerkrade", "a0X2"),
    PandenlijstPand("Overschiese Kleiweg", "667", None, None, "Rotterdam", "a0X3"),
    PandenlijstPand("Kerkstraat", "44", None, None, "Ede", "a0X4"),
    PandenlijstPand("Kerklaan", "44", None, None, "Ede", "a0X5"),
    PandenlijstPand("Rooseveltstraat", "13", None, None, "Hulst", None),
]


class TestZoekInLijst:
    def test_bindt_op_similariteit_en_toevoeging(self) -> None:
        m = zoek_in_lijst(AdresVoorstel(straat="Bleijeheiderstraat", huisnummer="123", toevoeging="B"), LIJST)
        assert m.gebonden and m.pand is not None and m.pand.salesforce_id == "a0X2" and m.pand.code == "sf-a0x2"
        m2 = zoek_in_lijst(AdresVoorstel(straat="Kleiweg", huisnummer="667"), LIJST)
        assert m2.gebonden and m2.pand is not None and m2.pand.salesforce_id == "a0X3"
        m3 = zoek_in_lijst(AdresVoorstel(straat="Rooseveltstraat", huisnummer="13"), LIJST)
        assert m3.gebonden and m3.pand is not None and m3.pand.code == "rooseveltstraat-13"  # zonder sf-id: adres-code

    def test_geen_kandidaat(self) -> None:
        m = zoek_in_lijst(AdresVoorstel(straat="Tapuitstraat", huisnummer="52", toevoeging="A"), LIJST)
        assert not m.gebonden and not m.meerduidig and m.kandidaten == ()

    def test_meerduidig_wordt_niet_gebonden(self) -> None:
        lijst = [
            PandenlijstPand("Kerkstraat", "44", None, None, "Ede", "a1"),
            PandenlijstPand("Kerkstraat", "44", None, None, "Wageningen", "a2"),
        ]
        m = zoek_in_lijst(AdresVoorstel(straat="Kerkstraat", huisnummer="44"), lijst)
        assert not m.gebonden and m.meerduidig and len(m.kandidaten) == 2
        # mét plaats in de tekst is het wél eenduidig
        m2 = zoek_in_lijst(AdresVoorstel(straat="Kerkstraat", huisnummer="44", plaats="Ede"), lijst)
        assert m2.gebonden and m2.pand is not None and m2.pand.salesforce_id == "a1"

    def test_beste_score_wint_bij_twee_kandidaten(self) -> None:
        # Kerkstraat 44 vs Kerklaan 44: alleen "Kerkstraat" haalt de drempel
        m = zoek_in_lijst(AdresVoorstel(straat="Kerkstraat", huisnummer="44"), LIJST)
        assert m.gebonden and m.pand is not None and m.pand.salesforce_id == "a0X4"


class TestCsv:
    def test_leest_puntkomma_en_komma(self, tmp_path: Path) -> None:
        p1 = tmp_path / "a.csv"
        p1.write_text(
            "Adres;Huisnummer;Toevoeging;Postcode;Plaats;Salesforce_Id\n"
            "Chevremontstraat;68;;6461 XT;Kerkrade;a0X1\n"
            "Bleijerheiderstraat;123B;;;Kerkrade;a0X2\n"
            ";12;;;;a0X9\n",
            encoding="utf-8",
        )
        lijst = CsvPandenlijst(p1)
        panden = lijst.panden()
        assert [p.code for p in panden] == ["sf-a0x1", "sf-a0x2"]
        assert panden[0].postcode == "6461XT" and panden[1].toevoeging == "B" and panden[1].huisnummer == "123"
        assert lijst.overgeslagen == ["regel 4: straat/huisnummer ontbreekt"]

        p2 = tmp_path / "b.csv"
        p2.write_text("straat,huisnummer,plaats\nKerkstraat,44,Ede\n", encoding="utf-8-sig")
        (pand,) = CsvPandenlijst(p2).panden()
        assert pand.code == "kerkstraat-44" and pand.salesforce_id is None

    def test_verplichte_kolommen(self, tmp_path: Path) -> None:
        p = tmp_path / "c.csv"
        p.write_text("naam;plaats\nx;y\n", encoding="utf-8")
        with pytest.raises(PandenlijstFout, match="huisnummer verplicht"):
            CsvPandenlijst(p).panden()

    def test_leeg_bestand(self, tmp_path: Path) -> None:
        p = tmp_path / "d.csv"
        p.write_text("adres;huisnummer\n", encoding="utf-8")
        with pytest.raises(PandenlijstFout, match="geen rijen"):
            CsvPandenlijst(p).panden()
