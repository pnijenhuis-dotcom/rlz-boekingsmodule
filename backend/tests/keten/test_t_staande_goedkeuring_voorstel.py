"""Casus (t, blok 7 run 11-09 middag) — staande-goedkeuring-voorstel alleen bij een periodiek patroon, getoetst op een
écht document (BDO 6088744, UBL zonder AI) door intake → prefill → aanbieden → accordeur-wachtrij (service + API-DTO).

Verwacht: een eerste (of eenmalige) factuur draagt NOOIT het voorstel — `staande_regel_kandidaat` False en het nieuwe,
additieve DTO-veld `staande_regel_patroon` is null; een handmatig akkoord zonder antwoord op het voorstel legt géén
stilte-rij aan (oude app-versies blijven werken). De Lusso-batch/maandhuur-varianten staan in
tests/accordering/test_staande_voorstel_periodiek.py; de export van de gouden set bevat de wachtrij niet."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.accordering import service as accordering_service
from app.auth import voorwaarden
from app.documenten import boekvoorstel
from app.documenten.models import DocumentStatus
from app.security.tokens import create_access_token
from tests.accordering.conftest import maak_accordeur, zet_schema
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import GB_ADVIES, PROJECT_26084, TAXRATE_HOOG, Keten

CASUS_H = Casus(casussen.H_BDO)


@pytest.fixture
def accordeur(keten: Keten, admin_engine: Engine, beheerder_id: uuid.UUID) -> uuid.UUID:  # noqa: F811
    k = maak_accordeur(admin_engine, beheerder_id, keten.administratie_id, "Accordeur K1")
    voorwaarden.leg_akkoord_vast(gebruiker_id=k)
    zet_schema(
        administratie_id=keten.administratie_id,
        beheerder_id=beheerder_id,
        lagen=[accordering_service.LaagInput(volgnummer=1, accordeur_gebruiker_id=k, bedrag_drempel=None)],
    )
    return k


def _sla_op(keten: Keten, document_id: uuid.UUID) -> None:
    voorstel = keten.prefill(document_id)
    regel = voorstel.regels[0]
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=keten.administratie_id,
        document_id=document_id,
        actor_id=keten.actor,
        vendor_id=keten.vendors["bdo"],
        referentie=voorstel.referentie,
        factuurdatum=voorstel.factuurdatum,
        totaalbedrag=voorstel.totaalbedrag,
        regels=[
            boekvoorstel.BoekvoorstelRegelData(
                ledger_id=GB_ADVIES,
                taxrate_id=TAXRATE_HOOG,
                project_id=PROJECT_26084,
                netto_bedrag=regel.netto_bedrag,
                btw_bedrag=regel.btw_bedrag,
                omschrijving="regel",
            )
        ],
    )


class TestEersteFactuurGeenVoorstel:
    def test_wachtrij_dto_draagt_patroon_null_en_geen_kandidaat(
        self, keten: Keten, accordeur: uuid.UUID, admin_engine: Engine
    ) -> None:
        pdf = CASUS_H.pdf()
        deel = keten.mail(
            [(CASUS_H.xml_bestandsnaam(), CASUS_H.xml(ingesloten_pdf=pdf)), (CASUS_H.pdf_bestandsnaam(), pdf)]
        )
        doc = deel.bijlagen[0].document_id
        _sla_op(keten, doc)
        resp = keten.api.post(
            f"/administraties/{keten.administratie_id}/accordering/documenten/{doc}/aanbieden", headers=keten.headers
        )
        assert resp.status_code == 200, resp.text
        assert keten.status(doc) == DocumentStatus.TER_ACCORDERING

        # Servicelaag: één echte factuur = geen reeks, geen patroon, geen voorstel.
        items = accordering_service.wachtrij_voor_accordeur(
            actor_id=accordeur, administratie_ids=[keten.administratie_id]
        )
        assert [i.document_id for i in items] == [doc]
        assert items[0].staande_regel_kandidaat is False
        assert items[0].staande_regel_patroon is None

        # API-DTO van de accordeur-app: het veld reist additief mee (null), de bestaande vlag ongewijzigd.
        resp = keten.api.get(
            "/accordering/wachtrij",
            headers={"Authorization": f"Bearer {create_access_token(accordeur, rol='klant_accordeur')}"},
        )
        assert resp.status_code == 200, resp.text
        rij = resp.json()["items"][0]
        assert rij["document_id"] == str(doc)
        assert rij["staande_regel_kandidaat"] is False
        assert rij["staande_regel_patroon"] is None

        # Akkoord zonder antwoord op het voorstel (oude app-versie): geen stilte-rij, wél het gewone akkoord-audit.
        resp = keten.api.post(
            f"/administraties/{keten.administratie_id}/accordering/documenten/{doc}/akkoord",
            json={"staande_regel_aanmaken": False},
            headers={"Authorization": f"Bearer {create_access_token(accordeur, rol='klant_accordeur')}"},
        )
        assert resp.status_code == 200, resp.text
        with admin_engine.connect() as conn:
            stil = conn.execute(text("SELECT count(*) FROM boekhouding.staande_goedkeuring_voorstel_stil")).scalar_one()
            akkoord = conn.execute(
                text("SELECT count(*) FROM platform.audit_event WHERE actie = 'accordering_akkoord'")
            ).scalar_one()
        assert stil == 0
        assert akkoord == 1
