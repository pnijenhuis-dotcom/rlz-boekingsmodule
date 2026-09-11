"""Casus (t) — verplaatsen naar een andere administratie onder een productie-gelijke functie-eigenaar (blok 1 run 11-09
middag).

Productie 11-09 11:55: "inv26010471 (1).pdf" van Kempen Facilities naar Universal Verkoop → tweemaal 500 op een RLS-
weigering in `boekhouding.verplaats_document` (0080; op Cloud SQL is de eigenaar géén superuser). Hier loopt het échte
gouden-set-document (casus a, Universal Nederland RLZ-2080143037, via de mailroute) door de échte HTTP-route
`POST …/verplaats` terwijl de DB-functie onder `rls_toets_eigenaar` draait (tests/security/rls_eigenaar.py): het
document verhuist, de tijdlijn draagt van→naar, geen audit `rls_weigering`. En andersom: een RLS-weigering in die route
is een leesbare 500 "automatisch gemeld" (nooit een kale code) mét audit."""

from __future__ import annotations

import uuid

import pytest
from psycopg.errors import InsufficientPrivilege
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError

from app.auth import service as auth_service
from app.documenten import router as documenten_router
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import Keten
from tests.security.rls_eigenaar import productie_eigenaar

CASUS = Casus(casussen.A_UNIVERSAL_NEDERLAND)


@pytest.fixture
def doel_id(admin_engine: Engine, beheerder_id: uuid.UUID, keten: Keten) -> uuid.UUID:
    """Doeladministratie 'Universal Verkoop (test)' mét scope voor de keten-actor (niet-Beheerder)."""
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, :naam, :rlz)"),
            {"id": aid, "naam": "Universal Verkoop (test)", "rlz": f"rlz-{aid}"},
        )
    auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=keten.actor, administratie_id=aid)
    return aid


def _document(keten: Keten) -> uuid.UUID:
    uitkomst = keten.mail([(CASUS.xml_bestandsnaam(), CASUS.xml())])
    return uitkomst.bijlagen[0].document_id


def _rls_weigeringen(admin_engine: Engine) -> int:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM platform.audit_event WHERE actie = 'rls_weigering'")
        ).scalar_one()


class TestVerplaatsenOnderProductieEigenaar:
    def test_document_verhuist_via_de_route_met_tijdlijn_van_naar(
        self, keten: Keten, doel_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        document_id = _document(keten)
        assert keten.rij(document_id)["status"] == "te_controleren"
        with productie_eigenaar(admin_engine):
            resp = keten.api.post(
                f"/administraties/{keten.administratie_id}/documenten/{document_id}/verplaats",
                json={"doel_administratie_id": str(doel_id)},
                headers=keten.headers,
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["naar_administratie_naam"] == "Universal Verkoop (test)"
        assert body["status"] == "te_controleren"  # UBL: her-extractie in het doel is direct klaar
        assert keten.rij(document_id)["administratie_id"] == doel_id
        verhuis = [d for d in keten.tijdlijn(document_id) if "verplaatst" in d]
        assert len(verhuis) == 1
        assert verhuis[0]["verplaatst"]["van_administratie_id"] == str(keten.administratie_id)
        assert verhuis[0]["verplaatst"]["naar_administratie_naam"] == "Universal Verkoop (test)"
        assert _rls_weigeringen(admin_engine) == 0
        # In de bron is het document weg uit de lijst; het doel toont het.
        assert str(document_id) not in keten.standaardlijst_ids()
        doel_lijst = keten.api.get(f"/administraties/{doel_id}/documenten", headers=keten.headers)
        assert resp.status_code == 200 and str(document_id) in {d["id"] for d in doel_lijst.json()["documenten"]}

    def test_rls_weigering_is_leesbare_500_automatisch_gemeld(
        self, keten: Keten, doel_id: uuid.UUID, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        document_id = _document(keten)

        def ontploft(**kw):
            raise ProgrammingError(
                "UPDATE", {}, InsufficientPrivilege('new row violates row-level security policy for table "document"')
            )

        monkeypatch.setattr(documenten_router.verplaatsen, "verplaats_document", ontploft)
        resp = keten.api.post(
            f"/administraties/{keten.administratie_id}/documenten/{document_id}/verplaats",
            json={"doel_administratie_id": str(doel_id)},
            headers=keten.headers,
        )
        assert resp.status_code == 500
        assert resp.json()["detail"].startswith("Verplaatsen is mislukt — automatisch gemeld (code ")
        assert _rls_weigeringen(admin_engine) == 1
        assert keten.rij(document_id)["administratie_id"] == keten.administratie_id
