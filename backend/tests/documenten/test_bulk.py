# ruff: noqa: F811 — pytest-fixtures als parameters
"""Bulk-acties documentenlijst (Peter 16-09, "nu moet dat 1 voor 1"): N × de bestaande per-document-route, uitkomst
per rij. Mix geboekt/niet-geboekt → deel overgeslagen mét reden; één reden voor de hele selectie; audit per rij; type
wijzigen (inkoopfactuur → kassarapport) = soort gezet + extractie opnieuw + tijdlijn/audit, idempotent bij dezelfde
soort; verplaatsen via de bestaande verhuisroute (doel zonder scope = geen_toegang); scope-test mét een echte
niet-Beheerder (RLS-les 25-08): een document van een andere administratie = geen_toegang, nooit een fout; route +
validatie."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service as auth_service
from app.db.models import GebruikerRol
from app.db.session import scoped_session
from app.documenten import bulk, service
from app.documenten.models import Document, DocumentSoort, DocumentStatus
from app.documenten.service import _schrijf_overgang
from app.documenten.storage import LokaleBestandsopslag
from app.main import app
from app.security.tokens import create_access_token
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import gescoopte_gebruiker, opslag  # noqa: F401
from tests.intake.conftest import bouw_ubl

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _upload(administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag, naam: str) -> uuid.UUID:
    """UBL = deterministische extractie → direct te_controleren (geen AI in de test)."""
    r = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=naam,
        inhoud=bouw_ubl(klant="Klant B.V.", factuurnummer=f"F-{uuid.uuid4().hex[:6]}"),
        actor_id=actor_id,
        opslag=opslag,
    )
    assert r.status == DocumentStatus.TE_CONTROLEREN
    return r.document_id


def _boek(administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        d = session.get(Document, document_id)
        _schrijf_overgang(session, document=d, naar=DocumentStatus.KLAAR_OM_TE_BOEKEN, actor_id=actor_id)
        _schrijf_overgang(session, document=d, naar=DocumentStatus.GEBOEKT, actor_id=actor_id)


def _rij(admin_engine: Engine, document_id: uuid.UUID) -> tuple[str, str]:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT status, soort FROM boekhouding.document WHERE id = :id"), {"id": document_id}
        ).one()


def _audit(admin_engine: Engine, document_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        return list(
            conn.execute(
                text(
                    "SELECT actie FROM platform.audit_event WHERE tabel = 'document' AND record_id = :id "
                    "ORDER BY tijdstip"
                ),
                {"id": document_id},
            ).scalars()
        )


class TestVerwijderenEnAfwijzen:
    def test_mix_geboekt_niet_geboekt_een_reden_audit_per_rij(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        a = _upload(administratie_id, gescoopte_gebruiker, opslag, "a.xml")
        b = _upload(administratie_id, gescoopte_gebruiker, opslag, "b.xml")
        g = _upload(administratie_id, gescoopte_gebruiker, opslag, "geboekt.xml")
        _boek(administratie_id, g, gescoopte_gebruiker)
        uit = bulk.voer_bulk_uit(
            administratie_id=administratie_id,
            document_ids=[a, b, g, a],  # dubbel id = één keer
            actie="verwijderen",
            actor_id=gescoopte_gebruiker,
            actor_rol=GebruikerRol.BOEKHOUDING,
            reden="ProfX-journaal, geen inkoopfactuur",
        )
        assert [(r.document_id, r.uitkomst) for r in uit.rijen] == [(a, "gelukt"), (b, "gelukt"), (g, "overgeslagen")]
        assert (uit.gelukt, uit.overgeslagen, uit.geen_toegang) == (2, 1, 0)
        assert uit.rijen[2].reden is not None and "geboekt" in uit.rijen[2].reden.lower()
        assert uit.rijen[2].bestandsnaam == "geboekt.xml"
        assert _rij(admin_engine, a)[0] == "verwijderd" and _rij(admin_engine, g)[0] == "geboekt"
        assert "status_verwijderd" in _audit(admin_engine, a) and "status_verwijderd" in _audit(admin_engine, b)
        with admin_engine.connect() as conn:
            redenen = (
                conn.execute(
                    text(
                        "SELECT detail->>'reden' FROM boekhouding.document_gebeurtenis "
                        "WHERE naar_status = 'verwijderd' AND document_id IN (:a, :b)"
                    ),
                    {"a": a, "b": b},
                )
                .scalars()
                .all()
            )
        assert redenen == ["ProfX-journaal, geen inkoopfactuur"] * 2

    def test_afwijzen_bulk_met_reden(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        a = _upload(administratie_id, gescoopte_gebruiker, opslag, "a.xml")
        uit = bulk.voer_bulk_uit(
            administratie_id=administratie_id,
            document_ids=[a],
            actie="afwijzen",
            actor_id=gescoopte_gebruiker,
            actor_rol=GebruikerRol.BOEKHOUDING,
            reden="verkeerde administratie",
        )
        assert uit.rijen[0].uitkomst == "gelukt" and _rij(admin_engine, a)[0] == "afgewezen"


class TestSoortWijzigen:
    def test_inkoopfactuur_naar_kassarapport_extractie_opnieuw_en_idempotent(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        a = _upload(administratie_id, gescoopte_gebruiker, opslag, "profx.xml")
        g = _upload(administratie_id, gescoopte_gebruiker, opslag, "geboekt.xml")
        _boek(administratie_id, g, gescoopte_gebruiker)
        uit = bulk.voer_bulk_uit(
            administratie_id=administratie_id,
            document_ids=[a, g],
            actie="soort_wijzigen",
            actor_id=gescoopte_gebruiker,
            actor_rol=GebruikerRol.BOEKHOUDING,
            soort=DocumentSoort.KASSARAPPORT,
        )
        assert uit.rijen[0].uitkomst == "gelukt" and uit.rijen[1].uitkomst == "overgeslagen"
        assert "Type wijzigen kan niet" in (uit.rijen[1].reden or "")
        status, soort = _rij(admin_engine, a)
        assert soort == "kassarapport" and status != "geboekt"
        assert "documentsoort_gewijzigd" in _audit(admin_engine, a) and "status_ontvangen" in _audit(admin_engine, a)
        with admin_engine.connect() as conn:
            detail = conn.execute(
                text(
                    "SELECT detail->>'documentsoort_gewijzigd' FROM boekhouding.document_gebeurtenis "
                    "WHERE document_id = :id AND detail ? 'documentsoort_gewijzigd'"
                ),
                {"id": a},
            ).scalar_one()
        assert detail == "inkoopfactuur -> kassarapport"
        # Zelfde soort nog eens = overgeslagen (idempotent, geen tweede tijdlijnregel).
        uit2 = bulk.voer_bulk_uit(
            administratie_id=administratie_id,
            document_ids=[a],
            actie="soort_wijzigen",
            actor_id=gescoopte_gebruiker,
            actor_rol=GebruikerRol.BOEKHOUDING,
            soort=DocumentSoort.KASSARAPPORT,
        )
        assert uit2.rijen[0].uitkomst == "overgeslagen" and "is al een kassarapport" in (uit2.rijen[0].reden or "")


class TestScopeEnVerplaatsen:
    def test_document_van_andere_administratie_is_geen_toegang_voor_niet_beheerder(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        andere = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Elders BV', :rlz)"),
                {"id": andere, "rlz": f"rlz-{andere}"},
            )
        elders = _upload(andere, beheerder_id, opslag, "elders.xml")
        eigen = _upload(administratie_id, gescoopte_gebruiker, opslag, "eigen.xml")
        uit = bulk.voer_bulk_uit(
            administratie_id=administratie_id,
            document_ids=[eigen, elders, uuid.uuid4()],
            actie="verwijderen",
            actor_id=gescoopte_gebruiker,
            actor_rol=GebruikerRol.BOEKHOUDING,
            reden="x",
        )
        assert [r.uitkomst for r in uit.rijen] == ["gelukt", "geen_toegang", "geen_toegang"]
        assert _rij(admin_engine, elders)[0] == "te_controleren"

    def test_verplaatsen_bulk_doel_zonder_scope_is_geen_toegang_met_scope_gelukt(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        doel = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO platform.administratie (id, naam, rlz_admin_id, eigenaar_gebruiker_id) "
                    "VALUES (:id, 'Doel BV', :rlz, :eig)"
                ),
                {"id": doel, "rlz": f"rlz-{doel}", "eig": beheerder_id},
            )
        a = _upload(administratie_id, gescoopte_gebruiker, opslag, "a.xml")
        zonder = bulk.voer_bulk_uit(
            administratie_id=administratie_id,
            document_ids=[a],
            actie="verplaatsen",
            actor_id=gescoopte_gebruiker,
            actor_rol=GebruikerRol.BOEKHOUDING,
            doel_administratie_id=doel,
        )
        assert zonder.rijen[0].uitkomst == "geen_toegang"
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=gescoopte_gebruiker, administratie_id=doel)
        met = bulk.voer_bulk_uit(
            administratie_id=administratie_id,
            document_ids=[a],
            actie="verplaatsen",
            actor_id=gescoopte_gebruiker,
            actor_rol=GebruikerRol.BOEKHOUDING,
            doel_administratie_id=doel,
        )
        assert met.rijen[0].uitkomst == "gelukt", met.rijen[0]
        with admin_engine.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT administratie_id FROM boekhouding.document WHERE id = :id"), {"id": a}
                ).scalar_one()
                == doel
            )


class TestRoute:
    def test_route_validatie_en_uitkomst(
        self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        a = _upload(administratie_id, gescoopte_gebruiker, opslag, "a.xml")
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        pad = f"/administraties/{administratie_id}/documenten/bulk"
        # Reden verplicht bij verwijderen/afwijzen; soort bij soort_wijzigen; doel bij verplaatsen.
        assert (
            client.post(pad, headers=headers, json={"document_ids": [str(a)], "actie": "verwijderen"}).status_code
            == 422
        )
        assert (
            client.post(pad, headers=headers, json={"document_ids": [str(a)], "actie": "soort_wijzigen"}).status_code
            == 422
        )
        assert (
            client.post(pad, headers=headers, json={"document_ids": [str(a)], "actie": "verplaatsen"}).status_code
            == 422
        )
        assert (
            client.post(pad, headers=headers, json={"document_ids": [], "actie": "afwijzen", "reden": "x"}).status_code
            == 422
        )
        r = client.post(
            pad,
            headers=headers,
            json={"document_ids": [str(a), str(uuid.uuid4())], "actie": "verwijderen", "reden": "dubbel"},
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert (d["actie"], d["geselecteerd"], d["gelukt"], d["overgeslagen"], d["geen_toegang"]) == (
            "verwijderen",
            2,
            1,
            0,
            1,
        )
        assert d["rijen"][0] == {
            "document_id": str(a),
            "bestandsnaam": "a.xml",
            "uitkomst": "gelukt",
            "reden": None,
            "status": "verwijderd",
        }
        assert d["rijen"][1]["uitkomst"] == "geen_toegang"
