"""Eerste sync (blok 3 run 11-09) + btw-default uit historie (0143): ná een geslaagde Ledgers-sync draait de afleiding —
puur code, geen onderdeel mét rechten; mislukt ze, dan blijft de eerste sync groen (loggen, de nacht herhaalt 'm)."""

from __future__ import annotations

import uuid

from app.beheer import eerste_sync
from app.geheugen import grootboek_btw_historie


def test_afleiding_alleen_na_geslaagde_ledgers_sync(monkeypatch) -> None:
    aanroepen: list[uuid.UUID] = []
    monkeypatch.setattr(grootboek_btw_historie, "herbereken_voor", lambda aid, **_k: aanroepen.append(aid))
    aid = uuid.uuid4()
    eerste_sync._btw_default_uit_historie_na_sync(aid, {"ledgers": {"status": "fout", "fout": "403"}})
    eerste_sync._btw_default_uit_historie_na_sync(aid, {})
    assert aanroepen == []
    eerste_sync._btw_default_uit_historie_na_sync(aid, {"ledgers": {"status": "klaar"}, "taxrates": {"status": "fout"}})
    assert aanroepen == [aid]


def test_fout_in_afleiding_maakt_eerste_sync_niet_rood(monkeypatch, caplog) -> None:
    def kapot(aid, **_k):  # noqa: ANN001
        raise RuntimeError("db weg")

    monkeypatch.setattr(grootboek_btw_historie, "herbereken_voor", kapot)
    eerste_sync._btw_default_uit_historie_na_sync(uuid.uuid4(), {"ledgers": {"status": "klaar"}})  # geen exception
    assert "Btw-default uit historie ná eerste sync mislukt" in caplog.text
