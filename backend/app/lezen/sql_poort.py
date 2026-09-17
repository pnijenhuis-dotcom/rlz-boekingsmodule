"""SELECT-only-poort voor vrije SQL (besluit Peter 17-09 punt 2 en 4). Deterministisch, geen parser-magie:
één statement (geen `;` behalve een afsluitende), begint met SELECT of WITH, en geen woord uit de weigerlijst
(schrijf-, DDL-, rechten-, sessie- en bestandsfuncties). De transactie eromheen is bovendien READ ONLY en de
replica kán niet schrijven — drie lagen, waarvan deze de leesbare weigering geeft."""

from __future__ import annotations

import re

MAX_LENGTE = 20_000
_START = re.compile(r"^\s*(select|with)\b", re.I)
_WEIGER = re.compile(
    r"\b(insert|update|delete|merge|truncate|drop|alter|create|grant|revoke|copy|call|do|vacuum|analyze|cluster|"
    r"reindex|refresh|listen|notify|lock|set|reset|discard|begin|commit|rollback|savepoint|prepare|execute|deallocate|"
    r"pg_read_file|pg_read_binary_file|pg_ls_dir|pg_stat_file|lo_import|lo_export|pg_terminate_backend|"
    r"pg_cancel_backend|pg_reload_conf|dblink|pg_sleep|set_config|current_setting|pg_advisory_lock)\b",
    re.I,
)
_COMMENTAAR = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)


class GeenSelect(ValueError):
    """De tekst is geen enkelvoudige SELECT — leesbaar geweigerd."""


def toets_select_only(sql: str) -> str:
    """→ de geschoonde SQL (zonder afsluitende `;`) of GeenSelect mét de reden."""
    if not sql or not sql.strip():
        raise GeenSelect("lege query")
    if len(sql) > MAX_LENGTE:
        raise GeenSelect(f"query langer dan {MAX_LENGTE} tekens")
    zonder = _COMMENTAAR.sub(" ", sql).strip()
    if zonder.endswith(";"):
        zonder = zonder[:-1].rstrip()
    if ";" in zonder:
        raise GeenSelect("één statement per keer (geen ';' in de query)")
    if not _START.match(zonder):
        raise GeenSelect("alleen SELECT (of WITH … SELECT) is toegestaan")
    m = _WEIGER.search(zonder)
    if m:
        raise GeenSelect(f"woord '{m.group(1)}' is niet toegestaan in een leesquery")
    # WITH … moet ook echt in een SELECT eindigen (geen data-modifying CTE — die woorden zijn al geweigerd).
    return zonder
