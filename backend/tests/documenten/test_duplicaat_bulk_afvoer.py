"""Bulk-afvoer op de Mogelijk-duplicaat-tab (B2 07-09): expliciete mensactie over de BESTAANDE één-klik-route
per document (`duplicaat_afvoer.voer_af_als_duplicaat` — zelfde harde match, kruisverwijzing, heropenen,
audit). Niet-afvoerbare rijen worden OVERGESLAGEN mét reden, dubbel klikken is idempotent (`al_afgevoerd`),
`alle=true` = server-side selectie op de tab-definitie, en de 20/dag-automatiseringsrem wordt niet geraakt
(alleen `automatisch_afgevoerd`-overgangen tellen). Scope: niet-Beheerder mét scope = groen pad; zonder scope
= 403 en geen effect."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.db.session import scoped_session
from app.documenten import duplicaat_afvoer, duplicaatsignaal
from app.documenten.models import Document, DocumentStatus
from app.documenten.service import _schrijf_overgang
from app.documenten.storage import LokaleBestandsopslag
from app.main import app
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.documenten.test_duplicaat_afvoer import REF, _afwijzing_rij, _audit_acties, _bearer, _upload_met_kop
from tests.documenten.test_vragen import _extra_gebruiker, _status

client = TestClient(app)

BULK_PAD = "/administraties/{aid}/documenten/duplicaten/afvoeren-bulk"


@pytest.fixture
def eigenaar_id(admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID) -> uuid.UUID:
    """Afwijzen wijst default toe aan de administratie-eigenaar (zelfde fixture als test_duplicaat_afvoer)."""
    gid = _extra_gebruiker(admin_engine, met_scope_op=administratie_id, beheerder_id=beheerder_id)
    beheer_service.zet_eigenaar(actor_id=beheerder_id, administratie_id=administratie_id, eigenaar_gebruiker_id=gid)
    return gid


@pytest.fixture
def noodrem_uit(beheerder_id: uuid.UUID) -> None:
    """Platformbrede auto-afvoer UIT: de duplicaten blijven op de tab staan voor de mens."""
    beheer_service.zet_duplicaat_autoafvoer_platform(actor_id=beheerder_id, ingeschakeld=False)


def _maak_geboekt(administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        assert document is not None
        _schrijf_overgang(session, document=document, naar=DocumentStatus.KLAAR_OM_TE_BOEKEN, actor_id=actor_id)
        _schrijf_overgang(session, document=document, naar=DocumentStatus.GEBOEKT, actor_id=actor_id)


def _aantal_afwijzingen(admin_engine: Engine, document_id: uuid.UUID) -> int:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM boekhouding.afwijzing WHERE document_id = :id"), {"id": document_id}
        ).scalar_one()


def _correlaties(admin_engine: Engine, *, actie: str, record_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    with admin_engine.connect() as conn:
        return set(
            conn.execute(
                text(
                    "SELECT correlatie_id FROM platform.audit_event WHERE tabel = 'document' AND actie = :actie "
                    "AND record_id = ANY(:ids)"
                ),
                {"actie": actie, "ids": record_ids},
            )
            .scalars()
            .all()
        )


def _signaal_met_rlz_treffer(administratie_id: uuid.UUID, document_id: uuid.UUID) -> None:
    """Gecachet RLZ-signaal `mogelijk_duplicaat` (origineel buiten de app) — mét de noodrem UIT voert het
    automatische pad niets af, zodat de rij op de tab blijft staan voor de mens."""
    duplicaatsignaal.bereken_duplicaatsignaal(
        administratie_id=administratie_id,
        document_id=document_id,
        client=FakeBoekClient(duplicaten=[{"id": str(uuid.uuid4()), "Reference": REF, "InvoiceNumber": "INK-77"}]),
    )


class TestBulkMotor:
    def test_drie_documenten_waarvan_een_geboekt_twee_afgevoerd_een_overgeslagen_met_reden(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        noodrem_uit: None,
        admin_engine: Engine,
    ) -> None:
        vendor_id = uuid.uuid4()
        up = lambda naam: _upload_met_kop(  # noqa: E731
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor_id,
            naam=naam,
        )
        a, b, c = up("a.pdf"), up("b.pdf"), up("c.pdf")
        _maak_geboekt(administratie_id, a, gescoopte_gebruiker)
        assert _status(admin_engine, b) == DocumentStatus.TE_CONTROLEREN.value  # noodrem uit: niets automatisch

        uitkomsten = duplicaat_afvoer.voer_af_in_bulk(
            administratie_id=administratie_id, document_ids=[a, b, c, b], actor_id=gescoopte_gebruiker
        )
        per_id = {u.document_id: u for u in uitkomsten}
        assert len(uitkomsten) == 3  # dubbel in de selectie = één keer
        assert per_id[a].uitkomst == "overgeslagen"
        assert per_id[a].reden is not None and "geboekt" in per_id[a].reden
        assert per_id[a].bestandsnaam == "a.pdf"
        for dup in (b, c):
            assert per_id[dup].uitkomst == "afgevoerd", per_id[dup]
            assert per_id[dup].origineel is not None and per_id[dup].origineel.document_id == a
            assert per_id[dup].origineel.bron == "geboekt"
            assert _status(admin_engine, dup) == DocumentStatus.AFGEWEZEN.value
            rij = _afwijzing_rij(admin_engine, dup)
            assert rij is not None and rij["automatisch"] is False
            assert rij["duplicaat_van_document_id"] == a and rij["duplicaat_van_referentie"] == REF
            assert rij["afgewezen_door"] == gescoopte_gebruiker  # actor = de mens, niet het systeem
            assert "duplicaat_afgevoerd" in _audit_acties(admin_engine, tabel="document", record_id=dup)
        assert _status(admin_engine, a) == DocumentStatus.GEBOEKT.value
        assert "duplicaat_afvoer_geweigerd" in _audit_acties(admin_engine, tabel="document", record_id=a)
        # Eén bulk-run = één correlatie-id over álle rijen (afgevoerd én geweigerd).
        assert (
            len(
                _correlaties(admin_engine, actie="duplicaat_afgevoerd", record_ids=[b, c])
                | _correlaties(admin_engine, actie="duplicaat_afvoer_geweigerd", record_ids=[a])
            )
            == 1
        )
        # Buiten de 20/dag-automatiseringsrem: de mens-afvoer telt niet als automatische overgang.
        with scoped_session(administratie_id) as session:
            assert duplicaat_afvoer._afgevoerd_vandaag(session, administratie_id=administratie_id) == 0

        # Idempotent bij dubbel klikken: geen tweede afwijzing, uitkomst al_afgevoerd, a nog steeds overgeslagen.
        herhaald = duplicaat_afvoer.voer_af_in_bulk(
            administratie_id=administratie_id, document_ids=[a, b, c], actor_id=gescoopte_gebruiker
        )
        per_id2 = {u.document_id: u for u in herhaald}
        assert per_id2[b].uitkomst == "al_afgevoerd" and per_id2[c].uitkomst == "al_afgevoerd"
        assert per_id2[a].uitkomst == "overgeslagen"
        assert _aantal_afwijzingen(admin_engine, b) == 1 and _aantal_afwijzingen(admin_engine, c) == 1
        assert _audit_acties(admin_engine, tabel="document", record_id=b).count("duplicaat_afgevoerd") == 1

    def test_onbekend_document_en_zacht_signaal_overgeslagen_met_reden(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        noodrem_uit: None,
        admin_engine: Engine,
    ) -> None:
        # Eén document zonder groepsgenoot: geen harde match → overgeslagen, blijft staan.
        alleen = _upload_met_kop(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, vendor_id=uuid.uuid4()
        )
        onbekend = uuid.uuid4()
        uitkomsten = duplicaat_afvoer.voer_af_in_bulk(
            administratie_id=administratie_id, document_ids=[alleen, onbekend], actor_id=gescoopte_gebruiker
        )
        per_id = {u.document_id: u for u in uitkomsten}
        assert per_id[alleen].uitkomst == "overgeslagen" and "harde duplicaat-match" in (per_id[alleen].reden or "")
        assert per_id[onbekend].uitkomst == "overgeslagen" and "Onbekend document" in (per_id[onbekend].reden or "")
        assert per_id[onbekend].bestandsnaam is None
        assert _status(admin_engine, alleen) == DocumentStatus.TE_CONTROLEREN.value


class TestRouter:
    def test_alle_variant_selecteert_server_side_op_de_tab_definitie(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        noodrem_uit: None,
        admin_engine: Engine,
    ) -> None:
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        vendor_id = uuid.uuid4()
        up = lambda naam, **kw: _upload_met_kop(  # noqa: E731
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor_id,
            naam=naam,
            **kw,
        )
        a, b = up("a.pdf"), up("b.pdf")  # beide: RLZ-signaal mogelijk_duplicaat → op de tab, afvoerbaar
        geboekt = up("geboekt.pdf")  # signaal, maar status geboekt → niet in de server-selectie
        zonder = up("zonder-signaal.pdf", referentie="ANDERS-1")  # geen signaal → niet op de tab
        for d in (a, b, geboekt):
            _signaal_met_rlz_treffer(administratie_id, d)
        _maak_geboekt(administratie_id, geboekt, gescoopte_gebruiker)
        assert _status(admin_engine, a) == DocumentStatus.TE_CONTROLEREN.value  # noodrem uit

        assert duplicaat_afvoer.selecteer_alle_bulk_kandidaten(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker
        ) == [a, b]

        resp = client.post(BULK_PAD.format(aid=administratie_id), json={"alle": True}, headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["geselecteerd"] == 2 and body["afgevoerd"] == 2 and body["overgeslagen"] == 0
        assert {r["document_id"] for r in body["resultaten"]} == {str(a), str(b)}
        assert all(r["uitkomst"] == "afgevoerd" and r["origineel"]["bron"] == "geboekt" for r in body["resultaten"])
        assert all(r["reden"].startswith(f"Duplicaat van {REF}") for r in body["resultaten"])
        assert _status(admin_engine, a) == _status(admin_engine, b) == DocumentStatus.AFGEWEZEN.value
        assert _status(admin_engine, geboekt) == DocumentStatus.GEBOEKT.value
        assert _status(admin_engine, zonder) == DocumentStatus.TE_CONTROLEREN.value

        # Nogmaals "alle": niets meer te selecteren — lege, leesbare uitkomst (geen fout, geen tweede afwijzing).
        herhaald = client.post(BULK_PAD.format(aid=administratie_id), json={"alle": True}, headers=headers)
        assert herhaald.status_code == 200 and herhaald.json()["geselecteerd"] == 0
        assert _aantal_afwijzingen(admin_engine, a) == 1

    def test_expliciete_ids_via_router_en_validatie(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        noodrem_uit: None,
        admin_engine: Engine,
    ) -> None:
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        vendor_id = uuid.uuid4()
        a = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor_id,
            naam="a.pdf",
        )
        b = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor_id,
            naam="b.pdf",
        )
        # Beide meegeven: a is het (oudste) origineel → overgeslagen mét reden, b afgevoerd.
        resp = client.post(
            BULK_PAD.format(aid=administratie_id), json={"document_ids": [str(a), str(b)]}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        per_id = {r["document_id"]: r for r in body["resultaten"]}
        assert body == {**body, "geselecteerd": 2, "afgevoerd": 1, "al_afgevoerd": 0, "overgeslagen": 1}
        assert per_id[str(b)]["uitkomst"] == "afgevoerd" and per_id[str(b)]["origineel"]["document_id"] == str(a)
        assert per_id[str(a)]["uitkomst"] == "overgeslagen" and "origineel" in per_id[str(a)]["reden"]
        # Validatie: leeg, of beide vormen tegelijk = 422.
        assert client.post(BULK_PAD.format(aid=administratie_id), json={}, headers=headers).status_code == 422
        assert (
            client.post(BULK_PAD.format(aid=administratie_id), json={"document_ids": []}, headers=headers).status_code
            == 422
        )
        assert (
            client.post(
                BULK_PAD.format(aid=administratie_id), json={"alle": True, "document_ids": [str(a)]}, headers=headers
            ).status_code
            == 422
        )

    def test_niet_beheerder_zonder_scope_403_en_geen_effect(
        self,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        eigenaar_id: uuid.UUID,
        noodrem_uit: None,
        admin_engine: Engine,
    ) -> None:
        vendor_id = uuid.uuid4()
        a = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor_id,
            naam="a.pdf",
        )
        b = _upload_met_kop(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            vendor_id=vendor_id,
            naam="b.pdf",
        )
        buitenstaander = _extra_gebruiker(admin_engine, met_scope_op=None, beheerder_id=beheerder_id)
        for body in ({"document_ids": [str(b)]}, {"alle": True}):
            resp = client.post(
                BULK_PAD.format(aid=administratie_id), json=body, headers=_bearer(buitenstaander, rol="boekhouding")
            )
            assert resp.status_code == 403, resp.text
        assert _status(admin_engine, a) == _status(admin_engine, b) == DocumentStatus.TE_CONTROLEREN.value
        assert _aantal_afwijzingen(admin_engine, b) == 0
        # NB de scope-poort is de router (`vereis_administratie_scope`), zoals bij de bestaande één-klik: de
        # gescoopte sessie scoopt op de administratie-context, niet op de scope-rijen van de actor.
        assert _status(admin_engine, b) == DocumentStatus.TE_CONTROLEREN.value
