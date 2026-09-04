# ruff: noqa: F811 — pytest-fixtures als parameters (patroon tests/odoo)
"""Materiaalcatalogus losgekoppeld van de uren-&-meerwerk-opt-in (Odoo-afrondingsrun 04-09 blok B, besluit Peter):
de CATALOGUS (leveranciers, categorieën, producten, seed) is open zodra een administratie de uren-opt-in ÓF een
Odoo-backend ÓF een Odoo-leesbron-koppeling heeft; bestellingen, transport, materiaalstand blijven uren-gated.
RLZ zonder beide: 409 mét de leesbare reden. `mijn-toegang` levert `administraties_met_catalogus` náást de
ongewijzigde `administraties_met_opt_in`. Echte niet-Beheerder MÉT scope voor het RLS-pad (les 25-08).

Rolpoort catalogus (Odoo-slotstuk C2, besluit Peter 04-09 — sloot beslispunt 2 van blok B): de drie LEESROUTES
(`/leveranciers`, `/leveranciers/{lid}/catalogus`, `/producten`) dragen dezelfde poort als de PUT-kant —
Beheerder óf B+P (`require_beheerder_of_bp` in de router + `_vereis_beheerder` in de motor), zónder het
module-recht 'Meerwerk & urenstaten'; Boekhouding mét dat recht krijgt 403, B+P zónder dat recht 200."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service as auth_service
from app.db.session import scoped_session
from app.main import app
from app.materiaal import service as materiaal
from app.odoo.models import OdooKoppeling
from app.security.envelope import wrap_secret
from app.security.tokens import create_access_token
from app.uren import service as uren_service
from tests.auth.conftest import beheerder_id  # noqa: F401
from tests.uren.conftest import administratie_id, administratie_zonder_opt_in, maak_gebruiker  # noqa: F401

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _administratie(admin_engine: Engine, *, naam: str, backend: str) -> uuid.UUID:
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.administratie (id, naam, rlz_admin_id, boekhoud_backend) "
                "VALUES (:id, :naam, :rlz, :backend)"
            ),
            {"id": aid, "naam": naam, "rlz": f"rlz-{aid}", "backend": backend},
        )
    return aid


def _odoo_koppeling(aid: uuid.UUID, actor_id: uuid.UUID, *, alleen_lezen: bool) -> None:
    ciphertext, wrapped = wrap_secret(b"sleutel")
    with scoped_session(None, actor_id=actor_id) as session:
        session.add(
            OdooKoppeling(
                administratie_id=aid,
                odoo_url="https://universal-steigers.odoo.com",
                company_id=3 if alleen_lezen else 1,
                company_naam="Universal Verkoop" if alleen_lezen else "Universal Steigerbouw",
                api_key_ciphertext=ciphertext,
                wrapped_data_key=wrapped,
                alleen_lezen=alleen_lezen,
                aangemaakt_door=actor_id,
            )
        )


@pytest.fixture
def administratie_odoo(admin_engine: Engine, beheerder_id: uuid.UUID) -> uuid.UUID:
    """Odoo-backend, GEEN uren-opt-in (de live-keten-casus van 04-09 stap 5)."""
    aid = _administratie(admin_engine, naam="Odoo zonder uren (test)", backend="odoo")
    _odoo_koppeling(aid, beheerder_id, alleen_lezen=False)
    return aid


@pytest.fixture
def administratie_leesbron(admin_engine: Engine, beheerder_id: uuid.UUID) -> uuid.UUID:
    """RLZ-administratie mét alleen-lezen Odoo-koppeling (Universal Verkoop-patroon), geen uren-opt-in."""
    aid = _administratie(admin_engine, naam="Leesbron zonder uren (test)", backend="rlz")
    _odoo_koppeling(aid, beheerder_id, alleen_lezen=True)
    return aid


class TestCatalogusPoort:
    @pytest.mark.parametrize("fixture_naam", ["administratie_odoo", "administratie_leesbron"])
    def test_odoo_of_leesbron_zonder_uren_optin_catalogus_open_steigerbouw_dicht(
        self, request, fixture_naam, beheerder_id, admin_engine
    ):
        aid = request.getfixturevalue(fixture_naam)
        r = materiaal.seed_universal(administratie_id=aid, actor_id=beheerder_id)
        assert r.producten_nieuw == 53 and r.categorieen_nieuw == 13
        levs = materiaal.leveranciers_overzicht(administratie_id=aid, actor_id=beheerder_id)
        assert len(levs) == 1 and levs[0].aantal_producten == 53
        cats = materiaal.catalogus(administratie_id=aid, leverancier_id=r.leverancier_id, actor_id=beheerder_id)
        assert len(cats) == 13
        _, totaal = materiaal.producten_overzicht(
            administratie_id=aid, actor_id=beheerder_id, leverancier_id=None, zoek="tubelock", pagina=1, per_pagina=3
        )
        assert totaal == 8
        lid = materiaal.zet_leverancier(
            administratie_id=aid,
            actor_id=beheerder_id,
            leverancier_id=None,
            naam="Floor Liften",
            bestel_email=None,
            telefoon=None,
            adres=None,
            vendor_id=None,
        )
        cid = materiaal.zet_categorie(
            administratie_id=aid,
            actor_id=beheerder_id,
            leverancier_id=lid,
            categorie_id=None,
            naam="Liften",
            bundel="overig",
            volgorde=1,
        )
        materiaal.zet_product(
            administratie_id=aid,
            actor_id=beheerder_id,
            leverancier_id=lid,
            product_id=None,
            categorie_id=cid,
            naam="Bouwlift 500 kg",
            verpakking="st.",
            eenheid="stuks",
            m2_lengte=None,
            volgorde=1,
        )
        # De steigerbouw-tak blijft dicht — met de BESTAANDE uren-reden.
        with pytest.raises(uren_service.ModuleUitgeschakeld, match="Uren & meerwerk is niet ingeschakeld"):
            materiaal.bestellingen_overzicht(administratie_id=aid, actor_id=beheerder_id)
        with pytest.raises(uren_service.ModuleUitgeschakeld):
            materiaal.maak_bestelling(
                administratie_id=aid, actor_id=beheerder_id, project_id=uuid.uuid4(), leverancier_id=lid
            )
        with pytest.raises(uren_service.ModuleUitgeschakeld):
            materiaal.transport_week(administratie_id=aid, actor_id=beheerder_id, jaar=2026, weeknummer=36)
        with pytest.raises(uren_service.ModuleUitgeschakeld):
            materiaal.materiaalstand(administratie_id=aid, project_id=uuid.uuid4(), actor_id=beheerder_id)
        # API-laag: catalogus 200, steigerbouw 409.
        h = _bearer(beheerder_id, rol="beheerder")
        assert client.get(f"/materiaal/{aid}/leveranciers", headers=h).status_code == 200
        assert client.get(f"/materiaal/{aid}/producten?zoek=ladder", headers=h).status_code == 200
        assert client.post(f"/materiaal/{aid}/seed-universal", headers=h).status_code == 200
        assert client.get(f"/materiaal/{aid}/bestellingen", headers=h).status_code == 409
        resp = client.post(
            f"/materiaal/{aid}/bestellingen",
            json={"project_id": str(uuid.uuid4()), "leverancier_id": str(lid)},
            headers=h,
        )
        assert resp.status_code == 409
        assert client.get(f"/materiaal/{aid}/transport?jaar=2026&weeknummer=36", headers=h).status_code == 409

    def test_rlz_zonder_uren_en_zonder_odoo_blijft_409_met_leesbare_reden(
        self, administratie_zonder_opt_in, beheerder_id
    ):
        aid = administratie_zonder_opt_in
        with pytest.raises(uren_service.ModuleUitgeschakeld, match="Uren & meerwerk óf een Odoo-koppeling"):
            materiaal.leveranciers_overzicht(administratie_id=aid, actor_id=beheerder_id)
        with pytest.raises(uren_service.ModuleUitgeschakeld):
            materiaal.seed_universal(administratie_id=aid, actor_id=beheerder_id)
        with pytest.raises(uren_service.ModuleUitgeschakeld):
            materiaal.zet_leverancier(
                administratie_id=aid,
                actor_id=beheerder_id,
                leverancier_id=None,
                naam="X",
                bestel_email=None,
                telefoon=None,
                adres=None,
                vendor_id=None,
            )
        resp = client.get(f"/materiaal/{aid}/leveranciers", headers=_bearer(beheerder_id, rol="beheerder"))
        assert resp.status_code == 409 and resp.json()["detail"] == materiaal.CATALOGUS_VEREIST_TEKST

    def test_onbekende_administratie_blijft_404(self, beheerder_id):
        with pytest.raises(uren_service.NietGevonden):
            materiaal.leveranciers_overzicht(administratie_id=uuid.uuid4(), actor_id=beheerder_id)

    def test_uren_optin_administratie_ongewijzigd(self, administratie_id, beheerder_id):
        r = materiaal.seed_universal(administratie_id=administratie_id, actor_id=beheerder_id)
        assert r.producten_nieuw == 53
        assert len(materiaal.leveranciers_overzicht(administratie_id=administratie_id, actor_id=beheerder_id)) == 1
        items, totaal = materiaal.bestellingen_overzicht(administratie_id=administratie_id, actor_id=beheerder_id)
        assert (items, totaal) == ([], 0)

    def test_catalogus_lezen_is_beheerder_of_bp_boekhouding_met_meerwerk_recht_403(
        self, administratie_odoo, beheerder_id, admin_engine
    ):
        """Besluit Peter 04-09 (C2): lezen = schrijven. Boekhouding MÉT scope én mét het module-recht 'Meerwerk &
        urenstaten' krijgt op de drie leesroutes 403 (router én motor) — precies zoals op de PUT-kant."""
        aid = administratie_odoo
        boekhouder = maak_gebruiker(admin_engine, "boekhouding", "Rob T.")
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=boekhouder, administratie_id=aid)
        uren_service.zet_meerwerk_recht(gebruiker_id=boekhouder, ingeschakeld=True, actor_id=beheerder_id)
        lid = materiaal.seed_universal(administratie_id=aid, actor_id=beheerder_id).leverancier_id
        with pytest.raises(uren_service.GeenToegang):
            materiaal.leveranciers_overzicht(administratie_id=aid, actor_id=boekhouder)
        with pytest.raises(uren_service.GeenToegang):
            materiaal.catalogus(administratie_id=aid, leverancier_id=lid, actor_id=boekhouder)
        with pytest.raises(uren_service.GeenToegang):
            materiaal.producten_overzicht(
                administratie_id=aid, actor_id=boekhouder, leverancier_id=None, zoek="", pagina=1, per_pagina=5
            )
        h = _bearer(boekhouder, rol="boekhouding")
        assert client.get(f"/materiaal/{aid}/leveranciers", headers=h).status_code == 403
        assert client.get(f"/materiaal/{aid}/leveranciers/{lid}/catalogus", headers=h).status_code == 403
        assert client.get(f"/materiaal/{aid}/producten?zoek=ladder", headers=h).status_code == 403
        assert client.put(f"/materiaal/{aid}/leveranciers", json={"naam": "X"}, headers=h).status_code == 403

    def test_bp_zonder_meerwerk_recht_met_scope_leest_en_schrijft_catalogus(
        self, administratie_odoo, beheerder_id, admin_engine
    ):
        """De asymmetrie van vóór 04-09 (B+P zónder meerwerk-recht kon producten zetten maar de lijst niet lezen)
        is weg: B+P MÉT scope, ZONDER module-recht leest de drie routes (RLS-pad, echte niet-Beheerder) én schrijft.
        Zonder scope blijft alles 403 — de administratie-scope is geen rolpoort maar blijft wél gelden."""
        aid = administratie_odoo
        bp = maak_gebruiker(admin_engine, "boekhouding_projecten", "Haci Y.")
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=bp, administratie_id=aid)
        assert not uren_service.heeft_meerwerk_urenstaten_recht(gebruiker_id=bp, rol="boekhouding_projecten")
        lid = materiaal.seed_universal(administratie_id=aid, actor_id=beheerder_id).leverancier_id
        levs = materiaal.leveranciers_overzicht(administratie_id=aid, actor_id=bp)
        assert len(levs) == 1 and levs[0].aantal_producten == 53
        assert len(materiaal.catalogus(administratie_id=aid, leverancier_id=lid, actor_id=bp)) == 13
        _, totaal = materiaal.producten_overzicht(
            administratie_id=aid, actor_id=bp, leverancier_id=None, zoek="tubelock", pagina=1, per_pagina=3
        )
        assert totaal == 8
        h = _bearer(bp, rol="boekhouding_projecten")
        assert client.get(f"/materiaal/{aid}/leveranciers", headers=h).status_code == 200
        assert client.get(f"/materiaal/{aid}/leveranciers/{lid}/catalogus", headers=h).status_code == 200
        resp = client.get(f"/materiaal/{aid}/producten?zoek=ladder&per_pagina=10", headers=h)
        assert resp.status_code == 200 and resp.json()["totaal"] == 2
        assert client.put(f"/materiaal/{aid}/leveranciers", json={"naam": "Floor Liften"}, headers=h).status_code == 200
        # Zonder scope: B+P op een andere administratie → 403 (scope-poort blijft náást de rolpoort).
        bp_zonder_scope = maak_gebruiker(admin_engine, "boekhouding_projecten", "Zonder scope")
        h2 = _bearer(bp_zonder_scope, rol="boekhouding_projecten")
        assert client.get(f"/materiaal/{aid}/leveranciers", headers=h2).status_code == 403
        assert client.get(f"/materiaal/{aid}/producten", headers=h2).status_code == 403


class TestMijnToegang:
    def test_administraties_met_catalogus_dekt_odoo_en_leesbron_opt_in_lijst_ongewijzigd(
        self, administratie_id, administratie_odoo, administratie_leesbron, administratie_zonder_opt_in, beheerder_id
    ):
        resp = client.get("/uren/kantoor/mijn-toegang", headers=_bearer(beheerder_id, rol="beheerder"))
        assert resp.status_code == 200
        body = resp.json()
        cat, opt = set(body["administraties_met_catalogus"]), set(body["administraties_met_opt_in"])
        assert {str(administratie_id), str(administratie_odoo), str(administratie_leesbron)} <= cat
        assert str(administratie_zonder_opt_in) not in cat
        assert str(administratie_id) in opt
        assert str(administratie_odoo) not in opt and str(administratie_leesbron) not in opt

    def test_niet_beheerder_ziet_alleen_de_eigen_scope(
        self, administratie_id, administratie_odoo, beheerder_id, admin_engine
    ):
        bp = maak_gebruiker(admin_engine, "boekhouding_projecten", "Haci Y.")
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=bp, administratie_id=administratie_odoo)
        resp = client.get("/uren/kantoor/mijn-toegang", headers=_bearer(bp, rol="boekhouding_projecten"))
        assert resp.status_code == 200
        body = resp.json()
        assert body["administraties_met_catalogus"] == [str(administratie_odoo)]
        assert body["administraties_met_opt_in"] == []
        assert body["is_beheerder_of_bp"] is True

    def test_pure_helper_zonder_koppeltabel_query_bij_lege_rest(
        self, administratie_id, administratie_odoo, beheerder_id
    ):
        with scoped_session(None, actor_id=beheerder_id) as session:
            from app.db.models import Administratie

            rijen = [session.get(Administratie, administratie_id), session.get(Administratie, administratie_odoo)]
            session.expunge_all()
        assert set(materiaal.administraties_met_catalogus_toegang(rijen)) == {administratie_id, administratie_odoo}
        assert materiaal.administraties_met_catalogus_toegang([]) == []
