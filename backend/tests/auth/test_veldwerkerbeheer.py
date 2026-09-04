"""Fijnmazig recht 'veldwerkerbeheer' (besluit Peter 31-08, migratie 0091): een B+P-medewerker
mét het recht mag UITSLUITEND veldwerkers (ZZP'er/uitvoerder/detacheerder) aanmaken (incl.
uitnodiging_later) en archiveren binnen de eigen administratie-scope — nooit kantoorrollen,
nooit rol-/scope-mutaties. Al het overige gebruikersbeheer blijft exclusief Beheerder."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service as auth_service
from app.main import app
from app.security.tokens import create_access_token
from app.uren import service as uren_service
from tests.uren.conftest import administratie_id, administratie_zonder_opt_in, maak_gebruiker  # noqa: F401

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


@pytest.fixture
def tweede_administratie(admin_engine: Engine) -> uuid.UUID:
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Andere BV (test)', :rlz)"),
            {"id": aid, "rlz": f"rlz-{aid}"},
        )
    return aid


@pytest.fixture
def bp_met_recht(admin_engine: Engine, beheerder_id, administratie_id) -> uuid.UUID:  # noqa: F811
    bp = maak_gebruiker(admin_engine, "boekhouding_projecten", "Haci K.")
    auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=bp, administratie_id=administratie_id)
    uren_service.zet_veldwerkerbeheer_recht(gebruiker_id=bp, ingeschakeld=True, actor_id=beheerder_id)
    return bp


def _uitnodiging(rol: str, administratie_ids: list[uuid.UUID], *, uitnodiging_later: bool = True) -> dict:
    return {
        "naam": "Nieuwe Veldwerker",
        "e_mail": f"{uuid.uuid4()}@test.local",
        "rol": rol,
        "administratie_ids": [str(a) for a in administratie_ids],
        "uitnodiging_later": uitnodiging_later,
    }


class TestRechtToekennen:
    def test_beheerder_only_en_alleen_kantoorrollen(self, admin_engine: Engine, beheerder_id):
        bp = maak_gebruiker(admin_engine, "boekhouding_projecten", "Haci K.")
        resp = client.put(
            "/uren/beheer/veldwerkerbeheer-recht",
            json={"gebruiker_id": str(bp), "ingeschakeld": True},
            headers=_bearer(bp, rol="boekhouding_projecten"),
        )
        assert resp.status_code == 403  # toekennen blijft Beheerder-only
        beheerder_headers = _bearer(beheerder_id, rol="beheerder")
        resp = client.put(
            "/uren/beheer/veldwerkerbeheer-recht",
            json={"gebruiker_id": str(bp), "ingeschakeld": True},
            headers=beheerder_headers,
        )
        assert resp.status_code == 200, resp.text
        resp = client.get("/uren/beheer/veldwerkerbeheer-recht", headers=beheerder_headers)
        assert str(bp) in resp.json()["gebruiker_ids"]
        # Nooit op een Beheerder of een externe rol.
        resp = client.put(
            "/uren/beheer/veldwerkerbeheer-recht",
            json={"gebruiker_id": str(beheerder_id), "ingeschakeld": True},
            headers=beheerder_headers,
        )
        assert resp.status_code == 422
        zzper = maak_gebruiker(admin_engine, "zzper", "Milan")
        resp = client.put(
            "/uren/beheer/veldwerkerbeheer-recht",
            json={"gebruiker_id": str(zzper), "ingeschakeld": True},
            headers=beheerder_headers,
        )
        assert resp.status_code == 422

    def test_los_van_meerwerk_recht(self, admin_engine: Engine, beheerder_id):
        """Eigen module-sleutel: één gebruiker draagt beide rechten tegelijk (PK-les 0091)."""
        bp = maak_gebruiker(admin_engine, "boekhouding_projecten", "Haci K.")
        uren_service.zet_meerwerk_recht(gebruiker_id=bp, ingeschakeld=True, actor_id=beheerder_id)
        uren_service.zet_veldwerkerbeheer_recht(gebruiker_id=bp, ingeschakeld=True, actor_id=beheerder_id)
        assert uren_service.heeft_meerwerk_urenstaten_recht(gebruiker_id=bp, rol="boekhouding_projecten") is True
        assert uren_service.heeft_veldwerkerbeheer_recht(gebruiker_id=bp, rol="boekhouding_projecten") is True
        uren_service.zet_veldwerkerbeheer_recht(gebruiker_id=bp, ingeschakeld=False, actor_id=beheerder_id)
        assert uren_service.heeft_meerwerk_urenstaten_recht(gebruiker_id=bp, rol="boekhouding_projecten") is True


class TestAanmaken:
    def test_zonder_recht_403(self, admin_engine: Engine, administratie_id):  # noqa: F811
        bp = maak_gebruiker(admin_engine, "boekhouding_projecten", "Zonder Recht")
        resp = client.post(
            "/auth/uitnodigingen",
            json=_uitnodiging("zzper", [administratie_id]),
            headers=_bearer(bp, rol="boekhouding_projecten"),
        )
        assert resp.status_code == 403

    def test_met_recht_alleen_veldwerkers_binnen_scope(
        self, bp_met_recht, administratie_id, tweede_administratie  # noqa: F811
    ):
        headers = _bearer(bp_met_recht, rol="boekhouding_projecten")
        # Veldrol binnen eigen scope, incl. uitnodiging_later-flow → OK.
        resp = client.post("/auth/uitnodigingen", json=_uitnodiging("zzper", [administratie_id]), headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["mail_uitgesteld"] is True
        # Kantoorrol → nooit.
        resp = client.post("/auth/uitnodigingen", json=_uitnodiging("boekhouding", [administratie_id]), headers=headers)
        assert resp.status_code == 403
        resp = client.post("/auth/uitnodigingen", json=_uitnodiging("beheerder", [administratie_id]), headers=headers)
        assert resp.status_code == 403
        # Scope buiten de eigen administraties of géén scope → nooit.
        resp = client.post(
            "/auth/uitnodigingen", json=_uitnodiging("zzper", [administratie_id, tweede_administratie]), headers=headers
        )
        assert resp.status_code == 403
        resp = client.post("/auth/uitnodigingen", json=_uitnodiging("zzper", []), headers=headers)
        assert resp.status_code == 403
        # Rol- en scope-mutaties blijven dicht (require_beheerder ongewijzigd).
        doel = uuid.uuid4()
        assert client.patch(f"/auth/gebruikers/{doel}/rol", json={"rol": "boekhouding"}, headers=headers).status_code == 403
        assert client.post(f"/auth/gebruikers/{doel}/scope", json={"administratie_id": str(administratie_id)}, headers=headers).status_code == 403

    def test_beheerder_ongewijzigd(self, beheerder_id, administratie_id):  # noqa: F811
        resp = client.post(
            "/auth/uitnodigingen",
            json=_uitnodiging("boekhouding", [administratie_id]),
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 200, resp.text


class TestArchiveren:
    def test_veldwerker_binnen_scope(self, admin_engine: Engine, bp_met_recht, beheerder_id, administratie_id):  # noqa: F811
        headers = _bearer(bp_met_recht, rol="boekhouding_projecten")
        veldwerker = maak_gebruiker(admin_engine, "zzper", "Milan K.")
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=veldwerker, administratie_id=administratie_id)
        assert client.get(f"/auth/gebruikers/{veldwerker}/open-werk", headers=headers).status_code == 200
        assert client.post(f"/auth/gebruikers/{veldwerker}/archiveren", headers=headers).status_code == 204
        # Dearchiveren blijft Beheerder-only.
        assert client.post(f"/auth/gebruikers/{veldwerker}/dearchiveren", headers=headers).status_code == 403

    def test_kantoorrol_of_buiten_scope_403(
        self, admin_engine: Engine, bp_met_recht, beheerder_id, administratie_id, tweede_administratie  # noqa: F811
    ):
        headers = _bearer(bp_met_recht, rol="boekhouding_projecten")
        # Kantoormedewerker archiveren → nooit.
        kantoor = maak_gebruiker(admin_engine, "boekhouding", "Rob T.")
        assert client.post(f"/auth/gebruikers/{kantoor}/archiveren", headers=headers).status_code == 403
        # Veldwerker mét een administratie búiten de scope van de actor → fail-closed 403.
        buiten = maak_gebruiker(admin_engine, "zzper", "Buiten Scope")
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=buiten, administratie_id=administratie_id)
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=buiten, administratie_id=tweede_administratie)
        assert client.post(f"/auth/gebruikers/{buiten}/archiveren", headers=headers).status_code == 403
        # Veldwerker zónder enige scope → fail-closed 403.
        los = maak_gebruiker(admin_engine, "zzper", "Zonder Scope")
        assert client.post(f"/auth/gebruikers/{los}/archiveren", headers=headers).status_code == 403


class TestRolgroepBijIngang:
    """Bugfix 04-09 (casus Peter): "+ Veldwerker uitnodigen" op /gebruikers maakte een KANTOORmedewerker aan — de
    rol-state van de dialoog werd maar éénmalig geïnitialiseerd. De server dwingt nu de rolgroep van de aanroepende
    ingang (`bron`) af, óók voor een Beheerder; de audit draagt de ingang."""

    def _post(self, beheerder_id, rol: str, bron: str | None, administratie_ids):
        body = _uitnodiging(rol, administratie_ids)
        if bron is not None:
            body["bron"] = bron
        return client.post("/auth/uitnodigingen", json=body, headers=_bearer(beheerder_id, rol="beheerder"))

    def test_veldwerkers_ingang_weigert_kantoorrol_ook_voor_beheerder(self, beheerder_id, administratie_id):  # noqa: F811
        for rol in ("boekhouding", "boekhouding_projecten", "beheerder"):
            resp = self._post(beheerder_id, rol, "veldwerkers", [administratie_id])
            assert resp.status_code == 422, resp.text
            assert "veldwerkers-ingang" in resp.json()["detail"]
            assert "tab Kantoor" in resp.json()["detail"]
        resp = self._post(beheerder_id, "klant_accordeur", "planning", [administratie_id])
        assert resp.status_code == 422

    def test_kantoor_ingang_weigert_veldrol_en_accordeur(self, beheerder_id, administratie_id):  # noqa: F811
        for rol in ("zzper", "uitvoerder", "detacheerder", "klant_accordeur"):
            resp = self._post(beheerder_id, rol, "kantoor", [administratie_id])
            assert resp.status_code == 422, resp.text
        resp = self._post(beheerder_id, "boekhouding", "klant_accordeurs", [administratie_id])
        assert resp.status_code == 422

    def test_passende_rolgroep_per_ingang_en_audit_draagt_bron(
        self, beheerder_id, administratie_id, admin_engine: Engine  # noqa: F811
    ):
        gevallen = [
            ("veldwerkers", "zzper"),
            ("veldwerkers", "detacheerder"),
            ("planning", "uitvoerder"),
            ("kantoor", "boekhouding"),
            ("kantoor", "beheerder"),
            ("klant_accordeurs", "klant_accordeur"),
        ]
        for bron, rol in gevallen:
            resp = self._post(beheerder_id, rol, bron, [administratie_id])
            assert resp.status_code == 200, (bron, rol, resp.text)
            gebruiker_id = resp.json()["gebruiker_id"]
            with admin_engine.connect() as conn:
                rij = conn.execute(
                    text(
                        "SELECT nieuwe_waarde FROM platform.audit_event WHERE actie = 'gebruiker_uitgenodigd' "
                        "AND correlatie_id = :g"
                    ),
                    {"g": gebruiker_id},
                ).scalar_one()
            assert rij["rol"] == rol and rij["bron"] == bron

    def test_zonder_bron_blijven_de_bestaande_poorten_gelden(self, beheerder_id, administratie_id):  # noqa: F811
        """Oudere client/scripts zonder `bron`: geen uitspraak over de ingang (audit bron=null)."""
        resp = self._post(beheerder_id, "boekhouding", None, [administratie_id])
        assert resp.status_code == 200, resp.text
        resp = self._post(beheerder_id, "zzper", None, [administratie_id])
        assert resp.status_code == 200, resp.text
