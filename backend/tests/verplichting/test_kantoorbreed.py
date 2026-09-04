"""Inzicht › Verplichtingen kantoorbreed (⑦): scope = mijn_administraties, facetten, sortering
(overschreden eerst), paginering en de gekoppelde facturen als uitklap."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.db.models import GebruikerRol
from app.db.session import scoped_session
from app.main import app
from app.security.tokens import create_access_token
from app.verplichting import kantoorbreed
from app.verplichting import service as verplichting_service
from app.verplichting.models import Verplichting
from tests.verplichting.conftest import OFFERTEBEDRAG

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str = "boekhouding") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def zet_verbruik(administratie_id: uuid.UUID, document_id: uuid.UUID, bedrag: str) -> None:
    with scoped_session(administratie_id, actor_id=None) as session:
        rij = session.get(Verplichting, document_id)
        assert rij is not None
        rij.verbruikt_bedrag_excl = Decimal(bedrag)


class TestLijst:
    def test_lopende_verplichting_met_verbruiksstand(
        self, administratie_id, gescoopte_gebruiker, geaccordeerde_offerte
    ):
        zet_verbruik(administratie_id, geaccordeerde_offerte, "27150.00")
        lijst = kantoorbreed.lijst(actor_id=gescoopte_gebruiker, rol=GebruikerRol.BOEKHOUDING)
        assert lijst.totaal == 1
        [rij] = lijst.rijen
        assert rij.status == "lopend"
        assert rij.offertenummer == "26140-OFF-01"
        assert rij.soort_label == "offerte"
        assert rij.leverancier_naam == "Confide Bouw B.V."
        assert rij.project_naam == "26140 Koningstraat (Confide)"
        assert rij.totaal_excl == OFFERTEBEDRAG
        assert rij.verbruikt_excl == Decimal("27150.00")
        assert rij.percentage == 56
        assert rij.over_excl is None
        assert rij.goedgekeurd_door_naam is not None
        assert rij.open_facturen_aantal == 0 and rij.open_facturen_excl == Decimal("0.00")
        assert lijst.tellers.lopend == 1 and lijst.tellers.overschreden == 0

    def test_overschreden_krijgt_het_bedrag_erover(
        self, administratie_id, gescoopte_gebruiker, geaccordeerde_offerte
    ):
        zet_verbruik(administratie_id, geaccordeerde_offerte, "51900.00")
        lijst = kantoorbreed.lijst(
            actor_id=gescoopte_gebruiker, rol=GebruikerRol.BOEKHOUDING, status="overschreden"
        )
        [rij] = lijst.rijen
        assert rij.status == "overschreden"
        assert rij.over_excl == Decimal("3400.00")
        assert rij.percentage == 107
        assert lijst.tellers.overschreden == 1
        # De default-status "lopend" laat 'm dan niet zien (facet = filter).
        default = kantoorbreed.lijst(actor_id=gescoopte_gebruiker, rol=GebruikerRol.BOEKHOUDING)
        assert default.totaal == 0
        assert default.facetten.status["overschreden"] == 1
        assert default.facetten.status["alle"] == 1

    def test_vervallen_verschijnt_onder_het_eigen_facet(
        self, administratie_id, gescoopte_gebruiker, geaccordeerde_offerte
    ):
        verplichting_service.laat_vervallen(
            administratie_id=administratie_id,
            document_id=geaccordeerde_offerte,
            actor_id=gescoopte_gebruiker,
            reden="opdracht ingetrokken",
        )
        lijst = kantoorbreed.lijst(
            actor_id=gescoopte_gebruiker, rol=GebruikerRol.BOEKHOUDING, status="vervallen"
        )
        assert [r.status for r in lijst.rijen] == ["vervallen"]
        assert lijst.tellers.vervallen == 1
        assert kantoorbreed.lijst(actor_id=gescoopte_gebruiker, rol=GebruikerRol.BOEKHOUDING).totaal == 0

    def test_zoekterm_filtert_op_leverancier_en_nummer(
        self, administratie_id, gescoopte_gebruiker, geaccordeerde_offerte
    ):
        assert (
            kantoorbreed.lijst(actor_id=gescoopte_gebruiker, rol=GebruikerRol.BOEKHOUDING, q="confide").totaal == 1
        )
        assert (
            kantoorbreed.lijst(actor_id=gescoopte_gebruiker, rol=GebruikerRol.BOEKHOUDING, q="26140-OFF").totaal == 1
        )
        assert kantoorbreed.lijst(actor_id=gescoopte_gebruiker, rol=GebruikerRol.BOEKHOUDING, q="gnm").totaal == 0

    def test_onbekende_status_is_een_domeinfout(self, gescoopte_gebruiker):
        with pytest.raises(verplichting_service.VerplichtingFout):
            kantoorbreed.lijst(actor_id=gescoopte_gebruiker, rol=GebruikerRol.BOEKHOUDING, status="onzin")

    def test_scope_filtert_administraties_zonder_toegang(
        self, admin_engine: Engine, administratie_id, geaccordeerde_offerte
    ):
        """Een boekhouder ZONDER scope op de administratie ziet niets (RLS + scope-bron)."""
        from tests.uren.conftest import maak_gebruiker

        zonder_scope = maak_gebruiker(admin_engine, "boekhouding", "Zonder Scope")
        lijst = kantoorbreed.lijst(actor_id=zonder_scope, rol=GebruikerRol.BOEKHOUDING)
        assert lijst.totaal == 0


class TestFacturenUitklap:
    def test_gematchte_facturen_reizen_mee(
        self, administratie_id, gescoopte_gebruiker, opslag, geaccordeerde_offerte, project_id
    ):
        from tests.verplichting.test_verbruik import maak_factuur

        maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            project_id=project_id,
            netto="12400.00",
            referentie="CF-2026-777",
        )
        lijst = kantoorbreed.lijst(actor_id=gescoopte_gebruiker, rol=GebruikerRol.BOEKHOUDING)
        [rij] = lijst.rijen
        assert len(rij.facturen) == 1
        [factuur] = rij.facturen
        assert factuur.referentie == "CF-2026-777"
        assert factuur.bedrag_excl == Decimal("12400.00")
        assert factuur.verrekend is False  # nog niet geboekt


class TestRouter:
    def test_endpoint_geeft_de_lijst_met_facetten(
        self, administratie_id, gescoopte_gebruiker, geaccordeerde_offerte
    ):
        resp = client.get("/verplichtingen", headers=_bearer(gescoopte_gebruiker))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["per_pagina"] == 25
        assert body["totaal"] == 1
        assert body["tellers"] == {"lopend": 1, "overschreden": 0, "vervallen": 0}
        assert body["rijen"][0]["offertenummer"] == "26140-OFF-01"
        assert body["administraties_in_selectie"] == 1
        assert len(body["facetten"]["administraties"]) == 1

    def test_onbekend_statusfacet_is_422(self, gescoopte_gebruiker):
        resp = client.get("/verplichtingen?status=onzin", headers=_bearer(gescoopte_gebruiker))
        assert resp.status_code == 422

    def test_administratie_facet_filtert(self, administratie_id, gescoopte_gebruiker, geaccordeerde_offerte):
        resp = client.get(
            f"/verplichtingen?administratie_id={administratie_id}", headers=_bearer(gescoopte_gebruiker)
        )
        assert resp.status_code == 200 and resp.json()["totaal"] == 1
        resp = client.get(f"/verplichtingen?administratie_id={uuid.uuid4()}", headers=_bearer(gescoopte_gebruiker))
        assert resp.status_code == 200 and resp.json()["totaal"] == 0
