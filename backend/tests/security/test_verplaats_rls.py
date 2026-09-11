"""Verplaatsen naar een andere administratie onder een PRODUCTIE-GELIJKE functie-eigenaar (blok 1 run 11-09 middag).

Productie 11-09 11:55 (correlatie-id 2fa4a61b-…): `POST …/verplaats` → `InsufficientPrivilege: new row violates
row-level security policy for table "document"` in `boekhouding.verplaats_document` (0080). De suite zag dat nooit:
de test-DB migreert als superuser en de eigenaar omzeilt dan RLS. Hier draait de functie onder `rls_toets_eigenaar`
(tests/security/rls_eigenaar.py — lid van de migratierol, geen superuser, geen BYPASSRLS = Cloud SQL's `postgres`):

1. regressie-vangst: de LETTERLIJKE 0080-functietekst faalt onder die eigenaar met InsufficientPrivilege;
2. de 0132-functie (verplaatsing-policies + transactie-lokale GUC) slaagt via de échte servicelaag voor een
   niet-Beheerder mét scope op bron én doel (document + vraag + bericht + afwijzing + duplicaat_signaal mee,
   tijdlijn van→naar) en voor een Beheerder;
3. scope alleen op de bron → GeenScopeOpDoel → router 403 leesbaar (geen 500);
4. de app-rol die zélf de GUC zet ziet buiten de definer-context géén rij van het document in een andere scope;
5. router + centrale handler: een InsufficientPrivilege wordt een leesbare 500 "automatisch gemeld" + audit
   `rls_weigering`."""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from psycopg.errors import InsufficientPrivilege
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.auth import service as auth_service
from app.db.models import GebruikerRol
from app.db.rls_weigering import AUDIT_ACTIE
from app.db.session import scoped_session
from app.documenten import afwijzen, service, verplaatsen, vragen
from app.documenten import router as documenten_router
from app.documenten.models import DocumentBron, DocumentStatus
from app.main import _bouw_onverwachte_fout_response, app
from app.security.tokens import create_access_token
from tests.auth.conftest import administratie_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker  # noqa: F401
from tests.intake.conftest import bouw_ubl
from tests.security.rls_eigenaar import EIGENAAR, productie_eigenaar

client = TestClient(app)
MIGRATIE_0132 = (
    Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0132_verplaats_document_rls_uitzondering.py"
)


def _laad_0132():
    spec = importlib.util.spec_from_file_location("migratie_0132", MIGRATIE_0132)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _maak_administratie(admin_engine: Engine, naam: str) -> uuid.UUID:
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, :naam, :rlz)"),
            {"id": aid, "naam": naam, "rlz": f"rlz-{aid}"},
        )
    return aid


@pytest.fixture
def doel_id(admin_engine: Engine, beheerder_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID) -> uuid.UUID:  # noqa: F811
    aid = _maak_administratie(admin_engine, "Universal Verkoop (test)")
    auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=gescoopte_gebruiker, administratie_id=aid)
    return aid


@pytest.fixture
def andere_id(admin_engine: Engine) -> uuid.UUID:
    return _maak_administratie(admin_engine, "Elders BV")


@pytest.fixture
def eigenaar(admin_engine: Engine):
    with productie_eigenaar(admin_engine) as rol:
        yield rol


def _upload(bron_id: uuid.UUID, actor_id: uuid.UUID) -> uuid.UUID:
    resultaat = service.upload_document(
        administratie_id=bron_id,
        bestandsnaam="inv26010471 (1).xml",
        inhoud=bouw_ubl(klant="Universal Verkoop B.V.", factuurnummer=f"F-{uuid.uuid4().hex[:6]}"),
        actor_id=actor_id,
        bron=DocumentBron.EMAIL,
        tenaamstelling="Universal Verkoop B.V.",
    )
    assert resultaat.status == DocumentStatus.TE_CONTROLEREN
    return resultaat.document_id


def _rij(admin_engine: Engine, tabel: str, waar: str, params: dict) -> list:
    with admin_engine.connect() as conn:
        return conn.execute(text(f"SELECT administratie_id FROM boekhouding.{tabel} WHERE {waar}"), params).all()


def _rls_weigeringen(admin_engine: Engine) -> list:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT nieuwe_waarde, correlatie_id FROM platform.audit_event WHERE actie = :a ORDER BY tijdstip"),
            {"a": AUDIT_ACTIE},
        ).all()


class TestRegressieVangst:
    def test_eigenaar_is_geen_superuser_en_de_0080_tekst_faalt_op_rls(
        self,
        eigenaar: str,
        administratie_id: uuid.UUID,  # noqa: F811
        doel_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,  # noqa: F811
        admin_engine: Engine,
    ) -> None:
        """De letterlijke 0080-functie (zonder verplaatsing-GUC) onder een eigenaar zonder superuser/BYPASSRLS —
        exact de productiefout. Als deze test ooit groen wordt zonder 0132-uitzondering, is de eigenaar in de suite
        weer een bypass-rol en bewijst de rest van dit bestand niets meer."""
        m = _laad_0132()
        toets_naam = "boekhouding._verplaats_document_0080_toets"
        tekst_0080 = m.functie_tekst(met_verplaatsing_guc=False).replace(
            "CREATE OR REPLACE FUNCTION boekhouding.verplaats_document(", f"CREATE OR REPLACE FUNCTION {toets_naam}("
        )
        assert "app.verplaatsing_document_id" not in tekst_0080 and "verplichting_match" not in tekst_0080
        document_id = _upload(administratie_id, gescoopte_gebruiker)
        with admin_engine.begin() as conn:
            conn.execute(text(tekst_0080))
            conn.execute(text(f"ALTER FUNCTION {toets_naam}(uuid, uuid, uuid) OWNER TO {EIGENAAR}"))
            conn.execute(text(f"GRANT EXECUTE ON FUNCTION {toets_naam}(uuid, uuid, uuid) TO boekhouding_app"))
            conn.execute(
                text("UPDATE boekhouding.document SET status = 'ontvangen' WHERE id = :id"), {"id": document_id}
            )
        try:
            with (
                pytest.raises(DBAPIError) as fout,
                scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session,
            ):
                session.execute(
                    text(f"SELECT {toets_naam}(:d, :van, :naar)"),
                    {"d": document_id, "van": administratie_id, "naar": doel_id},
                )
            assert isinstance(fout.value.orig, InsufficientPrivilege)
            assert 'row-level security policy for table "document"' in str(fout.value.orig)
            # Niets gewijzigd: het document staat nog in de bron.
            assert _rij(admin_engine, "document", "id = :id", {"id": document_id}) == [(administratie_id,)]
        finally:
            with admin_engine.begin() as conn:
                conn.execute(text(f"DROP FUNCTION IF EXISTS {toets_naam}(uuid, uuid, uuid)"))


class TestVerplaatsenOnderProductieEigenaar:
    def test_niet_beheerder_met_scope_op_bron_en_doel_verhuist_alles(
        self,
        eigenaar: str,
        administratie_id: uuid.UUID,  # noqa: F811
        doel_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,  # noqa: F811
        admin_engine: Engine,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker)
        # Kindrijen mét eigen administratie_id: heropende afwijzing (historie), open vraag + bericht, duplicaat-cache.
        afwijzing = afwijzen.wijs_af(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            reden="Hoort bij Universal Verkoop",
            toegewezen_aan=gescoopte_gebruiker,
        )
        afwijzen.heropen(administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker)
        vraag = vragen.stel_vraag(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            vraag_tekst="Welke BV is dit?",
            toegewezen_aan=gescoopte_gebruiker,
        )
        vragen.plaats_bericht(
            administratie_id=administratie_id,
            vraag_id=vraag.id,
            actor_id=gescoopte_gebruiker,
            tekst="Universal Verkoop.",
        )
        # De duplicaat-cache (duplicaat_signaal, PK = document_id) zet de post-extractie-hook al in de bron.
        assert _rij(admin_engine, "duplicaat_signaal", "document_id = :d", {"d": document_id}) == [(administratie_id,)]
        with admin_engine.begin() as conn:
            berichten_voor = conn.execute(
                text("SELECT count(*) FROM boekhouding.vraag_bericht WHERE vraag_id = :v"), {"v": vraag.id}
            ).scalar_one()
        assert berichten_voor >= 1

        resultaat = verplaatsen.verplaats_document(
            administratie_id=administratie_id,
            document_id=document_id,
            doel_administratie_id=doel_id,
            actor_id=gescoopte_gebruiker,
            actor_rol=GebruikerRol.BOEKHOUDING,
        )
        assert resultaat.naar_administratie_id == doel_id
        assert resultaat.vragen_verhuisd == 1

        assert _rij(admin_engine, "document", "id = :id", {"id": document_id}) == [(doel_id,)]
        assert _rij(admin_engine, "afwijzing", "id = :id", {"id": afwijzing.id}) == [(doel_id,)]
        assert _rij(admin_engine, "vraag", "id = :id", {"id": vraag.id}) == [(doel_id,)]
        assert set(_rij(admin_engine, "vraag_bericht", "vraag_id = :v", {"v": vraag.id})) == {(doel_id,)}
        assert _rij(admin_engine, "duplicaat_signaal", "document_id = :d", {"d": document_id}) == [(doel_id,)]
        # Gat van ná 0080 (11-09): verplichting_match (PK = document_id) verhuist mee, zodat de her-extractie in het
        # doel 'm kan verversen i.p.v. op een onzichtbare bron-rij te botsen ("Verplichting-match mislukt" in de log).
        assert _rij(admin_engine, "verplichting_match", "document_id = :d", {"d": document_id}) == [(doel_id,)]
        assert not any("Verplichting-match mislukt" in r.getMessage() for r in caplog.records)
        # De GUC is ná de functie leeg (de verplaatsing-policies zijn buiten de functie dood).
        with admin_engine.connect() as conn:
            assert conn.execute(text("SELECT platform.verplaatsing_document_id()")).scalar_one() is None
        # Tijdlijn van→naar in het doel.
        detail = service.haal_document_op(administratie_id=doel_id, document_id=document_id)
        verhuis = next(g for g in detail.gebeurtenissen if g.detail and "verplaatst" in g.detail)
        assert verhuis.detail["verplaatst"]["van_administratie_id"] == str(administratie_id)
        assert verhuis.detail["verplaatst"]["naar_administratie_naam"] == "Universal Verkoop (test)"
        assert _rls_weigeringen(admin_engine) == []

    def test_beheerder_zonder_scoperijen_verhuist(
        self,
        eigenaar: str,
        administratie_id: uuid.UUID,  # noqa: F811
        andere_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,  # noqa: F811
        admin_engine: Engine,
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker)
        resultaat = verplaatsen.verplaats_document(
            administratie_id=administratie_id,
            document_id=document_id,
            doel_administratie_id=andere_id,
            actor_id=beheerder_id,
            actor_rol=GebruikerRol.BEHEERDER,
        )
        assert resultaat.naar_administratie_naam == "Elders BV"
        assert _rij(admin_engine, "document", "id = :id", {"id": document_id}) == [(andere_id,)]

    def test_scope_alleen_op_bron_is_403_leesbaar(
        self,
        eigenaar: str,
        administratie_id: uuid.UUID,  # noqa: F811
        andere_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,  # noqa: F811
        admin_engine: Engine,
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker)
        with pytest.raises(verplaatsen.GeenScopeOpDoel):
            verplaatsen.verplaats_document(
                administratie_id=administratie_id,
                document_id=document_id,
                doel_administratie_id=andere_id,
                actor_id=gescoopte_gebruiker,
                actor_rol=GebruikerRol.BOEKHOUDING,
            )
        resp = client.post(
            f"/administraties/{administratie_id}/documenten/{document_id}/verplaats",
            json={"doel_administratie_id": str(andere_id)},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 403
        assert resp.json()["detail"].startswith("Verplaatsen niet toegestaan voor jouw scope")
        assert "Elders BV" in resp.json()["detail"]
        assert _rij(admin_engine, "document", "id = :id", {"id": document_id}) == [(administratie_id,)]

    def test_http_endpoint_slaagt_onder_productie_eigenaar(
        self,
        eigenaar: str,
        administratie_id: uuid.UUID,  # noqa: F811
        doel_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,  # noqa: F811
        admin_engine: Engine,
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker)
        resp = client.post(
            f"/administraties/{administratie_id}/documenten/{document_id}/verplaats",
            json={"doel_administratie_id": str(doel_id)},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["naar_administratie_naam"] == "Universal Verkoop (test)"
        assert _rij(admin_engine, "document", "id = :id", {"id": document_id}) == [(doel_id,)]


class TestPolicyDoodBuitenDefinerContext:
    def test_app_rol_die_zelf_de_guc_zet_ziet_niets_in_een_andere_scope(
        self,
        administratie_id: uuid.UUID,  # noqa: F811
        andere_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,  # noqa: F811
        app_engine: Engine,
        admin_engine: Engine,
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker)
        with app_engine.connect() as conn:
            conn.execute(text("SELECT set_config('app.current_administratie_id', :a, true)"), {"a": str(andere_id)})
            conn.execute(text("SELECT set_config('app.verplaatsing_document_id', :d, true)"), {"d": str(document_id)})
            assert conn.execute(text("SELECT current_user = session_user")).scalar_one() is True
            zichtbaar = conn.execute(
                text("SELECT count(*) FROM boekhouding.document WHERE id = :d"), {"d": document_id}
            ).scalar_one()
            geraakt = conn.execute(
                text("UPDATE boekhouding.document SET administratie_id = :a WHERE id = :d"),
                {"a": str(andere_id), "d": document_id},
            ).rowcount
            conn.rollback()
        assert zichtbaar == 0 and geraakt == 0
        assert _rij(admin_engine, "document", "id = :id", {"id": document_id}) == [(administratie_id,)]

    def test_in_de_eigen_scope_geeft_de_guc_geen_extra_rechten(
        self,
        administratie_id: uuid.UUID,  # noqa: F811
        andere_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,  # noqa: F811
        app_engine: Engine,
    ) -> None:
        """Wél zichtbaar in de eigen scope (gewone policy), maar de administratie wisselen blijft geweigerd."""
        document_id = _upload(administratie_id, gescoopte_gebruiker)
        with app_engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_administratie_id', :a, true)"), {"a": str(administratie_id)}
            )
            conn.execute(text("SELECT set_config('app.verplaatsing_document_id', :d, true)"), {"d": str(document_id)})
            with pytest.raises(ProgrammingError) as fout:
                conn.execute(
                    text("UPDATE boekhouding.document SET administratie_id = :a WHERE id = :d"),
                    {"a": str(andere_id), "d": document_id},
                )
            conn.rollback()
        assert isinstance(fout.value.orig, InsufficientPrivilege)


def _rls_fout() -> ProgrammingError:
    orig = InsufficientPrivilege('new row violates row-level security policy for table "document"')
    return ProgrammingError("UPDATE boekhouding.document …", {}, orig)


class TestSysteemfoutAutomatischGemeld:
    def test_router_vertaalt_rls_weigering_naar_leesbare_500_en_audit(
        self,
        administratie_id: uuid.UUID,  # noqa: F811
        doel_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,  # noqa: F811
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker)

        def ontploft(**kw):
            raise _rls_fout()

        monkeypatch.setattr(documenten_router.verplaatsen, "verplaats_document", ontploft)
        resp = client.post(
            f"/administraties/{administratie_id}/documenten/{document_id}/verplaats",
            json={"doel_administratie_id": str(doel_id)},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 500
        detail = resp.json()["detail"]
        assert detail.startswith("Verplaatsen is mislukt — automatisch gemeld (code ")
        rijen = _rls_weigeringen(admin_engine)
        assert len(rijen) == 1
        nw, correlatie_id = rijen[0]
        assert str(correlatie_id) in detail
        assert nw["route"] == f"/administraties/{administratie_id}/documenten/{document_id}/verplaats"
        assert nw["methode"] == "POST" and nw["tabel"] == "document"
        assert nw["gebruiker_id"] == str(gescoopte_gebruiker)
        assert nw["doel_administratie_id"] == str(doel_id)

    def test_andere_db_fout_blijft_het_algemene_vangnet(
        self,
        administratie_id: uuid.UUID,  # noqa: F811
        doel_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,  # noqa: F811
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker)

        def ontploft(**kw):
            raise ProgrammingError("SELECT 1", {}, Exception("syntax error"))

        monkeypatch.setattr(documenten_router.verplaatsen, "verplaats_document", ontploft)
        resp = client.post(
            f"/administraties/{administratie_id}/documenten/{document_id}/verplaats",
            json={"doel_administratie_id": str(doel_id)},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 500
        assert "code " in resp.json()["detail"] and "automatisch gemeld" not in resp.json()["detail"]
        assert _rls_weigeringen(admin_engine) == []

    def test_centrale_handler_herkent_rls_weigering_in_de_keten(
        self,
        gescoopte_gebruiker: uuid.UUID,  # noqa: F811
        admin_engine: Engine,
    ) -> None:
        token = create_access_token(gescoopte_gebruiker, rol="boekhouding")
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/administraties/x/iets",
                "raw_path": b"/administraties/x/iets",
                "query_string": b"",
                "headers": [(b"authorization", f"Bearer {token}".encode())],
                "scheme": "http",
                "server": ("test", 80),
            }
        )
        try:
            try:
                raise _rls_fout()
            except ProgrammingError as binnen:
                raise RuntimeError("wrapper") from binnen
        except RuntimeError as exc:
            response = _bouw_onverwachte_fout_response(request, exc)
        assert response.status_code == 500
        assert "automatisch gemeld" in bytes(response.body).decode()
        rijen = _rls_weigeringen(admin_engine)
        assert len(rijen) == 1
        assert rijen[0][0]["route"] == "/administraties/x/iets" and rijen[0][0]["gebruiker_id"] == str(
            gescoopte_gebruiker
        )

    def test_centrale_handler_zonder_rls_weigering_schrijft_geen_audit(self, admin_engine: Engine) -> None:
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/x",
                "raw_path": b"/x",
                "query_string": b"",
                "headers": [],
                "scheme": "http",
                "server": ("test", 80),
            }
        )
        try:
            raise RuntimeError("gewoon kapot")
        except RuntimeError as exc:
            response = _bouw_onverwachte_fout_response(request, exc)
        assert response.status_code == 500 and "automatisch gemeld" not in bytes(response.body).decode()
        assert _rls_weigeringen(admin_engine) == []
