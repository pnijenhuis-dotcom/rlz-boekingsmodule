"""Punt 12 run A (Peter 02-10: "als ik dan op projectniveau ben wil ik daar ook alle meerwerk statussen
(def en concept) kunnen zien"): het blok "Meerwerk" op de projectpagina leest
`GET /uren/kantoor/meerwerk?administratie_id=…&project_id=…` — DEZELFDE route/DTO/statusdefinitie als
Beoordelen › Meerwerk, gefilterd op één project, nieuwste bovenaan, álle statussen (gemeld · goedgekeurd ·
doorbelast · afgewezen); recht + scope blijven de poort."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.auth import service as auth_service
from app.auth import voorwaarden
from app.main import app
from app.security.tokens import create_access_token
from app.uren import service
from tests.uren.conftest import maak_gebruiker

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


@pytest.fixture
def kantoor_met_recht(admin_engine: Engine, administratie_id, beheerder_id):  # noqa: ANN001
    medewerker = maak_gebruiker(admin_engine, "boekhouding", "Rob T.")
    auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=medewerker, administratie_id=administratie_id)
    service.zet_meerwerk_recht(actor_id=beheerder_id, gebruiker_id=medewerker, ingeschakeld=True)
    return medewerker


@pytest.fixture
def melder(uitvoerder, administratie_id, project_id, tweede_project_id, beheerder_id):  # noqa: ANN001
    auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=uitvoerder, administratie_id=administratie_id)
    voorwaarden.leg_akkoord_vast(gebruiker_id=uitvoerder)
    for pid in (project_id, tweede_project_id):
        service.koppel_project(
            administratie_id=administratie_id, gebruiker_id=uitvoerder, project_id=pid, actor_id=beheerder_id
        )
    return uitvoerder


def _meld(administratie_id, project_id, wie, omschrijving):  # noqa: ANN001
    return service.meld_meerwerk(
        administratie_id=administratie_id,
        project_id=project_id,
        actor_id=wie,
        omschrijving=omschrijving,
        aantal=Decimal("12"),
        eenheid="m2",
        datum_uitgevoerd=date(2026, 9, 28),
    )


@pytest.fixture
def vier_statussen(administratie_id, project_id, tweede_project_id, melder, kantoor_met_recht):  # noqa: ANN001
    """Op het project één melding per status (in deze volgorde gemeld), plus één melding op het andere project."""
    a = _meld(administratie_id, project_id, melder, "A gemeld — blijft gemeld")
    b = _meld(administratie_id, project_id, melder, "B goedgekeurd")
    service.keur_meerwerk_goed(
        administratie_id=administratie_id,
        meerwerk_id=b.id,
        actor_id=kantoor_met_recht,
        prijs_per_eenheid=Decimal("9.20"),
        bedrag=Decimal("110.40"),
    )
    c = _meld(administratie_id, project_id, melder, "C doorbelast")
    service.keur_meerwerk_goed(
        administratie_id=administratie_id,
        meerwerk_id=c.id,
        actor_id=kantoor_met_recht,
        prijs_per_eenheid=Decimal("9.20"),
        bedrag=Decimal("110.40"),
    )
    service.markeer_doorbelast(
        administratie_id=administratie_id,
        meerwerk_id=c.id,
        actor_id=kantoor_met_recht,
        verkoopfactuur_referentie="VF-26149-3",
    )
    d = _meld(administratie_id, project_id, melder, "D afgewezen")
    service.wijs_meerwerk_af(
        administratie_id=administratie_id, meerwerk_id=d.id, actor_id=kantoor_met_recht, reden="eigen rekening"
    )
    ander = _meld(administratie_id, tweede_project_id, melder, "E op het andere project")
    return {"a": a, "b": b, "c": c, "d": d, "ander": ander}


class TestMeerwerkPerProject:
    def test_route_filtert_op_project_alle_statussen_nieuwste_bovenaan(
        self, administratie_id, project_id, tweede_project_id, kantoor_met_recht, vier_statussen
    ):
        headers = _bearer(kantoor_met_recht, rol="boekhouding")
        resp = client.get(
            "/uren/kantoor/meerwerk",
            params={"administratie_id": str(administratie_id), "project_id": str(project_id)},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        rijen = resp.json()
        # Álle vier statussen, alleen dit project, nieuwste (laatst gemeld) bovenaan.
        assert [r["omschrijving"] for r in rijen] == [
            "D afgewezen",
            "C doorbelast",
            "B goedgekeurd",
            "A gemeld — blijft gemeld",
        ]
        assert [r["status"] for r in rijen] == ["afgewezen", "doorbelast", "goedgekeurd", "gemeld"]
        assert {r["project_id"] for r in rijen} == {str(project_id)}
        assert rijen[1]["verkoopfactuur_referentie"] == "VF-26149-3"
        assert rijen[0]["afwijs_reden"] == "eigen rekening"
        # Zelfde DTO als de ongefilterde lijst (Beoordelen › Meerwerk): dezelfde sleutels, dezelfde rijen erin.
        alles = client.get(
            "/uren/kantoor/meerwerk", params={"administratie_id": str(administratie_id)}, headers=headers
        )
        assert alles.status_code == 200 and len(alles.json()) == 5
        assert set(alles.json()[0].keys()) == set(rijen[0].keys())
        assert {r["id"] for r in rijen} <= {r["id"] for r in alles.json()}
        # Het andere project toont alleen zijn eigen melding.
        ander = client.get(
            "/uren/kantoor/meerwerk",
            params={"administratie_id": str(administratie_id), "project_id": str(tweede_project_id)},
            headers=headers,
        )
        assert [r["omschrijving"] for r in ander.json()] == ["E op het andere project"]

    def test_onbekend_project_is_een_lege_lijst_geen_fout(self, administratie_id, kantoor_met_recht, vier_statussen):
        resp = client.get(
            "/uren/kantoor/meerwerk",
            params={"administratie_id": str(administratie_id), "project_id": str(uuid.uuid4())},
            headers=_bearer(kantoor_met_recht, rol="boekhouding"),
        )
        assert resp.status_code == 200 and resp.json() == []

    def test_recht_en_scope_blijven_de_poort(
        self, admin_engine: Engine, administratie_id, project_id, beheerder_id, vier_statussen
    ):
        """Zonder module-recht 403; mét recht maar zonder scope 403 — ook mét project_id (geen scope = geen data)."""
        zonder_recht = maak_gebruiker(admin_engine, "boekhouding", "Zonder recht")
        auth_service.voeg_scope_toe(
            actor_id=beheerder_id, doel_gebruiker_id=zonder_recht, administratie_id=administratie_id
        )
        resp = client.get(
            "/uren/kantoor/meerwerk",
            params={"administratie_id": str(administratie_id), "project_id": str(project_id)},
            headers=_bearer(zonder_recht, rol="boekhouding"),
        )
        assert resp.status_code == 403
        zonder_scope = maak_gebruiker(admin_engine, "boekhouding", "Zonder scope")
        service.zet_meerwerk_recht(gebruiker_id=zonder_scope, ingeschakeld=True, actor_id=beheerder_id)
        resp = client.get(
            "/uren/kantoor/meerwerk",
            params={"administratie_id": str(administratie_id), "project_id": str(project_id)},
            headers=_bearer(zonder_scope, rol="boekhouding"),
        )
        assert resp.status_code == 403

    def test_service_filter_is_dezelfde_lijst(self, administratie_id, project_id, kantoor_met_recht, vier_statussen):
        alles = service.meerwerk_lijst(administratie_id=administratie_id, actor_id=kantoor_met_recht)
        per_project = service.meerwerk_lijst(
            administratie_id=administratie_id, actor_id=kantoor_met_recht, project_id=project_id
        )
        assert [m.id for m in per_project] == [m.id for m in alles if m.project_id == project_id]
