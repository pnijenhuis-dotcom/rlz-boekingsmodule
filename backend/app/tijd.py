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

import re
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

TIJDZONE_NL = ZoneInfo("Europe/Amsterdam")

# --- Datuminvoer door een mens (run A 02-10 punt 15) ---------------------------------------------

DATUM_VOORBEELD = "31-12-2026"
DATUM_FOUT_TEKST = f"is geen geldige datum — schrijf de datum als {DATUM_VOORBEELD}"

_DATUM_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_DATUM_NL = re.compile(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$")


class OngeldigeDatum(ValueError):
    """Een getypte datum die geen van de drie aanvaarde vormen heeft of geen kalenderdag is."""


def parse_datum_nl(waarde: str | None, *, veld: str = "Datum") -> date | None:
    """Dé ene parser voor een door een mens getypte kalenderdag (punt 15 run A 02-10, Peter: "geldig_tot:
    invalid date separator"): accepteert `jjjj-mm-dd`, `dd-mm-jjjj` en `dd/mm/jjjj` (dag/maand mogen één
    cijfer zijn), leeg/witruimte = None. Elke andere vorm of een niet-bestaande dag (31-02) →
    `OngeldigeDatum` mét een melding in gewone taal ("Geldig tot: '31.12.2026' is geen geldige datum — schrijf
    de datum als 31-12-2026"). Geen tijdzone-conversie: de invoer IS de kalenderdag."""
    if waarde is None:
        return None
    tekst = waarde.strip()
    if not tekst:
        return None
    m = _DATUM_ISO.match(tekst)
    if m:
        jaar, maand, dag = (int(g) for g in m.groups())
    else:
        m = _DATUM_NL.match(tekst)
        if not m:
            raise OngeldigeDatum(f"{veld}: '{tekst}' {DATUM_FOUT_TEKST}")
        dag, maand, jaar = (int(g) for g in m.groups())
    try:
        return date(jaar, maand, dag)
    except ValueError as exc:
        raise OngeldigeDatum(f"{veld}: '{tekst}' {DATUM_FOUT_TEKST}") from exc


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
