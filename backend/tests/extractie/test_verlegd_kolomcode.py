"""Peter 15-09 (Olieman): verlegd herkennen op de btw-KOLOMCODE zonder het woord verlegd — deterministisch, de AI leest
alleen de kolomtekst voor (regel-key `bc`, sentinel-string)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.extractie import service
from app.extractie.controle import bouw_veldvoorstel, is_verlegd_kolomcode, verlegd_kolomcode_voor_factuur
from app.extractie.service import AiRegel
from tests.extractie.test_controle import _extractie, _veld


@pytest.mark.parametrize("tekst", ["V", "v", "VL", "verl.", "Verl", "BTW verlegd", "verlegd", "reverse charge", "RC"])
def test_verlegd_kolomcodes(tekst: str) -> None:
    assert is_verlegd_kolomcode(tekst)


@pytest.mark.parametrize("tekst", [None, "", "0", "0%", "0,00 %", "21%", "9%", "vrij", "nul", "H", "L", "n.v.t."])
def test_geen_verlegd_kolomcode(tekst: str | None) -> None:
    assert not is_verlegd_kolomcode(tekst)


def test_kolomcode_voor_de_factuur_alle_regels_met_bedrag() -> None:
    d = Decimal
    assert verlegd_kolomcode_voor_factuur(["V"], netto=[d("20000")]) == "V"
    assert (
        verlegd_kolomcode_voor_factuur(["V", "V", None], netto=[d("100"), d("50"), d("0")]) == "V"
    )  # nulregel telt niet
    assert (
        verlegd_kolomcode_voor_factuur(["V", "21%"], netto=[d("100"), d("50")]) is None
    )  # gemengd = geen factuur-verlegd
    assert verlegd_kolomcode_voor_factuur(["V", None], netto=[d("100"), d("50")]) is None
    assert verlegd_kolomcode_voor_factuur([None], netto=[d("100")]) is None
    assert verlegd_kolomcode_voor_factuur([], netto=[]) is None
    with pytest.raises(ValueError):
        verlegd_kolomcode_voor_factuur(["V"], netto=[])


def test_schema_en_normalisatie_dragen_bc_als_sentinel_string() -> None:
    props = service._REGEL_SCHEMA["properties"]
    assert props["bc"] == {"type": "string"} and "bc" in service._REGEL_SCHEMA["required"]
    uit = service._Genormaliseerd()
    service._normaliseer_regels(
        [
            {
                "o": "1e termijn",
                "n": "20000.00",
                "b": "0.00",
                "h": "1",
                "e": "",
                "p": "",
                "a": "",
                "proj": "",
                "bc": " V ",
                "z": 0.9,
            }
        ],
        uit,
    )
    assert uit.regels[0].btw_kolom == "V"
    service._normaliseer_regels(
        [{"o": "x", "n": "1", "b": "", "h": "", "e": "", "p": "", "a": "", "proj": "", "bc": "", "z": 0.9}], uit
    )
    assert uit.regels[1].btw_kolom is None


def test_veldvoorstel_draagt_kolomcode_per_regel_en_voor_de_factuur() -> None:
    regels = [
        AiRegel(
            omschrijving="1e termijn werkzaamheden",
            netto_bedrag="20000.00",
            btw_bedrag="0.00",
            hoeveelheid="1",
            zekerheid=0.9,
            btw_kolom="V",
        )
    ]
    extractie = _extractie(
        {"totaal_excl": _veld("20000.00"), "totaal_incl": _veld("20000.00"), "btw_bedrag": _veld("0.00")}, regels=regels
    )
    veldvoorstel = bouw_veldvoorstel(extractie, vendors=[], taxrates=[], zekerheid_drempel=0.7)
    assert veldvoorstel["btw_verlegd_kolom"] == "V"
    assert veldvoorstel["regels"][0]["btw_kolom"] == "V" and veldvoorstel["regels"][0]["btw_kolom_verlegd"] is True
    assert veldvoorstel["regels"][0]["taxrate_id"] is None  # de kolomcode vult zelf nooit een code: dat doet de prefill
    zonder = bouw_veldvoorstel(
        _extractie(regels=[AiRegel("x", "100.00", "21.00", None, 0.9, btw_kolom="21%")]),
        vendors=[],
        taxrates=[],
        zekerheid_drempel=0.7,
    )
    assert zonder["btw_verlegd_kolom"] is None and zonder["regels"][0]["btw_kolom_verlegd"] is False
