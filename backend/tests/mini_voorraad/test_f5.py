# ruff: noqa: F811
"""Blok F 06-09 — F5: de mini-voorraad als virtuele artikelgroep in de voorraad-aansluiting (bron 'mini_voorraad',
geen telling, signaal 'informatief') en de read-only materiaallijst voor planning/transport."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.beheer import service as beheer_service
from app.documenten import boeken
from app.main import app
from app.mini_voorraad import service
from app.security.tokens import create_access_token
from app.voorraad import service as voorraad_service
from tests.mini_voorraad.conftest import maak_document, regel

client = TestClient(app)
pytestmark = pytest.mark.usefixtures("_opslag_naar_tmp")


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


@pytest.fixture
def stand_24_min_4(
    mini_voorraad_aan, fake_client, administratie_id, gescoopte_gebruiker, opslag, actief_project
) -> uuid.UUID:
    doc = maak_document(
        administratie_id=administratie_id,
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
        regels=[regel("Stapelbok 1,25×0,85", "24", "560140.4"), regel("AR-40 gaffel", "12")],
    )
    boeken.boek_document(administratie_id=administratie_id, document_id=doc, actor_id=gescoopte_gebruiker)
    lijst = service.producten(administratie_id=administratie_id, actor_id=gescoopte_gebruiker)
    stapelbok = next(p for p in lijst.items if p.omschrijving == "Stapelbok 1,25×0,85")
    service.meld_beschadiging(
        administratie_id=administratie_id,
        actor_id=gescoopte_gebruiker,
        product_id=stapelbok.id,
        aantal="4",
        project_id=actief_project,
        datum=date(2026, 7, 2),
        toelichting=None,
    )
    return doc


class TestVoorraadAansluiting:
    def test_virtuele_groep_in_aansluiting(self, stand_24_min_4, administratie_id, beheerder_id) -> None:
        beheer_service.zet_voorraad_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        a = voorraad_service.aansluiting(administratie_id=administratie_id, van=date(2026, 7, 1), tot=date(2026, 7, 31))
        [groep] = [g for g in a.groepen if g.bron == "mini_voorraad"]
        assert groep.naam == "Speciale producten (mini-voorraad)"
        assert groep.artikelgroep_id == service.virtuele_groep_id(administratie_id)
        assert (groep.begin, groep.inkoop, groep.verkoop, groep.theoretisch) == (
            Decimal("0.000"),
            Decimal("36.000"),
            Decimal("4.000"),
            Decimal("32.000"),
        )
        assert groep.systeemstand is None and groep.telling_datum is None and groep.signaal == "informatief"
        assert groep.regels_in == 2 and groep.regels_uit == 1
        assert "mini_voorraad" in a.bronnen
        # Periode ná de mutaties: alles in `begin`.
        b = voorraad_service.aansluiting(administratie_id=administratie_id, van=date(2026, 8, 1), tot=date(2026, 8, 31))
        [groep_b] = [g for g in b.groepen if g.bron == "mini_voorraad"]
        assert (groep_b.begin, groep_b.inkoop, groep_b.verkoop, groep_b.theoretisch) == (
            Decimal("32.000"),
            Decimal("0.000"),
            Decimal("0.000"),
            Decimal("32.000"),
        )
        # Echte groepen dragen bron 'artikelgroep' (default) — additief.
        assert all(g.bron == "artikelgroep" for g in a.groepen if g is not groep)

    def test_zonder_mini_opt_in_geen_virtuele_groep(self, administratie_id, beheerder_id) -> None:
        beheer_service.zet_voorraad_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        a = voorraad_service.aansluiting(administratie_id=administratie_id, van=date(2026, 7, 1), tot=date(2026, 7, 31))
        assert [g for g in a.groepen if g.bron == "mini_voorraad"] == []

    def test_aansluiting_dto_draagt_bron(self, stand_24_min_4, administratie_id, beheerder_id) -> None:
        beheer_service.zet_voorraad_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        resp = client.get(
            f"/administraties/{administratie_id}/voorraad/aansluiting?van=2026-07-01&tot=2026-07-31",
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 200, resp.text
        [groep] = [g for g in resp.json()["groepen"] if g["bron"] == "mini_voorraad"]
        assert groep["signaal"] == "informatief" and groep["systeemstand"] is None and groep["theoretisch"] == "32.000"


class TestMateriaallijst:
    def test_materiaallijst_levert_alleen_stand_boven_nul(
        self, stand_24_min_4, administratie_id, gescoopte_gebruiker, actief_project
    ) -> None:
        h = _bearer(gescoopte_gebruiker, rol="boekhouding")
        resp = client.get(f"/mini-voorraad/{administratie_id}/materiaallijst", headers=h)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["categorie"] == "Speciale producten (mini-voorraad)"
        assert [(i["naam"], i["mini_voorraad_stand"], i["eenheid"]) for i in body["items"]] == [
            ("AR-40 gaffel", "12", "st"),
            ("Stapelbok 1,25×0,85", "20", "st"),
        ]
        # Weergavenaam wint in de lijst; stand 0 valt eruit.
        lijst = service.producten(administratie_id=administratie_id, actor_id=gescoopte_gebruiker)
        gaffel = next(p for p in lijst.items if p.omschrijving == "AR-40 gaffel")
        service.bevestig_naam(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            product_id=gaffel.id,
            weergavenaam="Gaffel AR-40",
        )
        service.meld_beschadiging(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            product_id=gaffel.id,
            aantal="12",
            project_id=actief_project,
            datum=date(2026, 7, 3),
            toelichting="volledig afgeschreven",
        )
        body = client.get(f"/mini-voorraad/{administratie_id}/materiaallijst", headers=h).json()
        assert [i["naam"] for i in body["items"]] == ["Stapelbok 1,25×0,85"]
