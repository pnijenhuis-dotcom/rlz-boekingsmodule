"""IBAN-validatie (mod-97, app/extractie/iban.py) + de verwerking in de controlelaag
(app/extractie/controle.py): geldig IBAN reist mee als gestructureerd veld, ongeldig wordt
gemarkeerd en nooit gebruikt."""

from __future__ import annotations

import pytest

from app.extractie.controle import bouw_veldvoorstel
from app.extractie.iban import is_geldig_iban, masker_iban, normaliseer_iban
from app.extractie.service import AiFactuurExtractie, AiRegel, AiVeld


class TestValidatie:
    @pytest.mark.parametrize(
        "iban",
        [
            "NL91ABNA0417164300",
            "nl91 abna 0417 1643 00",  # normalisatie: spaties + kleine letters
            "BE68539007547034",
            "DE89370400440532013000",
        ],
    )
    def test_geldige_ibans(self, iban: str) -> None:
        assert is_geldig_iban(iban)

    @pytest.mark.parametrize(
        "iban",
        [
            None,
            "",
            "NL91ABNA0417164301",  # mod-97 faalt (laatste cijfer gewijzigd)
            "NL00ABNA0417164300",  # controlecijfers kloppen niet
            "12345678",  # geen landcode
            "NLIBAN",  # te kort / geen cijfers
            "factuurnummer 20260064",  # vrije tekst
        ],
    )
    def test_ongeldige_ibans(self, iban: str | None) -> None:
        assert not is_geldig_iban(iban)

    def test_normaliseren(self) -> None:
        assert normaliseer_iban(" nl91-abna 0417.1643:00 ".replace(":", "")) == "NL91ABNA0417164300"
        assert normaliseer_iban(None) is None
        assert normaliseer_iban("   ") is None

    def test_masker_toont_nooit_het_volledige_nummer(self) -> None:
        masker = masker_iban("NL91ABNA0417164300")
        assert "NL91ABNA0417164300" not in masker
        assert masker.startswith("NL91")


def _veld(waarde: str | None, zekerheid: float = 0.95) -> AiVeld:
    return AiVeld(waarde=waarde, zekerheid=zekerheid)


def _extractie(iban: str | None) -> AiFactuurExtractie:
    kop = {
        "leverancier_naam": _veld("Bouwmaat Nederland B.V."),
        "factuurnummer": _veld("F-2026-001"),
        "factuurdatum": _veld("2026-07-01"),
        "vervaldatum": _veld("2026-07-31"),
        "valuta": _veld("EUR"),
        "totaal_excl": _veld("100.00"),
        "totaal_incl": _veld("121.00"),
        "btw_bedrag": _veld("21.00"),
        "iban": _veld(iban),
    }
    regels = [
        AiRegel(omschrijving="Regel", netto_bedrag="100.00", btw_bedrag="21.00", hoeveelheid=None, zekerheid=0.95)
    ]
    return AiFactuurExtractie(kop=kop, regels=regels, bsn_verwijderd=0)


class TestControlelaag:
    def test_geldig_iban_reist_genormaliseerd_mee(self) -> None:
        voorstel = bouw_veldvoorstel(
            _extractie("nl91 abna 0417 1643 00"), vendors=[], taxrates=[], zekerheid_drempel=0.8
        )
        assert voorstel["iban"] == "NL91ABNA0417164300"
        assert "iban" not in voorstel["controle"]["onparseerbaar"]

    def test_ongeldig_iban_wordt_gemarkeerd_en_niet_gebruikt(self) -> None:
        voorstel = bouw_veldvoorstel(
            _extractie("NL91ABNA0417164301"), vendors=[], taxrates=[], zekerheid_drempel=0.8
        )
        assert voorstel["iban"] is None
        assert "iban" in voorstel["controle"]["onparseerbaar"]

    def test_geen_iban_is_geen_markering(self) -> None:
        voorstel = bouw_veldvoorstel(_extractie(None), vendors=[], taxrates=[], zekerheid_drempel=0.8)
        assert voorstel["iban"] is None
        assert "iban" not in voorstel["controle"]["onparseerbaar"]
