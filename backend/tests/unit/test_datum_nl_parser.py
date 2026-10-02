"""Punt 15 run A 02-10 — dé ene parser voor een door een mens getypte kalenderdag (`app.tijd.parse_datum_nl`).

Peter 02-10: "kvk uittreksel upload geeft melding geldig_tot: Input should be a valid date or datetime, invalid
date separator, expected `-`". De drie aanvaarde vormen (jjjj-mm-dd, dd-mm-jjjj, dd/mm/jjjj) geven dezelfde dag;
al het andere één melding in gewone taal mét het voorbeeld 31-12-2026."""

from __future__ import annotations

from datetime import date

import pytest

from app.tijd import DATUM_FOUT_TEKST, OngeldigeDatum, parse_datum_nl


@pytest.mark.parametrize(
    "invoer",
    ["2026-12-31", "31-12-2026", "31/12/2026", " 2026-12-31 ", "2026-12-31\n", "31-12-2026 "],
)
def test_drie_vormen_geven_dezelfde_kalenderdag(invoer: str) -> None:
    assert parse_datum_nl(invoer) == date(2026, 12, 31)


@pytest.mark.parametrize("invoer", ["2026-1-5", "5-1-2026", "5/1/2026"])
def test_eencijferige_dag_en_maand_mogen(invoer: str) -> None:
    assert parse_datum_nl(invoer) == date(2026, 1, 5)


@pytest.mark.parametrize("invoer", [None, "", "   "])
def test_leeg_is_geen_datum(invoer: str | None) -> None:
    assert parse_datum_nl(invoer) is None


@pytest.mark.parametrize(
    "invoer",
    ["31.12.2026", "12/31/2026", "2026/12/31", "31-02-2026", "2026-02-30", "morgen", "31-12-26", "20261231"],
)
def test_ongeldige_vorm_of_dag_geeft_melding_in_gewone_taal(invoer: str) -> None:
    with pytest.raises(OngeldigeDatum) as exc:
        parse_datum_nl(invoer, veld="Geldig tot")
    tekst = str(exc.value)
    assert tekst.startswith("Geldig tot: ")
    assert f"'{invoer}'" in tekst
    assert DATUM_FOUT_TEKST in tekst
    assert "31-12-2026" in tekst
    # Nooit de Engelse Pydantic-tekst van de bug.
    assert "separator" not in tekst and "Input should" not in tekst


def test_ongeldige_datum_is_een_valueerror_voor_aanroepers_die_breed_vangen() -> None:
    with pytest.raises(ValueError):
        parse_datum_nl("niets")
