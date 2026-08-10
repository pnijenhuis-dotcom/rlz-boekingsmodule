"""Eenhedennormalisatie + categorie-semantiek (blok A 2026-08-10, app/sync/btw.py).

De vergelijkingsgrens taxrate_cache (fractie, bronformaat 0.2100) ↔ UBL (percentage, 21.00)
wordt hier met béíde formaten gevoed — de les uit registers/verbeteringen.md 2026-08-09: een
test die maar één formaat voedt, maskeert de mismatch."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.sync.btw import (
    factuur_fractie,
    normaliseer_categorie,
    taxrate_dekt_factuur_btw,
    taxrate_vlaggen,
    ubl_percent_naar_fractie,
)


def test_ubl_percent_naar_fractie() -> None:
    assert ubl_percent_naar_fractie(Decimal("21.00")) == Decimal("0.21")
    assert ubl_percent_naar_fractie(Decimal("9.00")) == Decimal("0.09")
    assert ubl_percent_naar_fractie(Decimal("0.00")) == Decimal("0")


def test_normaliseer_categorie() -> None:
    assert normaliseer_categorie("S") == "S"
    assert normaliseer_categorie(" ae ") == "AE"
    assert normaliseer_categorie("K") is None  # niet ondersteund → geen deterministische afleiding
    assert normaliseer_categorie(None) is None
    assert normaliseer_categorie("") is None


def test_factuur_fractie_nul_categorieen_zonder_percent() -> None:
    # E/Z/AE zijn per definitie 0 — een ontbrekend cbc:Percent is daar geen onbepaaldheid.
    for cat in ("E", "Z", "AE"):
        assert factuur_fractie(cat, None) == Decimal(0)
    # S zonder percentage is wél onbepaald.
    assert factuur_fractie("S", None) is None
    assert factuur_fractie(None, Decimal("21.00")) is None


def test_taxrate_vlaggen_rlz_spelling() -> None:
    assert taxrate_vlaggen({"IsRelayed": True, "IsExcempt": False}) == (True, False)
    assert taxrate_vlaggen({"IsExcempt": True}) == (False, True)
    assert taxrate_vlaggen({}) == (False, False)
    assert taxrate_vlaggen(None) == (False, False)


class TestStandaardTarief:
    def test_s_21_dekt_fractie_bronformaat(self) -> None:
        # DE regressietest van de bevinding 2026-08-09: UBL 21.00 vs cache-fractie 0.2100.
        assert taxrate_dekt_factuur_btw(
            categorie="S", factuur_pct=Decimal("21.00"),
            taxrate_percentage=Decimal("0.2100"), is_verlegd=False, is_vrijgesteld=False,
        )

    def test_s_21_dekt_geen_percentage_vorm_in_de_cache(self) -> None:
        # Een cache die (fout) 21.00 draagt mag NIET matchen — de eenheid is de fractie.
        assert not taxrate_dekt_factuur_btw(
            categorie="S", factuur_pct=Decimal("21.00"),
            taxrate_percentage=Decimal("21.00"), is_verlegd=False, is_vrijgesteld=False,
        )

    def test_s_matcht_nooit_op_percentage_alleen(self) -> None:
        # 21% verlegd (IsRelayed) dekt een S-regel niet, ook al zou het percentage passen.
        assert not taxrate_dekt_factuur_btw(
            categorie="S", factuur_pct=Decimal("21.00"),
            taxrate_percentage=Decimal("0.2100"), is_verlegd=True, is_vrijgesteld=False,
        )
        assert not taxrate_dekt_factuur_btw(
            categorie="S", factuur_pct=Decimal("21.00"),
            taxrate_percentage=Decimal("0.2100"), is_verlegd=False, is_vrijgesteld=True,
        )

    def test_s_0_procent_is_geen_standaardtarief(self) -> None:
        assert not taxrate_dekt_factuur_btw(
            categorie="S", factuur_pct=Decimal("0.00"),
            taxrate_percentage=Decimal("0"), is_verlegd=False, is_vrijgesteld=False,
        )

    def test_s_9_procent_laag_tarief(self) -> None:
        assert taxrate_dekt_factuur_btw(
            categorie="S", factuur_pct=Decimal("9.00"),
            taxrate_percentage=Decimal("0.0900"), is_verlegd=False, is_vrijgesteld=False,
        )
        assert not taxrate_dekt_factuur_btw(
            categorie="S", factuur_pct=Decimal("9.00"),
            taxrate_percentage=Decimal("0.2100"), is_verlegd=False, is_vrijgesteld=False,
        )


class TestNulCategorieen:
    def test_ae_verlegd_op_vlag(self) -> None:
        assert taxrate_dekt_factuur_btw(
            categorie="AE", factuur_pct=Decimal("0.00"),
            taxrate_percentage=Decimal("0"), is_verlegd=True, is_vrijgesteld=False,
        )
        # Niet-verlegd 0%-tarief dekt AE niet.
        assert not taxrate_dekt_factuur_btw(
            categorie="AE", factuur_pct=Decimal("0.00"),
            taxrate_percentage=Decimal("0"), is_verlegd=False, is_vrijgesteld=False,
        )

    def test_e_vrijgesteld_op_vlag(self) -> None:
        assert taxrate_dekt_factuur_btw(
            categorie="E", factuur_pct=Decimal("0.00"),
            taxrate_percentage=Decimal("0"), is_verlegd=False, is_vrijgesteld=True,
        )
        assert not taxrate_dekt_factuur_btw(
            categorie="E", factuur_pct=Decimal("0.00"),
            taxrate_percentage=Decimal("0"), is_verlegd=True, is_vrijgesteld=True,
        )
        assert not taxrate_dekt_factuur_btw(
            categorie="E", factuur_pct=Decimal("0.00"),
            taxrate_percentage=Decimal("0"), is_verlegd=False, is_vrijgesteld=False,
        )

    def test_z_nul_tarief_zonder_vlaggen(self) -> None:
        assert taxrate_dekt_factuur_btw(
            categorie="Z", factuur_pct=Decimal("0.00"),
            taxrate_percentage=Decimal("0.0000"), is_verlegd=False, is_vrijgesteld=False,
        )
        assert not taxrate_dekt_factuur_btw(
            categorie="Z", factuur_pct=Decimal("0.00"),
            taxrate_percentage=Decimal("0"), is_verlegd=False, is_vrijgesteld=True,
        )
        assert not taxrate_dekt_factuur_btw(
            categorie="Z", factuur_pct=Decimal("0.00"),
            taxrate_percentage=Decimal("0.2100"), is_verlegd=False, is_vrijgesteld=False,
        )


@pytest.mark.parametrize("categorie", ["K", "G", "O", None])
def test_niet_ondersteunde_categorie_resolvet_nooit(categorie: str | None) -> None:
    assert not taxrate_dekt_factuur_btw(
        categorie=categorie, factuur_pct=Decimal("21.00"),
        taxrate_percentage=Decimal("0.2100"), is_verlegd=False, is_vrijgesteld=False,
    )
