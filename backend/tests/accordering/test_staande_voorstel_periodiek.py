# ruff: noqa: F811 — pytest-fixtures als parameters
"""Staande goedkeuring: voorstel alleen bij een PERIODIEK patroon, één keer per leverancier, "niet nu" = 90 dagen
stil, "nooit" per leverancier (accordeur zelf + Beheerder), opheffen (blok 7 run 11-09 middag; casus Lusso:
12 gelijke facturen voor 12 chalets → 12× de vraag). Bestaande staande goedkeuringen blijven ongewijzigd (zie
test_service.py — die suite blijft groen)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app import tijd
from app.accordering import service
from app.auth import service as auth_service
from app.auth import voorwaarden
from app.db.session import scoped_session
from app.documenten import boekvoorstel
from app.documenten import service as documenten_service
from app.documenten.models import Document, DocumentStatus
from app.documenten.service import _schrijf_overgang
from app.main import app
from app.security.tokens import create_access_token
from tests.accordering.conftest import VENDOR_ID, maak_accordeur, zet_schema

client = TestClient(app)
HUUR = Decimal("1250.00")


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _document(
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    admin_engine: Engine,
    opslag,
    *,
    datum: date,
    bedrag: Decimal,
    n: int,
) -> uuid.UUID:
    """Boekklaar inkoopfactuur-document met eigen factuurdatum/bedrag (vaste vendor mét cache-naam)."""
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.vendor_cache (id, administratie_id, naam, brondata) "
                "VALUES (:id, :aid, 'Lusso Chalets B.V.', '{}') ON CONFLICT DO NOTHING"
            ),
            {"id": VENDOR_ID, "aid": administratie_id},
        )
    resultaat = documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=f"factuur-{n}.pdf",
        inhoud=f"%PDF-1.4 factuur {n} {datum}".encode(),
        actor_id=actor_id,
        opslag=opslag,
    )
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=actor_id,
        vendor_id=VENDOR_ID,
        referentie=f"L-{n}-{resultaat.document_id}",
        factuurdatum=datum,
        totaalbedrag=bedrag,
        regels=[
            boekvoorstel.BoekvoorstelRegelData(
                ledger_id=uuid.uuid4(),
                taxrate_id=uuid.uuid4(),
                project_id=None,
                netto_bedrag=bedrag - Decimal("21.00"),
                btw_bedrag=Decimal("21.00"),
                omschrijving="regel",
            )
        ],
    )
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, resultaat.document_id)
        _schrijf_overgang(session, document=document, naar=DocumentStatus.KLAAR_OM_TE_BOEKEN, actor_id=actor_id)
    return resultaat.document_id


def _bied_aan(administratie_id: uuid.UUID, actor_id: uuid.UUID, document_id: uuid.UUID) -> None:
    service.bied_ter_accordering_aan(
        administratie_id=administratie_id, document_id=document_id, actor_id=actor_id, actor_rol="boekhouding"
    )


def _wachtrij(accordeur: uuid.UUID, administratie_id: uuid.UUID) -> list[service.WachtrijItem]:
    return service.wachtrij_voor_accordeur(actor_id=accordeur, administratie_ids=[administratie_id])


def _kandidaten(accordeur: uuid.UUID, administratie_id: uuid.UUID) -> dict[uuid.UUID, str | None]:
    return {
        i.document_id: i.staande_regel_patroon
        for i in _wachtrij(accordeur, administratie_id)
        if i.staande_regel_kandidaat
    }


def _klok_op(monkeypatch: pytest.MonkeyPatch, dag: date) -> None:
    monkeypatch.setattr(tijd, "_klok", lambda: datetime(dag.year, dag.month, dag.day, 10, 0, tzinfo=UTC))


@pytest.fixture
def schema(administratie_id: uuid.UUID, beheerder_id: uuid.UUID, accordeur_1: uuid.UUID, boeken_aan: None) -> None:
    zet_schema(
        administratie_id=administratie_id,
        beheerder_id=beheerder_id,
        lagen=[service.LaagInput(volgnummer=1, accordeur_gebruiker_id=accordeur_1, bedrag_drempel=None)],
    )


@pytest.fixture
def maandhuur(
    schema: None, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine, opslag
) -> list[uuid.UUID]:
    """Drie maandelijkse huurfacturen (1 juni / 1 juli / 1 augustus), alle drie aangeboden."""
    docs = [
        _document(administratie_id, gescoopte_gebruiker, admin_engine, opslag, datum=date(2026, m, 1), bedrag=HUUR, n=m)
        for m in (6, 7, 8)
    ]
    for d in docs:
        _bied_aan(administratie_id, gescoopte_gebruiker, d)
    return docs


class TestLussoBatch:
    def test_twaalf_gelijke_facturen_in_een_week_geven_nul_voorstellen(
        self,
        schema: None,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        admin_engine: Engine,
        opslag,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from tests.accordering.test_service import _patch_rlz

        _patch_rlz(monkeypatch)
        docs = [
            _document(
                administratie_id,
                gescoopte_gebruiker,
                admin_engine,
                opslag,
                datum=date(2026, 9, 1) + timedelta(days=i % 5),
                bedrag=Decimal("890.00"),
                n=i,
            )
            for i in range(12)
        ]
        for d in docs:
            _bied_aan(administratie_id, gescoopte_gebruiker, d)
        # Vóór blok 7: ná het eerste handmatige akkoord droegen de overige elf het voorstel.
        service.geef_akkoord(administratie_id=administratie_id, document_id=docs[0], actor_id=accordeur_1)
        items = _wachtrij(accordeur_1, administratie_id)
        assert len(items) == 11
        assert all(not i.staande_regel_kandidaat and i.staande_regel_patroon is None for i in items)

    def test_twee_gelijke_facturen_zonder_patroon_geven_geen_voorstel_meer(
        self,
        schema: None,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        admin_engine: Engine,
        opslag,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Herziet de mockup-flow "voorstel op de 2e identieke factuur": zonder bewezen patroon geen vraag."""
        from tests.accordering.test_service import _patch_rlz

        _patch_rlz(monkeypatch)
        a = _document(
            administratie_id, gescoopte_gebruiker, admin_engine, opslag, datum=date(2026, 3, 1), bedrag=HUUR, n=1
        )
        b = _document(
            administratie_id, gescoopte_gebruiker, admin_engine, opslag, datum=date(2026, 8, 1), bedrag=HUUR, n=2
        )
        _bied_aan(administratie_id, gescoopte_gebruiker, a)
        _bied_aan(administratie_id, gescoopte_gebruiker, b)
        service.geef_akkoord(administratie_id=administratie_id, document_id=a, actor_id=accordeur_1)
        assert _kandidaten(accordeur_1, administratie_id) == {}


class TestMaandhuurPeriodiek:
    def test_drie_maandelijkse_facturen_precies_een_voorstel(
        self, maandhuur: list[uuid.UUID], administratie_id: uuid.UUID, accordeur_1: uuid.UUID, monkeypatch
    ) -> None:
        from tests.accordering.test_service import _patch_rlz

        _patch_rlz(monkeypatch)
        # Nog geen handmatig akkoord → geen voorstel (de accordeur moet 'm eerst één keer zelf goedgekeurd hebben).
        assert _kandidaten(accordeur_1, administratie_id) == {}
        service.geef_akkoord(administratie_id=administratie_id, document_id=maandhuur[0], actor_id=accordeur_1)
        # Twee gelijke facturen in de wachtrij, het patroon is bewezen (3 × maand) → precies ÉÉN voorstel, op de
        # eerste in lijstvolgorde, mét patroon.
        assert _kandidaten(accordeur_1, administratie_id) == {maandhuur[1]: "maand"}
        via_api_items = [i for i in _wachtrij(accordeur_1, administratie_id) if i.document_id == maandhuur[2]]
        assert via_api_items[0].staande_regel_kandidaat is False

    def test_niet_nu_is_negentig_dagen_stil_met_audit(
        self,
        maandhuur: list[uuid.UUID],
        administratie_id: uuid.UUID,
        accordeur_1: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from tests.accordering.test_service import _patch_rlz

        _patch_rlz(monkeypatch)
        _klok_op(monkeypatch, date(2026, 9, 11))
        service.geef_akkoord(administratie_id=administratie_id, document_id=maandhuur[0], actor_id=accordeur_1)
        assert maandhuur[1] in _kandidaten(accordeur_1, administratie_id)
        # "Niet nu" op het voorstel, in dezelfde akkoord-call.
        res = service.geef_akkoord(
            administratie_id=administratie_id,
            document_id=maandhuur[1],
            actor_id=accordeur_1,
            staande_regel_voorstel_antwoord="niet_nu",
        )
        assert res.staande_regel_id is None
        assert _kandidaten(accordeur_1, administratie_id) == {}  # derde factuur: stil
        with admin_engine.connect() as conn:
            rij = conn.execute(
                text(
                    "SELECT soort, stil_tot, actief, accordeur_gebruiker_id "
                    "FROM boekhouding.staande_goedkeuring_voorstel_stil"
                )
            ).one()
            audit = conn.execute(
                text(
                    "SELECT count(*) FROM platform.audit_event WHERE actie = 'staande_goedkeuring_voorstel_stil_gezet'"
                )
            ).scalar_one()
        assert (rij.soort, rij.stil_tot, rij.actief, rij.accordeur_gebruiker_id) == (
            "stil_tot",
            date(2026, 9, 11) + timedelta(days=service.VOORSTEL_STIL_DAGEN),
            True,
            accordeur_1,
        )
        assert audit == 1
        # Dag 89: nog stil; dag 90: de vraag mag weer.
        _klok_op(monkeypatch, date(2026, 9, 11) + timedelta(days=89))
        assert _kandidaten(accordeur_1, administratie_id) == {}
        _klok_op(monkeypatch, date(2026, 9, 11) + timedelta(days=90))
        assert _kandidaten(accordeur_1, administratie_id) == {maandhuur[2]: "maand"}
        # Lijst: de verstreken stilte telt niet meer als actieve uitzondering.
        assert service.voorstel_uitzonderingen(administratie_id=administratie_id) == []

    def test_nooit_door_accordeur_blijft_nooit(
        self,
        maandhuur: list[uuid.UUID],
        administratie_id: uuid.UUID,
        accordeur_1: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from tests.accordering.test_service import _patch_rlz

        _patch_rlz(monkeypatch)
        _klok_op(monkeypatch, date(2026, 9, 11))
        service.geef_akkoord(administratie_id=administratie_id, document_id=maandhuur[0], actor_id=accordeur_1)
        service.geef_akkoord(
            administratie_id=administratie_id,
            document_id=maandhuur[1],
            actor_id=accordeur_1,
            staande_regel_voorstel_antwoord="nooit",
        )
        _klok_op(monkeypatch, date(2028, 1, 1))
        assert _kandidaten(accordeur_1, administratie_id) == {}
        uitz = service.voorstel_uitzonderingen(administratie_id=administratie_id)
        assert [(u.soort, u.accordeur_gebruiker_id, u.leverancier_naam) for u in uitz] == [
            ("nooit", accordeur_1, "Lusso Chalets B.V.")
        ]
        # Opheffen door de accordeur zelf → de vraag mag weer.
        service.hef_voorstel_uitzondering_op(
            administratie_id=administratie_id, rij_id=uitz[0].id, actor_id=accordeur_1, actor_rol="klant_accordeur"
        )
        assert _kandidaten(accordeur_1, administratie_id) == {maandhuur[2]: "maand"}
        with pytest.raises(service.VoorstelUitzonderingFout):
            service.hef_voorstel_uitzondering_op(
                administratie_id=administratie_id, rij_id=uitz[0].id, actor_id=accordeur_1, actor_rol="klant_accordeur"
            )

    def test_ja_maakt_de_regel_aan_zoals_voorheen(
        self, maandhuur: list[uuid.UUID], administratie_id: uuid.UUID, accordeur_1: uuid.UUID, monkeypatch
    ) -> None:
        from tests.accordering.test_service import _patch_rlz

        _patch_rlz(monkeypatch)
        service.geef_akkoord(administratie_id=administratie_id, document_id=maandhuur[0], actor_id=accordeur_1)
        res = service.geef_akkoord(
            administratie_id=administratie_id,
            document_id=maandhuur[1],
            actor_id=accordeur_1,
            staande_regel_voorstel_antwoord="ja",
        )
        assert res.staande_regel_id is not None
        # Derde factuur: er is nu een actieve regel → geen voorstel (en de regel accordeert 'm bij een volgende
        # aanbieding automatisch — bestaand gedrag, test_service.py).
        assert _kandidaten(accordeur_1, administratie_id) == {}

    def test_onbekend_antwoord_geweigerd(
        self, maandhuur: list[uuid.UUID], administratie_id: uuid.UUID, accordeur_1: uuid.UUID
    ) -> None:
        with pytest.raises(service.AccorderingFout):
            service.geef_akkoord(
                administratie_id=administratie_id,
                document_id=maandhuur[0],
                actor_id=accordeur_1,
                staande_regel_voorstel_antwoord="misschien",
            )


class TestBeheerderUitzondering:
    def test_beheerder_zet_administratiebreed_nooit_en_heft_op(
        self,
        maandhuur: list[uuid.UUID],
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        accordeur_1: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from tests.accordering.test_service import _patch_rlz

        _patch_rlz(monkeypatch)
        voorwaarden.leg_akkoord_vast(gebruiker_id=accordeur_1)
        accordeur_2 = maak_accordeur(admin_engine, beheerder_id, administratie_id, "T. Tweede")
        voorwaarden.leg_akkoord_vast(gebruiker_id=accordeur_2)
        service.geef_akkoord(administratie_id=administratie_id, document_id=maandhuur[0], actor_id=accordeur_1)
        assert maandhuur[1] in _kandidaten(accordeur_1, administratie_id)

        # Beheerder via de kantoor-route: administratiebreed (accordeur null).
        resp = client.post(
            f"/administraties/{administratie_id}/accordering/staande-regels/voorstel-uitzonderingen",
            json={"vendor_id": str(VENDOR_ID), "reden": "chalets: elke factuur apart controleren"},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["soort"] == "nooit" and body["accordeur_gebruiker_id"] is None
        assert body["leverancier_naam"] == "Lusso Chalets B.V."
        assert _kandidaten(accordeur_1, administratie_id) == {}
        # Zichtbaar in de staande-goedkeuringen-lijst (kantoor én app lezen dezelfde route).
        lijst = client.get(
            f"/administraties/{administratie_id}/accordering/staande-regels",
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert lijst.status_code == 200
        assert [u["soort"] for u in lijst.json()["uitzonderingen"]] == ["nooit"]
        # Een gewone kantoorrol mag niet zetten of opheffen (Beheerder-instelling), de accordeur niet op een
        # administratiebrede rij.
        boekhouder = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                    "VALUES (:id, 'B. Boekhouder', :mail, 'boekhouding', 'actief')"
                ),
                {"id": boekhouder, "mail": f"{boekhouder}@test.local"},
            )
        auth_service.voeg_scope_toe(
            actor_id=beheerder_id, doel_gebruiker_id=boekhouder, administratie_id=administratie_id
        )
        resp = client.post(
            f"/administraties/{administratie_id}/accordering/staande-regels/voorstel-uitzonderingen/{body['id']}/opheffen",
            headers=_bearer(boekhouder, rol="boekhouding"),
        )
        assert resp.status_code == 403
        resp = client.post(
            f"/administraties/{administratie_id}/accordering/staande-regels/voorstel-uitzonderingen/{body['id']}/opheffen",
            headers=_bearer(accordeur_1, rol="klant_accordeur"),
        )
        assert resp.status_code == 404
        # Beheerder heft op → voorstel terug, audit oud→nieuw.
        resp = client.post(
            f"/administraties/{administratie_id}/accordering/staande-regels/voorstel-uitzonderingen/{body['id']}/opheffen",
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 204, resp.text
        assert _kandidaten(accordeur_1, administratie_id) == {maandhuur[1]: "maand"}
        with admin_engine.connect() as conn:
            acties = list(
                conn.execute(
                    text(
                        "SELECT actie FROM platform.audit_event WHERE tabel = 'staande_goedkeuring_voorstel_stil' "
                        "ORDER BY tijdstip"
                    )
                ).scalars()
            )
            rijen = conn.execute(
                text("SELECT count(*) FROM boekhouding.staande_goedkeuring_voorstel_stil")
            ).scalar_one()
        assert acties == ["staande_goedkeuring_voorstel_stil_gezet", "staande_goedkeuring_voorstel_stil_opgeheven"]
        assert rijen == 1  # nooit een DELETE

    def test_accordeur_kan_alleen_voor_zichzelf_nooit_zetten(
        self,
        maandhuur: list[uuid.UUID],
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        accordeur_1: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        voorwaarden.leg_akkoord_vast(gebruiker_id=accordeur_1)
        ander = maak_accordeur(admin_engine, beheerder_id, administratie_id, "A. Ander")
        resp = client.post(
            f"/administraties/{administratie_id}/accordering/staande-regels/voorstel-uitzonderingen",
            json={"vendor_id": str(VENDOR_ID), "accordeur_gebruiker_id": str(ander)},
            headers=_bearer(accordeur_1, rol="klant_accordeur"),
        )
        assert resp.status_code == 404
        resp = client.post(
            f"/administraties/{administratie_id}/accordering/staande-regels/voorstel-uitzonderingen",
            json={"vendor_id": str(VENDOR_ID)},
            headers=_bearer(accordeur_1, rol="klant_accordeur"),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["accordeur_gebruiker_id"] == str(accordeur_1)
        # Alleen voor hém stil — een andere accordeur (met eigen laag) zou het voorstel wél zien.
        assert _kandidaten(accordeur_1, administratie_id) == {}
        # Akkoord-route accepteert het antwoord additief (oude app zonder veld blijft werken).
        resp = client.post(
            f"/administraties/{administratie_id}/accordering/documenten/{maandhuur[0]}/akkoord",
            json={"staande_regel_aanmaken": False, "staande_regel_voorstel_antwoord": "niet_nu"},
            headers=_bearer(accordeur_1, rol="klant_accordeur"),
        )
        assert resp.status_code == 200, resp.text
