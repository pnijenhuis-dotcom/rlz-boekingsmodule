"""Guard "kalenderdag = Nederlandse dag" (blok 2 run 11-09 middag; middernacht-flake 10/11-09).

Domeinregel: geldigheids-, verval-, factuur-, boek- en periodedatums én dagtellers ("N per etmaal") zijn NEDERLANDSE
kalenderdagen. `date.today()` volgt de lokale klok van de machine (Cloud Run = UTC), `datetime.now(UTC).date()` de
UTC-dag: tussen 00:00 en 02:00 CEST zijn dat verschillende dagen. Daarom bestaat er in app/ precies één klok-anker,
`app.tijd._klok`, met `vandaag_nl()` / `nu_nl()` / `kalenderdag_nl()` eroverheen — één monkeypatch pint álles
(gouden set: `tests/keten` pint `_klok` op REFERENTIE_TIJDSTIP).

Mechanisme: sweep over álle `app/**/*.py` buiten `app/tijd.py`; élk verboden patroon = rood, met bestand:regel. Ook
een eigen `datetime.now(TIJDZONE).date()` is verboden — het was correct, maar een tweede anker is niet
monkeypatchbaar vanuit één plek. Whitelist: leeg. Een regel toevoegen kan alleen mét reden (bestand → reden),
nooit stil."""

from __future__ import annotations

import ast
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app import tijd

_APP_ROOT = Path(__file__).resolve().parents[2] / "app"
_UITGEZONDERD = {_APP_ROOT / "tijd.py"}

#: Verboden vormen (regex op de broncode). Het ontbrekende sluithaakje is bewust: ook `date.today( )` of een
#: variant met keyword-argumenten valt eronder.
_VERBODEN: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("date.today(", re.compile(r"(?<![\w.])date\.today\(")),
    ("datetime.today(", re.compile(r"datetime\.today\(")),
    (".now(UTC).date(", re.compile(r"\.now\(UTC\)\.date\(")),
    (".now(timezone.utc).date(", re.compile(r"\.now\(timezone\.utc\)\.date\(")),
    ("utcnow().date(", re.compile(r"utcnow\(\)\.date\(")),
    ("now(tz=UTC).date(", re.compile(r"now\(tz=UTC\)\.date\(")),
    (
        ".now(<eigen tijdzone>).date(",
        re.compile(r"\.now\((?:TIJDZONE|TIJDZONE_NL|_AMSTERDAM|ZoneInfo\([^)]*\))\)\.date\("),
    ),
)

#: Whitelist: relatief pad → reden. Leeg — een tijdstempel blijft `datetime.now(UTC)` (geen `.date()`), een
#: kalenderdag gaat door `vandaag_nl()`; er is geen derde categorie gevonden in de sweep van 11-09.
_WHITELIST: dict[str, str] = {}


def _app_bestanden() -> list[Path]:
    return sorted(p for p in _APP_ROOT.rglob("*.py") if p not in _UITGEZONDERD)


def test_geen_lokale_of_utc_kalenderdag_buiten_app_tijd() -> None:
    treffers: list[str] = []
    for pad in _app_bestanden():
        rel = pad.relative_to(_APP_ROOT.parent).as_posix()
        if rel in _WHITELIST:
            continue
        for nr, regel in enumerate(pad.read_text(encoding="utf-8").splitlines(), start=1):
            code = regel.split("#", 1)[0]
            for naam, patroon in _VERBODEN:
                if patroon.search(code):
                    treffers.append(
                        f"{rel}:{nr}: {naam} → app.tijd.vandaag_nl() (kalenderdag) of een tijdstempel zonder .date()"
                    )
    assert not treffers, "kalenderdag buiten app.tijd:\n" + "\n".join(treffers)


def test_whitelist_wijst_alleen_naar_bestaande_bestanden_met_reden() -> None:
    for rel, reden in _WHITELIST.items():
        assert (_APP_ROOT.parent / rel).is_file(), f"whitelist-regel zonder bestand: {rel}"
        assert reden.strip(), f"whitelist-regel zonder reden: {rel}"


def test_app_tijd_is_het_enige_anker() -> None:
    """`app/tijd.py` mag `datetime.now(UTC)` gebruiken — precies één keer, in `_klok` (docstrings tellen niet)."""
    boom = ast.parse((_APP_ROOT / "tijd.py").read_text(encoding="utf-8"))
    aanroepen = [
        n
        for n in ast.walk(boom)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "now"
    ]
    assert len(aanroepen) == 1 and aanroepen[0].lineno == next(
        n.lineno for n in boom.body if isinstance(n, ast.FunctionDef) and n.name == "_klok"
    ) + 2


class TestHelperInHetMiddernachtVenster:
    """De flake van 10/11-09 nagespeeld: 22:30 UTC = 00:30 CEST op de volgende dag."""

    VENSTER = datetime(2026, 9, 10, 22, 30, tzinfo=UTC)

    def test_vandaag_nl_geeft_de_nederlandse_dag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tijd, "_klok", lambda: self.VENSTER)
        assert self.VENSTER.date().isoformat() == "2026-09-10"  # de UTC-dag — dít was de bug
        assert tijd.vandaag_nl().isoformat() == "2026-09-11"
        assert tijd.nu_nl().isoformat() == "2026-09-11T00:30:00+02:00"

    def test_kalenderdag_nl_van_een_moment(self) -> None:
        assert tijd.kalenderdag_nl(self.VENSTER).isoformat() == "2026-09-11"
        # naïef = UTC (opslagconventie)
        assert tijd.kalenderdag_nl(datetime(2026, 9, 10, 22, 30)).isoformat() == "2026-09-11"
        # wintertijd: 23:30 UTC op 31-01 = 00:30 CET op 01-02
        assert tijd.kalenderdag_nl(datetime(2026, 1, 31, 23, 30, tzinfo=UTC)).isoformat() == "2026-02-01"
        # overdag zijn beide dagen gelijk
        assert tijd.kalenderdag_nl(datetime(2026, 9, 8, 12, 0, tzinfo=UTC)).isoformat() == "2026-09-08"
