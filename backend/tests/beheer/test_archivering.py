# ruff: noqa: F811 — pytest-fixtures als parameters
"""Instellingen › Administraties v2 (opdracht 30-08 blok A, mockup instellingen-administraties-v2,
migratie 0089): archiveren = actief uit + archiefspoor + webservice-login ingetrokken + syncs/jobs en
UI-lijsten filteren op actief + registersync levert de rij niet meer (contract v1.19); dearchiveren
vereist een nieuwe login mét groene probe; defaults boeken/AI AAN voor NIEUWE administraties;
verkoop-autoboeken volgt is_vastgoed. Nooit verwijderen."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.beheer import service
from app.credentialstore import service as credentialstore_service
from app.main import app
from app.security.tokens import create_access_token
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.beheer.test_onboarding import SchrijfFakeClient, _rlz_data

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str = "beheerder") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _rlz_admin_id(admin_engine: Engine, administratie_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT rlz_admin_id FROM platform.administratie WHERE id = :id"), {"id": administratie_id}
        ).scalar_one()


class TestArchiveren:
    def test_archiveren_trekt_login_in_stopt_jobs_en_is_omkeerbaar_met_nieuwe_login(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine, monkeypatch
    ) -> None:
        from app.auth import service as auth_service
        from app.beheer import onboarding
        from app.db.models import GebruikerRol
        from app.registersync import service as registersync_service
        from app.sync import service as sync_service

        credentialstore_service.zet_credential(
            actor_id=beheerder_id, administratie_id=administratie_id, webservice_username="ws_oud", wachtwoord="geheim"
        )
        r = service.archiveer_administratie(actor_id=beheerder_id, administratie_id=administratie_id)
        assert r.credential_ingetrokken is True and r.open_documenten == 0
        with admin_engine.connect() as conn:
            rij = conn.execute(
                text(
                    "SELECT actief, gearchiveerd_op, gearchiveerd_door, "
                    "(SELECT count(*) FROM platform.rlz_credential c WHERE c.administratie_id = a.id) AS creds "
                    "FROM platform.administratie a WHERE id = :id"
                ),
                {"id": administratie_id},
            ).one()
            acties = {
                a
                for (a,) in conn.execute(
                    text("SELECT actie FROM platform.audit_event WHERE record_id = :id"), {"id": administratie_id}
                ).all()
            }
        assert rij.actief is False and rij.gearchiveerd_op is not None and rij.gearchiveerd_door == beheerder_id
        assert rij.creds == 0  # login weg uit de store (het audit_event blijft)
        assert {"administratie_gearchiveerd", "credential_ingetrokken"} <= acties
        # Uit de UI-lijsten en jobs (actief-filter) …
        assert administratie_id not in {
            a.id for a in auth_service.mijn_administraties(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER)
        }
        assert administratie_id not in sync_service.sync_alle_administraties()
        # … en uit de registersync-snapshot (v1.19: afwezigheid = verdwenen), wél in het beheer-overzicht
        # achter het filter — met archiefspoor.
        snapshot, _ = registersync_service.bouw_snapshot()
        assert administratie_id not in {a.id for a in snapshot.administraties.rijen}
        assert administratie_id not in {a.administratie_id for a in service.overzicht_administratie_instellingen()}
        rij_v2 = next(
            a
            for a in service.overzicht_administratie_instellingen(inclusief_gearchiveerd=True)
            if a.administratie_id == administratie_id
        )
        assert rij_v2.gearchiveerd_op is not None and rij_v2.webservice_username is None
        # Nog eens archiveren = leesbare fout; nooit verwijderd.
        with pytest.raises(service.AdministratieGearchiveerd):
            service.archiveer_administratie(actor_id=beheerder_id, administratie_id=administratie_id)
        # Dearchiveren: nieuwe login mét admin-pin + groene probe → credential terug, actief terug.
        rlz_id = _rlz_admin_id(admin_engine, administratie_id)
        fake = SchrijfFakeClient(_rlz_data((rlz_id, "Testklant")))
        rapport = service.dearchiveer_administratie(
            actor_id=beheerder_id,
            administratie_id=administratie_id,
            webservice_username="ws_nieuw",
            wachtwoord="nieuw-geheim",
            client=fake,
        )
        assert all(v == "ok" for v in rapport.values())
        with admin_engine.connect() as conn:
            rij = conn.execute(
                text(
                    "SELECT a.actief, a.gearchiveerd_op, c.webservice_username FROM platform.administratie a "
                    "JOIN platform.rlz_credential c ON c.administratie_id = a.id WHERE a.id = :id"
                ),
                {"id": administratie_id},
            ).one()
        assert rij.actief is True and rij.gearchiveerd_op is None and rij.webservice_username == "ws_nieuw"
        assert administratie_id in {
            a.id for a in auth_service.mijn_administraties(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER)
        }
        # Dearchiveren van een niet-gearchiveerde = fout; probe niet groen = niets gewijzigd.
        with pytest.raises(service.BeheerFout, match="niet gearchiveerd"):
            service.dearchiveer_administratie(
                actor_id=beheerder_id,
                administratie_id=administratie_id,
                webservice_username="x",
                wachtwoord="y",
                client=fake,
            )
        service.archiveer_administratie(actor_id=beheerder_id, administratie_id=administratie_id)
        rood = SchrijfFakeClient(_rlz_data((rlz_id, "Testklant")))
        rood.fouten = {"Vendors": 403} if hasattr(rood, "fouten") else None
        monkeypatch.setattr(onboarding.credentialstore, "probe_is_groen", lambda rapport: False)
        with pytest.raises(onboarding.OnboardingFout, match="niet groen"):
            service.dearchiveer_administratie(
                actor_id=beheerder_id,
                administratie_id=administratie_id,
                webservice_username="ws_x",
                wachtwoord="y",
                client=rood,
            )
        with admin_engine.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT actief FROM platform.administratie WHERE id = :id"), {"id": administratie_id}
                ).scalar_one()
                is False
            )

    def test_endpoints_beheerder_only_en_statuscodes(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        pad = f"/instellingen/administraties/{administratie_id}"
        boekhouder = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                    "VALUES (:id, 'B', :m, 'boekhouding', 'actief')"
                ),
                {"id": boekhouder, "m": f"{boekhouder}@test.local"},
            )
        assert client.post(f"{pad}/archiveren", headers=_bearer(boekhouder, rol="boekhouding")).status_code == 403
        resp = client.post(f"{pad}/archiveren", headers=_bearer(beheerder_id))
        assert resp.status_code == 200, resp.text
        assert resp.json()["credential_ingetrokken"] is False and resp.json()["open_documenten"] == 0
        assert client.post(f"{pad}/archiveren", headers=_bearer(beheerder_id)).status_code == 409
        assert (
            client.post(
                f"/instellingen/administraties/{uuid.uuid4()}/archiveren", headers=_bearer(beheerder_id)
            ).status_code
            == 404
        )
        # Lijst: default zonder, mét vlag inclusief + archiefspoor.
        lijst = client.get("/instellingen/administraties", headers=_bearer(beheerder_id)).json()["administraties"]
        assert str(administratie_id) not in {a["id"] for a in lijst}
        lijst = client.get(
            "/instellingen/administraties", params={"inclusief_gearchiveerd": "true"}, headers=_bearer(beheerder_id)
        ).json()["administraties"]
        rij = next(a for a in lijst if a["id"] == str(administratie_id))
        assert rij["gearchiveerd_op"] is not None and rij["gearchiveerd_door_naam"]
        # Dearchiveren mét een login die de administratie niet ziet → 422 mét bericht (niets gewijzigd).
        resp = client.post(
            f"{pad}/dearchiveren",
            json={"webservice_username": "ws", "wachtwoord": "pw"},
            headers=_bearer(beheerder_id),
        )
        assert resp.status_code in (422, 502), resp.text


class TestDefaultsEnAutoboeken:
    def test_nieuwe_administratie_krijgt_boeken_en_ai_aan_bestaande_blijven(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        from app.beheer import onboarding

        fake = SchrijfFakeClient(_rlz_data(("rlz-nieuw-1", "Nieuwe Klant B.V.")))
        [nieuw] = onboarding.maak_administraties_aan(
            actor_id=beheerder_id,
            webservice_username="ws",
            wachtwoord="pw",
            rlz_admin_ids=["rlz-nieuw-1"],
            client=fake,
            start_sync=False,
        )
        with admin_engine.connect() as conn:
            rijen = conn.execute(
                text(
                    "SELECT id, boeken_ingeschakeld, ai_extractie_ingeschakeld FROM platform.administratie "
                    "WHERE id IN (:a, :b)"
                ),
                {"a": nieuw.id, "b": administratie_id},
            ).all()
        per = {r.id: (r.boeken_ingeschakeld, r.ai_extractie_ingeschakeld) for r in rijen}
        assert per[nieuw.id] == (True, True)  # default voor nieuwe
        assert per[administratie_id] == (False, False)  # bestaande rij (test-seed) ongewijzigd

    def test_verkoop_autoboeken_volgt_is_vastgoed(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        r = service.zet_is_vastgoed(actor_id=beheerder_id, administratie_id=administratie_id, is_vastgoed=True)
        assert r.verkoop_autoboeken_ingeschakeld is True  # spiegel gaat mee AAN
        # Afwijkend zetten is vervallen (409-pad), gelijk zetten is een no-op mét audit.
        with pytest.raises(service.BeheerFout, match="is_vastgoed"):
            service.zet_verkoop_autoboeken_ingeschakeld(
                actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=False
            )
        assert (
            service.zet_verkoop_autoboeken_ingeschakeld(
                actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
            )
            is True
        )
        r = service.zet_is_vastgoed(actor_id=beheerder_id, administratie_id=administratie_id, is_vastgoed=False)
        assert r.verkoop_autoboeken_ingeschakeld is False and r.verkoop_autoboeken_uitgezet is True
