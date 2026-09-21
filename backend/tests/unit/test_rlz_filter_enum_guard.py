"""Guard (BUG groepssaldi 21-09): RLZ's OData-model typeert `AccountType` als enum (`Reeleezee.DTO.AccountTypeEnum`);
een int-literal in `$filter` (`AccountType eq 3`) geeft 400 "A binary operator with incompatible types was detected.
Found operand types 'Reeleezee.DTO.AccountTypeEnum' and 'Edm.Int32'" — productie 16→21-09: alle 33 RLZ-leden van
"Kempen groep" status `fout`, vijf dagen zonder signaal, omdat de suite de client mockt en de letterlijke filterstring
nooit tegen bekend RLZ-gedrag toetst. Regel: enum-velden worden CLIENT-SIDE getoetst (`int(r["AccountType"]) in
(3, 4)`), nooit in `$filter` — ook geen enum-literal-syntax zonder STAP-0-bewijs. Fail-closed regex over álle
Python-bronnen onder `backend/app`."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BACKEND_APP = REPO / "backend" / "app"

#: RLZ-velden waarvan bewezen is dat ze in `$filter` een enum zijn (int-literal = 400). Uitbreiden mét bewijs
#: (api-verkenning "AccountType is een enum in $filter — 21-09").
ENUM_VELDEN = ("AccountType",)
PATROON = re.compile(r"\b(" + "|".join(ENUM_VELDEN) + r")\s+(eq|ne|gt|ge|lt|le)\s+(\d+|\{[A-Za-z_][A-Za-z_0-9]*\})")


def _bronnen() -> list[Path]:
    return sorted(p for p in BACKEND_APP.rglob("*.py") if "__pycache__" not in p.parts)


def test_geen_enum_veld_met_int_literal_in_een_rlz_filter() -> None:
    treffers: list[str] = []
    for pad in _bronnen():
        for nr, regel in enumerate(pad.read_text(encoding="utf-8").splitlines(), start=1):
            if PATROON.search(regel):
                treffers.append(f"{pad.relative_to(REPO)}:{nr}: {regel.strip()[:120]}")
    assert not treffers, (
        "enum-veld met int-literal in een RLZ-$filter (400 in productie) — toets client-side:\n" + "\n".join(treffers)
    )


def test_patroon_herkent_de_productiebug_en_de_f_string_vorm() -> None:
    assert PATROON.search('"$filter": "IsTotalAccount eq false and (AccountType eq 3 or AccountType eq 4)"')
    assert PATROON.search('f"IsTotalAccount eq false and (AccountType eq {ACTIVA} or AccountType eq {PASSIVA})"')
    assert not PATROON.search('"$filter": "IsTotalAccount eq false"')
    assert not PATROON.search('int(r.get("AccountType") or 0) == zijde')
    assert not PATROON.search("PaymentAccountType eq 3")  # ander veld, niet in de lijst zonder bewijs
