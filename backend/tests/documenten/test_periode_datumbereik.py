"""FV-13 (feedbackrun A 25-09, gebruikersfeedback Universal "Periode toont slechts één week"): de periode-chip toonde
alleen weeknummers, en bij de terugval (geen periode op de factuur) de ene ISO-week van de factuurdatum — dat leest als
"één week". Sinds 25-09 draagt de DTO `datum_van`/`datum_tot` ("van … tot …"): exacte datums als de factuur die noemt,
maandag t/m zondag van het weekbereik voor een periode uit de factuur of van de mens, en None bij de terugval (het scherm
zegt dan letterlijk "week van de factuurdatum (aanname)"). Weeklogica ongewijzigd. Puur — geen database."""

from __future__ import annotations

from datetime import date

import pytest

from app.documenten.periode import (
    HERKOMST_AFGELEID_FACTUURDATUM,
    HERKOMST_FACTUUR,
    HERKOMST_MENS,
    FactuurPeriode,
    bepaal_periode,
    datumbereik,
    normaliseer_periode,
)

FACTUURDATUM = date(2026, 8, 5)


@pytest.mark.parametrize(
    ("tekst", "van", "tot"),
    [
        ("01-07-2026 t/m 31-07-2026", date(2026, 7, 1), date(2026, 7, 31)),
        ("18-08-2026 t/m 22-08-2026", date(2026, 8, 18), date(2026, 8, 22)),
        ("juli 2026", date(2026, 7, 1), date(2026, 7, 31)),
        ("periode: 18/08/2026 - 22/08/2026", date(2026, 8, 18), date(2026, 8, 22)),
    ],
)
def test_exacte_datums_uit_de_factuurtekst(tekst: str, van: date, tot: date) -> None:
    p = normaliseer_periode(tekst, factuurdatum=FACTUURDATUM)
    assert p is not None
    assert (p.datum_van, p.datum_tot) == (van, tot)
    assert datumbereik(p, factuurdatum=FACTUURDATUM) == (van, tot)


def test_weekopgave_geeft_maandag_tm_zondag() -> None:
    p = normaliseer_periode("week 34-35 2026", factuurdatum=FACTUURDATUM)
    assert p is not None and (p.datum_van, p.datum_tot) == (None, None)
    assert datumbereik(p, factuurdatum=FACTUURDATUM) == (date(2026, 8, 17), date(2026, 8, 30))


def test_opgeslagen_periode_zonder_datums_herleidt_ze_uit_de_tekst() -> None:
    # De kolommen dragen alleen weken; de tekst blijft bewaard → exacte datums opnieuw herleid.
    p = FactuurPeriode(jaar=2026, week_van=27, week_tot=31, herkomst=HERKOMST_FACTUUR, tekst="01-07-2026 t/m 31-07-2026")
    assert datumbereik(p, factuurdatum=FACTUURDATUM) == (date(2026, 7, 1), date(2026, 7, 31))


def test_tekst_die_niet_meer_bij_de_weken_past_valt_terug_op_weekgrenzen() -> None:
    p = FactuurPeriode(jaar=2026, week_van=36, week_tot=36, herkomst=HERKOMST_MENS, tekst="01-07-2026 t/m 31-07-2026")
    assert datumbereik(p, factuurdatum=FACTUURDATUM) == (date(2026, 8, 31), date(2026, 9, 6))


def test_terugval_van_factuurdatum_heeft_geen_bereik() -> None:
    p = bepaal_periode(None, factuurdatum=FACTUURDATUM)
    assert p is not None and p.herkomst == HERKOMST_AFGELEID_FACTUURDATUM
    assert datumbereik(p, factuurdatum=FACTUURDATUM) is None
    assert datumbereik(None, factuurdatum=FACTUURDATUM) is None
