# ruff: noqa: F811 — pytest-fixtures als parameters
"""Feiten eerst (Peter 17-09): querybibliotheek, SELECT-only-poort, uitvoering per administratie-scope (RLS), vrije SELECT
uitsluitend op de leesreplica als Beheerder, Beheerder-only routes, audit per aanroep, en de read-only rol `rlz_lezer`
(migratie 0154) die aantoonbaar niet kan schrijven — als echte niet-eigenaar-test (SET ROLE), niet als aanname."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from app import cli
from app.config import settings
from app.db.models import AuditEvent
from app.db.session import scoped_session
from app.lezen import bibliotheek, service, sql_poort, uitvoer
from app.main import app
from app.security.tokens import create_access_token
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.bank.conftest import maak_bank_mutatie

client = TestClient(app)


def _bearer(gid: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gid, rol=rol)}"}


class TestBibliotheek:
    def test_alle_queries_laden_en_zijn_select_only_met_kop(self) -> None:
        alle = bibliotheek.laad_alle()
        verwacht = {
            "document-feiten", "bankmutatie-feiten", "reconciliatie-bevindingen", "sync-status", "project-cache",
            "whitelist-doelen", "documenten-zonder", "correcties", "activa-stand", "documenten-open", "administratie-stand", "grootboek-taal",
        }
        assert verwacht <= set(alle)
        for q in alle.values():
            assert q.versie and q.doel and q.kolommen
            assert q.scope in bibliotheek.SCOPES
            if q.scope == "administratie":
                assert "administratie_id" in q.parameters

    def test_kop_ontbreekt_of_schrijfwoord_is_rood(self, tmp_path: Path) -> None:
        p = tmp_path / "x.sql"
        p.write_text("-- naam: x\nSELECT 1", encoding="utf-8")
        with pytest.raises(bibliotheek.OngeldigeQueryDefinitie):
            bibliotheek.parse(p.read_text(), pad=p)
        p.write_text("-- naam: x\n-- versie: 1\n-- doel: d\n-- scope: platform\n-- parameters: -\n-- kolommen: a\nDELETE FROM platform.groep", encoding="utf-8")
        with pytest.raises(sql_poort.GeenSelect):
            bibliotheek.parse(p.read_text(), pad=p)
        p.write_text("-- naam: x\n-- versie: 1\n-- doel: d\n-- scope: platform\n-- parameters: -\n-- kolommen: a\nSELECT :onbekend", encoding="utf-8")
        with pytest.raises(bibliotheek.OngeldigeQueryDefinitie):
            bibliotheek.parse(p.read_text(), pad=p)
        with pytest.raises(bibliotheek.OnbekendeQuery):
            bibliotheek.zoek("bestaat-niet")


class TestSqlPoort:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT 1",
            "  select id from platform.administratie limit 5;",
            "WITH a AS (SELECT 1 AS x) SELECT x FROM a",
            "SELECT 1 -- commentaar met DELETE erin\n",
        ],
    )
    def test_select_toegestaan(self, sql: str) -> None:
        assert sql_poort.toets_select_only(sql)

    @pytest.mark.parametrize(
        "sql",
        [
            "",
            "DELETE FROM platform.groep",
            "SELECT 1; DELETE FROM platform.groep",
            "UPDATE boekhouding.document SET status='x'",
            "SELECT set_config('app.current_actor_id','x',true)",
            "SELECT pg_read_file('/etc/passwd')",
            "COPY platform.gebruiker TO '/tmp/x'",
            "WITH d AS (DELETE FROM platform.groep RETURNING *) SELECT * FROM d",
            "SET ROLE postgres",
            "SELECT pg_sleep(100)",
        ],
    )
    def test_alles_anders_geweigerd(self, sql: str) -> None:
        with pytest.raises(sql_poort.GeenSelect):
            sql_poort.toets_select_only(sql)


class TestUitvoer:
    def test_anonimisering_en_plafond(self) -> None:
        r = uitvoer.bouw_resultaat(
            ["tegenpartij_naam", "tegenrekening_iban", "omschrijving", "bedrag"],
            [("Hello Kitchen Duiven", "NL91 ABNA 0417 1646 32", "betaling NL91ABNA0417164632 factuur", 12600)] * 3,
            max_rijen=2,
        )
        assert r.totaal == 3 and r.afgekapt and len(r.rijen) == 2
        assert r.rijen[0][0] == "H.K.D." and r.rijen[0][1] == "…4632" and "…4632" in r.rijen[0][2] and "NL91" not in r.rijen[0][2]
        md = uitvoer.als_markdown(r)
        assert "| tegenpartij_naam |" in md and "3 rij(en), eerste 2 getoond" in md
        assert '"totaal": 3' in uitvoer.als_json(r)


class TestService:
    def test_bibliotheek_query_per_administratie_met_audit(self, administratie_id: uuid.UUID, admin_engine: Engine) -> None:
        maak_bank_mutatie(admin_engine, administratie_id=administratie_id, bedrag="-77.00", omschrijving="test Koppe", tegenrekening_iban="NL91ABNA0417164632", boekdatum="2026-08-15")
        u = service.voer_query_uit("bankmutatie-feiten", {"omschrijving": "koppe"}, administratie_id=administratie_id)
        assert u.resultaat.totaal == 1 and u.resultaat.administraties == 1
        rij = dict(zip(u.resultaat.kolommen, u.resultaat.rijen[0], strict=False))
        assert rij["richting"] == "uitgaand" and rij["tegenrekening_iban"] == "…4632" and rij["boekdatum"].isoformat() == "2026-08-15"
        # Zonder --administratie: alle administraties in scope, zelfde treffer.
        alles = service.voer_query_uit("bankmutatie-feiten", {"omschrijving": "koppe"})
        assert alles.resultaat.totaal == 1
        with pytest.raises(service.OntbrekendeParameter):
            service.voer_query_uit("documenten-zonder", {}, administratie_id=administratie_id)
        with pytest.raises(service.OntbrekendeParameter):
            service.voer_query_uit("bankmutatie-feiten", {"onzin": "1"}, administratie_id=administratie_id)
        with scoped_session(None) as session:
            audit = session.scalars(select(AuditEvent).where(AuditEvent.actie == "db_lezen")).all()
        assert len(audit) >= 2 and audit[-1].nieuwe_waarde["query"] == "bankmutatie-feiten"

    def test_vrije_sql_weigert_zonder_replica_en_zonder_beheerder(self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
        assert settings.lees_database_url == "", "vaste testconfig: geen replica"
        with pytest.raises(service.GeenLeesreplica):
            service.voer_sql_uit("SELECT 1", actor_id=beheerder_id)
        with pytest.raises(sql_poort.GeenSelect):
            service.voer_sql_uit("DELETE FROM platform.groep", actor_id=beheerder_id)
        with pytest.raises(service.GeenBeheerder):
            service.voer_sql_uit("SELECT 1", actor_id=uuid.uuid4(), engine=None)

    def test_vrije_sql_op_een_replica_engine_leest_read_only_als_beheerder_met_audit(self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, app_engine: Engine, admin_engine: Engine) -> None:
        # De testdatabase speelt de replica (engine geïnjecteerd): READ ONLY-transactie, actor gezet, plafond, audit.
        maak_bank_mutatie(admin_engine, administratie_id=administratie_id, bedrag="-1.00", omschrijving="replica-test")
        # bank_mutatie heeft een strikt administratie-beleid (geen Beheerder-clausule): zonder scope 0 rijen — RLS blijft gelden.
        leeg = service.voer_sql_uit(
            "SELECT omschrijving FROM boekhouding.bank_mutatie WHERE omschrijving = 'replica-test'", actor_id=beheerder_id, engine=app_engine
        )
        assert leeg.resultaat.totaal == 0
        u = service.voer_sql_uit(
            "SELECT omschrijving, bedrag FROM boekhouding.bank_mutatie WHERE omschrijving = 'replica-test'",
            actor_id=beheerder_id,
            administratie_id=administratie_id,
            engine=app_engine,
            max_rijen=5,
        )
        assert u.resultaat.totaal == 1 and u.resultaat.rijen[0][0] == "replica-test"
        with scoped_session(None) as session:
            audit = session.scalars(select(AuditEvent).where(AuditEvent.actie == "db_lezen_sql")).all()
        assert len(audit) == 2 and audit[-1].nieuwe_waarde["rijen"] == 1 and len(audit[-1].nieuwe_waarde["sha256"]) == 64


class TestReadOnlyRol:
    def test_rlz_lezer_kan_lezen_maar_niets_schrijven_echte_niet_eigenaar_test(self, admin_engine: Engine) -> None:
        with admin_engine.connect() as conn:
            conn.execute(text("BEGIN"))
            conn.execute(text("SET LOCAL ROLE rlz_lezer"))
            assert conn.execute(text("SELECT count(*) FROM platform.administratie")).scalar() is not None
            for stmt in (
                "INSERT INTO platform.groep (id, naam, code, actief) VALUES (gen_random_uuid(), 'x', 'X9', true)",
                "UPDATE platform.administratie SET naam = naam",
                "DELETE FROM platform.audit_event",
                "CREATE TABLE boekhouding.lezer_probe (id int)",
            ):
                with pytest.raises(Exception, match="permission denied|must be owner|InsufficientPrivilege"):
                    conn.execute(text("SAVEPOINT s"))
                    try:
                        conn.execute(text(stmt))
                    finally:
                        conn.execute(text("ROLLBACK TO SAVEPOINT s"))
            conn.execute(text("ROLLBACK"))


class TestRoutes:
    def test_beheerder_only_en_foutvertaling(self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
        hb = _bearer(beheerder_id, rol="beheerder")
        r = client.get("/lezen/queries", headers=hb)
        assert r.status_code == 200 and any(q["naam"] == "document-feiten" for q in r.json())
        r = client.post("/lezen/query/bankmutatie-feiten", json={"params": {"omschrijving": "x"}, "administratie_id": str(administratie_id)}, headers=hb)
        assert r.status_code == 200 and r.json()["query"] == "bankmutatie-feiten" and r.json()["totaal"] == 0
        assert client.post("/lezen/query/bestaat-niet", json={}, headers=hb).status_code == 404
        assert client.post("/lezen/query/documenten-zonder", json={}, headers=hb).status_code == 422
        assert client.post("/lezen/sql", json={"sql": "DELETE FROM platform.groep"}, headers=hb).status_code == 422
        assert client.post("/lezen/sql", json={"sql": "SELECT 1"}, headers=hb).status_code == 503  # geen replica
        # Niet-Beheerder: fail-closed.
        ander = uuid.uuid4()
        assert client.get("/lezen/queries", headers=_bearer(ander, rol="boekhouding")).status_code in (401, 403)
        assert client.post("/lezen/sql", json={"sql": "SELECT 1"}, headers=_bearer(ander, rol="boekhouding")).status_code in (401, 403)


class TestCli:
    def test_db_lezen_overzicht_query_en_weigeringen(self, capsys, administratie_id: uuid.UUID, admin_engine: Engine) -> None:
        assert cli.main(["db-lezen"]) == 0
        assert "bankmutatie-feiten" in capsys.readouterr().out
        maak_bank_mutatie(admin_engine, administratie_id=administratie_id, bedrag="-5.00", omschrijving="cli-test")
        assert cli.main(["db-lezen", "bankmutatie-feiten", "--param", "omschrijving=cli-test", "--administratie", str(administratie_id), "--json"]) == 0
        uit = capsys.readouterr().out
        assert "| administratie |" in uit and "cli-test" in uit and '"totaal": 1' in uit
        assert cli.main(["db-lezen", "bestaat-niet"]) == 2
        assert cli.main(["db-lezen", "bankmutatie-feiten", "--param", "kapot"]) == 2
        assert cli.main(["db-lezen", "--sql", "SELECT 1"]) == 2  # zonder --als
        assert cli.main(["db-lezen", "--sql", "SELECT 1", "--als", "niemand@test.local"]) == 2  # geen beheerder


class TestDocumentenOpen:
    """Bundelrun 24-09: meetlat-query `documenten-open` (blok 1 tweelingen / 7a Van Boxtel / 7b samenvoegen) — optionele filters,
    aantal opgeslagen regels en veldvoorstel-bedragen per open document; afgehandelde statussen vallen weg."""

    def test_documenten_open_filters_en_kolommen(self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, tmp_path: Path) -> None:
        from app.documenten import service as documenten_service
        from app.documenten.models import Document, DocumentStatus
        from app.documenten.storage import LokaleBestandsopslag

        opslag = LokaleBestandsopslag(tmp_path)
        open_doc = documenten_service.upload_document(
            administratie_id=administratie_id, bestandsnaam="factuur-RUB-2026-0031.pdf", inhoud=b"%PDF-1.4 rub", actor_id=beheerder_id, opslag=opslag
        )
        oud = documenten_service.upload_document(
            administratie_id=administratie_id, bestandsnaam="oud.pdf", inhoud=b"%PDF-1.4 oud", actor_id=beheerder_id, opslag=opslag
        )
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            session.get(Document, oud.document_id).status = DocumentStatus.GEBOEKT
        u = service.voer_query_uit("documenten-open", {}, administratie_id=administratie_id)
        assert u.resultaat.totaal == 1
        rij = dict(zip(u.resultaat.kolommen, u.resultaat.rijen[0], strict=False))
        assert rij["bestandsnaam"] == "factuur-RUB-2026-0031.pdf" and str(rij["document_id"]).startswith(str(open_doc.document_id)[:8])
        assert rij["opgeslagen_regels"] == 0 and rij["veldvoorstel_regels_met_netto"] == 0
        assert service.voer_query_uit("documenten-open", {"bestandsnaam": "RUB-2026"}, administratie_id=administratie_id).resultaat.totaal == 1
        assert service.voer_query_uit("documenten-open", {"bestandsnaam": "MEY-2026"}, administratie_id=administratie_id).resultaat.totaal == 0
        assert service.voer_query_uit("documenten-open", {"soort": "kassarapport"}, administratie_id=administratie_id).resultaat.totaal == 0


class TestAdministratieStandEnGrootboekTaal:
    """Bundelrun 24-09: meetlatten blok 3 (dearchiveren Odoo: actief/gearchiveerd_op/backend/company/probe_op per naamdeel, platformbreed)
    en blok 2 (Odoo taal-poort: Engelse rekeningnamen per administratie)."""

    def test_administratie_stand_platformbreed_met_naamfilter(self, administratie_id: uuid.UUID) -> None:
        u = service.voer_query_uit("administratie-stand", {})
        kolommen = u.resultaat.kolommen
        assert {"naam", "actief", "gearchiveerd_op", "boekhoud_backend", "odoo_company_id", "odoo_probe_op", "rlz_credential_aanwezig"} <= set(kolommen)
        rijen = [dict(zip(kolommen, r, strict=False)) for r in u.resultaat.rijen]
        assert any(str(r["administratie_id"]).startswith(str(administratie_id)[:8]) for r in rijen)
        assert service.voer_query_uit("administratie-stand", {"naam": "bestaat-niet-zzz"}).resultaat.totaal == 0

    def test_grootboek_taal_telt_engelse_namen(self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID) -> None:
        from app.db.models import Grootboekrekening

        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            for code, naam in (("1300", "Account Receivable"), ("1600", "Crediteuren"), ("4000", "Salaries Expenses")):
                session.add(
                    Grootboekrekening(ledger_id=uuid.uuid4(), administratie_id=administratie_id, code=code, naam=naam, soort=2, is_totaalrekening=False)
                )
        u = service.voer_query_uit("grootboek-taal", {}, administratie_id=administratie_id)
        rij = dict(zip(u.resultaat.kolommen, u.resultaat.rijen[0], strict=False))
        assert rij["totaal"] >= 3 and rij["engels"] == 2 and "1300 Account Receivable" in rij["voorbeelden"]
