# ruff: noqa: F811 — fixtures uit tests.auth.conftest worden via import geregistreerd en als parameter gebruikt
"""Beheerder-instelling "Intercompany-leveranciers" per administratie (nachtrun 08/09-09 blok 1).

Eén bron: dezelfde tabel `intercompany_tegenpartij` als de doorbelasting-mapping en de leesbron
`doorbelasting/intercompany.py` — markeren via de instelling maakt een crediteur direct "leverancier met IC-vlag" voor
de klant-accordering en het bank-afletteren; verwijderen = actief=False (nooit delete). Mapping-rijen zijn alleen-lezen.
Beheerder-only schrijven, audit oud→nieuw, tijdlijn (historie) uit het audit-spoor; CLI met dezelfde servicelaag."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app import cli
from app.db.session import scoped_session
from app.doorbelasting import intercompany, intercompany_beheer
from app.main import app
from app.security.tokens import create_access_token
from app.sync.models import VendorCache
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.bank.conftest import maak_intercompany_tegenpartij
from tests.uren.conftest import maak_gebruiker

client = TestClient(app)
VENDOR_UN = uuid.UUID("11111111-1111-4111-8111-111111111111")
VENDOR_FLOOR = uuid.UUID("22222222-2222-4222-8222-222222222222")


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


@pytest.fixture
def vendors(administratie_id: uuid.UUID) -> None:  # noqa: F811
    with scoped_session(administratie_id) as session:
        session.add(
            VendorCache(id=VENDOR_UN, administratie_id=administratie_id, naam="Universal Nederland B.V.", brondata={})
        )
        session.add(VendorCache(id=VENDOR_FLOOR, administratie_id=administratie_id, naam="Floor B.V.", brondata={}))


def _audit(admin_engine: Engine, administratie_id: uuid.UUID) -> list[tuple[dict | None, dict | None, uuid.UUID]]:
    with admin_engine.connect() as conn:
        return [
            (r[0], r[1], r[2])
            for r in conn.execute(
                text(
                    "SELECT oude_waarde, nieuwe_waarde, actor_id FROM platform.audit_event "
                    "WHERE administratie_id = :aid AND actie = :actie ORDER BY tijdstip, id"
                ),
                {"aid": administratie_id, "actie": intercompany_beheer.AUDIT_ACTIE},
            ).all()
        ]


class TestServicelaag:
    def test_markeren_maakt_de_crediteur_ic_voor_de_leesbron_met_audit(
        self,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        vendors,  # noqa: F811
    ) -> None:
        with scoped_session(administratie_id) as session:
            assert not intercompany.is_intercompany_leverancier(
                session, administratie_id=administratie_id, vendor_id=VENDOR_UN
            )
        dto = intercompany_beheer.markeer_intercompany_leverancier(
            administratie_id=administratie_id, vendor_id=VENDOR_UN, actor_id=beheerder_id, reden="besluit 08-09"
        )
        assert (dto.naam, dto.bron, dto.actief, dto.verwijderbaar) == (
            "Universal Nederland B.V.",
            "handmatig",
            True,
            True,
        )
        with scoped_session(administratie_id) as session:
            assert intercompany.is_intercompany_leverancier(
                session, administratie_id=administratie_id, vendor_id=VENDOR_UN
            )
            assert intercompany.intercompany_entity_guids(session, administratie_id=administratie_id) == {VENDOR_UN}
            # Floor blijft gewoon
            assert not intercompany.is_intercompany_leverancier(
                session, administratie_id=administratie_id, vendor_id=VENDOR_FLOOR
            )
        audit = _audit(admin_engine, administratie_id)
        assert len(audit) == 1
        oud, nieuw, actor = audit[0]
        assert oud is None and actor == beheerder_id
        assert nieuw == {
            "entity_guid": str(VENDOR_UN),
            "naam": "Universal Nederland B.V.",
            "bron": "handmatig",
            "actief": True,
            "reden": "besluit 08-09",
        }

    def test_markeren_is_idempotent_en_verwijderen_deactiveert_nooit_delete(
        self,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        vendors,  # noqa: F811
    ) -> None:
        intercompany_beheer.markeer_intercompany_leverancier(
            administratie_id=administratie_id, vendor_id=VENDOR_UN, actor_id=beheerder_id
        )
        intercompany_beheer.markeer_intercompany_leverancier(
            administratie_id=administratie_id, vendor_id=VENDOR_UN, actor_id=beheerder_id
        )
        with admin_engine.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT count(*) FROM boekhouding.intercompany_tegenpartij WHERE administratie_id = :a"),
                    {"a": administratie_id},
                ).scalar_one()
                == 1
            )
        intercompany_beheer.verwijder_intercompany_leverancier(
            administratie_id=administratie_id, vendor_id=VENDOR_UN, actor_id=beheerder_id, reden="vergissing"
        )
        with admin_engine.connect() as conn:
            rij = conn.execute(
                text("SELECT actief, bron FROM boekhouding.intercompany_tegenpartij WHERE administratie_id = :a"),
                {"a": administratie_id},
            ).one()
        assert (rij[0], rij[1]) == (False, "handmatig"), "verwijderen = actief=False, de rij blijft staan"
        with scoped_session(administratie_id) as session:
            assert not intercompany.is_intercompany_leverancier(
                session, administratie_id=administratie_id, vendor_id=VENDOR_UN
            )
            assert intercompany_beheer.lijst_intercompany_leveranciers(session, administratie_id=administratie_id) == []
            historie = intercompany_beheer.historie_intercompany_leveranciers(
                session, administratie_id=administratie_id
            )
        assert [h.actie for h in historie] == ["verwijderd", "gemarkeerd", "gemarkeerd"]
        assert historie[0].reden == "vergissing" and historie[0].actor_naam == "Test-Beheerder"
        # opnieuw markeren heractiveert dezelfde rij
        intercompany_beheer.markeer_intercompany_leverancier(
            administratie_id=administratie_id, vendor_id=VENDOR_UN, actor_id=beheerder_id
        )
        with scoped_session(administratie_id) as session:
            assert intercompany.is_intercompany_leverancier(
                session, administratie_id=administratie_id, vendor_id=VENDOR_UN
            )

    def test_onbekende_crediteur_geweigerd(self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, vendors) -> None:  # noqa: F811
        with pytest.raises(intercompany_beheer.CrediteurOnbekend):
            intercompany_beheer.markeer_intercompany_leverancier(
                administratie_id=administratie_id, vendor_id=uuid.uuid4(), actor_id=beheerder_id
            )
        with pytest.raises(intercompany_beheer.CrediteurOnbekend):
            intercompany_beheer.verwijder_intercompany_leverancier(
                administratie_id=administratie_id, vendor_id=VENDOR_FLOOR, actor_id=beheerder_id
            )

    def test_mapping_rij_is_alleen_lezen(
        self,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        vendors,  # noqa: F811
    ) -> None:
        maak_intercompany_tegenpartij(
            admin_engine, administratie_id=administratie_id, entity_guid=VENDOR_FLOOR, naam="Floor B.V."
        )
        with scoped_session(administratie_id) as session:
            lijst = intercompany_beheer.lijst_intercompany_leveranciers(session, administratie_id=administratie_id)
        assert [(lv.vendor_id, lv.bron, lv.verwijderbaar) for lv in lijst] == [
            (VENDOR_FLOOR, "doorbelasting_mapping", False)
        ]
        with pytest.raises(intercompany_beheer.RijUitDoorbelasting):
            intercompany_beheer.verwijder_intercompany_leverancier(
                administratie_id=administratie_id, vendor_id=VENDOR_FLOOR, actor_id=beheerder_id
            )
        # markeren van een al actieve mapping-rij verandert de rij niet (blijft mapping-herkomst)
        dto = intercompany_beheer.markeer_intercompany_leverancier(
            administratie_id=administratie_id, vendor_id=VENDOR_FLOOR, actor_id=beheerder_id
        )
        assert dto.bron == "doorbelasting_mapping" and dto.actief


class TestApi:
    def test_lezen_kantoor_met_scope_schrijven_beheerder_only(
        self,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        vendors,  # noqa: F811
    ) -> None:
        from app.auth import service as auth_service

        boekhouder = maak_gebruiker(admin_engine, "boekhouding", "Kantoor B.")
        auth_service.voeg_scope_toe(
            actor_id=beheerder_id, doel_gebruiker_id=boekhouder, administratie_id=administratie_id
        )
        basis = f"/administraties/{administratie_id}/intercompany-leveranciers"
        # PUT/DELETE door een boekhouder → 403
        assert (
            client.put(
                f"{basis}/{VENDOR_UN}", json={"reden": "x"}, headers=_bearer(boekhouder, rol="boekhouding")
            ).status_code
            == 403
        )
        assert client.delete(f"{basis}/{VENDOR_UN}", headers=_bearer(boekhouder, rol="boekhouding")).status_code == 403
        # Beheerder markeert
        resp = client.put(
            f"{basis}/{VENDOR_UN}",
            json={"reden": "besluit 08-09 intercompany Universal"},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert [(lv["naam"], lv["bron"], lv["verwijderbaar"]) for lv in body["leveranciers"]] == [
            ("Universal Nederland B.V.", "handmatig", True)
        ]
        assert (
            body["historie"][0]["actie"] == "gemarkeerd"
            and body["historie"][0]["reden"] == "besluit 08-09 intercompany Universal"
        )
        assert body["historie"][0]["actor_naam"] == "Test-Beheerder"
        # boekhouder mét scope leest
        resp = client.get(basis, headers=_bearer(boekhouder, rol="boekhouding"))
        assert resp.status_code == 200 and len(resp.json()["leveranciers"]) == 1
        # onbekende crediteur → 404; zonder body ook geldig
        assert client.put(f"{basis}/{uuid.uuid4()}", headers=_bearer(beheerder_id, rol="beheerder")).status_code == 404
        # verwijderen
        resp = client.delete(f"{basis}/{VENDOR_UN}", headers=_bearer(beheerder_id, rol="beheerder"))
        assert resp.status_code == 200 and resp.json()["leveranciers"] == []
        assert resp.json()["historie"][0]["actie"] == "verwijderd"
        assert client.delete(f"{basis}/{VENDOR_UN}", headers=_bearer(beheerder_id, rol="beheerder")).status_code == 404

    def test_mapping_rij_verwijderen_409_en_accordeur_403(
        self,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        vendors,  # noqa: F811
    ) -> None:
        maak_intercompany_tegenpartij(
            admin_engine, administratie_id=administratie_id, entity_guid=VENDOR_FLOOR, naam="Floor B.V."
        )
        basis = f"/administraties/{administratie_id}/intercompany-leveranciers"
        resp = client.delete(f"{basis}/{VENDOR_FLOOR}", headers=_bearer(beheerder_id, rol="beheerder"))
        assert resp.status_code == 409 and "doorbelasting" in resp.json()["detail"]
        accordeur = maak_gebruiker(admin_engine, "klant_accordeur", "K. Accordeur")
        assert client.get(basis, headers=_bearer(accordeur, rol="klant_accordeur")).status_code == 403


class TestCli:
    def _email(self, admin_engine: Engine, gid: uuid.UUID) -> str:
        with admin_engine.connect() as conn:
            return conn.execute(text("SELECT e_mail FROM platform.gebruiker WHERE id = :id"), {"id": gid}).scalar_one()

    def test_dry_run_schrijft_niets_echte_run_markeert_op_naam(
        self,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        vendors,
        capsys,  # noqa: F811
    ) -> None:
        email = self._email(admin_engine, beheerder_id)
        argv = [
            "intercompany-leverancier-markeren",
            "--administratie",
            str(administratie_id),
            "--crediteur",
            "Universal Nederland B.V.",
            "--actor-email",
            email,
            "--reden",
            "besluit 08-09 intercompany Universal",
        ]
        assert cli.main([*argv, "--dry-run"]) == 0
        assert _audit(admin_engine, administratie_id) == []
        assert cli.main(argv) == 0
        uit = capsys.readouterr().out
        assert "OK    intercompany-leveranciers" in uit and "Universal Nederland B.V. [handmatig]" in uit
        audit = _audit(admin_engine, administratie_id)
        assert (
            len(audit) == 1
            and audit[0][2] == beheerder_id
            and audit[0][1]["reden"] == "besluit 08-09 intercompany Universal"
        )
        with scoped_session(administratie_id) as session:
            assert intercompany.is_intercompany_leverancier(
                session, administratie_id=administratie_id, vendor_id=VENDOR_UN
            )
        # --verwijderen via dezelfde CLI
        assert cli.main([*argv, "--verwijderen"]) == 0
        with scoped_session(administratie_id) as session:
            assert not intercompany.is_intercompany_leverancier(
                session, administratie_id=administratie_id, vendor_id=VENDOR_UN
            )

    def test_niet_beheerder_of_onbekende_crediteur_weigert(
        self,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        vendors,  # noqa: F811
    ) -> None:
        boekhouder = maak_gebruiker(admin_engine, "boekhouding", "Kantoor B.")
        basis = ["intercompany-leverancier-markeren", "--administratie", str(administratie_id), "--reden", "r"]
        assert (
            cli.main(
                [
                    *basis,
                    "--crediteur",
                    "Universal Nederland B.V.",
                    "--actor-email",
                    self._email(admin_engine, boekhouder),
                ]
            )
            == 2
        )
        assert (
            cli.main([*basis, "--crediteur", "Bestaat Niet", "--actor-email", self._email(admin_engine, beheerder_id)])
            == 2
        )
        assert _audit(admin_engine, administratie_id) == []
