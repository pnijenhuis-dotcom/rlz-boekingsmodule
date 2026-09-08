"""Casus (n) — intercompany slaat klant-accordering over (blok 4 bundel 08-09 avond, besluit Peter 08-09).

Universal Nederland B.V. (casus a, RLZ-2080143037) factureert aan Universal Steigerbouw; in de administratie Universal
Steigerbouw staat klant-accordering AAN én draagt de crediteur Universal Nederland de IC-vlag (actieve rij in
`intercompany_tegenpartij` van déze administratie — dezelfde tabel die de Kempen-doorbelasting onderhoudt). Doelgedrag:
het document doorloopt exact dezelfde keten (intake → prefill → checks → boeken) maar de stap "ter accordering" wordt
overgeslagen: géén ronde, direct geboekt, tijdlijn + audit "intercompany — klant-accordering overgeslagen
(leveranciersregel)", het boekvoorstel-DTO draagt `accordering_overgeslagen_reden = "intercompany"` (knop "Boeken") en
de accorderingshistorie toont "overgeslagen — intercompany". Een niet-IC-leverancier (Floor, casus b) blijft in dezelfde
administratie gewoon "Ter accordering" (poort dicht)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.accordering import service as accordering_service
from app.documenten import boeken, boekvoorstel
from app.documenten.models import DocumentStatus
from tests.accordering.conftest import maak_accordeur, zet_schema
from tests.bank.conftest import maak_intercompany_tegenpartij
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import GB_HUUR_MATERIEEL, GB_INHUUR, PROJECT_25011, PROJECT_26084, TAXRATE_HOOG, Keten

CASUS_A = Casus(casussen.A_UNIVERSAL_NEDERLAND)
CASUS_B = Casus(casussen.B_FLOOR)


@pytest.fixture
def accordering_aan(keten: Keten, admin_engine: Engine, beheerder_id: uuid.UUID) -> uuid.UUID:  # noqa: F811
    """Klant-accordering AAN op Universal Steigerbouw met één accordeur-laag (alle facturen)."""
    accordeur = maak_accordeur(admin_engine, beheerder_id, keten.administratie_id, "K. Accordeur")
    zet_schema(
        administratie_id=keten.administratie_id,
        beheerder_id=beheerder_id,
        lagen=[accordering_service.LaagInput(volgnummer=1, accordeur_gebruiker_id=accordeur, bedrag_drempel=None)],
    )
    return accordeur


@pytest.fixture
def ic_universal_nederland(keten: Keten, admin_engine: Engine) -> uuid.UUID:
    """De IC-vlag: Universal Nederland B.V. is in de administratie Universal Steigerbouw intercompany-tegenpartij."""
    return maak_intercompany_tegenpartij(
        admin_engine,
        administratie_id=keten.administratie_id,
        entity_guid=keten.vendors["universal_nederland"],
        naam="Universal Nederland B.V.",
    )


def _rondes(admin_engine: Engine, document_id: uuid.UUID) -> int:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM boekhouding.document_accordering WHERE document_id = :id"), {"id": document_id}
        ).scalar_one()


def _sla_op_en_boek(keten: Keten, document_id: uuid.UUID, *, ledger_id: uuid.UUID, project_id: uuid.UUID) -> None:
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
                ledger_id=ledger_id,
                taxrate_id=r.taxrate_id or TAXRATE_HOOG,
                project_id=project_id,
                netto_bedrag=r.netto_bedrag,
                btw_bedrag=r.btw_bedrag,
                omschrijving=r.omschrijving or "regel",
            )
            for r in voorstel.regels
        ],
    )
    boeken.boek_document(administratie_id=keten.administratie_id, document_id=document_id, actor_id=keten.actor)


class TestIntercompanyDocument:
    @pytest.fixture
    def universal_nederland_doc(self, keten: Keten, accordering_aan: uuid.UUID, ic_universal_nederland: uuid.UUID):
        deel = keten.mail([(CASUS_A.pdf_bestandsnaam(), CASUS_A.pdf()), (CASUS_A.xml_bestandsnaam(), CASUS_A.xml())])
        return {r.bestandsnaam: r for r in deel.bijlagen}[CASUS_A.xml_bestandsnaam()].document_id

    def test_controlescherm_dto_zegt_boeken_ipv_ter_accordering(self, keten: Keten, universal_nederland_doc) -> None:
        dto = keten.open_controlescherm(universal_nederland_doc)
        assert dto["vendor_id"] == str(keten.vendors["universal_nederland"])
        assert dto["accordering_overgeslagen_reden"] == "intercompany"
        # Historie al vóór de boeking: "overgeslagen — intercompany", zonder stappen.
        resp = keten.api.get(
            f"/administraties/{keten.administratie_id}/accordering/documenten/{universal_nederland_doc}",
            headers=keten.headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "overgeslagen"
        assert resp.json()["overgeslagen_reden"] == "intercompany"
        assert resp.json()["overgeslagen_leverancier_naam"] == "Universal Nederland B.V."
        assert resp.json()["stappen"] == []

    def test_boeken_loopt_door_zonder_ronde_met_tijdlijn_en_audit(
        self, keten: Keten, universal_nederland_doc, admin_engine: Engine
    ) -> None:
        keten.open_controlescherm(universal_nederland_doc)
        _sla_op_en_boek(keten, universal_nederland_doc, ledger_id=GB_HUUR_MATERIEEL, project_id=PROJECT_26084)
        assert keten.status(universal_nederland_doc) == DocumentStatus.GEBOEKT
        assert len(keten.rlz.puts) == 1 and keten.rlz.puts[0]["reference"] == "RLZ-2080143037"
        assert _rondes(admin_engine, universal_nederland_doc) == 0, "intercompany = géén accorderingsronde"
        notities = [
            d[accordering_service.OVERGESLAGEN_TIJDLIJN_SLEUTEL]
            for d in keten.tijdlijn(universal_nederland_doc)
            if accordering_service.OVERGESLAGEN_TIJDLIJN_SLEUTEL in d
        ]
        assert len(notities) == 1
        assert notities[0]["reden"] == "intercompany"
        assert notities[0]["vendor_id"] == str(keten.vendors["universal_nederland"])
        assert notities[0]["leverancier_naam"] == "Universal Nederland B.V."
        with admin_engine.connect() as conn:
            audit = conn.execute(
                text("SELECT count(*) FROM platform.audit_event WHERE actie = :actie AND record_id = :id"),
                {"actie": accordering_service.OVERGESLAGEN_AUDIT_ACTIE, "id": universal_nederland_doc},
            ).scalar_one()
        assert audit == 1
        # Historie ná de boeking blijft "overgeslagen"; het detail (tijdlijn) draagt de notitie voor de frontend.
        resp = keten.api.get(
            f"/administraties/{keten.administratie_id}/accordering/documenten/{universal_nederland_doc}",
            headers=keten.headers,
        )
        assert resp.json()["status"] == "overgeslagen"
        detail = keten.detail(universal_nederland_doc)
        assert any(
            (g.get("detail") or {}).get(accordering_service.OVERGESLAGEN_TIJDLIJN_SLEUTEL) for g in detail["tijdlijn"]
        )

    def test_ter_accordering_knop_via_api_boekt_direct_zonder_ronde(
        self, keten: Keten, universal_nederland_doc, admin_engine: Engine
    ) -> None:
        """Een verouderd scherm of de bulk-knop: de aanbied-route maakt voor een IC-document geen ronde maar boekt."""
        keten.open_controlescherm(universal_nederland_doc)
        voorstel = keten.prefill(universal_nederland_doc)
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=keten.administratie_id,
            document_id=universal_nederland_doc,
            actor_id=keten.actor,
            vendor_id=voorstel.vendor_id,
            referentie=voorstel.referentie,
            factuurdatum=voorstel.factuurdatum,
            totaalbedrag=voorstel.totaalbedrag,
            regels=[
                boekvoorstel.BoekvoorstelRegelData(
                    ledger_id=GB_HUUR_MATERIEEL,
                    taxrate_id=TAXRATE_HOOG,
                    project_id=PROJECT_26084,
                    netto_bedrag=Decimal("175.38"),
                    btw_bedrag=Decimal("36.83"),
                    omschrijving="huur juli",
                )
            ],
        )
        resp = keten.api.post(
            f"/administraties/{keten.administratie_id}/accordering/documenten/{universal_nederland_doc}/aanbieden",
            headers=keten.headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["accordering"] is None
        assert body["accordering_overgeslagen_reden"] == "intercompany"
        assert body["geboekt"] is True and body["boek_fout"] is None
        assert keten.status(universal_nederland_doc) == DocumentStatus.GEBOEKT
        assert _rondes(admin_engine, universal_nederland_doc) == 0


class TestNietIntercompanyBlijftTerAccordering:
    def test_floor_in_dezelfde_administratie_blijft_geblokkeerd(
        self, keten: Keten, accordering_aan: uuid.UUID, ic_universal_nederland: uuid.UUID, admin_engine: Engine
    ) -> None:
        """De IC-rij van Universal Nederland raakt Floor niet: poort dicht, DTO zonder reden, geen IC-notitie."""
        deel = keten.mail([(CASUS_B.xml_bestandsnaam(), CASUS_B.xml())])
        floor_doc = deel.bijlagen[0].document_id
        dto = keten.open_controlescherm(floor_doc)
        assert dto["vendor_id"] == str(keten.vendors["floor"])
        assert dto["accordering_overgeslagen_reden"] is None
        with pytest.raises(boeken.AccorderingVereist):
            _sla_op_en_boek(keten, floor_doc, ledger_id=GB_INHUUR, project_id=PROJECT_25011)
        assert keten.status(floor_doc) != DocumentStatus.GEBOEKT
        assert not any(accordering_service.OVERGESLAGEN_TIJDLIJN_SLEUTEL in d for d in keten.tijdlijn(floor_doc))
        resp = keten.api.get(
            f"/administraties/{keten.administratie_id}/accordering/documenten/{floor_doc}", headers=keten.headers
        )
        assert resp.status_code == 200 and resp.json() is None

    def test_zonder_ic_rij_is_universal_nederland_ook_gewoon_ter_accordering(
        self, keten: Keten, accordering_aan: uuid.UUID
    ) -> None:
        """Lege IC-tabel = gewone flow (kernprincipe 7: er gebeurt dan niets bijzonders)."""
        deel = keten.mail([(CASUS_A.xml_bestandsnaam(), CASUS_A.xml())])
        doc = deel.bijlagen[0].document_id
        assert keten.open_controlescherm(doc)["accordering_overgeslagen_reden"] is None
        with pytest.raises(boeken.AccorderingVereist):
            _sla_op_en_boek(keten, doc, ledger_id=GB_HUUR_MATERIEEL, project_id=PROJECT_26084)
