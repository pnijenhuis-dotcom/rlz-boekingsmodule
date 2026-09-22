"""Verkoopkant in een NIET-btw-plichtige administratie (BUG Peter 22-09; Vastly 380/381 huur vrijgesteld — zelfde regel):
pure check `check_btw_niet_plichtig_verkoop` + de rij in `voer_verkoop_checks_uit` alleen bij btw_plichtig=False."""

from __future__ import annotations

from decimal import Decimal as D

from app.verkoop.checks import (
    NAAM_BTW_NIET_PLICHTIG,
    VerkoopCheckRegel,
    check_btw_niet_plichtig_verkoop,
    voer_verkoop_checks_uit,
)


def _regel(nr: int, netto: str, btw: str | None, *, pct: str | None, verlegd: bool = False) -> VerkoopCheckRegel:
    return VerkoopCheckRegel(
        volgnummer=nr,
        omschrijving="Huur",
        netto_bedrag=D(netto),
        btw_bedrag=D(btw) if btw is not None else None,
        gb_code="8000",
        ledger_id_bekend=True,
        taxrate_id_bekend=True,
        gb_code_status="bekend",
        taxrate_percentage=D(pct) if pct is not None else None,
        taxrate_is_verlegd=verlegd,
    )


def test_check_rood_bij_btw_of_tarief_groen_bij_bruto() -> None:
    r = check_btw_niet_plichtig_verkoop(
        regels=[_regel(1, "1000", "210", pct="0.21"), _regel(2, "100", "0", pct="0", verlegd=True)]
    )
    assert not r.ok and "regel 1: btw € 210, tarief 21 %" in r.melding and "regel 2: verlegd-tarief" in r.melding
    assert check_btw_niet_plichtig_verkoop(regels=[_regel(1, "1210", "0", pct="0")]).ok
    assert check_btw_niet_plichtig_verkoop(regels=[_regel(1, "1210", None, pct=None)]).ok


def test_rij_alleen_in_het_rapport_als_niet_plichtig() -> None:
    kw = dict(
        debiteur_naam="Huurder",
        factuurnummer="VF-1",
        factuurdatum=None,
        totaalbedrag_incl=D("1210"),
        regels=[_regel(1, "1000", "210", pct="0.21")],
        lokale_duplicaat_hits=0,
        rlz_duplicaat_hits=0,
        is_creditnota=False,
        gecrediteerd_factuurnummer=None,
        origineel_geboekt=False,
    )
    assert NAAM_BTW_NIET_PLICHTIG not in [r.naam for r in voer_verkoop_checks_uit(**kw).resultaten]
    rapport = voer_verkoop_checks_uit(btw_plichtig=False, **kw)
    namen = [r.naam for r in rapport.resultaten]
    assert namen.index(NAAM_BTW_NIET_PLICHTIG) == namen.index("btw_uit_factuur") + 1
    assert not next(r for r in rapport.resultaten if r.naam == NAAM_BTW_NIET_PLICHTIG).ok
