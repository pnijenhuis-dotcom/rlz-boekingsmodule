# ruff: noqa: F811 — pytest-fixtures als parameters
"""Blok 3 bundelrun 24-09 (BUG Peter 24-09, Recreatief Vastgoed Nederland B.V., company 13 actief / 11 gearchiveerd):
dearchiveren van een Odoo-administratie eiste een Reeleezee-webservice-login die zo'n administratie niet heeft → de weg
"dearchiveer die administratie" (CompanyClaim.reden) was dood. Sinds 24-09 is dearchiveren backend-bewust via de
0016-registry (`HeractiveerPort`): Odoo = bestaande koppeling + versleutelde API-sleutel opnieuw proben, company
ongewijzigd, geen loginvelden; Reeleezee = onveranderd (nieuwe login + probe). Archiveren laat de Odoo-sleutel bewust
staan (`odoo_sleutel_behouden`)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.backends.port import HeractiverenGeweigerd
from app.beheer import service
from app.db.session import scoped_session
from app.main import app
from app.odoo import heractiveer
from app.odoo.models import OdooKoppeling
from app.odoo.probe import ProbeUitkomst
from app.odoo.service import CompanyClaim
from app.security.envelope import wrap_secret
from app.security.tokens import create_access_token
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401

client = TestClient(app)
URL = "https://universal-steigers.odoo.com"
COMPANY = 13


def _bearer(gebruiker_id: uuid.UUID, *, rol: str = "beheerder") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _maak_odoo_administratie(
    admin_engine: Engine, aid: uuid.UUID, beheerder: uuid.UUID, *, company: int = COMPANY
) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE platform.administratie SET boekhoud_backend = 'odoo', rlz_admin_id = :rlz, "
                "naam = 'Recreatief Vastgoed Nederland B.V.' WHERE id = :id"
            ),
            {"id": aid, "rlz": f"odoo:universal-steigers.odoo.com:{company}"},
        )
    ct, wk = wrap_secret(b"odoo-api-sleutel")
    with scoped_session(None, actor_id=beheerder) as session:
        session.add(
            OdooKoppeling(
                administratie_id=aid,
                odoo_url=URL,
                company_id=company,
                company_naam="Recreatief Vastgoed Nederland B.V.",
                api_key_ciphertext=ct,
                wrapped_data_key=wk,
                aangemaakt_door=beheerder,
            )
        )


class FakeOdooClient:
    """Company-gebonden client zoals `odoo_client_voor` 'm levert; `teruggelezen` = het id dat res.company
    teruggeeft."""

    def __init__(self, company_id: int, *, teruggelezen: int | None = None) -> None:
        self.company_id = company_id
        self.teruggelezen = company_id if teruggelezen is None else teruggelezen
        self.gesloten = False

    def read_een(self, model: str, odoo_id: int, fields: list[str]) -> dict[str, Any] | None:
        assert model == "res.company" and odoo_id == self.company_id
        return (
            None
            if self.teruggelezen is None
            else {"id": self.teruggelezen, "name": "Recreatief Vastgoed Nederland B.V."}
        )

    def close(self) -> None:
        self.gesloten = True


class FakeVerbindingClient:
    company_id = 1

    def versie(self) -> dict[str, str]:
        return {"server_version": "19.0+e"}

    def __enter__(self) -> FakeVerbindingClient:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def close(self) -> None:
        return None


def _groen() -> ProbeUitkomst:
    return ProbeUitkomst(
        rapport={"verbinding": "ok", "account.move": "ok", "dagboek_inkoop": "ok"},
        company_naam="Recreatief Vastgoed Nederland B.V.",
        journal_purchase_id=7,
    )


def _rood() -> ProbeUitkomst:
    return ProbeUitkomst(rapport={"verbinding": "ok", "account.move": "geen rechten (AccessError)"})


def _stand(admin_engine: Engine, aid: uuid.UUID):  # noqa: ANN202
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT a.actief, a.gearchiveerd_op, k.probe_op, k.api_key_ciphertext IS NOT NULL AS sleutel, "
                "(SELECT count(*) FROM platform.rlz_credential c WHERE c.administratie_id = a.id) AS creds "
                "FROM platform.administratie a JOIN platform.odoo_koppeling k ON k.administratie_id = a.id "
                "WHERE a.id = :id"
            ),
            {"id": aid},
        ).one()


def _audit(admin_engine: Engine, aid: uuid.UUID, actie: str) -> list[dict]:
    with admin_engine.connect() as conn:
        return [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT nieuwe_waarde FROM platform.audit_event WHERE record_id = :id AND actie = :a "
                    "ORDER BY tijdstip"
                ),
                {"id": aid, "a": actie},
            ).all()
        ]


@pytest.fixture
def odoo_administratie(administratie_id: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine) -> uuid.UUID:
    _maak_odoo_administratie(admin_engine, administratie_id, beheerder_id)
    return administratie_id


class TestArchiverenOdoo:
    def test_archiveren_laat_de_odoo_sleutel_staan_en_zegt_dat(
        self, odoo_administratie: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        r = service.archiveer_administratie(actor_id=beheerder_id, administratie_id=odoo_administratie)
        assert r.credential_ingetrokken is False  # er wás geen RLZ-login
        assert r.odoo_sleutel_behouden is True
        stand = _stand(admin_engine, odoo_administratie)
        assert stand.actief is False and stand.gearchiveerd_op is not None
        assert stand.sleutel is True  # koppeling + versleutelde sleutel blijven — nodig voor dearchiveren zonder login

    def test_rlz_administratie_heeft_geen_odoo_sleutel_te_behouden(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID
    ) -> None:
        r = service.archiveer_administratie(actor_id=beheerder_id, administratie_id=administratie_id)
        assert r.odoo_sleutel_behouden is False


class TestDearchiverenOdoo:
    def test_groen_zonder_login_zet_actief_terug_en_verst_de_probe(
        self, odoo_administratie: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine, monkeypatch
    ) -> None:
        service.archiveer_administratie(actor_id=beheerder_id, administratie_id=odoo_administratie)
        fake = FakeOdooClient(COMPANY)
        monkeypatch.setattr(heractiveer, "odoo_client_voor", lambda aid: fake)
        monkeypatch.setattr(heractiveer, "voer_probe_uit", lambda c: _groen())
        rapport = service.dearchiveer_administratie(actor_id=beheerder_id, administratie_id=odoo_administratie)
        assert rapport == {"verbinding": "ok", "account.move": "ok", "dagboek_inkoop": "ok"}
        stand = _stand(admin_engine, odoo_administratie)
        assert stand.actief is True and stand.gearchiveerd_op is None
        assert stand.probe_op is not None and stand.creds == 0  # geen RLZ-credential aangemaakt
        assert fake.gesloten is True
        audits = _audit(admin_engine, odoo_administratie, "administratie_gedearchiveerd")
        assert len(audits) == 1 and audits[0]["backend"] == "odoo" and audits[0]["probe_rapport"]["verbinding"] == "ok"

    def test_company_mismatch_wijzigt_niets(
        self, odoo_administratie: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine, monkeypatch
    ) -> None:
        service.archiveer_administratie(actor_id=beheerder_id, administratie_id=odoo_administratie)
        monkeypatch.setattr(heractiveer, "odoo_client_voor", lambda aid: FakeOdooClient(COMPANY, teruggelezen=11))
        monkeypatch.setattr(heractiveer, "voer_probe_uit", lambda c: _groen())
        with pytest.raises(HeractiverenGeweigerd, match="company 11 terug waar de koppeling company 13 verwacht"):
            service.dearchiveer_administratie(actor_id=beheerder_id, administratie_id=odoo_administratie)
        stand = _stand(admin_engine, odoo_administratie)
        assert stand.actief is False and stand.gearchiveerd_op is not None and stand.probe_op is None
        assert _audit(admin_engine, odoo_administratie, "administratie_gedearchiveerd") == []

    def test_rode_probe_wijzigt_niets_en_draagt_het_rapport(
        self, odoo_administratie: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine, monkeypatch
    ) -> None:
        service.archiveer_administratie(actor_id=beheerder_id, administratie_id=odoo_administratie)
        monkeypatch.setattr(heractiveer, "odoo_client_voor", lambda aid: FakeOdooClient(COMPANY))
        monkeypatch.setattr(heractiveer, "voer_probe_uit", lambda c: _rood())
        with pytest.raises(HeractiverenGeweigerd, match="niet groen") as exc:
            service.dearchiveer_administratie(actor_id=beheerder_id, administratie_id=odoo_administratie)
        assert exc.value.rapport["account.move"].startswith("geen rechten")
        assert _stand(admin_engine, odoo_administratie).actief is False

    def test_login_meegegeven_is_niet_van_toepassing(
        self, odoo_administratie: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine, monkeypatch
    ) -> None:
        service.archiveer_administratie(actor_id=beheerder_id, administratie_id=odoo_administratie)
        monkeypatch.setattr(
            heractiveer, "odoo_client_voor", lambda aid: pytest.fail("geen probe bij een geweigerde login")
        )
        with pytest.raises(HeractiverenGeweigerd, match="niet van toepassing voor een Odoo-administratie"):
            service.dearchiveer_administratie(
                actor_id=beheerder_id, administratie_id=odoo_administratie, webservice_username="ws", wachtwoord="pw"
            )
        assert _stand(admin_engine, odoo_administratie).actief is False

    def test_reeleezee_pad_zonder_login_is_422_tekst(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID
    ) -> None:
        service.archiveer_administratie(actor_id=beheerder_id, administratie_id=administratie_id)
        with pytest.raises(HeractiverenGeweigerd, match="vereist een nieuwe webservice-login"):
            service.dearchiveer_administratie(actor_id=beheerder_id, administratie_id=administratie_id)


class TestRoute:
    def test_odoo_zonder_body_200_met_body_422_en_rlz_zonder_login_422(
        self, odoo_administratie: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine, monkeypatch
    ) -> None:
        pad = f"/instellingen/administraties/{odoo_administratie}/dearchiveren"
        service.archiveer_administratie(actor_id=beheerder_id, administratie_id=odoo_administratie)
        monkeypatch.setattr(heractiveer, "odoo_client_voor", lambda aid: FakeOdooClient(COMPANY))
        monkeypatch.setattr(heractiveer, "voer_probe_uit", lambda c: _groen())
        # Login meegegeven → 422 mét letterlijke reden, niets gewijzigd.
        resp = client.post(pad, json={"webservice_username": "ws", "wachtwoord": "pw"}, headers=_bearer(beheerder_id))
        assert resp.status_code == 422, resp.text
        assert "niet van toepassing voor een Odoo-administratie" in resp.json()["detail"]["bericht"]
        assert _stand(admin_engine, odoo_administratie).actief is False
        # Zonder body → probe + terugzetten.
        resp = client.post(pad, headers=_bearer(beheerder_id))
        assert resp.status_code == 200, resp.text
        assert resp.json()["rapport"]["verbinding"] == "ok"
        assert _stand(admin_engine, odoo_administratie).actief is True
        # Nog eens = 409 (niet gearchiveerd).
        assert client.post(pad, headers=_bearer(beheerder_id)).status_code == 409

    def test_rlz_zonder_login_422_en_boekhouding_403(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        pad = f"/instellingen/administraties/{administratie_id}/dearchiveren"
        service.archiveer_administratie(actor_id=beheerder_id, administratie_id=administratie_id)
        resp = client.post(pad, headers=_bearer(beheerder_id))
        assert resp.status_code == 422, resp.text
        assert "vereist een nieuwe webservice-login" in resp.json()["detail"]["bericht"]
        boekhouder = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                    "VALUES (:id, 'B', :m, 'boekhouding', 'actief')"
                ),
                {"id": boekhouder, "m": f"{boekhouder}@test.local"},
            )
        assert client.post(pad, headers=_bearer(boekhouder, rol="boekhouding")).status_code == 403
        # Archiveren-response draagt het nieuwe veld (RLZ: False).
        # (de administratie is al gearchiveerd; het veld staat op de DTO — vorm-toets via het schema)
        from app.beheer.schemas import ArchiveringResultaatDto

        assert "odoo_sleutel_behouden" in ArchiveringResultaatDto.model_fields


class TestWizardClaimLabel:
    def test_gearchiveerde_claim_zegt_dearchiveer(self) -> None:
        claim = CompanyClaim(
            administratie_id=uuid.uuid4(),
            administratie_naam="Recreatief Vastgoed Nederland B.V.",
            company_naam="Recreatief Vastgoed Nederland B.V.",
            migratie_doel=False,
            alleen_lezen=False,
            gearchiveerd=True,
        )
        assert claim.wizard_label() == "gearchiveerd — dearchiveer Recreatief Vastgoed Nederland B.V."

    def test_verbinding_testen_geeft_gearchiveerd_mee(
        self, odoo_administratie: uuid.UUID, beheerder_id: uuid.UUID, monkeypatch
    ) -> None:
        from app.odoo import service as odoo_service

        service.archiveer_administratie(actor_id=beheerder_id, administratie_id=odoo_administratie)
        monkeypatch.setattr(odoo_service, "_client", lambda url, key, cid, **kw: FakeVerbindingClient())
        monkeypatch.setattr(
            odoo_service,
            "lees_companies",
            lambda c: [{"id": COMPANY, "naam": "Recreatief Vastgoed Nederland B.V."}, {"id": 7, "naam": "Lusso"}],
        )
        companies = {c.company_id: c for c in odoo_service.test_verbinding(odoo_url=URL, api_key="x").companies}
        assert companies[COMPANY].al_gekoppeld is True and companies[COMPANY].gearchiveerd is True
        assert companies[COMPANY].gekoppeld_aan == "gearchiveerd — dearchiveer Recreatief Vastgoed Nederland B.V."
        assert companies[7].gearchiveerd is False
