"""Regel-sleutel-normalisatie (app/geheugen/normalisatie.py) — deterministisch fundament van het
regel-niveau in het boekingsgeheugen: geldlogica, dus elk pad expliciet."""

from __future__ import annotations

import pytest

from app.geheugen.normalisatie import normaliseer_regel_sleutel


class TestNormalisatie:
    def test_lowercase_en_leestekens_gestript(self) -> None:
        assert normaliseer_regel_sleutel("Diesel, NEN590!") == "diesel nen590"

    def test_whitespace_ingeklapt(self) -> None:
        assert normaliseer_regel_sleutel("  huur   heater \t 170kw ") == "170kw heater huur"

    def test_token_set_is_volgorde_onafhankelijk(self) -> None:
        assert normaliseer_regel_sleutel("huur heater 170KW") == normaliseer_regel_sleutel("170KW heater huur")

    def test_dubbele_tokens_tellen_een_keer(self) -> None:
        assert normaliseer_regel_sleutel("huur huur heater") == "heater huur"

    def test_deterministisch(self) -> None:
        invoer = "Steigerhuur week 27 — trappentoren 26014 Amersfoort (Universal)"
        assert normaliseer_regel_sleutel(invoer) == normaliseer_regel_sleutel(invoer)

    @pytest.mark.parametrize("leeg", [None, "", "   ", "—!?."])
    def test_leeg_of_alleen_leestekens_geeft_none(self, leeg: str | None) -> None:
        assert normaliseer_regel_sleutel(leeg) is None

    def test_diakrieten_blijven_onderscheidend(self) -> None:
        # à-ÿ hoort bij de tokens (namen als "Café" verliezen hun betekenis niet).
        assert normaliseer_regel_sleutel("Café kosten") == "café kosten"
