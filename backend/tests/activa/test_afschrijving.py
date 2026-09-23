"""Conventie afschrijvingsrekening = balansrekening-code + 1 in dezelfde 0xxx-reeks ÉN naam "Afschrijving…"
(BUG-opdracht 24-09 punt 1). Guard op het BLOw-schema (0101→0102 … 0115→0116, uit `db-lezen activa-stand
--administratie BLOw` 23-09) en op een schema zónder conventie (Rubicon 01100…, 28 MVA-rekeningen zonder
"Afschrijving"-opvolgers). Puur code, geen DB."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.activa import afschrijving
from app.db.models import Grootboekrekening

ADMIN = uuid.uuid4()
ANDERE_ADMIN = uuid.uuid4()

# BLOw B.V (5419878c…): acht 0xxx-balansrekeningen mét per rekening een "Afschrijving …"-rekening op code + 1.
BLOW = [
    ("0001", "Goodwill"),
    ("0002", "Afschrijving goodwill"),
    ("0101", "Gebouwen"),
    ("0102", "Afschrijving gebouwen"),
    ("0103", "Verbouwing"),
    ("0104", "Afschrijving verbouwing"),
    ("0105", "Machines"),
    ("0106", "Afschrijving machines"),
    ("0107", "Kantoorinventaris"),
    ("0108", "Afschrijving kantoormeubilair"),
    ("0109", "Bedrijfsinventaris"),
    ("0110", "Afschrijving bedrijfsinventaris"),
    ("0111", "ICT-apparatuur"),
    ("0112", "Afschrijving ICT-apparatuur"),
    ("0113", "Computersoftware"),
    ("0114", "Afschrijving computersoftware"),
    ("0115", "Vervoermiddelen"),
    ("0116", "Afschrijving vervoermiddelen"),
    ("0199", "Vaste activa totaal"),
    ("1300", "Debiteuren"),
]


def _rek(
    code: str,
    naam: str,
    *,
    soort: int = 3,
    admin: uuid.UUID = ADMIN,
    totaal: bool = False,
    verdwenen: bool = False,
) -> Grootboekrekening:
    return Grootboekrekening(
        ledger_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{admin}:{code}"),
        administratie_id=admin,
        code=code,
        naam=naam,
        soort=soort if not code.startswith("1") else 3,
        is_totaalrekening=totaal or naam.endswith("totaal"),
        verdwenen_uit_bron_op=datetime.now(UTC) if verdwenen else None,
    )


def _blow() -> list[Grootboekrekening]:
    return [_rek(c, n) for c, n in BLOW]


@pytest.mark.parametrize(
    ("balans", "verwacht"),
    [("0001", "0002"), ("0101", "0102"), ("0103", "0104"), ("0107", "0108"), ("0109", "0110"), ("0115", "0116")],
)
def test_blow_schema_elke_balansrekening_krijgt_code_plus_1_afschrijving(balans: str, verwacht: str) -> None:
    rekeningen = _blow()
    treffer = afschrijving.conventie_rekening(next(r for r in rekeningen if r.code == balans), rekeningen)
    assert treffer is not None and treffer.code == verwacht and treffer.naam.lower().startswith("afschrijving")


def test_rubicon_schema_zonder_afschrijving_opvolgers_geeft_niets() -> None:
    """Rubicon Investments: 01100…-reeks zonder "Afschrijving"-rekeningen op code + 1 → leeg (kaart: rekening
    verplicht)."""
    rekeningen = [
        _rek("01100", "Verhuurmateriaal"),
        _rek("01101", "Verhuurmateriaal cumulatieve afschrijving"),  # naam begint niet met "Afschrijving"
        _rek("01110", "Inventaris"),
        _rek("01120", "Vervoermiddelen"),
    ]
    for r in rekeningen:
        assert afschrijving.conventie_rekening(r, rekeningen) is None


def test_meer_dan_een_of_verdwenen_of_totaal_of_kosten_telt_niet() -> None:
    basis = _rek("0107", "Inventaris")
    # twee kandidaten op 0108 (dubbele code in de cache) → niet eenduidig → leeg
    dubbel = [basis, _rek("0108", "Afschrijving inventaris"), _rek("0108", "Afschrijving inventaris oud")]
    dubbel[2].ledger_id = uuid.uuid4()
    assert afschrijving.conventie_rekening(basis, dubbel) is None
    verdwenen = _rek("0108", "Afschrijving inventaris", verdwenen=True)
    assert afschrijving.conventie_rekening(basis, [basis, verdwenen]) is None
    assert afschrijving.conventie_rekening(basis, [basis, _rek("0108", "Afschrijving inventaris", totaal=True)]) is None
    # kostenrekening 4708 "Afschrijving inventaris" is géén code + 1 en géén soort 3
    kosten = _rek("4708", "Afschrijving inventaris", soort=2)
    assert afschrijving.conventie_rekening(basis, [basis, kosten]) is None
    # zelfde code in een andere administratie telt niet
    andere = _rek("0108", "Afschrijving inventaris", admin=ANDERE_ADMIN)
    assert afschrijving.conventie_rekening(basis, [basis, andere]) is None
    # precies één geldige → treffer
    assert afschrijving.conventie_rekening(basis, [basis, _rek("0108", "Afschrijving inventaris")]).code == "0108"


@pytest.mark.parametrize(
    ("code", "verwacht"),
    [
        ("0107", "0108"),
        ("0001", "0002"),
        ("01100", "01101"),
        ("0999", None),
        ("0", None),
        ("4400", None),
        ("abc", None),
        ("", None),
    ],
)
def test_volgende_code_blijft_in_de_0xxx_reeks(code: str, verwacht: str | None) -> None:
    assert afschrijving.volgende_code(code) == verwacht
