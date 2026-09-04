# ruff: noqa: F811 — pytest-fixtures als parameters (patroon tests/odoo/test_verkoop_uitstroom.py)
"""Odoo-adapter blok E (03-09, migratie 0104) — de Beheerder-endpoints achter de kantoor-UI:

- rolpoorten: 401 zonder token, 403 voor een klant-accordeur MÉT scope, 404 zonder koppeling;
- `POST /administraties/{id}/odoo/overstap` (ingang B, volledige backend): probe groen → 201, backend 'odoo',
  sentinel in `rlz_admin_id`, oud RLZ-id bewaard, RLZ-credential blijft staan, audit `odoo_overstap`, koppeling
  mét overgangsdatum, eerste sync als zichtbare run; probe rood → 422 mét rapport en NIETS opgeslagen;
  al-Odoo / alleen-lezen-koppeling / company elders gekoppeld / gearchiveerd → 422 leesbaar;
- `PUT …/odoo/overgangsdatum`: audit oud→nieuw, alleen-lezen → 422;
- `GET …/odoo`: stamgegevens-tellers (niet-verdwenen cache-rijen), probe-rapport, jongste sync-tijd;
- `GET /instellingen/administraties` draagt de additieve odoo_*-velden;
- eerste-sync-herstart vanuit de gedeelde UI-component draait voor een Odoo-administratie synchroon.
Probe + stamgegevenssync gemonkeypatcht — geen netwerk, geen Odoo-writes."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service as auth_service
from app.auth import voorwaarden
from app.backends.port import BackendBoekFout
from app.db.models import Grootboekrekening, RlzCredential
from app.db.session import scoped_session
from app.main import app
from app.odoo import mapping as odoo_mapping
from app.odoo import service as odoo_service
from app.odoo import sync as odoo_sync
from app.odoo.credentials import OdooVerbinding
from app.odoo.ids import odoo_admin_sentinel
from app.odoo.inkoop import OdooInkoopPort
from app.odoo.models import OdooKoppeling
from app.odoo.probe import ProbeUitkomst
from app.security.envelope import wrap_secret
from app.security.tokens import create_access_token
from app.sync.models import ProjectCache, TaxRateCache, VendorCache
from app.sync.service import SyncResultaat, SyncTelling
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import gescoopte_gebruiker  # noqa: F401
from tests.uren.conftest import maak_gebruiker

client = TestClient(app)

URL = "https://universal-steigers.odoo.com/"
COMPANY = 1
OVERGANG = date(2026, 9, 1)
KEY = "GEHEIM-SLEUTEL-123456"


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _groene_probe(**overrides: Any) -> ProbeUitkomst:
    return ProbeUitkomst(
        rapport={
            "verbinding": "ok",
            "company": "ok",
            "account.move:write": "ok",
            "journal_purchase": "ok",
            "lock_dates": "fiscalyear 2025-12-31",
        },
        company_naam="Universal Steigerbouw",
        journal_purchase_id=7,
        journal_general_id=8,
        journal_sale_id=9,
        analytic_plan_id=2,
        versie="19.0+e",
        **overrides,
    )


def _rode_probe() -> ProbeUitkomst:
    return ProbeUitkomst(
        rapport={"verbinding": "ok", "company": "ok", "account.move:write": "geen schrijfrecht op account.move"},
        company_naam="Universal Steigerbouw",
    )


@pytest.fixture
def probe_groen(monkeypatch: pytest.MonkeyPatch) -> ProbeUitkomst:
    """Groene probe + (blok A 04-09) een lege live Odoo-stamgegevenslijst voor de mapping-validatie — de
    mapping-tests in tests/odoo/test_mapping.py overschrijven `lees_live_odoo_stamgegevens` mét inhoud."""
    p = _groene_probe()
    monkeypatch.setattr(odoo_service, "probe_voor", lambda **kw: p)
    monkeypatch.setattr(odoo_mapping, "lees_live_odoo_stamgegevens", lambda **kw: ([], []))
    return p


@pytest.fixture
def sync_gefaked(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """De Odoo-stamgegevenssync (netwerk) vervangen door een vaste telling — de run-rij wordt wél geschreven."""
    aanroepen: list[uuid.UUID] = []

    def fake(*, administratie_id: uuid.UUID, client=None, actor_id=None) -> SyncResultaat:
        aanroepen.append(administratie_id)
        t = SyncTelling(aangemaakt=3, bijgewerkt=0, verdwenen=0)
        return SyncResultaat(ledgers=t, taxrates=t, vendors=t, projects=t)

    monkeypatch.setattr(odoo_sync, "sync_alles_voor_odoo_administratie", fake)
    return aanroepen


@pytest.fixture
def accordeur_met_scope(admin_engine: Engine, beheerder_id, administratie_id) -> uuid.UUID:
    gid = maak_gebruiker(admin_engine, "klant_accordeur", "Accordeur A.")
    auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=gid, administratie_id=administratie_id)
    voorwaarden.leg_akkoord_vast(gebruiker_id=gid)
    return gid


@pytest.fixture
def rlz_credential(administratie_id, beheerder_id) -> uuid.UUID:
    """Een RLZ-webservice-login in de store — moet ná de overstap blijven staan (nooit verwijderen)."""
    ciphertext, wrapped = wrap_secret(b"rlz-wachtwoord")
    with scoped_session(None, actor_id=beheerder_id) as session:
        session.add(
            RlzCredential(
                administratie_id=administratie_id,
                webservice_username="ws-universal",
                wachtwoord_ciphertext=ciphertext,
                wrapped_data_key=wrapped,
                aangemaakt_door=beheerder_id,
            )
        )
    return administratie_id


def _overstap(aid: uuid.UUID, beheerder: uuid.UUID, **body: Any):
    payload = {"odoo_url": URL, "api_key": KEY, "api_gebruiker": "n-module", "company_id": COMPANY}
    payload["overgangsdatum"] = OVERGANG.isoformat()
    payload["mapping"] = {"grootboek": [], "btw": []}  # lege administratie: niets in gebruik (blok A 04-09)
    payload.update(body)
    return client.post(
        f"/administraties/{aid}/odoo/overstap", json=payload, headers=_bearer(beheerder, rol="beheerder")
    )


def _administratie(admin_engine: Engine, aid: uuid.UUID) -> tuple[str, str]:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT boekhoud_backend, rlz_admin_id FROM platform.administratie WHERE id = :id"), {"id": aid}
        ).one()


def _koppeling(aid: uuid.UUID) -> OdooKoppeling | None:
    with scoped_session(None) as session:
        rij = session.get(OdooKoppeling, aid)
        if rij is not None:
            session.expunge(rij)
        return rij


def _leesbron(monkeypatch: pytest.MonkeyPatch, aid: uuid.UUID, beheerder: uuid.UUID) -> None:
    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

    monkeypatch.setattr(odoo_service, "_client", lambda url, key, cid: _Ctx())
    monkeypatch.setattr(odoo_service, "voer_leesprobe_uit", lambda c: _groene_probe())
    odoo_service.koppel_leesbron(
        actor_id=beheerder,
        administratie_id=aid,
        odoo_url=URL,
        api_key=KEY,
        company_id=3,
        voorraad_knip_datum=date(2026, 8, 1),
    )


class TestRolpoorten:
    def test_zonder_token_401(self, administratie_id) -> None:
        assert client.get(f"/administraties/{administratie_id}/odoo").status_code == 401
        assert client.post(f"/administraties/{administratie_id}/odoo/overstap", json={}).status_code == 401
        assert client.put(f"/administraties/{administratie_id}/odoo/overgangsdatum", json={}).status_code == 401

    def test_klant_accordeur_met_scope_403(self, administratie_id, accordeur_met_scope) -> None:
        h = _bearer(accordeur_met_scope, rol="klant_accordeur")
        assert client.get(f"/administraties/{administratie_id}/odoo", headers=h).status_code == 403
        r = client.post(
            f"/administraties/{administratie_id}/odoo/overstap",
            json={"odoo_url": URL, "api_key": KEY, "company_id": 1, "overgangsdatum": "2026-09-01"},
            headers=h,
        )
        assert r.status_code == 403
        r = client.put(
            f"/administraties/{administratie_id}/odoo/overgangsdatum", json={"overgangsdatum": "2026-09-01"}, headers=h
        )
        assert r.status_code == 403

    def test_boekhouder_zonder_beheerdersrol_403(self, administratie_id, gescoopte_gebruiker) -> None:
        h = _bearer(gescoopte_gebruiker, rol="boekhouding")
        assert client.get(f"/administraties/{administratie_id}/odoo", headers=h).status_code == 403

    def test_zonder_koppeling_404(self, administratie_id, beheerder_id) -> None:
        r = client.get(f"/administraties/{administratie_id}/odoo", headers=_bearer(beheerder_id, rol="beheerder"))
        assert r.status_code == 404 and "Geen Odoo-koppeling" in r.text


class TestOverstap:
    def test_groen_zet_backend_sentinel_koppeling_audit_en_sync(
        self, administratie_id, beheerder_id, rlz_credential, probe_groen, sync_gefaked, admin_engine: Engine
    ) -> None:
        backend_voor, oud_rlz_id = _administratie(admin_engine, administratie_id)
        assert backend_voor == "rlz"

        r = _overstap(administratie_id, beheerder_id)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["id"] == str(administratie_id) and body["company_id"] == COMPANY
        assert body["probe"] == probe_groen.rapport
        assert body["sync_run_id"] is not None
        assert body["sync"]["ledgers"] == {"status": "ok", "aangemaakt": 3, "bijgewerkt": 0, "verdwenen": 0}
        assert sync_gefaked == [administratie_id]
        assert KEY not in r.text  # nooit de sleutel

        # Administratie: backend + sentinel; het oude RLZ-id bewaard op de koppeling.
        backend, rlz_admin_id = _administratie(admin_engine, administratie_id)
        assert backend == "odoo" and rlz_admin_id == odoo_admin_sentinel(URL, COMPANY)
        rij = _koppeling(administratie_id)
        assert rij is not None
        assert rij.overgangsdatum == OVERGANG and rij.rlz_admin_id_voor_overstap == oud_rlz_id
        assert rij.alleen_lezen is False and rij.company_id == COMPANY and rij.journal_purchase_id == 7
        assert rij.company_naam == "Universal Steigerbouw" and rij.api_gebruiker == "n-module"

        # De RLZ-credential-rij blijft staan (via het sentinel onbereikbaar, nooit verwijderd).
        with admin_engine.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT count(*) FROM platform.rlz_credential WHERE administratie_id = :id"),
                    {"id": administratie_id},
                ).scalar_one()
                == 1
            )
            audit = conn.execute(
                text(
                    "SELECT oude_waarde::text, nieuwe_waarde::text FROM platform.audit_event "
                    "WHERE actie = 'odoo_overstap' AND record_id = :id"
                ),
                {"id": administratie_id},
            ).one()
        assert '"boekhoud_backend": "rlz"' in audit[0] and oud_rlz_id in audit[0]
        assert '"boekhoud_backend": "odoo"' in audit[1] and OVERGANG.isoformat() in audit[1]
        assert KEY not in audit[1]

        # Stand-endpoint draagt overgangsdatum, oud id, probe-rapport en stamgegevens-tellers.
        stand = client.get(f"/administraties/{administratie_id}/odoo", headers=_bearer(beheerder_id, rol="beheerder"))
        assert stand.status_code == 200, stand.text
        s = stand.json()
        assert s["overgangsdatum"] == OVERGANG.isoformat() and s["rlz_admin_id_voor_overstap"] == oud_rlz_id
        assert s["probe_rapport"] == probe_groen.rapport and s["probe_groen"] is True
        assert s["stamgegevens"] == {"ledgers": 0, "taxrates": 0, "vendors": 0, "projects": 0}
        assert s["alleen_lezen"] is False and s["company_naam"] == "Universal Steigerbouw"

        # Administraties-lijst: additieve odoo_*-velden.
        lijst = client.get("/instellingen/administraties", headers=_bearer(beheerder_id, rol="beheerder"))
        assert lijst.status_code == 200
        rij_dto = next(a for a in lijst.json()["administraties"] if a["id"] == str(administratie_id))
        assert rij_dto["boekhoud_backend"] == "odoo" and rij_dto["odoo_overgangsdatum"] == OVERGANG.isoformat()
        assert rij_dto["odoo_url"] == URL.rstrip("/") and rij_dto["odoo_alleen_lezen"] is False
        assert rij_dto["odoo_probe_op"] is not None and rij_dto["odoo_voorraad_knip_datum"] is None
        assert rij_dto["eerste_sync"]["status"] == "klaar"

        # Tweede overstap = leesbaar 422 (boekt al in Odoo).
        r2 = _overstap(administratie_id, beheerder_id)
        assert r2.status_code == 422 and "boekt al in Odoo" in r2.text

    def test_probe_rood_slaat_niets_op(
        self, administratie_id, beheerder_id, monkeypatch: pytest.MonkeyPatch, admin_engine: Engine
    ) -> None:
        monkeypatch.setattr(odoo_service, "probe_voor", lambda **kw: _rode_probe())
        backend_voor, rlz_id_voor = _administratie(admin_engine, administratie_id)
        r = _overstap(administratie_id, beheerder_id)
        assert r.status_code == 422, r.text
        detail = r.json()["detail"]
        assert "niets opgeslagen" in detail["bericht"] and "geen schrijfrecht" in detail["bericht"]
        assert detail["rapport"]["account.move:write"].startswith("geen schrijfrecht")
        assert _administratie(admin_engine, administratie_id) == (backend_voor, rlz_id_voor)
        assert _koppeling(administratie_id) is None
        with admin_engine.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT count(*) FROM platform.audit_event WHERE actie = 'odoo_overstap' AND record_id = :id"),
                    {"id": administratie_id},
                ).scalar_one()
                == 0
            )

    def test_alleen_lezen_koppeling_aanwezig_422(
        self, administratie_id, beheerder_id, probe_groen, monkeypatch: pytest.MonkeyPatch, admin_engine: Engine
    ) -> None:
        _leesbron(monkeypatch, administratie_id, beheerder_id)
        r = _overstap(administratie_id, beheerder_id)
        assert r.status_code == 422 and "alleen-lezen Odoo-koppeling" in r.text
        assert _administratie(admin_engine, administratie_id)[0] == "rlz"
        assert _koppeling(administratie_id).alleen_lezen is True  # ongewijzigd

    def test_company_al_elders_gekoppeld_422(
        self, administratie_id, beheerder_id, probe_groen, sync_gefaked, admin_engine: Engine
    ) -> None:
        assert _overstap(administratie_id, beheerder_id).status_code == 201
        andere = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Tweede', :rlz)"),
                {"id": andere, "rlz": f"rlz-{andere}"},
            )
        r = _overstap(andere, beheerder_id)
        assert r.status_code == 422 and "al gekoppeld aan een andere administratie" in r.text
        assert _administratie(admin_engine, andere) == ("rlz", f"rlz-{andere}")

    def test_gearchiveerde_administratie_422(self, administratie_id, beheerder_id, probe_groen, admin_engine) -> None:
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET actief = false, gearchiveerd_op = now() WHERE id = :id"),
                {"id": administratie_id},
            )
        r = _overstap(administratie_id, beheerder_id)
        assert r.status_code == 422 and "gearchiveerd" in r.text
        assert _koppeling(administratie_id) is None

    def test_invoer_zonder_overgangsdatum_422(self, administratie_id, beheerder_id, probe_groen) -> None:
        r = client.post(
            f"/administraties/{administratie_id}/odoo/overstap",
            json={"odoo_url": URL, "api_key": KEY, "company_id": COMPANY},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert r.status_code == 422
        assert _koppeling(administratie_id) is None

    def test_eerste_sync_herstart_draait_synchroon_voor_odoo(
        self, administratie_id, beheerder_id, probe_groen, sync_gefaked
    ) -> None:
        assert _overstap(administratie_id, beheerder_id).status_code == 201
        r = client.post(
            f"/instellingen/administraties/{administratie_id}/eerste-sync",
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert r.status_code == 202, r.text
        assert r.json()["status"] == "klaar" and r.json()["onderdelen"]["vendors"]["aangemaakt"] == 3
        assert sync_gefaked == [administratie_id, administratie_id]  # overstap + herstart
        status = client.get(
            f"/instellingen/administraties/{administratie_id}/eerste-sync/status",
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert status.status_code == 200 and status.json()["status"] == "klaar"


class TestOvergangsdatum:
    def test_wijzigen_met_audit_oud_naar_nieuw(
        self, administratie_id, beheerder_id, probe_groen, sync_gefaked, admin_engine: Engine
    ) -> None:
        assert _overstap(administratie_id, beheerder_id).status_code == 201
        r = client.put(
            f"/administraties/{administratie_id}/odoo/overgangsdatum",
            json={"overgangsdatum": "2026-10-01"},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert r.status_code == 200, r.text
        assert r.json()["overgangsdatum"] == "2026-10-01" and r.json()["company_id"] == COMPANY
        assert _koppeling(administratie_id).overgangsdatum == date(2026, 10, 1)
        with admin_engine.connect() as conn:
            rij = conn.execute(
                text(
                    "SELECT oude_waarde::text, nieuwe_waarde::text FROM platform.audit_event "
                    "WHERE actie = 'odoo_overgangsdatum_gewijzigd' AND record_id = :id"
                ),
                {"id": administratie_id},
            ).one()
        assert "2026-09-01" in rij[0] and "2026-10-01" in rij[1]

    def test_alleen_lezen_koppeling_422(self, administratie_id, beheerder_id, monkeypatch) -> None:
        _leesbron(monkeypatch, administratie_id, beheerder_id)
        r = client.put(
            f"/administraties/{administratie_id}/odoo/overgangsdatum",
            json={"overgangsdatum": "2026-10-01"},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert r.status_code == 422 and "voorraad-knip" in r.text
        assert _koppeling(administratie_id).overgangsdatum is None

    def test_zonder_koppeling_422(self, administratie_id, beheerder_id) -> None:
        r = client.put(
            f"/administraties/{administratie_id}/odoo/overgangsdatum",
            json={"overgangsdatum": "2026-10-01"},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert r.status_code == 422 and "geen Odoo-koppeling" in r.text

    def test_lege_body_422(self, administratie_id, beheerder_id, probe_groen, sync_gefaked) -> None:
        assert _overstap(administratie_id, beheerder_id).status_code == 201
        r = client.put(
            f"/administraties/{administratie_id}/odoo/overgangsdatum",
            json={},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert r.status_code == 422


class TestStand:
    def test_stamgegevens_tellers_en_sync_tijd(
        self, administratie_id, beheerder_id, probe_groen, sync_gefaked, gescoopte_gebruiker
    ) -> None:
        assert _overstap(administratie_id, beheerder_id).status_code == 201
        nu = datetime.now(UTC)
        with scoped_session(administratie_id) as session:
            session.add(
                Grootboekrekening(
                    ledger_id=uuid.uuid4(),
                    administratie_id=administratie_id,
                    code="4000",
                    naam="Kosten",
                    soort=2,
                    is_totaalrekening=False,
                )
            )
            session.add(
                Grootboekrekening(
                    ledger_id=uuid.uuid4(),
                    administratie_id=administratie_id,
                    code="4001",
                    naam="Verdwenen",
                    soort=2,
                    is_totaalrekening=False,
                    verdwenen_uit_bron_op=nu,
                )
            )
            for _ in range(2):
                session.add(TaxRateCache(id=uuid.uuid4(), administratie_id=administratie_id, naam="21%", brondata={}))
            for _ in range(3):
                session.add(VendorCache(id=uuid.uuid4(), administratie_id=administratie_id, naam="V", brondata={}))
            session.add(
                ProjectCache(
                    id=uuid.uuid4(),
                    administratie_id=administratie_id,
                    naam="P",
                    brondata={},
                    verdwenen_uit_bron_op=nu,
                )
            )
        r = client.get(f"/administraties/{administratie_id}/odoo", headers=_bearer(beheerder_id, rol="beheerder"))
        assert r.status_code == 200, r.text
        assert r.json()["stamgegevens"] == {"ledgers": 1, "taxrates": 2, "vendors": 3, "projects": 0}
        assert r.json()["laatste_sync_op"] is not None
        # De lijst leest de stand zonder de tellers (lichtgewicht) maar mét dezelfde sync-tijd-bron.
        stand = odoo_service.koppelstand([administratie_id], met_details=False)[administratie_id]
        assert stand.stamgegevens is None and stand.laatste_sync_op is None and stand.overgangsdatum == OVERGANG


class TestAdapterPoort:
    def test_factuurdatum_voor_overgangsdatum_wordt_leesbaar_geweigerd(self) -> None:
        verbinding = OdooVerbinding(
            administratie_id=uuid.uuid4(),
            odoo_url=URL,
            company_id=COMPANY,
            company_naam="Universal Steigerbouw",
            journal_purchase_id=7,
            journal_general_id=8,
            journal_sale_id=9,
            analytic_plan_id=2,
            overgangsdatum=OVERGANG,
        )
        port = OdooInkoopPort(verbinding.administratie_id, verbinding, client=object())  # type: ignore[arg-type]
        with pytest.raises(BackendBoekFout, match="hoort nog in Reeleezee"):
            port._toets_overgangsdatum(date(2026, 8, 31))
        port._toets_overgangsdatum(OVERGANG)  # op de dag zelf mag
        # Zonder overgangsdatum (bestaande koppelingen) geen poort.
        zonder = OdooVerbinding(
            administratie_id=verbinding.administratie_id,
            odoo_url=URL,
            company_id=COMPANY,
            company_naam=None,
            journal_purchase_id=7,
            journal_general_id=None,
            journal_sale_id=None,
            analytic_plan_id=None,
        )
        OdooInkoopPort(zonder.administratie_id, zonder, client=object())._toets_overgangsdatum(  # type: ignore[arg-type]
            date(2020, 1, 1)
        )


class TestKoppelenSentinelConflict:
    """Live keten-cyclus 04-09: een (gearchiveerde) administratie die het sentinel-`rlz_admin_id` van een company
    nog draagt zónder koppeling-rij liet `POST /instellingen/odoo/koppelen` stranden op een UniqueViolation (500).
    Het sentinel is uniek — de wizard moet dat vooraf zien: leesbare 422, niets opgeslagen."""

    def test_sentinel_zonder_koppeling_geeft_422_en_slaat_niets_op(
        self, administratie_id, beheerder_id, probe_groen, sync_gefaked, admin_engine: Engine
    ) -> None:
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET rlz_admin_id = :s, actief = false WHERE id = :id"),
                {"s": odoo_admin_sentinel(URL, COMPANY), "id": administratie_id},
            )
        r = client.post(
            "/instellingen/odoo/koppelen",
            json={"odoo_url": URL, "api_key": KEY, "api_gebruiker": "n-module", "company_ids": [COMPANY]},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert r.status_code == 422, r.text
        assert "al gekoppeld" in r.json()["detail"]["bericht"] and "dearchiveer" in r.json()["detail"]["bericht"]
        assert sync_gefaked == []
        with scoped_session(None) as session:
            assert session.scalars(select_koppelingen_voor(COMPANY)).all() == []

    def test_verbinding_testen_markeert_sentinel_company_als_al_gekoppeld(
        self, administratie_id, beheerder_id, monkeypatch: pytest.MonkeyPatch, admin_engine: Engine
    ) -> None:
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET rlz_admin_id = :s WHERE id = :id"),
                {"s": odoo_admin_sentinel(URL, COMPANY), "id": administratie_id},
            )

        class _Client:
            def __init__(self, **kw: Any) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a: object) -> None:
                pass

            def versie(self) -> dict:
                return {"server_version": "19.0+e"}

        monkeypatch.setattr(odoo_service, "OdooClient", _Client)
        companies = [{"id": COMPANY, "naam": "Universal"}, {"id": 3, "naam": "Verkoop"}]
        monkeypatch.setattr(odoo_service, "lees_companies", lambda c: companies)
        r = client.post(
            "/instellingen/odoo/verbinding-testen",
            json={"odoo_url": URL, "api_key": KEY},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert r.status_code == 200, r.text
        stand = {c["company_id"]: c["al_gekoppeld"] for c in r.json()["companies"]}
        assert stand == {COMPANY: True, 3: False}


def select_koppelingen_voor(company_id: int):
    from sqlalchemy import select

    return select(OdooKoppeling).where(OdooKoppeling.company_id == company_id)
