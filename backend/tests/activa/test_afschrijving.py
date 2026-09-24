"""Conventie afschrijvingsrekening = KOSTENrekening 4xxx (soort 2) waarvan de omschrijving ná het voorvoegsel
"Afschrijving(en)/Afschrijvingskosten" gelijk is aan de omschrijving van de activarekening (besluit Peter 24-09 07:5x,
bundelrun blok 6 — herziet "code + 1 op 0xxx" van de BUG-run 23-09; STAP-0 Pilates Bloom: het échte activum draagt
4706 Afschrijvingskosten als `DepreciationAccount`). Guards op een realistisch RGS-schema (0xxx-balans + 4700-reeks
afschrijvingskosten), op naam-varianten, en op alles wat niet telt. Puur code, geen DB."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.activa import afschrijving
from app.db.models import Grootboekrekening

ADMIN = uuid.uuid4()
ANDERE_ADMIN = uuid.uuid4()

# Realistisch RGS-schema: 0xxx-balans (soort 3) + 4700-reeks afschrijvingskosten (soort 2). BLOw-namen: 0107
# Kantoorinventaris, 0111 ICT-apparatuur; Pilates Bloom: 4706 Afschrijvingskosten (bewijs STAP-0 23-09).
SCHEMA = [
    ("0001", "Goodwill", 3),
    ("0002", "Cumulatieve afschrijving goodwill", 3),  # balanskant — nooit DepreciationAccount
    ("0101", "Gebouwen", 3),
    ("0107", "Kantoorinventaris", 3),
    ("0108", "Afschrijving kantoorinventaris", 3),  # oude conventie-kandidaat: soort 3 telt niet meer
    ("0110", "ICT", 3),
    ("0111", "ICT-apparatuur", 3),
    ("0115", "Vervoermiddelen", 3),
    ("0199", "Vaste activa totaal", 3),
    ("4700", "Afschrijving goodwill", 2),
    ("4701", "Afschrijvingskosten gebouwen", 2),
    ("4703", "Afschrijving kantoorinventaris", 2),
    ("4704", "Afschrijvingskosten ICT", 2),
    ("4705", "ICT-apparatuur afschrijving", 2),  # omgekeerde vorm
    ("4707", "Afschrijvingen op vervoermiddelen", 2),
    ("4799", "Afschrijvingskosten totaal", 2),
    ("4400", "Inhuur onderaannemers", 2),
    ("1300", "Debiteuren", 3),
]


def _rek(
    code: str,
    naam: str,
    *,
    soort: int = 2,
    admin: uuid.UUID = ADMIN,
    totaal: bool = False,
    verdwenen: bool = False,
) -> Grootboekrekening:
    return Grootboekrekening(
        ledger_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{admin}:{code}:{naam}"),
        administratie_id=admin,
        code=code,
        naam=naam,
        soort=soort,
        is_totaalrekening=totaal or naam.endswith("totaal"),
        verdwenen_uit_bron_op=datetime.now(UTC) if verdwenen else None,
    )


def _schema() -> list[Grootboekrekening]:
    return [_rek(c, n, soort=s) for c, n, s in SCHEMA]


@pytest.mark.parametrize(
    ("balans", "verwacht"),
    [
        ("0001", "4700"),  # "Afschrijving goodwill"
        ("0101", "4701"),  # "Afschrijvingskosten gebouwen"
        ("0107", "4703"),  # 0108 (soort 3) telt niet meer mee — de kostenrekening wint
        ("0110", "4704"),  # "Afschrijvingskosten ICT" → ICT (opdracht: ICT → ICT)
        ("0111", "4705"),  # omgekeerde vorm "ICT-apparatuur afschrijving"
        ("0115", "4707"),  # "Afschrijvingen op vervoermiddelen"
    ],
)
def test_rgs_schema_elke_activarekening_krijgt_de_kostenrekening_met_dezelfde_omschrijving(
    balans: str, verwacht: str
) -> None:
    rekeningen = _schema()
    treffer = afschrijving.conventie_rekening(next(r for r in rekeningen if r.code == balans), rekeningen)
    assert treffer is not None and treffer.code == verwacht and int(treffer.soort) == afschrijving.SOORT_KOSTEN


def test_oude_conventie_code_plus_1_op_0xxx_geeft_niets_meer() -> None:
    """BLOw 23-09: 0107 → 0108 "Afschrijving kantoormeubilair" (balans) was de vorige conventie; een balansrekening is
    nooit meer `DepreciationAccount` — zonder kostenrekening mét dezelfde omschrijving blijft het leeg (combobox)."""
    rekeningen = [_rek("0107", "Kantoorinventaris", soort=3), _rek("0108", "Afschrijving kantoormeubilair", soort=3)]
    assert afschrijving.conventie_rekening(rekeningen[0], rekeningen) is None


def test_rubicon_schema_zonder_afschrijvingskostenrekeningen_geeft_niets() -> None:
    rekeningen = [
        _rek("01100", "Verhuurmateriaal", soort=3),
        _rek("01101", "Verhuurmateriaal cumulatieve afschrijving", soort=3),
        _rek("4400", "Inhuur", soort=2),
    ]
    for r in rekeningen:
        assert afschrijving.conventie_rekening(r, rekeningen) is None


def test_meer_dan_een_of_verdwenen_of_totaal_of_soort_3_of_andere_administratie_telt_niet() -> None:
    basis = _rek("0107", "Inventaris", soort=3)
    # twee kostenrekeningen met dezelfde genormaliseerde naam → niet eenduidig → leeg
    dubbel = [basis, _rek("4703", "Afschrijving inventaris"), _rek("4713", "Afschrijvingskosten inventaris")]
    assert afschrijving.conventie_rekening(basis, dubbel) is None
    assert afschrijving.conventie_rekening(basis, [basis, _rek("4703", "Afschrijving inventaris", verdwenen=True)]) is None
    assert afschrijving.conventie_rekening(basis, [basis, _rek("4703", "Afschrijving inventaris", totaal=True)]) is None
    # balansrekening mét de juiste naam maar soort 3 → nooit
    assert afschrijving.conventie_rekening(basis, [basis, _rek("0108", "Afschrijving inventaris", soort=3)]) is None
    # kostenrekening buiten de 4xxx-reeks → nooit
    assert afschrijving.conventie_rekening(basis, [basis, _rek("8703", "Afschrijving inventaris")]) is None
    # andere administratie telt niet
    assert afschrijving.conventie_rekening(basis, [basis, _rek("4703", "Afschrijving inventaris", admin=ANDERE_ADMIN)]) is None
    # andere omschrijving telt niet (geen fuzzy match)
    assert afschrijving.conventie_rekening(basis, [basis, _rek("4703", "Afschrijving kantoorinventaris")]) is None
    # precies één geldige → treffer; diakrieten/leestekens/hoofdletters vallen weg
    assert afschrijving.conventie_rekening(basis, [basis, _rek("4703", "AFSCHRIJVING: Inventaris")]).code == "4703"
    accent = _rek("0120", "Machines & installaties", soort=3)
    assert afschrijving.conventie_rekening(accent, [accent, _rek("4720", "Afschrijving machines/installaties")]).code == "4720"


@pytest.mark.parametrize(
    ("naam", "kern"),
    [
        ("Afschrijving kantoorinventaris", "kantoorinventaris"),
        ("Afschrijvingskosten ICT", "ict"),
        ("Afschrijvingen op vervoermiddelen", "vervoermiddelen"),
        ("Afschrijving van gebouwen", "gebouwen"),
        ("Kantoorinventaris afschrijving", "kantoorinventaris"),
        ("Afschrijvingskosten", None),  # geen kern (Pilates Bloom 4706 kale naam → geen naam-match, combobox)
        ("Cumulatieve afschrijving goodwill", None),  # begint niet met het voorvoegsel, eindigt er niet op
        ("Inhuur onderaannemers", None),
        ("", None),
        (None, None),
    ],
)
def test_kern_van_afschrijvingsnaam(naam: str | None, kern: str | None) -> None:
    assert afschrijving.kern_van_afschrijvingsnaam(naam) == kern
    assert afschrijving.is_afschrijvingsrekening_naam(naam) == (kern is not None or naam in ("Afschrijvingskosten",))
