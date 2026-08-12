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
