"""Querybibliotheek: `app/lezen/queries/<naam>.sql` mét kopregels (`-- naam:`, `-- versie:`, `-- doel:`, `-- scope:`,
`-- parameters:`, `-- kolommen:`). Een nieuwe query = commit + review, nooit ad hoc. `scope: administratie` = de query loopt
per administratie in een gescoopte sessie (RLS via `app.current_administratie_id`) en krijgt `:administratie_id` mee;
`scope: platform` = één keer in `scoped_session(None)`. Parameters zijn bind-parameters (`:naam`) — nooit string-formatting."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

QUERIES_MAP = Path(__file__).resolve().parent / "queries"
_KOP = re.compile(r"^--\s*(naam|versie|doel|scope|parameters|kolommen|optioneel)\s*:\s*(.*)$")
_NAAM = re.compile(r"^[a-z][a-z0-9-]*$")
SCOPES = ("administratie", "platform")


class OnbekendeQuery(KeyError):
    """Querynaam niet in de bibliotheek (allowlist-weigering, geen gok)."""


class OngeldigeQueryDefinitie(ValueError):
    """Een .sql-bestand mist een verplichte kopregel of bevat iets anders dan één SELECT."""


@dataclass(frozen=True)
class Query:
    naam: str
    versie: str
    doel: str
    scope: str
    parameters: tuple[str, ...]
    optioneel: tuple[str, ...]
    kolommen: tuple[str, ...]
    sql: str
    pad: Path = field(compare=False)

    @property
    def verplicht(self) -> tuple[str, ...]:
        return tuple(p for p in self.parameters if p not in self.optioneel)


def _lijst(waarde: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in waarde.split(",") if x.strip() and x.strip() != "-")


def parse(tekst: str, *, pad: Path) -> Query:
    from app.lezen.sql_poort import toets_select_only

    kop: dict[str, str] = {}
    sql_regels: list[str] = []
    for regel in tekst.splitlines():
        m = _KOP.match(regel.strip())
        if m and not sql_regels:
            kop[m.group(1)] = m.group(2).strip()
        elif regel.strip().startswith("--") and not sql_regels:
            continue
        else:
            sql_regels.append(regel)
    for sleutel in ("naam", "versie", "doel", "scope", "parameters", "kolommen"):
        if sleutel not in kop:
            raise OngeldigeQueryDefinitie(f"{pad.name}: kopregel '-- {sleutel}:' ontbreekt")
    if not _NAAM.match(kop["naam"]) or kop["naam"] != pad.stem:
        raise OngeldigeQueryDefinitie(f"{pad.name}: naam {kop['naam']!r} hoort gelijk te zijn aan de bestandsnaam")
    if kop["scope"] not in SCOPES:
        raise OngeldigeQueryDefinitie(f"{pad.name}: scope {kop['scope']!r} (administratie | platform)")
    sql = "\n".join(sql_regels).strip().rstrip(";").strip()
    toets_select_only(sql)  # een bibliotheek-query is óók SELECT-only — geen uitzondering voor "gereviewd"
    parameters = _lijst(kop["parameters"])
    optioneel = _lijst(kop.get("optioneel", ""))
    if kop["scope"] == "administratie" and "administratie_id" not in parameters:
        raise OngeldigeQueryDefinitie(f"{pad.name}: scope administratie vereist parameter administratie_id")
    for p in re.findall(r"(?<!:):([a-z_][a-z0-9_]*)", sql):
        if p not in parameters:
            raise OngeldigeQueryDefinitie(f"{pad.name}: bind-parameter :{p} staat niet in '-- parameters:'")
    return Query(
        naam=kop["naam"],
        versie=kop["versie"],
        doel=kop["doel"],
        scope=kop["scope"],
        parameters=parameters,
        optioneel=optioneel,
        kolommen=_lijst(kop["kolommen"]),
        sql=sql,
        pad=pad,
    )


def laad_alle(map_: Path | None = None) -> dict[str, Query]:
    uit: dict[str, Query] = {}
    for pad in sorted((map_ or QUERIES_MAP).glob("*.sql")):
        q = parse(pad.read_text(encoding="utf-8"), pad=pad)
        uit[q.naam] = q
    return uit


def zoek(naam: str, map_: Path | None = None) -> Query:
    alle = laad_alle(map_)
    if naam not in alle:
        raise OnbekendeQuery(f"onbekende query {naam!r} — beschikbaar: {', '.join(sorted(alle))}")
    return alle[naam]
