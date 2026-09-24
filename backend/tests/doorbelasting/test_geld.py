"""Pure geldlogica-tests (werkwijze: tests verplicht op geldlogica vóór al het andere).
De verwachtingswaarden komen uit de geverifieerde praktijk: Rubicon-spiegel §2c
(357,00 → 74,97; 17,85 → 3,75) en de mockup-#verdeelmodal-belofte "er raakt nooit een
cent kwijt" (grootste-rest)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.doorbelasting.geld import btw_over, provisie_over, verdeel_grootste_rest

D = Decimal


class TestVerdeelGrootsteRest:
    def test_exact_deelbaar(self) -> None:
        assert verdeel_grootste_rest(D("100.00"), [D(50), D(30), D(20)]) == [
            D("50.00"),
            D("30.00"),
            D("20.00"),
        ]

    def test_mockup_casus_411_10(self) -> None:
        # mockup #verdeelmodal: € 411,10 over 50/30/20 → 205,55 + 123,33 + 82,22
        delen = verdeel_grootste_rest(D("411.10"), [D(50), D(30), D(20)])
        assert delen == [D("205.55"), D("123.33"), D("82.22")]
        assert sum(delen) == D("411.10")

    def test_restcent_naar_grootste_rest(self) -> None:
        # 100,00 over 3×33,33% + 0,01 restruimte bestaat niet — som moet 100 zijn;
        # klassieke casus: 100 over 1/3-1/3-1/3 kan hier niet (33,33+33,33+33,34=100)
        delen = verdeel_grootste_rest(D("100.00"), [D("33.33"), D("33.33"), D("33.34")])
        assert sum(delen) == D("100.00")
        assert all(d >= D("33.33") for d in delen)

    def test_som_altijd_exact_ook_bij_lelijke_percentages(self) -> None:
        bedrag = D("999.99")
        delen = verdeel_grootste_rest(bedrag, [D("12.5"), D("12.5"), D("25"), D("50")])
        assert sum(delen) == bedrag

    def test_negatief_bedrag_creditnota(self) -> None:
        delen = verdeel_grootste_rest(D("-411.10"), [D(50), D(30), D(20)])
        assert sum(delen) == D("-411.10")
        assert delen[0] == D("-205.55")

    def test_percentages_moeten_op_100_sommen(self) -> None:
        with pytest.raises(ValueError, match="niet 100"):
            verdeel_grootste_rest(D("100.00"), [D(50), D(30)])

    def test_lege_lijst(self) -> None:
        with pytest.raises(ValueError, match="lege"):
            verdeel_grootste_rest(D("100.00"), [])

    def test_een_ontvanger_krijgt_alles(self) -> None:
        assert verdeel_grootste_rest(D("123.45"), [D(100)]) == [D("123.45")]


class TestBtwOver:
    def test_rubicon_kostenregel(self) -> None:
        assert btw_over(D("357.00"), D("21.00")) == D("74.97")

    def test_rubicon_provisieregel_afronding_omhoog(self) -> None:
        # 17,85 × 21% = 3,7485 → 3,75 (ROUND_HALF_UP, geverifieerd §2c)
        assert btw_over(D("17.85"), D("21.00")) == D("3.75")

    def test_half_up_grens(self) -> None:
        assert btw_over(D("0.10"), D("21.00")) == D("0.02")  # 0,021 → 0,02
        assert btw_over(D("0.50"), D("21.00")) == D("0.11")  # 0,105 → 0,11 (half-up)

    def test_nul_percentage(self) -> None:
        assert btw_over(D("100.00"), D("0")) == D("0.00")


class TestProvisieOver:
    def test_kempen_5_procent(self) -> None:
        # verkenning §2a: 2549,00 → 127,45
        assert provisie_over(D("2549.00"), D("5.00")) == D("127.45")

    def test_rubicon_bloxs(self) -> None:
        # §2c: 357,00 → 17,85
        assert provisie_over(D("357.00"), D("5.00")) == D("17.85")

    def test_afronding(self) -> None:
        # 33,33 × 5% = 1,6665 → 1,67
        assert provisie_over(D("33.33"), D("5.00")) == D("1.67")

    def test_config_niet_5(self) -> None:
        assert provisie_over(D("100.00"), D("7.50")) == D("7.50")


# ---- RLZ-vorm (STAP-0 24-09, opdracht "doorbelasting btw per tarief over subtotaal") -----------------------------------
#
# Bewijs: verkenning/stap0-doorbelasting-btw-rekenregel-24-09.tsv — 166/166 productiedocumenten (85 doorbelastingsverkopen
# KF, 49 spiegels, 32 gewone inkoopfacturen waarvan 15 mét twee tarieven; 10 exacte-halve-gevallen; 6 creditregels).
# Regel: document-btw per tarief = ROUND_HALF_UP(Σ netto × pct); per regel ROUND_HALF_UP(netto × pct), de grootste regel
# (|netto|, bij gelijk de eerste) draagt het verschil. De verwachtingswaarden hieronder zijn letterlijk RLZ-records.

from app.doorbelasting.geld import btw_rlz_vorm, btw_rlz_vorm_per_tarief  # noqa: E402

P21 = D("21.00")


class TestBtwRlzVorm:
    def test_lusso_261004_kf_naar_molenhof_verhuur(self) -> None:
        # RLZ-01-00002726 / RLZ-04-00000614: RLZ legt 1.045,51 vast (995,72 + 49,79), de oude motor boekte 995,73 + 49,79.
        totaal, regels = btw_rlz_vorm([D("4741.55"), D("237.08")], P21)
        assert totaal == D("1045.51")
        assert regels == [D("995.72"), D("49.79")]
        assert sum(regels) == totaal
        assert D("4741.55") + D("237.08") + totaal == D("6024.14")

    def test_verschil_omhoog_naar_de_grootste_regel(self) -> None:
        # V-24713244 (1.641,26 + 82,06): per regel 344,66 + 17,23 = 361,89, RLZ 361,90 → grootste regel +0,01.
        totaal, regels = btw_rlz_vorm([D("1641.26"), D("82.06")], P21)
        assert totaal == D("361.90") and regels == [D("344.67"), D("17.23")]

    def test_grootste_regel_wint_ook_als_die_niet_de_eerste_is(self) -> None:
        # V-24713352: RLZ ['78.75', '806.39', '86.0', '46.41', '50.88'] — de tweede regel (3.840) draagt −0,01.
        totaal, regels = btw_rlz_vorm([D("375"), D("3840"), D("409.5"), D("221"), D("242.28")], P21)
        assert regels == [D("78.75"), D("806.39"), D("86.00"), D("46.41"), D("50.88")]
        assert totaal == D("1068.43")

    def test_twee_centen_verschil_op_de_grootste_regel(self) -> None:
        # V-24713368 (8 regels): RLZ 417,24 op 1.986,96 waar round(1.986,96 × 21 %) = 417,26 → −0,02 op de grootste.
        nettos = [D("834.75"), D("302.6"), D("1986.96"), D("80.42"), D("556.5"), D("80.42"), D("553.09"), D("219.74")]
        totaal, regels = btw_rlz_vorm(nettos, P21)
        assert totaal == D("969.04") and regels[2] == D("417.24") and sum(regels) == totaal

    def test_gelijke_grootste_regels_de_eerste_draagt_het_verschil(self) -> None:
        # I-KF-RLZ-04-00004327 (139,50 + 139,50): RLZ 29,29 + 29,30 = 58,59.
        totaal, regels = btw_rlz_vorm([D("139.50"), D("139.50")], P21)
        assert totaal == D("58.59") and regels == [D("29.29"), D("29.30")]

    @pytest.mark.parametrize(
        ("nettos", "verwacht"),
        [
            ([D("650.00"), D("32.50")], D("143.33")),  # 682,50 × 21 % = 143,325 → half-up (RLZ 143,33; half-even zou 143,32 geven)
            ([D("1850.00"), D("92.50")], D("407.93")),
            ([D("2250.00"), D("112.50")], D("496.13")),
            ([D("223.33"), D("11.17")], D("49.25")),
        ],
    )
    def test_exacte_helft_rondt_half_up(self, nettos: list[Decimal], verwacht: Decimal) -> None:
        totaal, _ = btw_rlz_vorm(nettos, P21)
        assert totaal == verwacht

    def test_creditregel_negatief(self) -> None:
        # V-24713270 (−300 + provisie −15): RLZ −63,00 / −3,15 = −66,15.
        totaal, regels = btw_rlz_vorm([D("-300.00"), D("-15.00")], P21)
        assert totaal == D("-66.15") and regels == [D("-63.00"), D("-3.15")]
        # V-24713286 (kostenregels mét een negatieve correctieregel): RLZ 56,34 / −0,21 / 9,58 / 3,29 = 69,00.
        totaal, regels = btw_rlz_vorm([D("268.31"), D("-1.00"), D("45.60"), D("15.65")], P21)
        assert totaal == D("69.00") and regels == [D("56.34"), D("-0.21"), D("9.58"), D("3.29")]

    def test_een_regel_is_ongewijzigd_gedrag(self) -> None:
        for netto in (D("357.00"), D("17.85"), D("0.50"), D("100.00")):
            totaal, regels = btw_rlz_vorm([netto], P21)
            assert regels == [btw_over(netto, P21)] and totaal == regels[0]

    def test_provisie_nul(self) -> None:
        totaal, regels = btw_rlz_vorm([D("100.00"), D("0.00")], P21)
        assert totaal == D("21.00") and regels == [D("21.00"), D("0.00")]

    def test_geen_regels_is_een_fout(self) -> None:
        with pytest.raises(ValueError, match="geen regels"):
            btw_rlz_vorm([], P21)

    def test_property_som_regel_btw_is_altijd_de_document_btw(self) -> None:
        """Eigenschap: Σ regel-btw == ROUND_HALF_UP(Σ netto × pct) voor willekeurige regelsets (incl. negatief, nul,
        exacte halven), en élke niet-grootste regel is exact ROUND_HALF_UP(netto × pct)."""
        import random

        rnd = random.Random(2409)
        for _ in range(2000):
            n = rnd.randint(1, 9)
            nettos = [D(rnd.randint(-500000, 500000)) / 100 for _ in range(n)]
            if rnd.random() < 0.3:
                nettos[rnd.randrange(n)] = D(rnd.randint(0, 9999)) + D("0.50")  # exacte-helft-kandidaat
            pct = rnd.choice([P21, D("9.00"), D("0.00")])
            totaal, regels = btw_rlz_vorm(nettos, pct)
            assert sum(regels, D(0)) == totaal == btw_over(sum(nettos, D(0)), pct)
            grootste = max(range(n), key=lambda i: (abs(nettos[i]), -i))
            for i, (netto, btw) in enumerate(zip(nettos, regels, strict=True)):
                if i != grootste:
                    assert btw == btw_over(netto, pct)
            assert abs(regels[grootste] - btw_over(nettos[grootste], pct)) <= D("0.01") * n


class TestBtwRlzVormPerTarief:
    def test_twee_tarieven_kf_rlz_04_00004480(self) -> None:
        # 974,50 à 21 % + 339,18 à 9 %: RLZ 204,65 + 30,53 = 235,18 (per tarief; 313,68 × … zou 235,17 geven).
        totaal, regels = btw_rlz_vorm_per_tarief([(D("974.50"), P21), (D("339.18"), D("9.00"))])
        assert totaal == D("235.18") and regels == [D("204.65"), D("30.53")]

    def test_twee_tarieven_verschil_binnen_de_groep_blijft_in_de_groep(self) -> None:
        # BLOw RLZ-04-00000386: 8,21 à 21 % + 1,28 à 9 % → 1,72 + 0,12 = 1,84 (onze registratie droeg 1,85).
        totaal, regels = btw_rlz_vorm_per_tarief([(D("8.21"), P21), (D("1.28"), D("9.00"))])
        assert totaal == D("1.84") and regels == [D("1.72"), D("0.12")]

    def test_een_tarief_valt_samen_met_btw_rlz_vorm(self) -> None:
        nettos = [D("4741.55"), D("237.08")]
        assert btw_rlz_vorm_per_tarief([(n, P21) for n in nettos]) == btw_rlz_vorm(nettos, P21)

    def test_nul_tarief_regels_dragen_nul(self) -> None:
        # I-KF-RLZ-04-00004406: 268,31 à 21 % + −1,00 à 0 % + 45,60 à 21 % → RLZ 56,34 / 0,00 / 9,58 = 65,92.
        totaal, regels = btw_rlz_vorm_per_tarief([(D("268.31"), P21), (D("-1.00"), D("0")), (D("45.60"), P21)])
        assert totaal == D("65.92") and regels == [D("56.34"), D("0.00"), D("9.58")]
