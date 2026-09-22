# ruff: noqa: F811 — pytest-fixtures als parameters
"""Kassarapport in een NIET-btw-plichtige administratie (BUG Peter 22-09): de incl-splitsing gebruikt percentage 0 voor
élke code (bruto in de omzet, TaxAmount 0) en de check-rij "Btw in niet-btw-plichtige administratie" blokkeert een
categorie mét een tarief > 0 % — btw-plichtig = geen extra rij."""

from __future__ import annotations

import uuid
from decimal import Decimal as D

from app.beheer import btw_plichtig
from app.db.session import scoped_session
from app.documenten.checks import CheckRapport
from app.omzet import boeken as omzet_boeken
from app.omzet import voorstel as omzet_voorstel
from app.omzet.voorstel import NAAM_BTW_NIET_PLICHTIG, OmzetRegelData
from app.sync.models import TaxRateCache
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401

HOOG = uuid.UUID("55555555-0000-0000-0000-000000000021")
VRIJ = uuid.UUID("55555555-0000-0000-0000-000000000010")


def _regel(taxrate: uuid.UUID | None, categorie: str = "Bloemen") -> OmzetRegelData:
    return OmzetRegelData(
        categorie=categorie,
        categorie_sleutel=categorie.lower(),
        omzet_bedrag=D("121.00"),
        kostprijs_bedrag=None,
        omzet_ledger_id=uuid.uuid4(),
        taxrate_id=taxrate,
        kostprijs_ledger_id=None,
        herkomst="mapping",
    )


def test_percentages_nul_en_check_rij(administratie_id, beheerder_id) -> None:
    with scoped_session(administratie_id) as session:
        session.add(
            TaxRateCache(
                id=HOOG, administratie_id=administratie_id, naam="NL, Hoog Tarief", percentage=D("0.21"), brondata={}
            )
        )
        session.add(
            TaxRateCache(
                id=VRIJ,
                administratie_id=administratie_id,
                naam="NL, Geen BTW (Vrijgesteld)",
                percentage=D("0"),
                brondata={"IsExcempt": True},
            )
        )
    leeg = CheckRapport(())
    # Btw-plichtig: percentages zoals gesynct, geen extra rij.
    assert omzet_boeken._taxrate_percentages(administratie_id)[HOOG] == D("0.21")
    assert (
        omzet_voorstel._met_niet_btw_plichtig(leeg, administratie_id=administratie_id, regels=[_regel(HOOG)]).resultaten
        == ()
    )
    btw_plichtig.zet(actor_id=beheerder_id, administratie_id=administratie_id, btw_plichtig=False)
    assert omzet_boeken._taxrate_percentages(administratie_id) == {HOOG: D(0), VRIJ: D(0)}
    rood = omzet_voorstel._met_niet_btw_plichtig(leeg, administratie_id=administratie_id, regels=[_regel(HOOG)])
    assert [r.naam for r in rood.resultaten] == [NAAM_BTW_NIET_PLICHTIG] and not rood.resultaten[0].ok
    assert "Bloemen: NL, Hoog Tarief" in rood.resultaten[0].melding
    groen = omzet_voorstel._met_niet_btw_plichtig(
        leeg, administratie_id=administratie_id, regels=[_regel(VRIJ), _regel(None, "Kas")]
    )
    assert groen.resultaten[0].ok
