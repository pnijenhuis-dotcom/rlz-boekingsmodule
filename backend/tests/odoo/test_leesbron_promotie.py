# ruff: noqa: F811 — pytest-fixtures als parameters (patroon tests/odoo/test_router.py)
"""Leesbron → overstap (besluit Peter 28-09 "nee niet te moeilijk maken nu … RLZ los en Odoo aan"; casus Universal
Verkoop B.V.: RLZ-backend mét alleen-lezen Odoo-koppeling company 3, knip 01-09-2026):

- een bestaande ALLEEN-LEZEN koppeling op dezelfde host én company blokkeert de overstap niet meer maar wordt in
  dezelfde transactie GEPROMOVEERD: `alleen_lezen` false, `overgangsdatum` = kanteldatum, knip blijft, RLZ-id →
  sentinel, oud RLZ-id bewaard, credential-rij blijft, audit `odoo_leesbron_gepromoveerd` oud → nieuw (nooit de
  sleutel), géén tweede koppeling-rij en geen `odoo_koppeling_aangemaakt`;
- andere company of andere host = 422 leesbaar, niets gewijzigd;
- sleutelveld leeg = de bewaarde sleutel wordt hergebruikt (probe draait ermee, ciphertext ongewijzigd, audit
  `sleutel: hergebruikt`); leeg zónder leesbron = 422 "vul de API-sleutel in";
- `overstap/voorbereiden` en `verbinding-testen` werken zonder sleutel op dezelfde poort; de eigen leesbron-company is
  in de verbindingstest kiesbaar (`eigen_leesbron`), andere claims blijven grijs;
- het gewone RLZ-pad (geen koppeling) is ongewijzigd (tests/odoo/test_router.py::TestOverstap blijft de norm).
Probe + sync gemonkeypatcht — geen netwerk, geen Odoo-writes."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pytest
from sqlalchemy import Engine, text

from app.odoo import service as odoo_service
from app.odoo.ids import odoo_admin_sentinel
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.odoo.test_router import (  # noqa: F401
    COMPANY,
    KEY,
    OVERGANG,
    URL,
    _administratie,
    _bearer,
    _groene_probe,
    _koppeling,
    _leesbron,
    _overstap,
    client,
    probe_groen,
    rlz_credential,
    sync_gefaked,
)

LEESBRON_COMPANY = 3  # zie `_leesbron` in test_router: company 3, knip 2026-08-01
KNIP = date(2026, 8, 1)


def _audit(admin_engine: Engine, actie: str, aid: uuid.UUID) -> list[tuple[str | None, str]]:
    with admin_engine.connect() as conn:
        return [
            (r[0], r[1])
            for r in conn.execute(
                text(
                    "SELECT oude_waarde::text, nieuwe_waarde::text FROM platform.audit_event "
                    "WHERE actie = :actie AND record_id = :id ORDER BY tijdstip"
                ),
                {"actie": actie, "id": aid},
            )
        ]


def _koppelingen(admin_engine: Engine, aid: uuid.UUID) -> int:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM platform.odoo_koppeling WHERE administratie_id = :id"), {"id": aid}
        ).scalar_one()


@pytest.fixture
def probe_vangt(monkeypatch: pytest.MonkeyPatch, probe_groen) -> list[dict[str, Any]]:
    """Groene probe (fixture uit test_router) die de aanroep-argumenten vastlegt — bewijs welke sleutel gebruikt is."""
    aanroepen: list[dict[str, Any]] = []

    def fake(**kw: Any):
        aanroepen.append(dict(kw))
        return probe_groen

    monkeypatch.setattr(odoo_service, "probe_voor", fake)
    return aanroepen


class TestPromotie:
    def test_zelfde_host_en_company_promoveert_de_leesbron_in_een_transactie(
        self,
        administratie_id,
        beheerder_id,
        rlz_credential,
        probe_vangt,
        sync_gefaked,
        monkeypatch: pytest.MonkeyPatch,
        admin_engine: Engine,
    ) -> None:
        _leesbron(monkeypatch, administratie_id, beheerder_id)
        _, oud_rlz_id = _administratie(admin_engine, administratie_id)
        voor = _koppeling(administratie_id)
        assert voor is not None and voor.alleen_lezen is True and voor.voorraad_knip_datum == KNIP

        r = _overstap(administratie_id, beheerder_id, company_id=LEESBRON_COMPANY, api_key="NIEUWE-SLEUTEL-987654")
        assert r.status_code == 201, r.text
        assert "NIEUWE-SLEUTEL" not in r.text and KEY not in r.text
        assert probe_vangt[-1]["api_key"] == "NIEUWE-SLEUTEL-987654"

        backend, rlz_admin_id = _administratie(admin_engine, administratie_id)
        assert backend == "odoo" and rlz_admin_id == odoo_admin_sentinel(URL, LEESBRON_COMPANY)
        na = _koppeling(administratie_id)
        assert na is not None
        assert na.alleen_lezen is False and na.overgangsdatum == OVERGANG
        assert na.voorraad_knip_datum == KNIP  # de knip blijft staan
        assert na.rlz_admin_id_voor_overstap == oud_rlz_id and na.company_id == LEESBRON_COMPANY
        assert na.journal_purchase_id == 7 and na.probe_rapport == probe_groen_rapport()
        assert na.api_key_ciphertext != voor.api_key_ciphertext  # sleutel vervangen
        assert _koppelingen(admin_engine, administratie_id) == 1  # zelfde rij, geen tweede

        # Audit: promotie oud → nieuw zonder sleutel; de overstap-audit draagt de promotie-vlag; geen 'aangemaakt'.
        promotie = _audit(admin_engine, "odoo_leesbron_gepromoveerd", administratie_id)
        assert len(promotie) == 1
        oud, nieuw = promotie[0]
        assert oud is not None and '"alleen_lezen": true' in oud and '"voorraad_knip_datum": "2026-08-01"' in oud
        assert '"alleen_lezen": false' in nieuw and OVERGANG.isoformat() in nieuw and '"sleutel": "vervangen"' in nieuw
        assert '"voorraad_knip_datum": "2026-08-01"' in nieuw and oud_rlz_id in nieuw
        assert "NIEUWE-SLEUTEL" not in nieuw and KEY not in nieuw
        overstap = _audit(admin_engine, "odoo_overstap", administratie_id)
        assert len(overstap) == 1 and '"leesbron_gepromoveerd": true' in overstap[0][1]
        assert _audit(admin_engine, "odoo_koppeling_aangemaakt", administratie_id) == []
        assert _audit(admin_engine, "odoo_koppeling_dubbel_geweigerd", administratie_id) == []

        # Credential-rij blijft (nooit verwijderen); sync gestart; stand + lijst tonen de volledige backend.
        with admin_engine.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT count(*) FROM platform.rlz_credential WHERE administratie_id = :id"),
                    {"id": administratie_id},
                ).scalar_one()
                == 1
            )
        assert sync_gefaked == [administratie_id]
        stand = client.get(f"/administraties/{administratie_id}/odoo", headers=_bearer(beheerder_id, rol="beheerder"))
        assert stand.status_code == 200
        s = stand.json()
        assert s["alleen_lezen"] is False and s["overgangsdatum"] == OVERGANG.isoformat()
        assert s["voorraad_knip_datum"] == KNIP.isoformat() and s["rlz_admin_id_voor_overstap"] == oud_rlz_id
        lijst = client.get("/instellingen/administraties", headers=_bearer(beheerder_id, rol="beheerder"))
        rij = next(a for a in lijst.json()["administraties"] if a["id"] == str(administratie_id))
        assert rij["boekhoud_backend"] == "odoo" and rij["odoo_alleen_lezen"] is False
        assert rij["odoo_overgangsdatum"] == OVERGANG.isoformat()

    def test_andere_company_422_niets_gewijzigd(
        self, administratie_id, beheerder_id, probe_vangt, monkeypatch: pytest.MonkeyPatch, admin_engine: Engine
    ) -> None:
        _leesbron(monkeypatch, administratie_id, beheerder_id)
        r = _overstap(administratie_id, beheerder_id, company_id=COMPANY)  # leesbron = company 3, gevraagd 1
        assert r.status_code == 422, r.text
        bericht = r.json()["detail"]["bericht"]
        assert "alleen-lezen Odoo-koppeling" in bericht and "company 3" in bericht and "company 1" in bericht
        assert probe_vangt == []  # geen probe, niets geraakt
        assert _administratie(admin_engine, administratie_id)[0] == "rlz"
        na = _koppeling(administratie_id)
        assert na is not None and na.alleen_lezen is True and na.overgangsdatum is None
        assert _audit(admin_engine, "odoo_leesbron_gepromoveerd", administratie_id) == []

    def test_andere_host_422_niets_gewijzigd(
        self, administratie_id, beheerder_id, probe_vangt, monkeypatch: pytest.MonkeyPatch, admin_engine: Engine
    ) -> None:
        _leesbron(monkeypatch, administratie_id, beheerder_id)
        r = _overstap(
            administratie_id, beheerder_id, company_id=LEESBRON_COMPANY, odoo_url="https://andere-omgeving.odoo.com"
        )
        assert r.status_code == 422, r.text
        assert "universal-steigers.odoo.com company 3" in r.json()["detail"]["bericht"]
        assert probe_vangt == []
        assert _administratie(admin_engine, administratie_id)[0] == "rlz"
        assert _koppeling(administratie_id).alleen_lezen is True

    def test_sleutel_leeg_hergebruikt_de_bewaarde_sleutel(
        self,
        administratie_id,
        beheerder_id,
        rlz_credential,
        probe_vangt,
        sync_gefaked,
        monkeypatch: pytest.MonkeyPatch,
        admin_engine: Engine,
    ) -> None:
        _leesbron(monkeypatch, administratie_id, beheerder_id)
        voor = _koppeling(administratie_id)
        payload = {
            "odoo_url": URL,
            "company_id": LEESBRON_COMPANY,
            "overgangsdatum": OVERGANG.isoformat(),
            "mapping": {"grootboek": [], "btw": []},
        }  # géén api_key, géén api_gebruiker → beide uit de leesbron-rij
        r = client.post(
            f"/administraties/{administratie_id}/odoo/overstap",
            json=payload,
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert r.status_code == 201, r.text
        assert probe_vangt[-1]["api_key"] == KEY  # de bewaarde sleutel is ontsleuteld en gebruikt
        na = _koppeling(administratie_id)
        assert na.alleen_lezen is False and na.api_key_ciphertext == voor.api_key_ciphertext
        assert na.wrapped_data_key == voor.wrapped_data_key and na.api_gebruiker == voor.api_gebruiker
        promotie = _audit(admin_engine, "odoo_leesbron_gepromoveerd", administratie_id)
        assert len(promotie) == 1 and '"sleutel": "hergebruikt"' in promotie[0][1] and KEY not in promotie[0][1]

    def test_sleutel_leeg_zonder_leesbron_422(
        self, administratie_id, beheerder_id, probe_vangt, admin_engine: Engine
    ) -> None:
        payload = {
            "odoo_url": URL,
            "company_id": COMPANY,
            "overgangsdatum": OVERGANG.isoformat(),
            "mapping": {"grootboek": [], "btw": []},
        }
        r = client.post(
            f"/administraties/{administratie_id}/odoo/overstap",
            json=payload,
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert r.status_code == 422, r.text
        assert "vul de API-sleutel in" in r.json()["detail"]["bericht"]
        assert probe_vangt == [] and _koppeling(administratie_id) is None
        assert _administratie(admin_engine, administratie_id)[0] == "rlz"

    def test_te_korte_sleutel_blijft_422_validatie(self, administratie_id, beheerder_id, probe_vangt) -> None:
        r = _overstap(administratie_id, beheerder_id, api_key="kort")
        assert r.status_code == 422 and probe_vangt == []


class TestVoorbereidenEnVerbinding:
    def test_voorbereiden_zonder_sleutel_gebruikt_de_leesbron_sleutel(
        self, administratie_id, beheerder_id, probe_vangt, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _leesbron(monkeypatch, administratie_id, beheerder_id)
        r = client.post(
            f"/administraties/{administratie_id}/odoo/overstap/voorbereiden",
            json={"odoo_url": URL, "company_id": LEESBRON_COMPANY},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert r.status_code == 200, r.text
        assert probe_vangt[-1]["api_key"] == KEY and KEY not in r.text
        assert r.json()["company_naam"] == "Universal Steigerbouw"
        # Andere company zonder sleutel: de poort weigert vóór de probe.
        r2 = client.post(
            f"/administraties/{administratie_id}/odoo/overstap/voorbereiden",
            json={"odoo_url": URL, "company_id": COMPANY},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert r2.status_code == 422 and len(probe_vangt) == 1

    def test_verbinding_testen_zonder_sleutel_markeert_de_eigen_leesbron_kiesbaar(
        self, administratie_id, beheerder_id, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _leesbron(monkeypatch, administratie_id, beheerder_id)
        gebruikte_sleutels: list[str] = []

        class _Ctx:
            def __init__(self, key: str) -> None:
                gebruikte_sleutels.append(key)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return None

            def versie(self) -> str:
                return "19.0+e"

        monkeypatch.setattr(odoo_service, "_client", lambda url, key, cid: _Ctx(key))
        monkeypatch.setattr(
            odoo_service,
            "lees_companies",
            lambda c: [
                {"id": LEESBRON_COMPANY, "naam": "Universal Verkoop"},
                {"id": COMPANY, "naam": "Universal Steigerbouw"},
            ],
        )
        h = _bearer(beheerder_id, rol="beheerder")
        r = client.post(
            "/instellingen/odoo/verbinding-testen",
            json={"odoo_url": URL, "administratie_id": str(administratie_id)},
            headers=h,
        )
        assert r.status_code == 200, r.text
        assert gebruikte_sleutels == [KEY] and KEY not in r.text
        per_id = {c["company_id"]: c for c in r.json()["companies"]}
        assert per_id[LEESBRON_COMPANY]["eigen_leesbron"] is True and per_id[LEESBRON_COMPANY]["al_gekoppeld"] is True
        assert per_id[LEESBRON_COMPANY]["gekoppeld_aan"] == "huidige leesbron — overstappen"
        assert per_id[COMPANY]["eigen_leesbron"] is False and per_id[COMPANY]["al_gekoppeld"] is False
        # Zonder sleutel én zonder administratie = 422; mét sleutel voor een andere administratie blijft de rij grijs.
        r2 = client.post("/instellingen/odoo/verbinding-testen", json={"odoo_url": URL}, headers=h)
        assert r2.status_code == 422 and "Geen API-sleutel" in r2.text
        r3 = client.post("/instellingen/odoo/verbinding-testen", json={"odoo_url": URL, "api_key": KEY}, headers=h)
        assert r3.status_code == 200
        c3 = next(c for c in r3.json()["companies"] if c["company_id"] == LEESBRON_COMPANY)
        assert c3["eigen_leesbron"] is False and c3["gekoppeld_aan"].startswith("al gekoppeld (")


def probe_groen_rapport() -> dict[str, str]:
    return _groene_probe().rapport
