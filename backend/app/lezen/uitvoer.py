"""Uitvoer van een leesquery: geanonimiseerd (PII), begrensd (rijenplafond mét teller), als markdown-tabel + JSON."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

MAX_RIJEN_CLI = 500
MAX_RIJEN_ROUTE = 5_000
_IBAN = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}[A-Z0-9]{8,30}(?![A-Za-z0-9])")
#: Kolomnamen die een persoons-/bedrijfsnaam dragen → initialen (bedrijfsnamen zijn geen PII, maar de kolom kan beide
#: dragen; voor een analyse volstaan initialen + id).
NAAM_KOLOMMEN = frozenset({"naam", "tegenpartij_naam", "entity_naam", "gebruiker_naam", "actor_naam", "e_mail", "email"})
IBAN_KOLOMMEN = frozenset({"iban", "tegenrekening_iban", "nieuw_iban"})


@dataclass
class Resultaat:
    kolommen: list[str]
    rijen: list[list[Any]]
    totaal: int
    afgekapt: bool
    administraties: int = 0
    meta: dict[str, Any] = field(default_factory=dict)


def _initialen(tekst: str) -> str:
    delen = [d for d in re.split(r"[\s\-]+", tekst.strip()) if d]
    return "".join(d[0].upper() + "." for d in delen[:4]) or "?"


def anonimiseer_waarde(kolom: str, waarde: Any, *, anonimiseer_namen: bool) -> Any:
    if waarde is None:
        return None
    if isinstance(waarde, str):
        if anonimiseer_namen and kolom.lower() in NAAM_KOLOMMEN:
            return _initialen(waarde) if "@" not in waarde else waarde.split("@", 1)[0][:1] + "…@" + waarde.split("@", 1)[1]
        if kolom.lower() in IBAN_KOLOMMEN:
            return "…" + waarde.replace(" ", "")[-4:]
        return _IBAN.sub(lambda m: "…" + m.group(0)[-4:], waarde)
    if isinstance(waarde, dict | list):
        return json.loads(json.dumps(waarde, default=_json_default))
    return waarde


def _json_default(x: Any) -> Any:
    if isinstance(x, uuid.UUID):
        return str(x)
    if isinstance(x, datetime | date):
        return x.isoformat()
    if isinstance(x, Decimal):
        return str(x)
    return str(x)


def bouw_resultaat(
    kolommen: list[str],
    rijen: list[tuple[Any, ...]],
    *,
    max_rijen: int,
    anonimiseer_namen: bool = True,
    meta: dict[str, Any] | None = None,
) -> Resultaat:
    totaal = len(rijen)
    afgekapt = totaal > max_rijen
    uit: list[list[Any]] = []
    for rij in rijen[:max_rijen]:
        uit.append([anonimiseer_waarde(k, v, anonimiseer_namen=anonimiseer_namen) for k, v in zip(kolommen, rij, strict=False)])
    return Resultaat(kolommen=list(kolommen), rijen=uit, totaal=totaal, afgekapt=afgekapt, meta=dict(meta or {}))


def _cel(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, dict | list):
        s = json.dumps(x, ensure_ascii=False, default=_json_default)
    else:
        s = str(x)
    s = s.replace("|", "\\|").replace("\n", " ")
    return s if len(s) <= 120 else s[:117] + "…"


def als_markdown(r: Resultaat) -> str:
    regels = ["| " + " | ".join(r.kolommen) + " |", "|" + "---|" * len(r.kolommen)]
    for rij in r.rijen:
        regels.append("| " + " | ".join(_cel(x) for x in rij) + " |")
    staart = f"\n{r.totaal} rij(en)" + (f", eerste {len(r.rijen)} getoond" if r.afgekapt else "")
    if r.administraties:
        staart += f" over {r.administraties} administratie(s)"
    return "\n".join(regels) + staart


def als_json(r: Resultaat) -> str:
    return json.dumps(
        {
            "kolommen": r.kolommen,
            "rijen": r.rijen,
            "totaal": r.totaal,
            "afgekapt": r.afgekapt,
            "administraties": r.administraties,
            **({"meta": r.meta} if r.meta else {}),
        },
        ensure_ascii=False,
        indent=2,
        default=_json_default,
    )
