from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.documenten.schemas import BoekvoorstelInput, BoekvoorstelRegelDto


class TestNlDecimaleNotatie:
    """Design-pass taak P2: de backend-schema's accepteren komma-decimalen als defensief
    vangnet, ook al normaliseert de frontend altijd vóór verzending naar punt-decimaal."""

    def test_nl_notatie_met_duizendtal_punt(self) -> None:
        invoer = BoekvoorstelInput(totaalbedrag="1.234,56")
        assert invoer.totaalbedrag == Decimal("1234.56")

    def test_nl_notatie_zonder_duizendtal_punt(self) -> None:
        invoer = BoekvoorstelInput(totaalbedrag="121,00")
        assert invoer.totaalbedrag == Decimal("121.00")

    def test_punt_decimaal_blijft_werken(self) -> None:
        invoer = BoekvoorstelInput(totaalbedrag="1234.56")
        assert invoer.totaalbedrag == Decimal("1234.56")

    def test_regel_bedragen_accepteren_ook_komma(self) -> None:
        regel = BoekvoorstelRegelDto(
            ledger_id=uuid.uuid4(), taxrate_id=uuid.uuid4(), netto_bedrag="100,00", btw_bedrag="21,00"
        )
        assert regel.netto_bedrag == Decimal("100.00")
        assert regel.btw_bedrag == Decimal("21.00")

    def test_geen_bedrag_blijft_none(self) -> None:
        invoer = BoekvoorstelInput(totaalbedrag=None)
        assert invoer.totaalbedrag is None

    def test_ongeldige_string_geeft_nette_validatiefout_niet_een_kale_crash(self) -> None:
        with pytest.raises(ValidationError, match="totaalbedrag"):
            BoekvoorstelInput(totaalbedrag="geen-bedrag,00")
