"""Omzet-reconciliatie: bevinding `tussenrekening_open` (opdracht 4 blok A, 16-09) reist mee in `reconcilieer_omzet`
náást de bestaande RLZ-staat-controles — een tegenzijde-post van een geboekte omzetbatch die ná 14 dagen geen
bankmatch heeft, mét handeling in de detailtekst."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.omzet import reconciliatie
from tests.bank.test_tussenrekening_post import UITBETAALDATUM, _boek_pilates_batch, _open_post
from tests.omzet.conftest import FakeOmzetClient
from tests.omzet.test_bronnen import seed_rekeningschema


def test_reconcilieer_omzet_meldt_tussenrekening_open_naast_rlz_controle(
    administratie_id, gescoopte_gebruiker, opslag, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: ANN001
    seed_rekeningschema(administratie_id)
    verkoop = uuid.uuid4()
    _boek_pilates_batch(administratie_id, gescoopte_gebruiker, opslag, verkoop_rlz_id=verkoop)
    _open_post(administratie_id, rlz_document_id=verkoop)
    client = FakeOmzetClient()
    client.put_sales_invoice(verkoop, customer_id=None, lines=[])
    client.sales_invoices[str(verkoop)]["Status"] = 2
    monkeypatch.setattr(reconciliatie, "client_voor_rlz_admin_id", lambda rlz_admin_id: client)
    monkeypatch.setattr(reconciliatie, "vandaag_nl", lambda: UITBETAALDATUM + timedelta(days=30))

    afwijkingen = reconciliatie.reconcilieer_omzet(administratie_id)
    assert [a.soort for a in afwijkingen] == ["tussenrekening_open"]  # de RLZ-staat zelf klopt (Status 2)
    assert "30 dagen zonder bankontvangst" in afwijkingen[0].detail
    assert "koppel de bankontvangst of accepteer met reden" in afwijkingen[0].detail

    # Binnen de grens: niets te melden.
    monkeypatch.setattr(reconciliatie, "vandaag_nl", lambda: UITBETAALDATUM + timedelta(days=3))
    assert reconciliatie.reconcilieer_omzet(administratie_id) == []
    assert isinstance(date.today(), date)  # sanity: geen echte klok gebruikt hierboven
