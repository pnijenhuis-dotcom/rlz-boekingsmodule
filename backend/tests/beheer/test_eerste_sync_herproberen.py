"""Eerste sync ná groene probe: 403 = herproberen (blok 3 run 11-09 middag; bevinding Peter Baard / Box Beheer /
Kempen B.V.: probe groen 11:5x, sync 403 direct erna, RLZ-check groen de volgende ochtend).

Gedrag: een 403 op een route die de opgeslagen rechten-probe groen had → status `rechten_onderweg` + automatisch
herproberen (5, 15, 60 min, daarna elk uur, max 24 u) via de wekker in de kwartier-job; pas daarna `fout` mét het
letterlijke RLZ-antwoord. Een 403 op een niet-groene route, een 401 of een andere fout blijft direct `fout`."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.beheer import eerste_sync, onboarding
from app.bewaking import service as bewaking_service
from app.main import app
from app.rlz.client import RlzApiError
from app.security.tokens import create_access_token
from tests.beheer.conftest import Klok
from tests.sync.conftest import FakeRlzClient

client = TestClient(app)
ADMIN_A = "11111111-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
BODY = '{"Message":"Actie niet toegestaan bij huidige gebruikersrechten","ExceptionMessage":null}'
PROBE_ROUTES = (
    "Ledgers",
    "TaxRates",
    "Vendors",
    "Customers",
    "Projects",
    "SalesInvoices",
    "PurchaseInvoices",
    "JournalEntries",
    "PaymentAccounts",
)


def _rlz_data() -> dict[str, list[dict[str, Any]]]:
    data: dict[str, list[dict[str, Any]]] = {"Administrations": [{"id": ADMIN_A, "Name": "Baard beheer & management"}]}
    for endpoint in PROBE_ROUTES:
        data[endpoint] = []
    return data


def _403(pad: str) -> RlzApiError:
    return RlzApiError(403, "GET", f"/{ADMIN_A}/{pad}", BODY)


class ReeksClient(FakeRlzClient):
    """Per pad een reeks antwoorden: een Exception wordt geworpen, None = gewoon antwoord (bv. 403 → 403 → 200)."""

    def __init__(self, reeks: dict[str, list[Exception | None]]) -> None:
        super().__init__({p: [] for p in PROBE_ROUTES})
        self._reeks = reeks
        self.list_payment_accounts = lambda: []  # type: ignore[method-assign]

    def get(self, path: str) -> dict[str, Any]:
        self.opgevraagde_paden.append(path)
        reeks = self._reeks.get(path)
        if reeks:
            volgende = reeks.pop(0)
            if volgende is not None:
                raise volgende
        return {"value": self._data.get(path, [])}


@pytest.fixture
def geen_voertuig(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(eerste_sync, "_start_voertuig", lambda administratie_id: None)


@pytest.fixture
def nieuwe_administratie(beheerder_id: uuid.UUID, klok: Klok) -> uuid.UUID:
    """Aangesloten via de wizard mét groene probe (10/10) — exact de Baard-situatie vóór de eerste sync."""
    [nieuw] = onboarding.maak_administraties_aan(
        actor_id=beheerder_id,
        webservice_username="ws",
        wachtwoord="geheim",
        rlz_admin_ids=[ADMIN_A],
        client=FakeRlzClient(_rlz_data()),
        start_sync=False,
    )
    return nieuw.id


def _audit_acties(admin_engine: Engine, run_id: uuid.UUID) -> list[tuple[str, dict]]:
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text(
                "SELECT actie, nieuwe_waarde FROM platform.audit_event WHERE tabel = 'administratie_sync_run' "
                "AND record_id = :id ORDER BY tijdstip, actie"
            ),
            {"id": run_id},
        ).all()
    return [(r[0], r[1]) for r in rijen]


def _bearer(gebruiker_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol='beheerder')}"}


class TestPuur:
    def test_intervallen_5_15_60_daarna_elk_uur(self) -> None:
        assert [eerste_sync.herprobeer_interval(n) for n in (1, 2, 3, 4, 9)] == [
            timedelta(minutes=5),
            timedelta(minutes=15),
            timedelta(minutes=60),
            timedelta(minutes=60),
            timedelta(minutes=60),
        ]
        assert timedelta(hours=24) == eerste_sync.HERPROBEER_MAX

    def test_is_herprobeerbaar_alleen_403_op_probe_groene_routes(self) -> None:
        groen = {r: "ok" for r in ("Administrations", *PROBE_ROUTES)}
        f403 = eerste_sync._fout_stand("ledgers", _403("Ledgers"))
        klaar = {"status": "klaar"}
        assert eerste_sync.is_herprobeerbaar({"ledgers": f403, "taxrates": klaar}, groen) is True
        # route die de probe óók rood had → direct fout
        assert eerste_sync.is_herprobeerbaar({"ledgers": f403}, {**groen, "Ledgers": "403"}) is False
        # geen probe-rapport → direct fout
        assert eerste_sync.is_herprobeerbaar({"ledgers": f403}, None) is False
        # 401 = login zelf geweigerd → direct fout
        f401 = eerste_sync._fout_stand("vendors", RlzApiError(401, "GET", "/x/Vendors", "Unauthorized"))
        assert eerste_sync.is_herprobeerbaar({"vendors": f401}, groen) is False
        # één herprobeerbaar + één andere fout → direct fout (de andere fout is echt)
        f500 = eerste_sync._fout_stand("vendors", RlzApiError(500, "GET", "/x/Vendors", "boom"))
        assert eerste_sync.is_herprobeerbaar({"ledgers": f403, "vendors": f500}, groen) is False
        assert eerste_sync.is_herprobeerbaar({"ledgers": klaar}, groen) is False  # niets mislukt


class TestHerproberen:
    def test_403_403_200_reeks_wordt_groen_via_de_wekker(
        self,
        nieuwe_administratie: uuid.UUID,
        beheerder_id: uuid.UUID,
        klok: Klok,
        geen_voertuig: None,
        monkeypatch: pytest.MonkeyPatch,
        admin_engine: Engine,
    ) -> None:
        aid = nieuwe_administratie
        run = eerste_sync.start_run(administratie_id=aid, actor_id=beheerder_id)
        sync_client = ReeksClient({"Ledgers": [_403("Ledgers"), _403("Ledgers"), None]})
        monkeypatch.setattr("app.rlz.credentials.client_voor_rlz_admin_id", lambda rlz_admin_id: sync_client)

        # poging 1: Ledgers 403 op een probe-groene route → rechten onderweg, opnieuw over 5 min
        assert eerste_sync.verwerk_wachtrij_voor(aid) == 1
        info = eerste_sync.laatste_run(aid)
        assert info.run_id == run.run_id
        assert info.status == "rechten_onderweg"
        assert info.pogingen == 1
        assert info.volgende_poging_op == klok.nu + timedelta(minutes=5)
        assert info.beeindigd_op is None and info.fout_reden is None
        ledgers = info.onderdelen["ledgers"]
        assert ledgers["status"] == "rechten_onderweg" and ledgers["http_status"] == 403
        assert ledgers["rlz_melding"] == BODY  # letterlijk RLZ-antwoord blijft zichtbaar (tooltip)
        assert ledgers["rlz_recht"].startswith("leesrecht Grootboek")
        assert info.onderdelen["taxrates"]["status"] == "klaar"
        assert info.onderdelen["payment_accounts"]["status"] == "klaar"

        # de status-DTO draagt pogingen + volgende_poging_op (frontend-chip "opnieuw over N min")
        resp = client.get(f"/instellingen/administraties/{aid}/eerste-sync/status", headers=_bearer(beheerder_id))
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "rechten_onderweg" and resp.json()["pogingen"] == 1
        assert resp.json()["volgende_poging_op"] is not None

        # wekker vóór het tijdstip: niets
        assert eerste_sync.herprobeer_vervallen(klok.nu) == 0
        assert eerste_sync.laatste_run(aid).status == "rechten_onderweg"

        # +5 min: wekker zet 'm terug in de wachtrij; poging 2 = alleen Ledgers opnieuw (de rest was al klaar)
        klok.verzet(minutes=5)
        assert eerste_sync.herprobeer_vervallen(klok.nu) == 1
        assert eerste_sync.laatste_run(aid).status == "wachtrij"
        paden_voor = list(sync_client.opgevraagde_paden)
        assert eerste_sync.verwerk_wachtrij_voor(aid) == 1
        nieuw_opgevraagd = sync_client.opgevraagde_paden[len(paden_voor) :]
        assert [p for p in nieuw_opgevraagd if p.endswith("Ledgers")] and not [
            p for p in nieuw_opgevraagd if p.endswith("TaxRates")
        ]
        info = eerste_sync.laatste_run(aid)
        assert info.status == "rechten_onderweg" and info.pogingen == 2
        assert info.volgende_poging_op == klok.nu + timedelta(minutes=15)

        # +15 min: poging 3 → 200 → klaar, zelfde run
        klok.verzet(minutes=15)
        assert eerste_sync.herprobeer_vervallen(klok.nu) == 1
        assert eerste_sync.verwerk_wachtrij_voor(aid) == 1
        info = eerste_sync.laatste_run(aid)
        assert info.run_id == run.run_id
        assert info.status == "klaar" and info.pogingen == 3
        assert info.volgende_poging_op is None and info.beeindigd_op == klok.nu
        assert info.onderdelen["ledgers"]["status"] == "klaar"

        # audit per herpoging (systeem-actor): 2× gepland, 2× gestart door de wekker
        acties = _audit_acties(admin_engine, run.run_id)
        assert [a for a, _ in acties].count("eerste_sync_herpoging_gepland") == 2
        gestart = [nw for a, nw in acties if a == "eerste_sync_herpoging_gestart"]
        assert [nw["aanleiding"] for nw in gestart] == ["wekker", "wekker"]
        assert sorted(nw["poging"] for nw in gestart) == [2, 3]
        gepland = [nw for a, nw in acties if a == "eerste_sync_herpoging_gepland"]
        assert gepland[0]["onderdelen"] == ["ledgers"] and gepland[0]["rlz_melding"] == BODY

    def test_403_op_route_die_de_probe_niet_groen_had_is_direct_fout(
        self,
        nieuwe_administratie: uuid.UUID,
        beheerder_id: uuid.UUID,
        klok: Klok,
        geen_voertuig: None,
        monkeypatch: pytest.MonkeyPatch,
        admin_engine: Engine,
    ) -> None:
        aid = nieuwe_administratie
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE platform.rlz_rechten_probe SET rapport = jsonb_set(rapport, '{Ledgers}', '\"403\"') "
                    "WHERE administratie_id = :id"
                ),
                {"id": aid},
            )
        eerste_sync.start_run(administratie_id=aid, actor_id=beheerder_id)
        sync_client = ReeksClient({"Ledgers": [_403("Ledgers")]})
        monkeypatch.setattr("app.rlz.credentials.client_voor_rlz_admin_id", lambda rlz_admin_id: sync_client)
        assert eerste_sync.verwerk_wachtrij_voor(aid) == 1
        info = eerste_sync.laatste_run(aid)
        assert info.status == "fout" and info.pogingen == 1 and info.volgende_poging_op is None
        assert info.onderdelen["ledgers"]["status"] == "fout"
        assert "LET OP: Reeleezee weigert de opgeslagen webservice-login (HTTP 403) op ledgers" in str(info.fout_reden)
        assert _audit_acties(admin_engine, info.run_id) == []  # geen herpoging gepland

    def test_401_en_andere_fouten_blijven_direct_fout(
        self,
        nieuwe_administratie: uuid.UUID,
        beheerder_id: uuid.UUID,
        klok: Klok,
        geen_voertuig: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        aid = nieuwe_administratie
        eerste_sync.start_run(administratie_id=aid, actor_id=beheerder_id)
        sync_client = ReeksClient(
            {
                "Ledgers": [_403("Ledgers")],
                "Vendors": [RlzApiError(401, "GET", f"/{ADMIN_A}/Vendors", "Unauthorized")],
            }
        )
        monkeypatch.setattr("app.rlz.credentials.client_voor_rlz_admin_id", lambda rlz_admin_id: sync_client)
        assert eerste_sync.verwerk_wachtrij_voor(aid) == 1
        info = eerste_sync.laatste_run(aid)
        assert info.status == "fout"
        assert info.onderdelen["ledgers"]["status"] == "fout" and info.onderdelen["vendors"]["status"] == "fout"

    def test_na_24_uur_nog_403_wordt_fout_met_letterlijk_rlz_antwoord(
        self,
        nieuwe_administratie: uuid.UUID,
        beheerder_id: uuid.UUID,
        klok: Klok,
        geen_voertuig: None,
        monkeypatch: pytest.MonkeyPatch,
        admin_engine: Engine,
    ) -> None:
        aid = nieuwe_administratie
        run = eerste_sync.start_run(administratie_id=aid, actor_id=beheerder_id)
        sync_client = ReeksClient({"Ledgers": [_403("Ledgers")] * 40})
        monkeypatch.setattr("app.rlz.credentials.client_voor_rlz_admin_id", lambda rlz_admin_id: sync_client)
        assert eerste_sync.verwerk_wachtrij_voor(aid) == 1
        # herpogingen doorlopen: 5, 15, 60, dan elk uur — tot ná het venster
        pogingen = 1
        while eerste_sync.laatste_run(aid).status == "rechten_onderweg":
            info = eerste_sync.laatste_run(aid)
            klok.nu = info.volgende_poging_op
            assert eerste_sync.herprobeer_vervallen(klok.nu) == 1
            assert eerste_sync.verwerk_wachtrij_voor(aid) == 1
            pogingen += 1
            assert pogingen < 40, "herproberen stopt nooit — 24-uursgrens werkt niet"
        info = eerste_sync.laatste_run(aid)
        assert info.status == "fout" and info.run_id == run.run_id
        # poging 1 t=0, 2 t=5, 3 t=20, 4 t=80 min, daarna elk uur: poging k op 80+60(k-4) min → ≥ 1440 bij k=27
        assert info.pogingen == pogingen == 27
        assert klok.nu - info.aangevraagd_op >= eerste_sync.HERPROBEER_MAX
        assert info.beeindigd_op == klok.nu and info.volgende_poging_op is None
        verwacht_kop = f"{eerste_sync.OPGEGEVEN_PREFIX} (27 pogingen sinds 11-09-2026 10:00 UTC)"
        assert (info.fout_reden or "").startswith(verwacht_kop)
        assert f'RLZ zegt: "{BODY}"' in info.onderdelen["ledgers"]["fout"]
        assert "LET OP: Reeleezee weigert de opgeslagen webservice-login (HTTP 403) op ledgers" in info.fout_reden
        acties = [a for a, _ in _audit_acties(admin_engine, run.run_id)]
        assert acties.count("eerste_sync_herproberen_opgegeven") == 1
        assert acties.count("eerste_sync_herpoging_gestart") == 26

    def test_sync_opnieuw_starten_op_wachtende_run_probeert_direct_dezelfde_run(
        self,
        nieuwe_administratie: uuid.UUID,
        beheerder_id: uuid.UUID,
        klok: Klok,
        geen_voertuig: None,
        monkeypatch: pytest.MonkeyPatch,
        admin_engine: Engine,
    ) -> None:
        aid = nieuwe_administratie
        run = eerste_sync.start_run(administratie_id=aid, actor_id=beheerder_id)
        sync_client = ReeksClient({"Ledgers": [_403("Ledgers"), None]})
        monkeypatch.setattr("app.rlz.credentials.client_voor_rlz_admin_id", lambda rlz_admin_id: sync_client)
        assert eerste_sync.verwerk_wachtrij_voor(aid) == 1
        assert eerste_sync.laatste_run(aid).status == "rechten_onderweg"
        # "Sync opnieuw starten" (bestaande route) één minuut later: geen nieuwe run, direct in de wachtrij
        klok.verzet(minutes=1)
        resp = client.post(f"/instellingen/administraties/{aid}/eerste-sync", headers=_bearer(beheerder_id))
        assert resp.status_code == 202, resp.text
        assert resp.json()["run_id"] == str(run.run_id) and resp.json()["status"] == "wachtrij"
        assert eerste_sync.verwerk_wachtrij_voor(aid) == 1
        info = eerste_sync.laatste_run(aid)
        assert info.status == "klaar" and info.pogingen == 2 and info.run_id == run.run_id
        gestart = [nw for a, nw in _audit_acties(admin_engine, run.run_id) if a == "eerste_sync_herpoging_gestart"]
        assert [nw["aanleiding"] for nw in gestart] == ["handmatig"]

    def test_wekker_valt_terug_op_in_process_als_het_voertuig_niet_start(
        self,
        nieuwe_administratie: uuid.UUID,
        beheerder_id: uuid.UUID,
        klok: Klok,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        aid = nieuwe_administratie
        monkeypatch.setattr(eerste_sync, "_start_voertuig", lambda administratie_id: None)
        eerste_sync.start_run(administratie_id=aid, actor_id=beheerder_id)
        sync_client = ReeksClient({"Ledgers": [_403("Ledgers"), None]})
        monkeypatch.setattr("app.rlz.credentials.client_voor_rlz_admin_id", lambda rlz_admin_id: sync_client)
        assert eerste_sync.verwerk_wachtrij_voor(aid) == 1
        assert eerste_sync.laatste_run(aid).status == "rechten_onderweg"

        def kapot(administratie_id: uuid.UUID) -> None:
            raise RuntimeError("403 run.invoker ontbreekt")

        monkeypatch.setattr(eerste_sync, "_start_voertuig", kapot)
        klok.verzet(minutes=5)
        assert eerste_sync.herprobeer_vervallen(klok.nu) == 1
        assert eerste_sync.laatste_run(aid).status == "klaar"  # in-process verwerkt — nooit stil blijven hangen

    def test_bewaking_kwartierrun_draagt_de_wekker_als_uitkomst(
        self,
        nieuwe_administratie: uuid.UUID,
        beheerder_id: uuid.UUID,
        klok: Klok,
        geen_voertuig: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        aid = nieuwe_administratie
        eerste_sync.start_run(administratie_id=aid, actor_id=beheerder_id)
        sync_client = ReeksClient({"Ledgers": [_403("Ledgers"), None]})
        monkeypatch.setattr("app.rlz.credentials.client_voor_rlz_admin_id", lambda rlz_admin_id: sync_client)
        assert eerste_sync.verwerk_wachtrij_voor(aid) == 1
        klok.verzet(minutes=6)
        uitkomst = bewaking_service._meet("eerste_sync_wekker", lambda: bewaking_service._wekker_eerste_sync(klok.nu))
        assert uitkomst.status == "ok" and uitkomst.detail == "1 herpoging(en) gestart"
        assert eerste_sync.laatste_run(aid).status == "wachtrij"

        def kapot(nu):  # noqa: ANN001
            raise RuntimeError("db weg")

        monkeypatch.setattr(eerste_sync, "herprobeer_vervallen", kapot)
        fout = bewaking_service._meet("eerste_sync_wekker", lambda: bewaking_service._wekker_eerste_sync(klok.nu))
        assert fout.status == "fout" and "db weg" in (fout.detail or "")  # kapotte wekker = zichtbare bewakingsfout
