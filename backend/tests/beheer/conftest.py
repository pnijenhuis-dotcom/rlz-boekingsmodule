from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app import tijd
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import gescoopte_gebruiker  # noqa: F401


class Klok:
    """Stuurbare klok voor `app.tijd._klok` (blok 3 run 11-09): de eerste-sync-module leest élk tijdstempel hieruit,
    zodat een test 5/15/60 min of 24 u kan laten verstrijken zonder te wachten."""

    def __init__(self, start: datetime) -> None:
        self.nu = start

    def verzet(self, **kw) -> datetime:
        self.nu += timedelta(**kw)
        return self.nu


@pytest.fixture
def klok(monkeypatch: pytest.MonkeyPatch) -> Klok:
    k = Klok(datetime(2026, 9, 11, 10, 0, tzinfo=UTC))
    monkeypatch.setattr(tijd, "_klok", lambda: k.nu)
    return k
