"""Periodiek vs batch — pure classificatie van een reeks GELIJKE facturen (blok 7 run 11-09 middag; casus Lusso:
12 gelijke facturen voor 12 chalets in één week → géén staande-goedkeuring-voorstel). Eén gedeelde motor
(`app/terugkerend/service.py::classificeer_reeks` bovenop `detecteer_patroon`), drempels als benoemde constanten."""

from __future__ import annotations

from datetime import date, timedelta

from app.terugkerend import service
from app.terugkerend.service import ReeksClassificatie as R


def _reeks(start: date, *, aantal: int, stap_dagen: int) -> list[date]:
    return [start + timedelta(days=i * stap_dagen) for i in range(aantal)]


class TestConstanten:
    def test_drempels_hebben_een_naam_en_zijn_consistent(self) -> None:
        assert service.PERIODIEK_MIN_TUSSENPOOS_DAGEN == 21
        assert service.BATCH_VENSTER_DAGEN == 30
        assert service.BATCH_MIN_AANTAL == 2
        assert service.PERIODIEK_MIN_FACTUREN == service.MIN_FACTUREN == 3
        # Een maandpatroon (nominaal 30,44 d, ondergrens 19,8 d) mag nooit onder de batch-grens uitkomen: de
        # 21-dagengrens ligt bewust bóven de tolerantie-ondergrens, anders zou een krap maandpatroon "periodiek"
        # én "batch" tegelijk kunnen zijn.
        assert service.NOMINAAL["maand"] * (1 - service.TOLERANTIE) < service.PERIODIEK_MIN_TUSSENPOOS_DAGEN


class TestBatch:
    def test_lusso_twaalf_gelijke_facturen_op_een_dag_is_batch(self) -> None:
        uit = service.classificeer_reeks([date(2026, 9, 1)] * 12)
        assert uit.classificatie is R.BATCH
        assert uit.patroon is None
        assert "0 dagen" in uit.reden

    def test_twaalf_gelijke_facturen_in_een_week_is_batch(self) -> None:
        uit = service.classificeer_reeks(_reeks(date(2026, 9, 1), aantal=12, stap_dagen=0) + [date(2026, 9, 5)])
        assert uit.classificatie is R.BATCH

    def test_twee_gelijke_facturen_binnen_dertig_dagen_zonder_patroon_is_batch(self) -> None:
        # 25 dagen: niet < 21 (dus geen zelfde-dag/deellevering-signaal) maar ook geen bewezen patroon (n = 2).
        uit = service.classificeer_reeks([date(2026, 8, 1), date(2026, 8, 26)])
        assert uit.classificatie is R.BATCH
        assert "binnen 30 dagen" in uit.reden

    def test_maandpatroon_met_zelfde_dag_dubbel_is_batch(self) -> None:
        """Lusso-variant "12 chalets élke maand": de korte tussenpoos wint van het maandritme — élke factuur zien."""
        datums = _reeks(date(2026, 1, 1), aantal=4, stap_dagen=30) + [date(2026, 3, 2)]
        assert service.classificeer_reeks(datums).classificatie is R.BATCH

    def test_deellevering_veertien_dagen_is_batch(self) -> None:
        assert service.classificeer_reeks([date(2026, 6, 1), date(2026, 6, 15)]).classificatie is R.BATCH


class TestPeriodiek:
    def test_maandhuur_drie_facturen(self) -> None:
        uit = service.classificeer_reeks([date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1)])
        assert uit.classificatie is R.PERIODIEK
        assert uit.patroon is not None and uit.patroon.soort == "maand" and uit.patroon.aantal == 3

    def test_kwartaal(self) -> None:
        uit = service.classificeer_reeks(_reeks(date(2026, 1, 1), aantal=4, stap_dagen=91))
        assert uit.classificatie is R.PERIODIEK and uit.patroon is not None and uit.patroon.soort == "kwartaal"

    def test_volgorde_van_invoer_maakt_niet_uit(self) -> None:
        datums = [date(2026, 8, 1), date(2026, 6, 1), date(2026, 7, 1)]
        assert service.classificeer_reeks(datums).classificatie is R.PERIODIEK

    def test_krap_maandpatroon_boven_21_dagen_blijft_periodiek(self) -> None:
        assert (
            service.classificeer_reeks(_reeks(date(2026, 1, 1), aantal=4, stap_dagen=22)).classificatie is R.PERIODIEK
        )


class TestOnbepaald:
    def test_een_factuur(self) -> None:
        uit = service.classificeer_reeks([date(2026, 6, 1)])
        assert uit.classificatie is R.ONBEPAALD and uit.patroon is None

    def test_geen_facturen(self) -> None:
        assert service.classificeer_reeks([]).classificatie is R.ONBEPAALD

    def test_twee_facturen_ver_uit_elkaar_nog_geen_patroon(self) -> None:
        """Vóór blok 7 kreeg de accordeur hier al het voorstel (2e identieke factuur); nu pas bij een bewezen
        patroon van drie."""
        uit = service.classificeer_reeks([date(2026, 6, 1), date(2026, 8, 1)])
        assert uit.classificatie is R.ONBEPAALD
        assert "nog geen 3" in uit.reden

    def test_tweede_maandfactuur_is_nog_batch_derde_maakt_periodiek(self) -> None:
        """Exact 30 dagen (1 juni → 1 juli) valt binnen het batch-venster zolang er geen patroon van drie is: de
        tweede maandhuur krijgt dus geen voorstel, de derde wél — precies één voorstel per patroon."""
        assert service.classificeer_reeks([date(2026, 6, 1), date(2026, 7, 1)]).classificatie is R.BATCH
        derde = service.classificeer_reeks([date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1)])
        assert derde.classificatie is R.PERIODIEK

    def test_onregelmatig(self) -> None:
        uit = service.classificeer_reeks([date(2026, 1, 1), date(2026, 2, 15), date(2026, 8, 1)])
        assert uit.classificatie is R.ONBEPAALD
