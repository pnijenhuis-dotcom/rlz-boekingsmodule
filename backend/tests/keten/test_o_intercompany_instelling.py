"""Casus (o) — IC-leverancier gezet via de Beheerder-INSTELLING in een administratie met klant-accordering (nachtrun
08/09-09 blok 3).

Vervolg op casus (n): daar staat de IC-rij er "van buiten" (zoals de doorbelasting-mapping die zet). Hier zet de
Beheerder de vlag via Instellingen › Administraties › Universal Steigerbouw › Klant-accordering ("Intercompany —
accordering overslaan") — de nieuwe route `PUT /administraties/{id}/intercompany-leveranciers/{vendor}` — en dáárna
doorloopt een Universal-Nederland-document (casus a) de keten: geen ronde, `accordering_overgeslagen_reden =
"intercompany"`, boeken direct. Verwijderen via de instelling zet de gewone flow terug (poort dicht)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.accordering import service as accordering_service
from app.documenten import boeken, boekvoorstel
from app.documenten.models import DocumentStatus
from app.security.tokens import create_access_token
from tests.accordering.conftest import maak_accordeur, zet_schema
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import GB_HUUR_MATERIEEL, PROJECT_26084, TAXRATE_HOOG, Keten

CASUS_A = Casus(casussen.A_UNIVERSAL_NEDERLAND)


@pytest.fixture
def accordering_aan(keten: Keten, admin_engine: Engine, beheerder_id: uuid.UUID) -> uuid.UUID:  # noqa: F811
    accordeur = maak_accordeur(admin_engine, beheerder_id, keten.administratie_id, "K. Accordeur")
    zet_schema(
        administratie_id=keten.administratie_id,
        beheerder_id=beheerder_id,
        lagen=[accordering_service.LaagInput(volgnummer=1, accordeur_gebruiker_id=accordeur, bedrag_drempel=None)],
    )
    return accordeur


def _beheerder_headers(beheerder_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(beheerder_id, rol='beheerder')}"}


def _rondes(admin_engine: Engine, document_id: uuid.UUID) -> int:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM boekhouding.document_accordering WHERE document_id = :id"), {"id": document_id}
        ).scalar_one()


def _sla_op(keten: Keten, document_id: uuid.UUID) -> None:
    voorstel = keten.prefill(document_id)
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=keten.administratie_id,
        document_id=document_id,
        actor_id=keten.actor,
        vendor_id=voorstel.vendor_id,
        referentie=voorstel.referentie,
        factuurdatum=voorstel.factuurdatum,
        totaalbedrag=voorstel.totaalbedrag,
        regels=[
            boekvoorstel.BoekvoorstelRegelData(
                ledger_id=GB_HUUR_MATERIEEL,
                taxrate_id=r.taxrate_id or TAXRATE_HOOG,
                project_id=PROJECT_26084,
                netto_bedrag=r.netto_bedrag,
                btw_bedrag=r.btw_bedrag,
                omschrijving=r.omschrijving or "regel",
            )
            for r in voorstel.regels
        ],
    )


def _sla_op_en_boek(keten: Keten, document_id: uuid.UUID) -> None:
    _sla_op(keten, document_id)
    boeken.boek_document(administratie_id=keten.administratie_id, document_id=document_id, actor_id=keten.actor)


class TestInstellingStuurtDeKeten:
    def test_beheerder_markeert_via_instelling_daarna_boekt_universal_nederland_zonder_ronde(
        self, keten: Keten, accordering_aan: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        basis = f"/administraties/{keten.administratie_id}/intercompany-leveranciers"
        vendor = keten.vendors["universal_nederland"]
        # Vooraf: leeg, en het document zou gewoon ter accordering gaan.
        assert keten.api.get(basis, headers=keten.headers).json()["leveranciers"] == []
        resp = keten.api.put(
            f"{basis}/{vendor}",
            json={"reden": "besluit 08-09 intercompany Universal"},
            headers=_beheerder_headers(beheerder_id),
        )
        assert resp.status_code == 200, resp.text
        assert [(lv["naam"], lv["bron"]) for lv in resp.json()["leveranciers"]] == [
            ("Universal Nederland B.V.", "handmatig")
        ]
        # De live GET toont de instelling (meetrecept blok 2).
        lijst = keten.api.get(basis, headers=keten.headers).json()
        assert lijst["leveranciers"][0]["vendor_id"] == str(vendor)
        assert lijst["historie"][0]["actie"] == "gemarkeerd"

        deel = keten.mail([(CASUS_A.pdf_bestandsnaam(), CASUS_A.pdf()), (CASUS_A.xml_bestandsnaam(), CASUS_A.xml())])
        doc = {r.bestandsnaam: r for r in deel.bijlagen}[CASUS_A.xml_bestandsnaam()].document_id
        dto = keten.open_controlescherm(doc)
        assert dto["vendor_id"] == str(vendor)
        assert dto["accordering_overgeslagen_reden"] == "intercompany"
        # Ná het invullen: kantoorwerk (niet ter_accordering / "wachten op anderen") — het document staat in de
        # standaardlijst (groep kantoor) en de boekknop zegt "Boeken".
        _sla_op(keten, doc)
        assert keten.status(doc) in {DocumentStatus.TE_CONTROLEREN, DocumentStatus.KLAAR_OM_TE_BOEKEN}
        assert keten.status(doc) != DocumentStatus.TER_ACCORDERING
        assert keten.lijst_rij(doc, groep="kantoor") is not None
        assert keten.lijst_rij(doc, groep="wachten") is None
        boeken.boek_document(administratie_id=keten.administratie_id, document_id=doc, actor_id=keten.actor)
        assert keten.status(doc) == DocumentStatus.GEBOEKT
        assert _rondes(admin_engine, doc) == 0
        assert any(accordering_service.OVERGESLAGEN_TIJDLIJN_SLEUTEL in d for d in keten.tijdlijn(doc))

    def test_verwijderen_via_instelling_zet_de_gewone_flow_terug(
        self, keten: Keten, accordering_aan: uuid.UUID, beheerder_id: uuid.UUID
    ) -> None:
        basis = f"/administraties/{keten.administratie_id}/intercompany-leveranciers"
        vendor = keten.vendors["universal_nederland"]
        hdr = _beheerder_headers(beheerder_id)
        assert keten.api.put(f"{basis}/{vendor}", headers=hdr).status_code == 200
        resp = keten.api.delete(f"{basis}/{vendor}", headers=hdr)
        assert resp.status_code == 200 and resp.json()["leveranciers"] == []
        deel = keten.mail([(CASUS_A.xml_bestandsnaam(), CASUS_A.xml())])
        doc = deel.bijlagen[0].document_id
        assert keten.open_controlescherm(doc)["accordering_overgeslagen_reden"] is None
        with pytest.raises(boeken.AccorderingVereist):
            _sla_op_en_boek(keten, doc)
        assert keten.status(doc) != DocumentStatus.GEBOEKT
