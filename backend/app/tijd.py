"""Kalenderdag = Nederlandse dag (blok 2 run 11-09 middag; middernacht-flake 10/11-09).

Domeinregel: geldigheids-, verval-, factuur- en periodedatums zijn Nederlandse kalenderdagen. Tussen
00:00 en 02:00 (CEST) geeft `datetime.now(UTC).date()` nog de dag van gisteren — dáár kwamen de
rode `test_kantoorbreed`/`test_verstreken_geldigheid` van. Tijdstempels voor audit en opslag blijven
UTC (`datetime.now(UTC)`); alleen wie een KALENDERDAG bedoelt, gebruikt `vandaag_nl()`.

Testbaar: monkeypatch `app.tijd._klok` (of `vandaag_nl`/`nu_nl` op de importerende module).
Guard: `tests/unit/test_kalenderdag_guard.py` verbiedt `date.today()`/`now(UTC).date()` in app/ buiten dit
bestand.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

TIJDZONE_NL = ZoneInfo("Europe/Amsterdam")


def _klok() -> datetime:
    """Het enige `now()`-punt van deze module (UTC, tz-aware) — monkeypatch-anker voor tests."""
    return datetime.now(UTC)


def nu_nl() -> datetime:
    """Huidig tijdstip in Nederlandse tijd (tz-aware, Europe/Amsterdam)."""
    return _klok().astimezone(TIJDZONE_NL)


def vandaag_nl() -> date:
    """De Nederlandse kalenderdag van dit moment."""
    return nu_nl().date()


def kalenderdag_nl(moment: datetime) -> date:
    """Nederlandse kalenderdag van een tz-aware moment (naïef = UTC)."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(TIJDZONE_NL).date()
