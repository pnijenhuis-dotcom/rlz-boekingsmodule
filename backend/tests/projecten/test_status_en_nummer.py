# ruff: noqa: F811 — pytest-fixtures als parameters
"""Blok 3 18-09 (Peter): projectstatus lopend/afgesloten + projectnummer uniek.

A — afsluiten zet EERST de bron inactief (RLZ klant-loze PUT mét bestaande naam + terugleesverificatie; Odoo `active=False`
via de company-client) en pas dán de module-status + audit; heropenen is het spiegelbeeld; RLZ wint bij conflict (bron
bevestigt niet → 502, status ongewijzigd); rolpoort Beheerder/B+P; afgesloten projecten verdwijnen uit de standaardlijst
(en via `is_actief` uit álle keuzelijsten) en blijven terugvindbaar onder de toggle; kandidaat-afsluiten deterministisch.
B — het projectnummer (cijfer-prefix) is uniek binnen de administratie over cache + RLZ: zelfde nummer met een andere
plaats/opdrachtgever = `ProjectnummerBestaatAl` (API 409 mét het bestaande project), exact dezelfde naam = idempotent;
dubbele nummers = lees-only rapport + reconciliatie-soort `project_nummer_dubbel` (stand `meten`).
Oranje signaal op een factuurregel naar een afgesloten project: `check_project_afgesloten` (nooit blokkerend)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from app.db.models import AuditEvent
from app.db.session import scoped_session
from app.documenten.checks import CheckRegel, check_project_afgesloten
from app.main import app
from app.projecten import kantoor, kantoorbreed
from app.projecten import nummer as nummer_module
from app.projecten import status as status_service
from app.reconciliatie import soort_stand
from app.reconciliatie.run import Verzamelaar
from app.security.tokens import create_access_token
from app.sync.models import ProjectCache
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.projecten.conftest import FakeProjectClient
from tests.uren.conftest import maak_gebruiker, maak_project

client = TestClient(app)
VANDAAG = date(2026, 9, 18)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str = "beheerder") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _project_via_motor(aid: uuid.UUID, actor: uuid.UUID, fake: FakeProjectClient, nummer="26127", plaats="Tilburg", og="Heijmans"):
    return kantoor.maak_project_aan(
        administratie_id=aid, actor_id=actor, projectnummer=nummer, plaats=plaats, opdrachtgever=og, client=fake
    )


def _rij(aid: uuid.UUID, pid: uuid.UUID) -> ProjectCache:
    with scoped_session(aid) as session:
        rij = session.get(ProjectCache, (pid, aid))
        session.expunge(rij)
        return rij


def _audit(aid: uuid.UUID, actie: str) -> list[AuditEvent]:
    # audit_event mét administratie_id is RLS-gescoopt — lezen binnen de administratie-scope.
    with scoped_session(aid) as session:
        return list(session.scalars(select(AuditEvent).where(AuditEvent.actie == actie)))


class TestAfsluitenHeropenen:
    def test_afsluiten_zet_bron_eerst_inactief_dan_status_met_audit(self, administratie_id, beheerder_id) -> None:
        fake = FakeProjectClient()
        res = _project_via_motor(administratie_id, beheerder_id, fake)
        stand = status_service.sluit_project_af(
            administratie_id=administratie_id,
            project_id=res.rlz_project_id,
            actor_id=beheerder_id,
            reden="Werk opgeleverd",
            datum=date(2026, 9, 15),
            client=fake,
        )
        assert stand.status == "afgesloten" and stand.is_actief is False and stand.afsluit_reden == "Werk opgeleverd"
        assert stand.afgesloten_op.date() == date(2026, 9, 15) and stand.afgesloten_door == beheerder_id
        # Bron: PUT mét de BESTAANDE naam en IsActive false; cache spiegelt de bron.
        rec = fake.projects[str(res.rlz_project_id)]
        assert rec["IsActive"] is False and rec["Name"] == "26127 Tilburg (Heijmans)"
        rij = _rij(administratie_id, res.rlz_project_id)
        assert (rij.status, rij.is_actief) == ("afgesloten", False)
        auditrij = _audit(administratie_id, "project_afgesloten")
        assert len(auditrij) == 1 and auditrij[0].oude_waarde["status"] == "lopend"
        assert auditrij[0].nieuwe_waarde["status"] == "afgesloten"
        # Nog een keer = 409-fout, niets gebeurd.
        with pytest.raises(status_service.StatusOngewijzigd):
            status_service.sluit_project_af(
                administratie_id=administratie_id, project_id=res.rlz_project_id, actor_id=beheerder_id, client=fake
            )
        # Terugweg.
        terug = status_service.heropen_project(
            administratie_id=administratie_id, project_id=res.rlz_project_id, actor_id=beheerder_id, client=fake
        )
        assert terug.status == "lopend" and terug.is_actief is True and terug.afsluit_reden is None
        assert fake.projects[str(res.rlz_project_id)]["IsActive"] is True
        assert len(_audit(administratie_id, "project_heropend")) == 1

    def test_rlz_wint_bij_conflict_status_ongewijzigd(self, administratie_id, beheerder_id) -> None:
        fake = FakeProjectClient()
        res = _project_via_motor(administratie_id, beheerder_id, fake)
        fake.negeer_is_active = True  # RLZ neemt IsActive niet over → teruglezen zegt nog true
        with pytest.raises(status_service.BronWeigert, match="RLZ wint"):
            status_service.sluit_project_af(
                administratie_id=administratie_id, project_id=res.rlz_project_id, actor_id=beheerder_id, client=fake
            )
        rij = _rij(administratie_id, res.rlz_project_id)
        assert (rij.status, rij.is_actief) == ("lopend", True)
        assert _audit(administratie_id, "project_afgesloten") == []

    def test_rolpoort_boekhouding_mag_niet_afsluiten(self, admin_engine: Engine, administratie_id, beheerder_id) -> None:
        fake = FakeProjectClient()
        res = _project_via_motor(administratie_id, beheerder_id, fake)
        boekhouder = maak_gebruiker(admin_engine, "boekhouding", "Barbara B.")
        with pytest.raises(kantoor.GeenSchrijfrecht):
            status_service.sluit_project_af(
                administratie_id=administratie_id, project_id=res.rlz_project_id, actor_id=boekhouder, client=fake
            )
        assert fake.projects[str(res.rlz_project_id)]["IsActive"] is True

    def test_odoo_administratie_archiveert_analytic_account_via_client(
        self, admin_engine: Engine, administratie_id, beheerder_id
    ) -> None:
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET boekhoud_backend = 'odoo' WHERE id = :id"), {"id": administratie_id}
            )
        pid = maak_project(admin_engine, administratie_id, "26050 Zwolle (Odoo)")
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE boekhouding.project_cache SET brondata = '{\"odoo_id\": 77, \"backend\": \"odoo\"}'::jsonb WHERE id = :id"),
                {"id": pid},
            )

        class NepOdoo:
            def __init__(self) -> None:
                self.writes: list[tuple[str, list[int], dict[str, Any]]] = []
                self.actief = True

            def write(self, model: str, ids: list[int], vals: dict[str, Any]) -> bool:
                self.writes.append((model, ids, vals))
                self.actief = bool(vals.get("active"))
                return True

            def search_read(self, model: str, domain: list, fields: list[str]) -> list[dict[str, Any]]:
                return [{"id": 77, "active": self.actief}]

            def close(self) -> None:
                pass

        odoo = NepOdoo()
        stand = status_service.sluit_project_af(
            administratie_id=administratie_id, project_id=pid, actor_id=beheerder_id, reden="klaar", client=odoo
        )
        assert stand.status == "afgesloten"
        assert odoo.writes == [("account.analytic.account", [77], {"active": False})]
        rij = _rij(administratie_id, pid)
        assert rij.is_actief is False and rij.status == "afgesloten"

    def test_lijst_standaard_zonder_afgesloten_toggle_met_en_teller(
        self, admin_engine: Engine, administratie_id, beheerder_id
    ) -> None:
        fake = FakeProjectClient()
        a = _project_via_motor(administratie_id, beheerder_id, fake, "26001", "Breda", "Moeskops")
        b = _project_via_motor(administratie_id, beheerder_id, fake, "26002", "Zwolle", "BAM")
        status_service.sluit_project_af(
            administratie_id=administratie_id, project_id=b.rlz_project_id, actor_id=beheerder_id, client=fake
        )
        standaard = kantoor.projecten_lijst(administratie_id=administratie_id)
        assert [r.project_id for r in standaard] == [a.rlz_project_id]
        alles = kantoor.projecten_lijst(administratie_id=administratie_id, alleen_actief=False)
        assert {r.project_id: r.status for r in alles} == {a.rlz_project_id: "lopend", b.rlz_project_id: "afgesloten"}
        assert kantoor.aantal_afgesloten(administratie_id=administratie_id) == 1
        detail = kantoor.project_detail(administratie_id=administratie_id, project_id=b.rlz_project_id)
        assert detail.status == "afgesloten" and detail.afgesloten_door == beheerder_id
        # Keuzelijst-bron (`GET /administraties/{id}/projecten` leest lijst_projects): het afgesloten project staat
        # onderaan als inactief — het combobox-patroon van 16-09 (zichtbaar, chip), nooit bovenaan.
        from app.sync import service as sync_service

        volgorde = sync_service.lijst_projects(administratie_id=administratie_id)
        assert [p.id for p in volgorde] == [a.rlz_project_id, b.rlz_project_id]
        assert volgorde[-1].is_actief is False

    def test_kantoorbreed_toggle_facet_en_tellers(self, admin_engine: Engine, administratie_id, beheerder_id) -> None:
        fake = FakeProjectClient()
        a = _project_via_motor(administratie_id, beheerder_id, fake, "26001", "Breda", "Moeskops")
        b = _project_via_motor(administratie_id, beheerder_id, fake, "26002", "Zwolle", "BAM")
        status_service.sluit_project_af(
            administratie_id=administratie_id, project_id=b.rlz_project_id, actor_id=beheerder_id, client=fake
        )
        zonder = kantoorbreed.lijst(actor_id=beheerder_id, rol="beheerder", vandaag=VANDAAG)
        assert [r.project_id for r in zonder.rijen] == [a.rlz_project_id]
        assert zonder.tellers.afgesloten == 1 and zonder.tellers.projecten == 1
        met = kantoorbreed.lijst(actor_id=beheerder_id, rol="beheerder", vandaag=VANDAAG, toon_afgesloten=True)
        assert [r.project_id for r in met.rijen] == [a.rlz_project_id, b.rlz_project_id]  # afgesloten onderaan
        assert met.rijen[-1].status == "afgesloten"
        facet = kantoorbreed.lijst(actor_id=beheerder_id, rol="beheerder", vandaag=VANDAAG, status="afgesloten")
        assert [r.project_id for r in facet.rijen] == [b.rlz_project_id]

    def test_api_afsluiten_en_heropenen(self, administratie_id, beheerder_id, monkeypatch) -> None:
        fake = FakeProjectClient()
        res = _project_via_motor(administratie_id, beheerder_id, fake)
        import app.rlz.credentials as cred

        monkeypatch.setattr(cred, "rlz_admin_id_voor", lambda aid: "fake-admin")
        monkeypatch.setattr(cred, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
        h = _bearer(beheerder_id)
        r = client.post(
            f"/projecten/{administratie_id}/{res.rlz_project_id}/afsluiten", json={"reden": "Opgeleverd"}, headers=h
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "afgesloten" and r.json()["afsluit_reden"] == "Opgeleverd"
        r2 = client.post(f"/projecten/{administratie_id}/{res.rlz_project_id}/afsluiten", json={}, headers=h)
        assert r2.status_code == 409
        lijst = client.get(f"/projecten/{administratie_id}", headers=h).json()
        assert lijst["projecten"] == [] and lijst["aantal_afgesloten"] == 1
        lijst_alles = client.get(f"/projecten/{administratie_id}?alleen_actief=false", headers=h).json()
        assert lijst_alles["projecten"][0]["status"] == "afgesloten"
        r3 = client.post(f"/projecten/{administratie_id}/{res.rlz_project_id}/heropenen", headers=h)
        assert r3.status_code == 200 and r3.json()["status"] == "lopend"
        detail = client.get(f"/projecten/{administratie_id}/{res.rlz_project_id}", headers=h).json()
        assert detail["status"] == "lopend" and detail["is_actief"] is True


# Kandidaat afsluiten: sinds 19-09 in `tests/projecten/test_afsluiten.py` (motor `app/projecten/afsluiten.py` — herziet het
# 18-09-criterium op contract-m²).


class TestProjectnummerUniek:
    def test_zelfde_nummer_andere_plaats_is_409_zelfde_naam_idempotent(self, administratie_id, beheerder_id) -> None:
        fake = FakeProjectClient()
        eerste = _project_via_motor(administratie_id, beheerder_id, fake, "26127", "Tilburg", "Heijmans")
        with pytest.raises(nummer_module.ProjectnummerBestaatAl) as exc:
            _project_via_motor(administratie_id, beheerder_id, fake, "26127", "Breda", "Moeskops")
        assert str(exc.value) == "26127 bestaat al: 26127 Tilburg (Heijmans), lopend — openen?"
        assert exc.value.als_detail()["bestaand_project_id"] == str(eerste.rlz_project_id)
        assert fake.put_project_aanroepen == 1  # niets aangemaakt
        # Exact dezelfde naam = idempotente herhaal-klik (bestond_al), geen 409.
        tweede = _project_via_motor(administratie_id, beheerder_id, fake, "26127", "Tilburg", "Heijmans")
        assert tweede.bestond_al is True and fake.put_project_aanroepen == 1

    def test_afgesloten_project_bezet_het_nummer_ook(self, administratie_id, beheerder_id) -> None:
        fake = FakeProjectClient()
        res = _project_via_motor(administratie_id, beheerder_id, fake, "26127", "Tilburg", "Heijmans")
        status_service.sluit_project_af(
            administratie_id=administratie_id, project_id=res.rlz_project_id, actor_id=beheerder_id, client=fake
        )
        with pytest.raises(nummer_module.ProjectnummerBestaatAl, match="afgesloten"):
            _project_via_motor(administratie_id, beheerder_id, fake, "26127", "Breda", "Moeskops")

    def test_rlz_treffer_buiten_de_cache_blokkeert_ook_en_prefix_is_exact(self, administratie_id, beheerder_id) -> None:
        fake = FakeProjectClient()
        # Buiten de module om in RLZ aangemaakt (ander GUID, niet in de cache).
        fake.projects["extern"] = {"id": str(uuid.uuid4()), "Name": "26127 Handmatig in RLZ (X)", "IsActive": True}
        fake.projects["lang"] = {"id": str(uuid.uuid4()), "Name": "261270 Ander nummer (Y)", "IsActive": True}
        with pytest.raises(nummer_module.ProjectnummerBestaatAl) as exc:
            _project_via_motor(administratie_id, beheerder_id, fake, "26127", "Tilburg", "Heijmans")
        assert exc.value.treffer.bron == "rlz"
        # 261270 is géén treffer voor 26127 (cijfer-prefix exact) en 26128 is vrij.
        res = _project_via_motor(administratie_id, beheerder_id, fake, "26128", "Tilburg", "Heijmans")
        assert res.bestond_al is False

    def test_api_409_met_bestaand_project(self, administratie_id, beheerder_id, monkeypatch) -> None:
        fake = FakeProjectClient()
        eerste = _project_via_motor(administratie_id, beheerder_id, fake, "26127", "Tilburg", "Heijmans")
        import app.projecten.kantoor as kantoor_module

        monkeypatch.setattr(kantoor_module, "rlz_admin_id_voor", lambda aid: "fake-admin")
        monkeypatch.setattr(kantoor_module, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
        r = client.post(
            f"/projecten/{administratie_id}",
            json={"projectnummer": "26127", "plaats": "Breda", "opdrachtgever": "Moeskops"},
            headers=_bearer(beheerder_id),
        )
        assert r.status_code == 409, r.text
        detail = r.json()["detail"]
        assert detail["code"] == "projectnummer_bestaat_al"
        assert detail["bestaand_project_id"] == str(eerste.rlz_project_id) and detail["status"] == "lopend"
        assert detail["melding"].startswith("26127 bestaat al: 26127 Tilburg (Heijmans)")

    def test_cijfer_prefix(self) -> None:
        assert nummer_module.cijfer_prefix("26127 Tilburg (Heijmans)") == "26127"
        assert nummer_module.cijfer_prefix("  26127Tilburg") == "26127"
        assert nummer_module.cijfer_prefix("Kantoorpand Eindhoven") is None
        assert nummer_module.cijfer_prefix(None) is None
        assert nummer_module.cijfer_prefix("1234567 te lang") is None


class TestDubbeleNummers:
    def test_rapport_en_reconciliatie_blok(self, admin_engine: Engine, administratie_id, beheerder_id) -> None:
        a = maak_project(admin_engine, administratie_id, "26127 Tilburg (Heijmans)")
        b = maak_project(admin_engine, administratie_id, "26127 Breda (Moeskops)")
        maak_project(admin_engine, administratie_id, "26128 Uniek (Z)")
        zzper = maak_gebruiker(admin_engine, "zzper", "Irfan O.")
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.planning_toewijzing (administratie_id, gebruiker_id, project_id, datum, dagdeel, "
                    "toegevoegd_door) VALUES (:aid, :gid, :pid, :d, 'heel', :gid)"
                ),
                {"aid": administratie_id, "gid": zzper, "pid": a, "d": VANDAAG},
            )
        with scoped_session(administratie_id) as session:
            dubbel = nummer_module.dubbele_nummers(session, administratie_id=administratie_id)
        assert [d.nummer for d in dubbel] == ["26127"]
        assert {t.project_id for t in dubbel[0].projecten} == {a, b}
        assert dubbel[0].tellers[a]["planning"] == 1 and dubbel[0].tellers[b]["planning"] == 0
        regels = nummer_module.rapportregels(dubbel)
        assert any("voorstel: blijft" in r and str(a) in r for r in regels)

        verzamelaar = Verzamelaar()
        verzamelaar.start_blok(nummer_module.BLOK)
        uit: list[str] = []
        exit_code = nummer_module.cli_blok(None, verzamelaar=verzamelaar, stdout=uit.append)
        assert exit_code == 1
        bev = [b for b in verzamelaar.bevindingen if b.blok == "projecten"]
        assert len(bev) == 1 and bev[0].detail["afwijking_soort"] == "project_nummer_dubbel"
        assert bev[0].vingerafdruk == f"projecten:{administratie_id}:26127"
        # Nieuwe soort start in `meten` (registry) — telt, geen actiemail.
        assert soort_stand.code_default("project_nummer_dubbel") == soort_stand.METEN
        from app.reconciliatie import teksten

        leesbaar = teksten.leesbaar(bev[0], administratie_naam="Scope-test")
        assert leesbaar.titel.startswith("Projectnummer dubbel") and "26127" in leesbaar.wat
        assert "nooit automatisch" in leesbaar.doe


class TestSignaalAfgeslotenProject:
    def test_check_is_oranje_signaal_nooit_blokkerend(self) -> None:
        pid = uuid.uuid4()
        regels = [
            CheckRegel(ledger_id=None, taxrate_id=None, netto_bedrag=Decimal("10"), btw_bedrag=None, project_id=pid),
            CheckRegel(ledger_id=None, taxrate_id=None, netto_bedrag=Decimal("10"), btw_bedrag=None, project_id=pid),
        ]
        uit = check_project_afgesloten(regels=regels, afgesloten={pid: ("26127 Tilburg (Heijmans)", date(2026, 9, 15))})
        assert uit is not None and uit.ok is True and uit.signaal is True
        assert uit.melding.count("26127") == 1 and "afgesloten op 15-09-2026" in uit.melding
        assert check_project_afgesloten(regels=regels, afgesloten={}) is None
