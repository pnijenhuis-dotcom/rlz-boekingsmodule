"""Gouden-set-casus ao (blok 4 feedbackrun A 25-09, FV-16 aangepaste vorm): de échte BDO-UBL (casus h, factuurdatum
2026-07-02) in een administratie waarvan de btw-aangifte Q3 2026 al is ingediend — de controle-rij "Factuurdatum valt in
een ingediende aangifteperiode" is ORANJE mét de bewuste keuze "Boeken (btw in volgend tijdvak)"; ná de keuze staat de
rij oranje "bevestigd door …" zonder actie en draagt de tijdlijn de regel. Nooit blokkerend."""

from __future__ import annotations

import uuid

import pytest

from app.documenten import aangifteperiode
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import Keten

CASUS = Casus(casussen.H_BDO)
INGEDIEND_Q3_2026 = {"Status": 2, "StartDate": "2026-07-01T00:00:00", "Date": "2026-09-30T00:00:00"}


def _rij(dto: dict) -> dict:
    return next(r for r in dto["resultaten"] if r["naam"] == aangifteperiode.NAAM)


@pytest.fixture
def bdo_in_ingediende_periode(keten: Keten) -> uuid.UUID:
    keten.rlz.aangiften = [INGEDIEND_Q3_2026]
    pdf = CASUS.pdf()
    resultaat = keten.mail([(CASUS.xml_bestandsnaam(), CASUS.xml(ingesloten_pdf=pdf)), (CASUS.pdf_bestandsnaam(), pdf)])
    document_id = resultaat.bijlagen[0].document_id
    keten.open_controlescherm(document_id)
    return document_id


class TestFactuurdatumInIngediendeAangifte:
    def test_rij_is_oranje_met_actie_en_blokkeert_niet(self, keten: Keten, bdo_in_ingediende_periode: uuid.UUID) -> None:
        dto = keten.checks_dto(bdo_in_ingediende_periode)
        rij = _rij(dto)
        assert rij["ok"] is True and rij["signaal"] is True
        assert "2026-07-02" in rij["melding"] and "2026-07-01 t/m 2026-09-30" in rij["melding"]
        assert [a["code"] for a in rij["acties"]] == [aangifteperiode.ACTIE_CODE]
        # Alleen de bekende ontbrekende velden blokkeren (grootboek/btw/project) — de aangifte-rij nooit.
        assert all(r["ok"] for r in dto["resultaten"] if r["naam"] == aangifteperiode.NAAM)

    def test_bewuste_keuze_via_de_route_zet_de_rij_op_bevestigd(
        self, keten: Keten, bdo_in_ingediende_periode: uuid.UUID
    ) -> None:
        document_id = bdo_in_ingediende_periode
        resp = keten.api.post(
            f"/administraties/{keten.administratie_id}/documenten/{document_id}/boekvoorstel/aangifte-periode-bevestigen",
            headers=keten.headers,
        )
        assert resp.status_code == 200, resp.text
        rij = _rij(resp.json())
        assert rij["signaal"] is True and rij["acties"] == [] and "bevestigd" in rij["melding"]
        tijdlijn = keten.tijdlijn(document_id)
        assert any(aangifteperiode.SLEUTEL in g for g in tijdlijn), tijdlijn
        # Tweede klik = idempotent (200, nog steeds bevestigd).
        resp2 = keten.api.post(
            f"/administraties/{keten.administratie_id}/documenten/{document_id}/boekvoorstel/aangifte-periode-bevestigen",
            headers=keten.headers,
        )
        assert resp2.status_code == 200

    def test_open_periode_geeft_groene_rij(self, keten: Keten) -> None:
        keten.rlz.aangiften = [{**INGEDIEND_Q3_2026, "Status": 1}]
        pdf = CASUS.pdf()
        resultaat = keten.mail([(CASUS.xml_bestandsnaam(), CASUS.xml(ingesloten_pdf=pdf)), (CASUS.pdf_bestandsnaam(), pdf)])
        document_id = resultaat.bijlagen[0].document_id
        keten.open_controlescherm(document_id)
        rij = _rij(keten.checks_dto(document_id))
        assert rij["ok"] and not rij["signaal"] and rij["acties"] == []
