"""Poortlogica van de storno-blokkade ná ingediende btw-aangifte (app/rlz/aangifte.py,
besluit Peter 2026-08-15): datum-in-periode-toets, statusmodel (2/3 = ingediend, 1 = concept),
document-uitzonderingen (404/concept = vrij) en het fail-closed-gedrag bij álles wat niet
leesbaar is. Feiten: api-verkenning "Actie 19 in een periode met ingediende btw-aangifte"."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.rlz.aangifte import (
    STORNO_BLOKKADE_MELDING,
    AangiftePoort,
    KantToets,
    StornoGeblokkeerdDoorAangifte,
    blokkeer_bij_ingediende_aangifte,
)
from app.rlz.client import RlzApiError


class MiniClient:
    """Kleinste duck-typed client voor de poort: alleen list_tax_declarations."""

    def __init__(self, aangiften: list[dict[str, Any]] | None = None, *, fout: RlzApiError | None = None) -> None:
        self.aangiften = aangiften or []
        self.fout = fout
        self.reads = 0

    def list_tax_declarations(self) -> list[dict[str, Any]]:
        self.reads += 1
        if self.fout is not None:
            raise self.fout
        return self.aangiften


def _aangifte(status: int, start: str, eind: str) -> dict[str, Any]:
    return {"Status": status, "StartDate": f"{start}T00:00:00", "Date": f"{eind}T00:00:00"}


INGEDIEND_Q1 = _aangifte(2, "2026-01-01", "2026-03-31")
AFGEHANDELD_2018 = _aangifte(3, "2018-07-01", "2018-09-30")
CONCEPT_Q3 = _aangifte(1, "2026-07-01", "2026-09-30")


class TestToetsBoekdatum:
    def test_datum_in_ingediende_periode_blokkeert_met_periode(self) -> None:
        poort = AangiftePoort(MiniClient([INGEDIEND_Q1, CONCEPT_Q3]))
        toets = poort.toets_boekdatum(date(2026, 2, 15), kant="verkoopfactuur")
        assert toets.toegestaan is False
        assert toets.periode_start == date(2026, 1, 1)
        assert toets.periode_eind == date(2026, 3, 31)
        assert "2026-01-01 t/m 2026-03-31" in (toets.reden or "")

    def test_status_3_afgehandeld_telt_ook_als_ingediend(self) -> None:
        poort = AangiftePoort(MiniClient([AFGEHANDELD_2018]))
        assert poort.toets_boekdatum(date(2018, 8, 1), kant="x").toegestaan is False

    def test_periodegrenzen_zijn_inclusief(self) -> None:
        poort = AangiftePoort(MiniClient([INGEDIEND_Q1]))
        assert poort.toets_boekdatum(date(2026, 1, 1), kant="x").toegestaan is False
        assert poort.toets_boekdatum(date(2026, 3, 31), kant="x").toegestaan is False
        assert poort.toets_boekdatum(date(2025, 12, 31), kant="x").toegestaan is True
        assert poort.toets_boekdatum(date(2026, 4, 1), kant="x").toegestaan is True

    def test_concept_aangifte_blokkeert_niet(self) -> None:
        poort = AangiftePoort(MiniClient([CONCEPT_Q3]))
        assert poort.toets_boekdatum(date(2026, 8, 1), kant="x").toegestaan is True

    def test_leesfout_is_fail_closed(self) -> None:
        poort = AangiftePoort(MiniClient(fout=RlzApiError(500, "GET", "TaxDeclarations", "boem")))
        toets = poort.toets_boekdatum(date(2026, 8, 1), kant="x")
        assert toets.toegestaan is False
        assert "niet leesbaar" in (toets.reden or "")

    def test_ingediende_aangifte_zonder_leesbare_periode_is_fail_closed(self) -> None:
        poort = AangiftePoort(MiniClient([{"Status": 2, "StartDate": None, "Date": "kapot"}]))
        toets = poort.toets_boekdatum(date(2026, 8, 1), kant="x")
        assert toets.toegestaan is False
        assert "zonder leesbare periode" in (toets.reden or "")

    def test_aangiften_worden_maar_een_keer_gelezen(self) -> None:
        client = MiniClient([INGEDIEND_Q1])
        poort = AangiftePoort(client)
        poort.toets_boekdatum(date(2026, 2, 1), kant="a")
        poort.toets_boekdatum(date(2026, 8, 1), kant="b")
        assert client.reads == 1


class TestToetsDocument:
    def _poort(self) -> AangiftePoort:
        return AangiftePoort(MiniClient([INGEDIEND_Q1]))

    def test_geboekt_document_in_ingediende_periode_blokkeert(self) -> None:
        toets = self._poort().toets_document(
            lambda: {"Status": 2, "Date": "2026-02-15T00:00:00"}, kant="verkoopfactuur"
        )
        assert toets.toegestaan is False

    def test_gesloten_document_status_3_wordt_ook_getoetst(self) -> None:
        toets = self._poort().toets_document(
            lambda: {"Status": 3, "Date": "2026-02-15T00:00:00"}, kant="bankboeking"
        )
        assert toets.toegestaan is False

    def test_404_is_vrij_want_niets_geboekt(self) -> None:
        def ophalen() -> dict:
            raise RlzApiError(404, "GET", "SalesInvoices/x", "weg")

        assert self._poort().toets_document(ophalen, kant="x").toegestaan is True

    def test_concept_status_1_is_vrij(self) -> None:
        toets = self._poort().toets_document(lambda: {"Status": 1, "Date": "2026-02-15T00:00:00"}, kant="x")
        assert toets.toegestaan is True

    def test_andere_leesfout_is_fail_closed(self) -> None:
        def ophalen() -> dict:
            raise RlzApiError(502, "GET", "SalesInvoices/x", "gateway")

        toets = self._poort().toets_document(ophalen, kant="x")
        assert toets.toegestaan is False
        assert "document niet leesbaar" in (toets.reden or "")

    def test_geboekt_document_zonder_datum_is_fail_closed(self) -> None:
        toets = self._poort().toets_document(lambda: {"Status": 2}, kant="x")
        assert toets.toegestaan is False
        assert "boekdatum" in (toets.reden or "")


class TestBlokkeer:
    def test_een_geblokkeerde_kant_blokkeert_de_hele_set(self) -> None:
        kanten = [
            KantToets(kant="verkoopfactuur (bron)", toegestaan=True),
            KantToets(kant="spiegel (Rubicon)", toegestaan=False, reden="valt in ingediende aangifte"),
        ]
        with pytest.raises(StornoGeblokkeerdDoorAangifte) as excinfo:
            blokkeer_bij_ingediende_aangifte(kanten)
        assert excinfo.value.kanten == kanten
        assert STORNO_BLOKKADE_MELDING in str(excinfo.value)
        assert "spiegel (Rubicon): valt in ingediende aangifte" in excinfo.value.detail_tekst()

    def test_alles_toegestaan_laat_door(self) -> None:
        blokkeer_bij_ingediende_aangifte([KantToets(kant="a", toegestaan=True)])
