"""Migratie-guard bij startup: geen raadsel-500 meer door een gemiste `make migrate` (gebeurde
drie keer op één dag). Test de pure vergelijk-/besluitfunctie met gemockte versies — zelfde
patroon als test_jwt_secret_guard.py, geen echte database of migrations-directory nodig."""

import logging

import pytest

from app.db.migratie_guard import MigratieVersieAchterstand, controleer_versies


def test_gelijke_versies_doet_niets(caplog: pytest.LogCaptureFixture) -> None:
    controleer_versies(huidige="0013", laatste="0013", fail_fast=True)
    assert caplog.records == []


def test_mismatch_fail_fast_raiset_met_duidelijke_melding() -> None:
    with pytest.raises(MigratieVersieAchterstand, match=r"0011.*0013.*make migrate"):
        controleer_versies(huidige="0011", laatste="0013", fail_fast=True)


def test_geen_alembic_version_rij_telt_als_achterstand() -> None:
    """`huidige=None` (lege/verse database, of alembic_version bestaat nog niet) mag niet als
    'toevallig gelijk' doorglippen."""
    with pytest.raises(MigratieVersieAchterstand):
        controleer_versies(huidige=None, laatste="0013", fail_fast=True)


def test_mismatch_zonder_fail_fast_logt_alleen_een_waarschuwing(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        controleer_versies(huidige="0011", laatste="0013", fail_fast=False)
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.WARNING
    melding = caplog.records[0].getMessage()
    assert "0011" in melding
    assert "0013" in melding
