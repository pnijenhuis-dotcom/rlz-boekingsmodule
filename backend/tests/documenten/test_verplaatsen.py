"""Document verplaatsen naar een andere administratie (addendum kantoor-run 27-08 punt 5).

Dekt: de volledige verhuizing (document + bestanden + tijdlijn + boekvoorstel weg + her-extractie in
het doel), het toewijzings-geheugen dat mee terugleert (alleen de regel die naar de oude administratie
wees), de status-poorten (geboekt/ter_accordering = 409-klasse), scope op het doel, open vragen die
meeverhuizen (+ hertoewijzing zonder doel-scope + terug op vraag_open ná de extractie), een open
afwijzing die door de verhuizing sluit, de DB-functie-poorten (bron-scope + status ontvangen) en de
HTTP-laag."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.auth import service as auth_service
from app.db.models import GebruikerRol
from app.db.session import scoped_session
from app.documenten import afwijzen, service, verplaatsen, vragen
from app.documenten.models import DocumentBron, DocumentStatus
from app.intake.toewijzing import bepaal_toewijzing, leer_toewijzing
from app.main import app
from app.security.tokens import create_access_token
from tests.intake.conftest import bouw_ubl

client = TestClient(app)

TENAAMSTELLING = "Port of Rotterdam N.V."
AFZENDER = "facturen@arvum.example"


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


@pytest.fixture
def doel_id(admin_engine: Engine, beheerder_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID) -> uuid.UUID:
    """Tweede administratie waar de boekhouder óók scope op heeft; eigenaar = de Beheerder."""
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.administratie (id, naam, rlz_admin_id, eigenaar_gebruiker_id) "
                "VALUES (:id, 'Port of Rotterdam (test)', :rlz, :eig)"
            ),
            {"id": aid, "rlz": f"rlz-{aid}", "eig": beheerder_id},
        )
    auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=gescoopte_gebruiker, administratie_id=aid)
    return aid


@pytest.fixture
def andere_id(admin_engine: Engine) -> uuid.UUID:
    """Derde administratie zónder scope voor de boekhouder."""
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Elders BV', :rlz)"),
            {"id": aid, "rlz": f"rlz-{aid}"},
        )
    return aid


def _upload(administratie_id: uuid.UUID, actor_id: uuid.UUID, *, naam: str = "factuur.xml") -> uuid.UUID:
    """UBL = deterministische extractie → direct te_controleren (geen AI nodig in de test)."""
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=naam,
        inhoud=bouw_ubl(klant=TENAAMSTELLING, factuurnummer=f"F-{uuid.uuid4().hex[:6]}"),
        actor_id=actor_id,
        bron=DocumentBron.EMAIL,
        tenaamstelling=TENAAMSTELLING,
        afzender_hint=AFZENDER,
    )
    assert resultaat.status == DocumentStatus.TE_CONTROLEREN
    return resultaat.document_id


def _leer_naar(administratie_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    with scoped_session(None, actor_id=actor_id) as session:
        leer_toewijzing(
            session,
            administratie_id=administratie_id,
            actor_id=actor_id,
            tenaamstelling=TENAAMSTELLING,
            afzender=AFZENDER,
        )


def _document_rij(admin_engine: Engine, document_id: uuid.UUID):
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT administratie_id, status, opslag_pad, toegewezen_aan, mogelijk_duplicaat_van_id "
                "FROM boekhouding.document WHERE id = :id"
            ),
            {"id": document_id},
        ).one()


def _actieve_regels(admin_engine: Engine) -> set[tuple[str, uuid.UUID]]:
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text("SELECT soort, administratie_id FROM boekhouding.toewijzing_regel WHERE actief")
        ).all()
    return {(r.soort, r.administratie_id) for r in rijen}


def _zet_status(admin_engine: Engine, document_id: uuid.UUID, status: str) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE boekhouding.document SET status = :s WHERE id = :id"), {"s": status, "id": document_id}
        )


class TestVerplaatsen:
    def test_volledige_verhuizing_met_herextractie_en_geheugen_correctie(
        self,
        administratie_id: uuid.UUID,
        doel_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        _leer_naar(administratie_id, gescoopte_gebruiker)  # de foute leer-regel die de toewijzing veroorzaakte
        document_id = _upload(administratie_id, gescoopte_gebruiker)
        oud = _document_rij(admin_engine, document_id)
        assert oud.opslag_pad.startswith(f"{administratie_id}/")

        resultaat = verplaatsen.verplaats_document(
            administratie_id=administratie_id,
            document_id=document_id,
            doel_administratie_id=doel_id,
            actor_id=gescoopte_gebruiker,
            actor_rol=GebruikerRol.BOEKHOUDING,
        )
        assert resultaat.naar_administratie_id == doel_id
        assert resultaat.naar_administratie_naam == "Port of Rotterdam (test)"
        # UBL → de her-extractie in het doel is direct klaar.
        assert resultaat.status == DocumentStatus.TE_CONTROLEREN
        assert set(resultaat.leerregels_gecorrigeerd) == {"tenaamstelling", "afzender"}

        nieuw = _document_rij(admin_engine, document_id)
        assert nieuw.administratie_id == doel_id
        assert nieuw.status == "te_controleren"
        assert nieuw.opslag_pad.startswith(f"{doel_id}/")
        assert nieuw.toegewezen_aan is None
        # Bestand is in het doel leesbaar (kopie), het origineel blijft staan (retentie).
        with scoped_session(doel_id) as session:
            from app.documenten.models import Document

            doc = session.get(Document, document_id)
            assert doc is not None
            assert service._standaard_opslag().bestaat(pad=doc.opslag_pad)
        assert service._standaard_opslag().bestaat(pad=oud.opslag_pad)

        # Onzichtbaar in de bron, zichtbaar in het doel — mét tijdlijn incl. de verhuisregel en
        # een NIEUW veldvoorstel ná de "vervallen"-markering.
        with pytest.raises(service.DocumentNietGevonden):
            service.haal_document_op(administratie_id=administratie_id, document_id=document_id)
        detail = service.haal_document_op(administratie_id=doel_id, document_id=document_id)
        verhuis = [g for g in detail.gebeurtenissen if g.detail and "verplaatst" in g.detail]
        assert len(verhuis) == 1
        assert verhuis[0].naar_status == DocumentStatus.ONTVANGEN
        assert verhuis[0].detail["verplaatst"]["van_administratie_id"] == str(administratie_id)
        assert verhuis[0].detail["verplaatst"]["naar_administratie_naam"] == "Port of Rotterdam (test)"
        assert verhuis[0].detail["veldvoorstel_vervallen"] is True
        assert verhuis[0].detail["leerregels_gecorrigeerd"] == ["tenaamstelling", "afzender"]
        index_verhuis = detail.gebeurtenissen.index(verhuis[0])
        assert any("veldvoorstel" in (g.detail or {}) for g in detail.gebeurtenissen[index_verhuis + 1 :])
        assert detail.veldvoorstel is not None

        # Het geheugen leert mee terug: de volgende mail van deze afzender/tenaamstelling landt goed.
        assert _actieve_regels(admin_engine) == {("tenaamstelling", doel_id), ("afzender", doel_id)}
        with scoped_session(None) as session:
            besluit = bepaal_toewijzing(session, tenaamstelling=TENAAMSTELLING, afzender=AFZENDER)
        assert besluit.administratie_id == doel_id

        # Platform-breed audit-feit + bron-audit van de statusovergang.
        with admin_engine.connect() as conn:
            acties = conn.execute(
                text(
                    "SELECT actie, administratie_id FROM platform.audit_event WHERE record_id = :id ORDER BY tijdstip"
                ),
                {"id": document_id},
            ).all()
        assert ("document_verplaatst", None) in {(a.actie, a.administratie_id) for a in acties}
        assert ("status_ontvangen", administratie_id) in {(a.actie, a.administratie_id) for a in acties}

    def test_boekvoorstel_wordt_weggegooid_en_duplicaatvlag_opnieuw_bepaald(
        self,
        administratie_id: uuid.UUID,
        doel_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        from app.documenten import boekvoorstel as boekvoorstel_service

        document_id = _upload(administratie_id, gescoopte_gebruiker)
        boekvoorstel_service.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            vendor_id=None,
            referentie="F-1",
            factuurdatum=None,
            totaalbedrag=None,
            regels=[],
        )
        # Zelfde bytes bestaan al in het DOEL → daar wordt het verplaatste document een mogelijk duplicaat.
        inhoud = bouw_ubl(klant=TENAAMSTELLING, factuurnummer="F-DUP")
        origineel = service.upload_document(
            administratie_id=doel_id, bestandsnaam="a.xml", inhoud=inhoud, actor_id=gescoopte_gebruiker
        ).document_id
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE boekhouding.document SET sha256_hash = "
                    "(SELECT sha256_hash FROM boekhouding.document WHERE id = :o) WHERE id = :d"
                ),
                {"o": origineel, "d": document_id},
            )

        verplaatsen.verplaats_document(
            administratie_id=administratie_id,
            document_id=document_id,
            doel_administratie_id=doel_id,
            actor_id=gescoopte_gebruiker,
            actor_rol=GebruikerRol.BOEKHOUDING,
        )
        with admin_engine.connect() as conn:
            aantal = conn.execute(
                text("SELECT count(*) FROM boekhouding.boekvoorstel WHERE document_id = :id"), {"id": document_id}
            ).scalar_one()
        assert aantal == 0
        assert _document_rij(admin_engine, document_id).mogelijk_duplicaat_van_id == origineel

    def test_handmatige_toewijzing_zonder_leerregel_verplaatst_alleen(
        self,
        administratie_id: uuid.UUID,
        doel_id: uuid.UUID,
        andere_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        # Een regel die naar een DERDE administratie wijst is niet de oorzaak — blijft onaangeraakt.
        with scoped_session(None, actor_id=beheerder_id) as session:
            leer_toewijzing(
                session, administratie_id=andere_id, actor_id=beheerder_id, tenaamstelling=None, afzender=AFZENDER
            )
        document_id = _upload(administratie_id, gescoopte_gebruiker)
        resultaat = verplaatsen.verplaats_document(
            administratie_id=administratie_id,
            document_id=document_id,
            doel_administratie_id=doel_id,
            actor_id=gescoopte_gebruiker,
            actor_rol=GebruikerRol.BOEKHOUDING,
        )
        assert resultaat.leerregels_gecorrigeerd == ()
        assert _actieve_regels(admin_engine) == {("afzender", andere_id)}
        assert _document_rij(admin_engine, document_id).administratie_id == doel_id

    @pytest.mark.parametrize(
        ("status", "kern"),
        [("geboekt", "storno"), ("ter_accordering", "trek de accordering eerst in"), ("extractie_bezig", "loopt nog")],
    )
    def test_niet_toegestane_statussen_geven_uitleg_en_wijzigen_niets(
        self,
        status: str,
        kern: str,
        administratie_id: uuid.UUID,
        doel_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        _leer_naar(administratie_id, gescoopte_gebruiker)
        document_id = _upload(administratie_id, gescoopte_gebruiker)
        _zet_status(admin_engine, document_id, status)
        with pytest.raises(verplaatsen.VerplaatsenNietToegestaan, match=kern):
            verplaatsen.verplaats_document(
                administratie_id=administratie_id,
                document_id=document_id,
                doel_administratie_id=doel_id,
                actor_id=gescoopte_gebruiker,
                actor_rol=GebruikerRol.BOEKHOUDING,
            )
        rij = _document_rij(admin_engine, document_id)
        assert rij.administratie_id == administratie_id
        assert rij.status == status
        assert _actieve_regels(admin_engine) == {("tenaamstelling", administratie_id), ("afzender", administratie_id)}

    def test_zelfde_administratie_en_ontbrekende_doelscope(
        self,
        administratie_id: uuid.UUID,
        andere_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker)
        with pytest.raises(verplaatsen.VerplaatsenNietToegestaan, match="al in deze administratie"):
            verplaatsen.verplaats_document(
                administratie_id=administratie_id,
                document_id=document_id,
                doel_administratie_id=administratie_id,
                actor_id=gescoopte_gebruiker,
                actor_rol=GebruikerRol.BOEKHOUDING,
            )
        with pytest.raises(verplaatsen.GeenScopeOpDoel):
            verplaatsen.verplaats_document(
                administratie_id=administratie_id,
                document_id=document_id,
                doel_administratie_id=andere_id,
                actor_id=gescoopte_gebruiker,
                actor_rol=GebruikerRol.BOEKHOUDING,
            )
        with pytest.raises(verplaatsen.OnbekendeDoelAdministratie):
            verplaatsen.verplaats_document(
                administratie_id=administratie_id,
                document_id=document_id,
                doel_administratie_id=uuid.uuid4(),
                actor_id=gescoopte_gebruiker,
                actor_rol=GebruikerRol.BOEKHOUDING,
            )
        assert _document_rij(admin_engine, document_id).administratie_id == administratie_id

    def test_open_vraag_verhuist_mee_en_blokkeert_weer_na_de_extractie(
        self,
        administratie_id: uuid.UUID,
        doel_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker)
        vraag = vragen.stel_vraag(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            vraag_tekst="Welke BV is dit?",
            toegewezen_aan=gescoopte_gebruiker,
        )
        assert _document_rij(admin_engine, document_id).status == "vraag_open"

        resultaat = verplaatsen.verplaats_document(
            administratie_id=administratie_id,
            document_id=document_id,
            doel_administratie_id=doel_id,
            actor_id=gescoopte_gebruiker,
            actor_rol=GebruikerRol.BOEKHOUDING,
        )
        assert resultaat.vragen_verhuisd == 1
        assert resultaat.vragen_hertoegewezen == 0  # de boekhouder heeft óók scope op het doel
        # Ná de her-extractie staat het document weer op vraag_open — de vraag blokkeert boeken opnieuw.
        assert resultaat.status == DocumentStatus.VRAAG_OPEN
        rij = _document_rij(admin_engine, document_id)
        assert rij.status == "vraag_open"
        assert rij.toegewezen_aan == gescoopte_gebruiker
        with admin_engine.connect() as conn:
            v = conn.execute(
                text("SELECT administratie_id, status, status_voor_vraag FROM boekhouding.vraag WHERE id = :id"),
                {"id": vraag.id},
            ).one()
        assert v.administratie_id == doel_id
        assert v.status == "open"
        assert v.status_voor_vraag == "te_controleren"
        # De vraag is in het doel gewoon leesbaar en afhandelbaar door de vraagsteller.
        lijst = vragen.lijst_vragen(administratie_id=doel_id, document_id=document_id)
        assert [x.id for x in lijst] == [vraag.id]
        vragen.handel_vraag_af(administratie_id=doel_id, vraag_id=vraag.id, actor_id=gescoopte_gebruiker)
        assert _document_rij(admin_engine, document_id).status == "te_controleren"

    def test_open_vraag_aan_iemand_zonder_doelscope_gaat_naar_de_doeleigenaar(
        self,
        administratie_id: uuid.UUID,
        doel_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        # Collega mét scope op de bron, zonder scope op het doel.
        collega = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                    "VALUES (:id, 'Collega', :mail, 'boekhouding', 'actief')"
                ),
                {"id": collega, "mail": f"{collega}@test.local"},
            )
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=collega, administratie_id=administratie_id)
        document_id = _upload(administratie_id, gescoopte_gebruiker)
        vraag = vragen.stel_vraag(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            vraag_tekst="Klopt dit?",
            toegewezen_aan=collega,
        )
        resultaat = verplaatsen.verplaats_document(
            administratie_id=administratie_id,
            document_id=document_id,
            doel_administratie_id=doel_id,
            actor_id=gescoopte_gebruiker,
            actor_rol=GebruikerRol.BOEKHOUDING,
        )
        assert resultaat.vragen_hertoegewezen == 1
        with admin_engine.connect() as conn:
            v = conn.execute(
                text("SELECT toegewezen_aan, aan_de_beurt FROM boekhouding.vraag WHERE id = :id"), {"id": vraag.id}
            ).one()
        # Doel-eigenaar = de Beheerder (fixture) — nooit iemand zonder toegang.
        assert v.toegewezen_aan == beheerder_id
        assert v.aan_de_beurt == beheerder_id
        assert _document_rij(admin_engine, document_id).toegewezen_aan == beheerder_id

    def test_open_afwijzing_sluit_door_de_verhuizing(
        self,
        administratie_id: uuid.UUID,
        doel_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker)
        afwijzing = afwijzen.wijs_af(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            reden="Hoort bij Port of Rotterdam",
            toegewezen_aan=gescoopte_gebruiker,
        )
        resultaat = verplaatsen.verplaats_document(
            administratie_id=administratie_id,
            document_id=document_id,
            doel_administratie_id=doel_id,
            actor_id=gescoopte_gebruiker,
            actor_rol=GebruikerRol.BOEKHOUDING,
        )
        assert resultaat.status == DocumentStatus.TE_CONTROLEREN
        with admin_engine.connect() as conn:
            a = conn.execute(
                text("SELECT administratie_id, status, heropend_door FROM boekhouding.afwijzing WHERE id = :id"),
                {"id": afwijzing.id},
            ).one()
        assert a.administratie_id == doel_id
        assert a.status == "heropend"
        assert a.heropend_door == gescoopte_gebruiker
        assert afwijzen.open_afwijzing_van(administratie_id=doel_id, document_id=document_id) is None
        detail = service.haal_document_op(administratie_id=doel_id, document_id=document_id)
        verhuis = next(g for g in detail.gebeurtenissen if g.detail and "verplaatst" in g.detail)
        assert verhuis.detail["afwijzing_gesloten_door_verplaatsing"] == str(afwijzing.id)


class TestDbFunctiePoorten:
    """De SECURITY DEFINER-functie (migratie 0080) is de enige RLS-passage — en poort zichzelf."""

    def test_weigert_buiten_de_bronscope_en_buiten_status_ontvangen(
        self,
        administratie_id: uuid.UUID,
        doel_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker)
        # (a) gescoped op het DOEL i.p.v. de bron → geweigerd, niets gewijzigd.
        with (
            pytest.raises(DBAPIError, match="niet gescoped op de bron-administratie"),
            scoped_session(doel_id, actor_id=gescoopte_gebruiker) as session,
        ):
            session.execute(
                text("SELECT boekhouding.verplaats_document(:d, :van, :naar)"),
                {"d": document_id, "van": administratie_id, "naar": doel_id},
            )
        # (b) juiste scope, maar status te_controleren (de servicelaag zet eerst ontvangen) → geweigerd.
        with (
            pytest.raises(DBAPIError, match="verwacht ontvangen"),
            scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session,
        ):
            session.execute(
                text("SELECT boekhouding.verplaats_document(:d, :van, :naar)"),
                {"d": document_id, "van": administratie_id, "naar": doel_id},
            )
        assert _document_rij(admin_engine, document_id).administratie_id == administratie_id

    def test_geboekt_kan_op_db_niveau_nooit_verhuizen(
        self, administratie_id: uuid.UUID, doel_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker)
        _zet_status(admin_engine, document_id, "geboekt")
        with (
            pytest.raises(DBAPIError, match="staat op geboekt"),
            scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session,
        ):
            session.execute(
                text("SELECT boekhouding.verplaats_document(:d, :van, :naar)"),
                {"d": document_id, "van": administratie_id, "naar": doel_id},
            )
        assert _document_rij(admin_engine, document_id).administratie_id == administratie_id


class TestHttp:
    def test_endpoint_verplaatst_en_geeft_doel_terug(
        self, administratie_id: uuid.UUID, doel_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker)
        resp = client.post(
            f"/administraties/{administratie_id}/documenten/{document_id}/verplaats",
            json={"doel_administratie_id": str(doel_id)},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["naar_administratie_id"] == str(doel_id)
        assert body["naar_administratie_naam"] == "Port of Rotterdam (test)"
        assert body["status"] == "te_controleren"
        assert body["leerregels_gecorrigeerd"] == []
        assert _document_rij(admin_engine, document_id).administratie_id == doel_id
        # Detail in het doel leesbaar, in de bron 404.
        assert (
            client.get(
                f"/administraties/{doel_id}/documenten/{document_id}",
                headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
            ).status_code
            == 200
        )
        assert (
            client.get(
                f"/administraties/{administratie_id}/documenten/{document_id}",
                headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
            ).status_code
            == 404
        )

    def test_endpoint_409_met_uitleg_bij_geboekt_en_403_zonder_doelscope(
        self,
        administratie_id: uuid.UUID,
        doel_id: uuid.UUID,
        andere_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker)
        resp = client.post(
            f"/administraties/{administratie_id}/documenten/{document_id}/verplaats",
            json={"doel_administratie_id": str(andere_id)},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 403
        _zet_status(admin_engine, document_id, "geboekt")
        resp = client.post(
            f"/administraties/{administratie_id}/documenten/{document_id}/verplaats",
            json={"doel_administratie_id": str(doel_id)},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 409
        assert "storno" in resp.json()["detail"]
        # Bron-scope ontbreekt → 403 vóór alles (dependency).
        resp = client.post(
            f"/administraties/{andere_id}/documenten/{document_id}/verplaats",
            json={"doel_administratie_id": str(doel_id)},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 403


class TestOnthoudTenaamstelling:
    """Punt 6a (werkstroom-run 27/28-08): optionele checkbox in de verplaats-modal — géén automatische
    leer-regel; alleen op expliciet verzoek leert het geheugen de tenaamstelling naar het doel."""

    def test_default_uit_leert_niets(
        self, administratie_id: uuid.UUID, doel_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        document_id = _upload(
            administratie_id, gescoopte_gebruiker
        )  # toewijzing zónder leer-regel (register-match-gat)
        resultaat = verplaatsen.verplaats_document(
            administratie_id=administratie_id,
            document_id=document_id,
            doel_administratie_id=doel_id,
            actor_id=gescoopte_gebruiker,
            actor_rol=GebruikerRol.BOEKHOUDING,
        )
        assert resultaat.leerregels_gecorrigeerd == ()
        assert resultaat.tenaamstelling_geleerd is False
        assert _actieve_regels(admin_engine) == set()

    def test_onthoud_leert_alleen_de_tenaamstelling_naar_het_doel(
        self, administratie_id: uuid.UUID, doel_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker)
        resultaat = verplaatsen.verplaats_document(
            administratie_id=administratie_id,
            document_id=document_id,
            doel_administratie_id=doel_id,
            actor_id=gescoopte_gebruiker,
            actor_rol=GebruikerRol.BOEKHOUDING,
            onthoud_tenaamstelling=True,
        )
        assert resultaat.tenaamstelling_geleerd is True
        # Alleen tenaamstelling — de afzender is een hint, geen bewijs.
        assert _actieve_regels(admin_engine) == {("tenaamstelling", doel_id)}
        with scoped_session(None) as session:
            besluit = bepaal_toewijzing(session, tenaamstelling=TENAAMSTELLING, afzender=None)
        assert besluit.administratie_id == doel_id
        detail = service.haal_document_op(administratie_id=doel_id, document_id=document_id)
        verhuis = next(g for g in detail.gebeurtenissen if g.detail and "verplaatst" in g.detail)
        assert verhuis.detail["tenaamstelling_geleerd"] == TENAAMSTELLING

    def test_http_vlag_en_response(
        self, administratie_id: uuid.UUID, doel_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker)
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        detail = client.get(f"/administraties/{administratie_id}/documenten/{document_id}", headers=headers).json()
        assert detail["tenaamstelling"] == TENAAMSTELLING  # voedt de checkbox-tekst in de modal
        resp = client.post(
            f"/administraties/{administratie_id}/documenten/{document_id}/verplaats",
            json={"doel_administratie_id": str(doel_id), "onthoud_tenaamstelling": True},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["tenaamstelling_geleerd"] is True
        assert _actieve_regels(admin_engine) == {("tenaamstelling", doel_id)}
