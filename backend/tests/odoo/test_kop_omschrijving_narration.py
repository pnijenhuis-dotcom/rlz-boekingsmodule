"""Blok 9 vervolgrun 07-09: de kop-omschrijving van het boekvoorstel landt in Odoo als `narration` (het vrije
omschrijvingsveld op de factuur); `ref` blijft het factuurnummer van de leverancier (duplicaatquery/bank-matching
sleutelen daarop). Hergebruikt de adapter-fake uit test_boekdatum (zelfde monkeypatch-seams)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from app.odoo import inkoop
from tests.odoo.test_boekdatum import LOCK_2025, _FakeOdoo, _port, _voorstel

OMSCHRIJVING = "Huur steigermateriaal project 26123 week 34"


def test_move_payload_draagt_narration_en_ref_blijft_referentie(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeOdoo(lock_dates=LOCK_2025)
    port = _port(monkeypatch, client)
    voorstel = replace(_voorstel(date(2026, 6, 5)), omschrijving=OMSCHRIJVING, omschrijving_herkomst="factuur")

    port.boek_inkoopfactuur(document_id=voorstel.document_id, voorstel=voorstel, bestand=b"%PDF", bestandsnaam="f.pdf")

    [(model, vals)] = client.creates
    assert model == inkoop.MODEL_MOVE
    assert vals["narration"] == OMSCHRIJVING
    assert vals["ref"] == "F-2025-1215"


def test_zonder_omschrijving_geen_narration_sleutel(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeOdoo(lock_dates=LOCK_2025)
    port = _port(monkeypatch, client)
    voorstel = _voorstel(date(2026, 6, 5))
    assert voorstel.omschrijving is None

    port.boek_inkoopfactuur(document_id=voorstel.document_id, voorstel=voorstel, bestand=b"%PDF", bestandsnaam="f.pdf")

    [(_, vals)] = client.creates
    assert "narration" not in vals


def test_concept_verversen_zet_narration_ook(monkeypatch: pytest.MonkeyPatch) -> None:
    """Een hergebruikt concept (eerdere poging) krijgt kop + regels van het ACTUELE voorstel — incl. de omschrijving."""
    client = _FakeOdoo(lock_dates=LOCK_2025)
    port = _port(monkeypatch, client)
    voorstel = replace(_voorstel(date(2026, 6, 5)), omschrijving=OMSCHRIJVING)
    client.moves[4711] = {"id": 4711, "state": "draft", "date": "2026-06-05", "invoice_date": "2026-06-05", "ref": None}
    port._ververs_concept(4711, voorstel=voorstel, partner_id=5, regels=[], boekdatum=date(2026, 6, 5))
    [(model, ids, vals)] = client.writes
    assert model == inkoop.MODEL_MOVE and ids == [4711]
    assert vals["narration"] == OMSCHRIJVING and vals["ref"] == "F-2025-1215"
