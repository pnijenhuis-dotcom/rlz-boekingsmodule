"""`bank-voorstellen-lezen` (bundel 09-09 blok 0): lees-only nameting-instrument voor de matchmotor bank op de
gedeployde job-image — print het voorstel per onverwerkte mutatie, schrijft niets."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app import cli
from app.bank import matchmotor


def _administratie(admin_engine: Engine, naam: str) -> uuid.UUID:
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, :naam, :rlz)"),
            {"id": aid, "naam": naam, "rlz": f"rlz-{aid}"},
        )
    return aid


def test_bank_voorstellen_lezen_print_tabel_en_schrijft_niets(
    admin_engine: Engine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    aid = _administratie(admin_engine, "Nijenhuis C.V. (test)")
    mutatie = matchmotor.MutatieGegevens(
        id=uuid.uuid4(), bedrag=Decimal("12500.00"), open_bedrag=Decimal("12500.00"),
        tegenpartij_naam="Nijenhuis-Pertien", omschrijving="kenmerk 26247623521810",
        tegenrekening_iban=None, rlz_voorstel_item_id=None,
    )
    voorstel = SimpleNamespace(soort=matchmotor.VoorstelSoort.HANDMATIG, bron="geen match")
    rij = SimpleNamespace(mutatie=mutatie, boekdatum="2026-09-08", voorstel=voorstel, open_post=None)
    aanroepen: list[dict] = []

    def nep(*, administratie_id, payment_account_id=None):
        aanroepen.append({"administratie_id": administratie_id, "payment_account_id": payment_account_id})
        return [rij]

    from app.bank import voorstellen

    monkeypatch.setattr(voorstellen, "open_mutaties_met_voorstellen", nep)
    assert cli.main(["bank-voorstellen-lezen", "--administratie", "Nijenhuis C.V."]) == 0
    uit = capsys.readouterr().out
    assert aanroepen == [{"administratie_id": aid, "payment_account_id": None}]
    assert "onverwerkte mutaties: 1" in uit
    assert "Nijenhuis-Pertien" in uit and "handmatig → -" in uit and "geen match" in uit
    assert "Per soort: {'handmatig': 1}" in uit and "Geen schrijfacties uitgevoerd." in uit


def test_bank_voorstellen_lezen_onbekende_administratie_is_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["bank-voorstellen-lezen", "--administratie", "bestaat-niet-xyz"]) == 2
    assert "onbekend" in capsys.readouterr().err
