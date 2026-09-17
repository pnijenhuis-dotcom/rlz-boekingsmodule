# ruff: noqa: F811 — pytest-fixtures als parameters
"""Klant-accordering — accorderingsroute per LEVERANCIER (Peter 17-09: "1 losse accordeur die alleen de aangevinkte
leveranciers ziet — dus NIET langs de andere accordeurs"; migratie 0156). Casus (blok C, synthetisch): administratie mét
administratieroute A (accordeur_1, drempel € 100) + leveranciersroute Q (Sophia = accordeur_2). Factuur van Q gaat
uitsluitend door Q's route (Sophia), factuur van R uitsluitend door A (accordeur_1); Sophia ziet alleen Q en kan op R niets
besluiten (server-side). Eén leverancier in één route (409); identiteit over crediteurrecords (voorkeur); herberekening bij
toevoegen/verwijderen/deactiveren; route zonder lagen = zichtbare fout."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.accordering import service
from app.accordering.models import AccorderingLaag, DocumentAccordering
from app.db.session import scoped_session
from app.documenten import boekvoorstel
from tests.accordering.conftest import maak_accordeur, maak_klaar_document, zet_schema
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import gescoopte_gebruiker, opslag  # noqa: F401

VENDOR_Q = uuid.UUID("aaaaaaaa-1111-4111-8111-aaaaaaaaaaa1")
VENDOR_Q_DUBBEL = uuid.UUID("aaaaaaaa-1111-4111-8111-aaaaaaaaaaa2")  # verliezer-record van dezelfde identiteit
VENDOR_R = uuid.UUID("bbbbbbbb-2222-4222-8222-bbbbbbbbbbb1")


def _vendor(admin_engine: Engine, administratie_id: uuid.UUID, vendor_id: uuid.UUID, naam: str, voorkeur: uuid.UUID | None = None) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.vendor_cache (id, administratie_id, naam, brondata, voorkeur_vendor_id) "
                "VALUES (:id, :aid, :naam, '{}', :voorkeur) ON CONFLICT DO NOTHING"
            ),
            {"id": vendor_id, "aid": administratie_id, "naam": naam, "voorkeur": voorkeur},
        )


def _document_van(gescoopte_gebruiker, administratie_id, admin_engine, opslag, *, vendor_id: uuid.UUID, bedrag: str, naam: str) -> uuid.UUID:  # noqa: ANN001
    doc_id = maak_klaar_document(gescoopte_gebruiker, administratie_id, admin_engine, opslag, naam=naam)
    from datetime import date

    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=doc_id,
        actor_id=gescoopte_gebruiker,
        vendor_id=vendor_id,
        referentie=f"F-{naam}",
        factuurdatum=date(2026, 7, 1),
        totaalbedrag=Decimal(bedrag),
        regels=[
            boekvoorstel.BoekvoorstelRegelData(
                ledger_id=uuid.uuid4(), taxrate_id=uuid.uuid4(), project_id=None,
                netto_bedrag=Decimal(bedrag) / Decimal("1.21"), btw_bedrag=Decimal(bedrag) - Decimal(bedrag) / Decimal("1.21"), omschrijving="regel",
            )
        ],
    )
    return doc_id


def _stappen(administratie_id: uuid.UUID, document_id: uuid.UUID) -> list[tuple[int, uuid.UUID, bool]]:
    with scoped_session(administratie_id) as session:
        ronde = session.query(DocumentAccordering).filter_by(document_id=document_id, status="open").one()
        stappen = service._stappen_van(session, ronde.id)
        return [(s.volgnummer, s.accordeur_gebruiker_id, s.vereist) for s in stappen], (ronde.detail or {}).get("leverancier_route_naam")


@pytest.fixture
def opzet(admin_engine: Engine, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, boeken_aan) -> dict:  # noqa: ANN001
    a1 = maak_accordeur(admin_engine, beheerder_id, administratie_id, "A. Algemeen")
    sophia = maak_accordeur(admin_engine, beheerder_id, administratie_id, "Sophia")
    directeur = maak_accordeur(admin_engine, beheerder_id, administratie_id, "D. Directeur")
    _vendor(admin_engine, administratie_id, VENDOR_Q, "Firma Q B.V.")
    _vendor(admin_engine, administratie_id, VENDOR_Q_DUBBEL, "Firma Q BV (dubbel)", voorkeur=VENDOR_Q)
    _vendor(admin_engine, administratie_id, VENDOR_R, "Firma R B.V.")
    zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[service.LaagInput(1, a1, Decimal("100"))])
    return {"a1": a1, "sophia": sophia, "directeur": directeur}


def _route(administratie_id, beheerder_id, *, vendor_ids, lagen, naam="Route Q", route_id=None):  # noqa: ANN001, ANN202
    return service.leverancier_route_opslaan(
        administratie_id=administratie_id,
        actor_id=beheerder_id,
        actor_rol="beheerder",
        route_id=route_id,
        invoer=service.LeverancierRouteInput(naam=naam, vendor_ids=list(vendor_ids), lagen=lagen),
    )


class TestLeveranciersrouteVervangtAdministratieroute:
    def test_casus_q_alleen_sophia_r_alleen_a_en_wachtrij_scherp(self, opzet, administratie_id, beheerder_id, gescoopte_gebruiker, admin_engine, opslag) -> None:  # noqa: ANN001
        route_id, rondes = _route(administratie_id, beheerder_id, vendor_ids=[VENDOR_Q], lagen=[
            service.LaagInput(1, opzet["sophia"], None),
            service.LaagInput(2, opzet["directeur"], Decimal("5000")),
        ])
        assert rondes.herberekend == 0
        doc_q = _document_van(gescoopte_gebruiker, administratie_id, admin_engine, opslag, vendor_id=VENDOR_Q, bedrag="2500.00", naam="q.pdf")
        doc_r = _document_van(gescoopte_gebruiker, administratie_id, admin_engine, opslag, vendor_id=VENDOR_R, bedrag="2500.00", naam="r.pdf")
        for d in (doc_q, doc_r):
            service.bied_ter_accordering_aan(administratie_id=administratie_id, document_id=d, actor_id=beheerder_id, actor_rol="beheerder")
        stappen_q, route_q = _stappen(administratie_id, doc_q)
        stappen_r, route_r = _stappen(administratie_id, doc_r)
        # Q: uitsluitend de leveranciersroute — Sophia vereist, directeur niet (€ 2.500 ≤ € 5.000); A staat er NIET tussen.
        assert stappen_q == [(1, opzet["sophia"], True), (2, opzet["directeur"], False)] and route_q == "Route Q"
        # R: uitsluitend de administratieroute — A; Sophia staat er NIET tussen.
        assert stappen_r == [(1, opzet["a1"], True)] and route_r is None
        # Wachtrij: Sophia ziet alleen Q, A alleen R.
        assert [i.document_id for i in service.wachtrij_voor_accordeur(actor_id=opzet["sophia"], administratie_ids=[administratie_id])] == [doc_q]
        assert [i.document_id for i in service.wachtrij_voor_accordeur(actor_id=opzet["a1"], administratie_ids=[administratie_id])] == [doc_r]
        # Server-side: Sophia kan op R niets besluiten (geen stap van haar op die ronde).
        with pytest.raises(service.AccorderingFout):
            service.geef_akkoord(administratie_id=administratie_id, document_id=doc_r, actor_id=opzet["sophia"])
        # > € 5.000 bij Q: óók de directeur (tweede laag mét drempel binnen de route).
        doc_q2 = _document_van(gescoopte_gebruiker, administratie_id, admin_engine, opslag, vendor_id=VENDOR_Q, bedrag="7500.00", naam="q2.pdf")
        service.bied_ter_accordering_aan(administratie_id=administratie_id, document_id=doc_q2, actor_id=beheerder_id, actor_rol="beheerder")
        assert _stappen(administratie_id, doc_q2)[0] == [(1, opzet["sophia"], True), (2, opzet["directeur"], True)]

    def test_identiteit_over_crediteurrecords_en_een_route_per_leverancier(self, opzet, administratie_id, beheerder_id, gescoopte_gebruiker, admin_engine, opslag) -> None:  # noqa: ANN001
        _route(administratie_id, beheerder_id, vendor_ids=[VENDOR_Q], lagen=[service.LaagInput(1, opzet["sophia"], None)])
        # Factuur op het verliezer-record van Q volgt óók de route van Q (identiteit via voorkeur).
        doc = _document_van(gescoopte_gebruiker, administratie_id, admin_engine, opslag, vendor_id=VENDOR_Q_DUBBEL, bedrag="300.00", naam="qd.pdf")
        service.bied_ter_accordering_aan(administratie_id=administratie_id, document_id=doc, actor_id=beheerder_id, actor_rol="beheerder")
        assert _stappen(administratie_id, doc) == ([(1, opzet["sophia"], True)], "Route Q")
        # Zelfde leverancier (ook via zijn dubbel-record) in een tweede route = 409 mét de naam van de eerste route.
        with pytest.raises(service.LeverancierAlInRoute, match="Route Q"):
            _route(administratie_id, beheerder_id, naam="Route 2", vendor_ids=[VENDOR_Q_DUBBEL], lagen=[service.LaagInput(1, opzet["directeur"], None)])
        # Route zonder leverancier of zonder laag = geweigerd; onbekende route = fout.
        with pytest.raises(service.OngeldigeAanbieding):
            _route(administratie_id, beheerder_id, naam="Leeg", vendor_ids=[], lagen=[service.LaagInput(1, opzet["directeur"], None)])
        with pytest.raises(service.GeenLagenIngesteld):
            _route(administratie_id, beheerder_id, naam="Zonder lagen", vendor_ids=[VENDOR_R], lagen=[])

    def test_herberekening_bij_toevoegen_verwijderen_en_deactiveren(self, opzet, administratie_id, beheerder_id, gescoopte_gebruiker, admin_engine, opslag) -> None:  # noqa: ANN001
        # Ronde van Q loopt nog op de administratieroute (A) …
        doc_q = _document_van(gescoopte_gebruiker, administratie_id, admin_engine, opslag, vendor_id=VENDOR_Q, bedrag="2500.00", naam="q.pdf")
        doc_r = _document_van(gescoopte_gebruiker, administratie_id, admin_engine, opslag, vendor_id=VENDOR_R, bedrag="2500.00", naam="r.pdf")
        for d in (doc_q, doc_r):
            service.bied_ter_accordering_aan(administratie_id=administratie_id, document_id=d, actor_id=beheerder_id, actor_rol="beheerder")
        assert _stappen(administratie_id, doc_q)[0] == [(1, opzet["a1"], True)]
        # … Q wordt aangevinkt → de ronde van Q wordt herberekend naar Sophia; R blijft bij A.
        route_id, rondes = _route(administratie_id, beheerder_id, vendor_ids=[VENDOR_Q], lagen=[service.LaagInput(1, opzet["sophia"], None)])
        assert rondes.herberekend == 1 and rondes.vervallen == 0
        assert _stappen(administratie_id, doc_q)[0] == [(1, opzet["sophia"], True)]
        assert _stappen(administratie_id, doc_r)[0] == [(1, opzet["a1"], True)]
        # Administratieroute wijzigen raakt de Q-ronde niet.
        rondes_admin = zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[service.LaagInput(1, opzet["directeur"], None)])
        assert rondes_admin.herberekend == 1  # alleen R
        assert _stappen(administratie_id, doc_q)[0] == [(1, opzet["sophia"], True)]
        assert _stappen(administratie_id, doc_r)[0] == [(1, opzet["directeur"], True)]
        # Q uit de route (lege vendor-lijst mag niet; vervang door R) → Q terug naar de administratieroute, R naar Sophia.
        _, rondes2 = _route(administratie_id, beheerder_id, route_id=route_id, vendor_ids=[VENDOR_R], lagen=[service.LaagInput(1, opzet["sophia"], None)])
        assert rondes2.herberekend == 2
        assert _stappen(administratie_id, doc_q)[0] == [(1, opzet["directeur"], True)]
        assert _stappen(administratie_id, doc_r)[0] == [(1, opzet["sophia"], True)]
        # Deactiveren → alles terug naar de administratieroute; lagen van de route inactief; lijst leeg.
        uit = service.leverancier_route_deactiveren(administratie_id=administratie_id, actor_id=beheerder_id, actor_rol="beheerder", route_id=route_id)
        assert uit.herberekend == 1
        assert _stappen(administratie_id, doc_r)[0] == [(1, opzet["directeur"], True)]
        assert service.leverancier_routes_ophalen(administratie_id=administratie_id) == []
        with scoped_session(administratie_id) as session:
            assert all(not laag.actief for laag in session.query(AccorderingLaag).filter_by(leverancier_route_id=route_id))

    def test_route_zonder_lagen_is_zichtbare_fout_bij_aanbieden(self, opzet, administratie_id, beheerder_id, gescoopte_gebruiker, admin_engine, opslag) -> None:  # noqa: ANN001
        route_id, _ = _route(administratie_id, beheerder_id, vendor_ids=[VENDOR_Q], lagen=[service.LaagInput(1, opzet["sophia"], None)])
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            for laag in session.query(AccorderingLaag).filter_by(leverancier_route_id=route_id):
                laag.actief = False
        doc_q = _document_van(gescoopte_gebruiker, administratie_id, admin_engine, opslag, vendor_id=VENDOR_Q, bedrag="2500.00", naam="q.pdf")
        with pytest.raises(service.GeenLagenIngesteld, match="Leveranciersroute 'Route Q' heeft geen accorderingslagen"):
            service.bied_ter_accordering_aan(administratie_id=administratie_id, document_id=doc_q, actor_id=beheerder_id, actor_rol="beheerder")


class TestRoutes:
    def test_beheerder_crud_en_kantoor_leest(self, opzet, administratie_id, beheerder_id, gescoopte_gebruiker) -> None:  # noqa: ANN001
        from fastapi.testclient import TestClient

        from app.main import app
        from app.security.tokens import create_access_token

        client = TestClient(app)
        hb = {"Authorization": f"Bearer {create_access_token(beheerder_id, rol='beheerder')}"}
        hk = {"Authorization": f"Bearer {create_access_token(gescoopte_gebruiker, rol='boekhouding')}"}
        basis = f"/administraties/{administratie_id}/accordering/leverancier-routes"
        body = {"naam": "Route Q", "vendor_ids": [str(VENDOR_Q)], "lagen": [{"volgnummer": 1, "accordeur_gebruiker_id": str(opzet["sophia"]), "bedrag_drempel": None}, {"volgnummer": 2, "accordeur_gebruiker_id": str(opzet["directeur"]), "bedrag_drempel": "5000"}]}
        assert client.post(basis, json=body, headers=hk).status_code == 403  # kantoor mag lezen, niet wijzigen
        r = client.post(basis, json=body, headers=hb)
        assert r.status_code == 201, r.text
        route = r.json()["routes"][0]
        assert route["naam"] == "Route Q" and route["leveranciers"][0]["naam"] == "Firma Q B.V."
        assert route["samenvatting"] == "laag 1 Sophia → laag 2 D. Directeur · > € 5.000,00 · alleen Firma Q B.V."
        assert client.get(basis, headers=hk).status_code == 200 and len(client.get(basis, headers=hk).json()["routes"]) == 1
        # tweede route met dezelfde leverancier = 409
        r2 = client.post(basis, json={**body, "naam": "Route 2"}, headers=hb)
        assert r2.status_code == 409 and "Route Q" in r2.json()["detail"]
        r3 = client.put(f"{basis}/{route['id']}", json={**body, "vendor_ids": [str(VENDOR_Q), str(VENDOR_R)]}, headers=hb)
        assert r3.status_code == 200 and len(r3.json()["routes"][0]["leveranciers"]) == 2
        r4 = client.delete(f"{basis}/{route['id']}", headers=hb)
        assert r4.status_code == 200 and r4.json()["routes"] == []
        assert client.get(basis, headers={"Authorization": f"Bearer {create_access_token(opzet['sophia'], rol='klant_accordeur')}"}).status_code in (401, 403)
