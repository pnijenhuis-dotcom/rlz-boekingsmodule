"""Factuurmatch × factuurperiode (blok 11 vervolgrun 07-09): de periode op het boekvoorstel (0120) is een extra
NIET-blokkerend signaal in het match-resultaat — komt de factuurperiode niet overeen met de weken van de gematchte
weekstaat/-staten, dan `details["periode_signaal"]` met een leesbare tekst; `uitkomst` verandert nooit. Geen signaal
bij een periode die alleen uit de factuurdatum is afgeleid (die ligt per definitie ná de gewerkte week)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.documenten import boekvoorstel
from app.documenten.periode import HERKOMST_AFGELEID_FACTUURDATUM, HERKOMST_MENS, FactuurPeriode
from app.documenten.storage import LokaleBestandsopslag
from app.uren import factuurmatch
from tests.uren.test_factuurmatch import JAAR, WEEK, koppel_crediteur, maak_factuur, maak_goedgekeurde_staat


@pytest.fixture
def opslag(tmp_path: Path) -> LokaleBestandsopslag:
    return LokaleBestandsopslag(tmp_path / "documenten")


def _zet_periode(administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, periode: tuple[int, int, int]) -> None:
    """Mens-correctie via het gewone opslagpad (zonder veldvoorstel is élke opgave ≠ de factuurdatum-afleiding → `mens`)."""
    data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        vendor_id=data.vendor_id,
        referentie=data.referentie,
        factuurdatum=data.factuurdatum,
        totaalbedrag=data.totaalbedrag,
        regels=data.regels,
        periode=periode,
    )


class TestPeriodeSignaal:
    def test_afwijkende_periode_geeft_oranje_signaal_zonder_statuswijziging(
        self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag
    ):
        maak_goedgekeurde_staat(administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder)  # week 30
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, gekoppelde_zzper, vendor_id, beheerder_id, uurtarief="42.50")
        document_id = maak_factuur(administratie_id, beheerder_id, opslag, vendor_id, nettos=("680.00",))
        _zet_periode(administratie_id, document_id, beheerder_id, (JAAR, 31, 31))
        data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert data.periode == FactuurPeriode(JAAR, 31, 31, HERKOMST_MENS, None)

        resultaat = factuurmatch.bereken_match(administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id)

        assert resultaat.uitkomst == "match"  # bedrag klopt — het periode-signaal verandert de uitkomst niet
        signaal = resultaat.details["periode_signaal"]
        assert signaal is not None
        assert signaal["tekst"] == (
            f"Factuurperiode wk 31 · {JAAR} komt niet overeen met de weekstaten in deze match (wk {WEEK} · {JAAR}) "
            "— controleer de periode op de factuur of kies andere weekstaten."
        )
        assert signaal["factuurperiode"] == {"jaar": JAAR, "week_van": 31, "week_tot": 31, "herkomst": HERKOMST_MENS}
        assert signaal["staten_weken"] == [{"jaar": JAAR, "weeknummer": WEEK}]

    def test_overeenkomende_periode_geeft_geen_signaal(
        self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag
    ):
        maak_goedgekeurde_staat(administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder, week=WEEK)
        maak_goedgekeurde_staat(administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder, week=WEEK + 1)
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, gekoppelde_zzper, vendor_id, beheerder_id, uurtarief="42.50")
        document_id = maak_factuur(administratie_id, beheerder_id, opslag, vendor_id, nettos=("1360.00",))
        _zet_periode(administratie_id, document_id, beheerder_id, (JAAR, WEEK, WEEK + 1))

        resultaat = factuurmatch.bereken_match(administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id)

        assert resultaat.uitkomst == "match"
        assert resultaat.details["periode_signaal"] is None

    def test_periode_afgeleid_van_factuurdatum_geeft_bewust_geen_signaal(
        self, administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag
    ):
        maak_goedgekeurde_staat(administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder)  # week 30
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, gekoppelde_zzper, vendor_id, beheerder_id, uurtarief="42.50")
        document_id = maak_factuur(administratie_id, beheerder_id, opslag, vendor_id, nettos=("680.00",))
        data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        # maak_factuur slaat op zonder periode → de afleiding uit de factuurdatum (ISO-week 32) is gepersisteerd.
        assert data.periode is not None and data.periode.herkomst == HERKOMST_AFGELEID_FACTUURDATUM
        assert data.periode.week_van == 32 != WEEK

        resultaat = factuurmatch.bereken_match(administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id)

        assert resultaat.uitkomst == "match"
        assert resultaat.details["periode_signaal"] is None

    def test_zonder_staten_geen_signaal(self, administratie_id, gekoppelde_zzper, beheerder_id, opslag):
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, gekoppelde_zzper, vendor_id, beheerder_id, uurtarief="42.50")
        document_id = maak_factuur(administratie_id, beheerder_id, opslag, vendor_id, nettos=("680.00",))
        _zet_periode(administratie_id, document_id, beheerder_id, (JAAR, 31, 31))

        resultaat = factuurmatch.bereken_match(administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id)

        assert resultaat.uitkomst == "afwijking"  # toetsbron leeg — de bestaande uitkomst
        assert resultaat.details["periode_signaal"] is None
