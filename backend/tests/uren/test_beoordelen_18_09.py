"""BUG 18-09 — chip "N meerwerk/urenstaten te beoordelen" landde op een lege Meerwerk-pagina (0/0/0/0): de N waren
ingediende weekstaten, de pagina toonde alleen meerwerk. Fix: één landingsplek "Beoordelen" mét tabs Urenstaten (N)
en Meerwerk (M) uit dezelfde definities als de teller (guard: chip == som van de tabs), kantoor-keuring als vangnet,
en — besluit Peter 18-09, letterlijk: "uitvoerder moet gewoon alle ingediende urenstaten controleren, los van welk
project hij gepland staat" — de uitvoerder-keurlijst zonder projectkoppeling (guard: nieuw account zonder koppelingen
ziet alles)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service as auth_service
from app.auth import voorwaarden
from app.main import app
from app.security.tokens import create_access_token
from app.uren import overzichten, service
from tests.uren.conftest import maak_gebruiker, maak_project

client = TestClient(app)

JAAR, WEEK = 2026, 34
MA, DI = date(2026, 8, 17), date(2026, 8, 18)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _met_scope(gebruiker_id, administratie_id, beheerder_id):  # noqa: ANN001
    auth_service.voeg_scope_toe(
        actor_id=beheerder_id, doel_gebruiker_id=gebruiker_id, administratie_id=administratie_id
    )
    voorwaarden.leg_akkoord_vast(gebruiker_id=gebruiker_id)
    return gebruiker_id


def _ingediend(administratie_id, wie, project_id, *, datum=MA, uren="8"):  # noqa: ANN001
    service.zet_dag(
        administratie_id=administratie_id,
        zzper_id=wie,
        project_id=project_id,
        jaar=JAAR,
        weeknummer=WEEK,
        datum=datum,
        uren=Decimal(uren),
        actor_id=wie,
    )
    return service.dien_week_in(
        administratie_id=administratie_id, zzper_id=wie, project_id=project_id, jaar=JAAR, weeknummer=WEEK, actor_id=wie
    )


def _meld(administratie_id, project_id, wie):  # noqa: ANN001
    return service.meld_meerwerk(
        administratie_id=administratie_id,
        project_id=project_id,
        actor_id=wie,
        omschrijving="Extra trapsteiger achterzijde",
        aantal=Decimal("12"),
        eenheid="m2",
        datum_uitgevoerd=MA,
    )


@pytest.fixture
def zzper_met_scope(zzper, administratie_id, beheerder_id):  # noqa: ANN001
    return _met_scope(zzper, administratie_id, beheerder_id)


@pytest.fixture
def uitvoerder_met_scope(uitvoerder, administratie_id, beheerder_id):  # noqa: ANN001
    return _met_scope(uitvoerder, administratie_id, beheerder_id)


@pytest.fixture
def kantoor_met_recht(admin_engine: Engine, administratie_id, beheerder_id):  # noqa: ANN001
    medewerker = maak_gebruiker(admin_engine, "boekhouding", "Rob T.")
    auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=medewerker, administratie_id=administratie_id)
    service.zet_meerwerk_recht(actor_id=beheerder_id, gebruiker_id=medewerker, ingeschakeld=True)
    return medewerker


class TestUitvoerderKeurtAllesInScope:
    def test_guard_nieuw_uitvoerder_account_zonder_koppelingen_ziet_alle_ingediende_staten(
        self, admin_engine, administratie_id, project_id, tweede_project_id, zzper_met_scope, uitvoerder_met_scope
    ):
        """Guard-test opdracht: geen enkele `uren_project_toewijzing` voor de uitvoerder — toch álle ingediende
        staten van de administratie in zijn keurlijst, behalve de eigen."""
        wie = uitvoerder_met_scope
        with admin_engine.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT count(*) FROM boekhouding.uren_project_toewijzing WHERE gebruiker_id = :id"),
                    {"id": wie},
                ).scalar_one()
                == 0
            )
        s1 = _ingediend(administratie_id, zzper_met_scope, project_id)
        s2 = _ingediend(administratie_id, zzper_met_scope, tweede_project_id, datum=DI, uren="4")
        eigen = _ingediend(administratie_id, wie, project_id, datum=DI, uren="6")  # eigen staat: nooit in de lijst
        items = overzichten.te_keuren(uitvoerder_id=wie)
        assert {i.weekstaat_id for i in items} == {s1.id, s2.id}
        assert eigen.id not in {i.weekstaat_id for i in items}
        resp = client.get("/uren/uitvoerder/te-keuren", headers=_bearer(wie, rol="uitvoerder"))
        assert resp.status_code == 200 and len(resp.json()) == 2

    def test_keuren_zonder_koppeling_mag_eigen_staat_niet(
        self, administratie_id, project_id, zzper_met_scope, uitvoerder_met_scope
    ):
        wie = uitvoerder_met_scope
        staat = _ingediend(administratie_id, zzper_met_scope, project_id)
        goed = service.keur_week_goed(administratie_id=administratie_id, weekstaat_id=staat.id, actor_id=wie)
        assert goed.status == "goedgekeurd" and goed.goedgekeurd_door_naam == "Ben v. Dijk"
        eigen = _ingediend(administratie_id, wie, project_id, datum=DI)
        with pytest.raises(service.GeenToegang, match="eigen weekstaat"):
            service.keur_week_goed(administratie_id=administratie_id, weekstaat_id=eigen.id, actor_id=wie)

    def test_buiten_scope_blijft_dicht(self, admin_engine, administratie_id, project_id, zzper_met_scope, uitvoerder):
        """Scope + opt-in blijven de poort: een uitvoerder ZONDER scope op de administratie ziet en keurt niets."""
        voorwaarden.leg_akkoord_vast(gebruiker_id=uitvoerder)
        staat = _ingediend(administratie_id, zzper_met_scope, project_id)
        assert overzichten.te_keuren(uitvoerder_id=uitvoerder) == []
        with pytest.raises(service.UrenFout):
            service.keur_week_goed(administratie_id=administratie_id, weekstaat_id=staat.id, actor_id=uitvoerder)


class TestBeoordelenKantoor:
    def test_guard_chip_teller_is_som_van_de_tabs(
        self,
        admin_engine,
        administratie_id,
        project_id,
        tweede_project_id,
        zzper_met_scope,
        uitvoerder_met_scope,
        kantoor_met_recht,
    ):
        """De chip "N urenstaten · M meerwerk te beoordelen" leest `uren_stand`; de tabs lezen `kantoor_weekstaten` en
        `meerwerk_lijst`. Guard: N == len(tab Urenstaten), M == len(tab Meerwerk › te beoordelen) — nooit uit de
        pas."""
        _ingediend(administratie_id, zzper_met_scope, project_id)
        _ingediend(administratie_id, zzper_met_scope, tweede_project_id, datum=DI)
        _ingediend(
            administratie_id, uitvoerder_met_scope, project_id, datum=DI
        )  # ook de eigen staat van een uitvoerder
        _meld(administratie_id, project_id, uitvoerder_met_scope)
        stand = service.uren_stand(administratie_id=administratie_id, actor_id=kantoor_met_recht)
        weekstaten = overzichten.kantoor_weekstaten(administratie_id=administratie_id, actor_id=kantoor_met_recht)
        meerwerk = [
            m
            for m in service.meerwerk_lijst(administratie_id=administratie_id, actor_id=kantoor_met_recht)
            if m.status == "gemeld"
        ]
        assert stand.urenstaten_wachten_op_keuring == len(weekstaten.items) == 3
        assert stand.meerwerk_te_beoordelen == len(meerwerk) == 1
        assert weekstaten.laatste_keuring_op is None  # nog nooit gekeurd → lege stand zegt dat

    def test_kantoor_keurt_goed_en_af_via_de_api_met_audit_keurder_kantoor(
        self, admin_engine, administratie_id, project_id, tweede_project_id, zzper_met_scope, kantoor_met_recht
    ):
        s1 = _ingediend(administratie_id, zzper_met_scope, project_id)
        s2 = _ingediend(administratie_id, zzper_met_scope, tweede_project_id, datum=DI)
        headers = _bearer(kantoor_met_recht, rol="boekhouding")
        resp = client.get(
            "/uren/kantoor/weekstaten", params={"administratie_id": str(administratie_id)}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        assert {i["weekstaat_id"] for i in resp.json()["items"]} == {str(s1.id), str(s2.id)}
        assert resp.json()["laatste_keuring_op"] is None

        resp = client.post(f"/uren/kantoor/weekstaten/{administratie_id}/{s1.id}/goedkeuren", headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "goedgekeurd" and resp.json()["goedgekeurd_door_naam"] == "Rob T."
        resp = client.post(
            f"/uren/kantoor/weekstaten/{administratie_id}/{s2.id}/afkeuren", json={"reden": ""}, headers=headers
        )
        assert resp.status_code == 422  # reden verplicht
        resp = client.post(
            f"/uren/kantoor/weekstaten/{administratie_id}/{s2.id}/afkeuren",
            json={"reden": "Dinsdag was een vrije dag — graag corrigeren"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "corrigeren"

        resp = client.get(
            "/uren/kantoor/weekstaten", params={"administratie_id": str(administratie_id)}, headers=headers
        )
        assert resp.json()["items"] == [] and resp.json()["laatste_keuring_op"] is not None
        with admin_engine.connect() as conn:
            keurders = (
                conn.execute(
                    text(
                        "SELECT nieuwe_waarde->>'keurder' FROM platform.audit_event "
                        "WHERE actie = 'weekstaat_goedgekeurd' AND record_id = :id"
                    ),
                    {"id": s1.id},
                )
                .scalars()
                .all()
            )
        assert keurders == ["kantoor"]

    def test_zonder_module_recht_403(self, admin_engine, administratie_id, project_id, zzper_met_scope, beheerder_id):
        zonder = maak_gebruiker(admin_engine, "boekhouding", "Zonder R.")
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=zonder, administratie_id=administratie_id)
        staat = _ingediend(administratie_id, zzper_met_scope, project_id)
        headers = _bearer(zonder, rol="boekhouding")
        assert (
            client.get(
                "/uren/kantoor/weekstaten", params={"administratie_id": str(administratie_id)}, headers=headers
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/uren/kantoor/weekstaten/{administratie_id}/{staat.id}/goedkeuren", headers=headers
            ).status_code
            == 403
        )
        # Een veldrol komt nooit op de kantoor-route.
        assert (
            client.get(
                "/uren/kantoor/weekstaten",
                params={"administratie_id": str(administratie_id)},
                headers=_bearer(zzper_met_scope, rol="zzper"),
            ).status_code
            == 403
        )

    def test_uitvoerder_keurlijst_en_kantoor_tab_delen_de_definitie(
        self, admin_engine, administratie_id, project_id, zzper_met_scope, uitvoerder_met_scope, kantoor_met_recht
    ):
        derde = maak_project(admin_engine, administratie_id, "26030 Venlo (Dura)")
        _ingediend(administratie_id, zzper_met_scope, project_id)
        _ingediend(administratie_id, zzper_met_scope, derde, datum=DI)
        kantoor = overzichten.kantoor_weekstaten(administratie_id=administratie_id, actor_id=kantoor_met_recht).items
        uitv = overzichten.te_keuren(uitvoerder_id=uitvoerder_met_scope)
        assert [i.weekstaat_id for i in kantoor] == [i.weekstaat_id for i in uitv]
        assert [i.project_naam for i in kantoor] == ["26014 Eindhoven (BAM)", "26030 Venlo (Dura)"]
