"""Casus (p) — accorderingsronde HERBEREKEND i.p.v. vervallen bij een configuratiewijziging (bundel 09-09 blok 2;
besluit Peter 08-09, herziet "GECOMBINEERDE RUN 01-09" blok A beslispunt 2).

Patroon van casus (o): een écht document (BDO 6088744, UBL zonder AI) doorloopt intake → prefill → aanbieden in
Universal Steigerbouw met klant-accordering [1: K1, 2: K2]; K1 geeft akkoord; de Beheerder wijzigt de lagen via
Instellingen › Administraties › Klant-accordering (PUT) naar [1: K1, 2: K3]. Verwacht: laag 1 behouden, laag 2
opnieuw aangevraagd bij K3, het document blijft in de lijst-groep "Wachten op anderen" mét K3 aan de beurt, de
tijdlijn draagt de herberekening en er is géén vervallen-banner."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.accordering import service as accordering_service
from app.documenten import boekvoorstel
from app.documenten.models import DocumentStatus
from app.security.tokens import create_access_token
from tests.accordering.conftest import maak_accordeur, zet_schema
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import GB_ADVIES, PROJECT_26084, TAXRATE_HOOG, Keten

CASUS_H = Casus(casussen.H_BDO)


@pytest.fixture
def accordeurs(keten: Keten, admin_engine: Engine, beheerder_id: uuid.UUID) -> dict[str, uuid.UUID]:  # noqa: F811
    k = {
        naam: maak_accordeur(admin_engine, beheerder_id, keten.administratie_id, f"Accordeur {naam}")
        for naam in ("K1", "K2", "K3")
    }
    zet_schema(
        administratie_id=keten.administratie_id,
        beheerder_id=beheerder_id,
        lagen=[
            accordering_service.LaagInput(volgnummer=1, accordeur_gebruiker_id=k["K1"], bedrag_drempel=None),
            accordering_service.LaagInput(volgnummer=2, accordeur_gebruiker_id=k["K2"], bedrag_drempel=None),
        ],
    )
    return k


def _beheerder_headers(beheerder_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(beheerder_id, rol='beheerder')}"}


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


def _rondes(admin_engine: Engine, document_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        return list(
            conn.execute(
                text(
                    "SELECT status FROM boekhouding.document_accordering WHERE document_id = :id ORDER BY aangeboden_op"
                ),
                {"id": document_id},
            ).scalars()
        )


class TestConfiguratiewijzigingHerberekentDeRonde:
    def test_akkoord_laag_1_blijft_laag_2_opnieuw_aangevraagd_lijst_toont_wachten(
        self, keten: Keten, accordeurs: dict[str, uuid.UUID], beheerder_id: uuid.UUID, admin_engine: Engine
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
        akkoord = accordering_service.geef_akkoord(
            administratie_id=keten.administratie_id, document_id=doc, actor_id=accordeurs["K1"]
        )
        assert akkoord.alles_akkoord is False
        rij = keten.lijst_rij(doc, groep="wachten")
        assert rij is not None and rij["accordeur_aan_de_beurt"]["naam"] == "Accordeur K2"

        # Beheerder wijzigt de lagen via de detail-tab: K2 → K3 in laag 2.
        resp = keten.api.put(
            f"/administraties/{keten.administratie_id}/accordering/instellingen",
            json={
                "ingeschakeld": True,
                "lagen": [
                    {"volgnummer": 1, "accordeur_gebruiker_id": str(accordeurs["K1"])},
                    {"volgnummer": 2, "accordeur_gebruiker_id": str(accordeurs["K3"])},
                ],
            },
            headers=_beheerder_headers(beheerder_id),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["rondes_herberekend"] == 1
        assert resp.json()["rondes_vervallen"] == 0

        # Ronde blijft OPEN (geen tweede ronde), document blijft "Wachten op anderen" mét K3 aan de beurt.
        assert _rondes(admin_engine, doc) == ["open"]
        assert keten.status(doc) == DocumentStatus.TER_ACCORDERING
        rij = keten.lijst_rij(doc, groep="wachten")
        assert rij is not None and rij["status"] == "ter_accordering"
        assert rij["accordeur_aan_de_beurt"]["naam"] == "Accordeur K3"
        assert keten.lijst_rij(doc, groep="kantoor") is None
        # Historie op het controlescherm: laag 1 akkoord behouden, laag 2 = K3 open.
        historie = keten.api.get(
            f"/administraties/{keten.administratie_id}/accordering/documenten/{doc}", headers=keten.headers
        ).json()
        assert historie["status"] == "open"
        assert [
            (s["volgnummer"], s["accordeur_naam"], s["besluit"], s["aan_de_beurt"]) for s in historie["stappen"]
        ] == [
            (1, "Accordeur K1", "akkoord", False),
            (2, "Accordeur K3", None, True),
        ]
        # Wachtrij accordeur-app: K3 ziet 'm, K2 niet meer, K1 niet.
        for naam, verwacht in (("K1", []), ("K2", []), ("K3", [doc])):
            wachtrij = accordering_service.wachtrij_voor_accordeur(
                actor_id=accordeurs[naam], administratie_ids=[keten.administratie_id]
            )
            assert [w.document_id for w in wachtrij] == verwacht, naam
        # Tijdlijn + audit: herberekend, geen vervallen, geen banner.
        tijdlijn = keten.tijdlijn(doc)
        herberekend = [d for d in tijdlijn if accordering_service.HERBEREKEND_TIJDLIJN_SLEUTEL in d]
        assert len(herberekend) == 1
        assert herberekend[0][accordering_service.HERBEREKEND_TIJDLIJN_SLEUTEL]["akkoorden_behouden"] == 1
        assert herberekend[0][accordering_service.HERBEREKEND_TIJDLIJN_SLEUTEL]["opnieuw_aangevraagd"] == [2]
        assert not any("accordering_vervallen" in d for d in tijdlijn)
        assert accordering_service.vervallen_meldingen(administratie_id=keten.administratie_id) == []
        with admin_engine.connect() as conn:
            acties = set(
                conn.execute(
                    text("SELECT actie FROM platform.audit_event WHERE tabel = 'document_accordering'")
                ).scalars()
            )
        assert accordering_service.HERBEREKEND_AUDIT_ACTIE in acties and "accordering_vervallen" not in acties
        # K3 kan gewoon door; dan is alles akkoord (afrondingsroute).
        resultaat = accordering_service.geef_akkoord(
            administratie_id=keten.administratie_id, document_id=doc, actor_id=accordeurs["K3"]
        )
        assert resultaat.alles_akkoord is True
