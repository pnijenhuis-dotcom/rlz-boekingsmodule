"""Accorderingsronde HERBEREKENEN i.p.v. vervallen bij een configuratiewijziging (bundel 09-09 blok 2; besluit
Peter 08-09, herziet "GECOMBINEERDE RUN 01-09" blok A beslispunt 2). Integratie over de servicelaag + HTTP:
akkoord behouden / laag opnieuw aangevraagd / afronding-en-boeken / vervallen-pad / compleet akkoord onaangeraakt /
drie ingangen (detail-tab, bulk, accordeur-venster) delen één pad / audit + tijdlijn / preview-telling / melding
heropend. De pure overgangen staan in test_herberekening_puur.py."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.accordering import service
from app.accordering.models import AccorderingStatus, StapBesluit
from app.documenten import boeken
from app.documenten import service as documenten_service
from app.main import app
from app.security.tokens import create_access_token
from tests.accordering.conftest import document_status, maak_accordeur, zet_schema
from tests.documenten.fake_rlz_client import FakeBoekClient

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _laag(volgnummer: int, accordeur: uuid.UUID, drempel: str | None = None) -> service.LaagInput:
    return service.LaagInput(
        volgnummer=volgnummer, accordeur_gebruiker_id=accordeur, bedrag_drempel=Decimal(drempel) if drempel else None
    )


def _bied_aan(administratie_id: uuid.UUID, document_id: uuid.UUID, actor: uuid.UUID) -> None:
    service.bied_ter_accordering_aan(
        administratie_id=administratie_id, document_id=document_id, actor_id=actor, actor_rol="boekhouding"
    )


def _ronde_statussen(admin_engine: Engine, document_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        return [
            r.status
            for r in conn.execute(
                text(
                    "SELECT status FROM boekhouding.document_accordering WHERE document_id = :id ORDER BY aangeboden_op"
                ),
                {"id": document_id},
            )
        ]


def _alle_stap_rijen(admin_engine: Engine, document_id: uuid.UUID) -> list[tuple[int, str | None, bool]]:
    """Álle stap-rijen incl. de bij herberekening vervallen (historie) — rechtstreeks uit de DB."""
    with admin_engine.connect() as conn:
        return [
            (r.volgnummer, r.besluit, r.vereist)
            for r in conn.execute(
                text(
                    "SELECT s.volgnummer, s.besluit, s.vereist FROM boekhouding.accordering_stap s "
                    "JOIN boekhouding.document_accordering a ON a.id = s.accordering_id "
                    "WHERE a.document_id = :id ORDER BY s.volgnummer, s.besluit"
                ),
                {"id": document_id},
            )
        ]


def _audit_acties(admin_engine: Engine, tabel: str) -> list[str]:
    with admin_engine.connect() as conn:
        return [
            r.actie for r in conn.execute(text("SELECT actie FROM platform.audit_event WHERE tabel = :t"), {"t": tabel})
        ]


def _herberekend_regels(administratie_id: uuid.UUID, document_id: uuid.UUID) -> list:
    detail = documenten_service.haal_document_op(administratie_id=administratie_id, document_id=document_id)
    return [g for g in detail.gebeurtenissen if g.detail and service.HERBEREKEND_TIJDLIJN_SLEUTEL in g.detail]


def _stappen(administratie_id: uuid.UUID, document_id: uuid.UUID) -> list[tuple[int, uuid.UUID, str | None, bool]]:
    data = service.accordering_van_document(administratie_id=administratie_id, document_id=document_id)
    assert data is not None
    return [(s.volgnummer, s.accordeur_gebruiker_id, s.besluit, s.aan_de_beurt) for s in data.stappen]


def _wachtrij(accordeur: uuid.UUID, administratie_id: uuid.UUID) -> list[uuid.UUID]:
    return [
        w.document_id for w in service.wachtrij_voor_accordeur(actor_id=accordeur, administratie_ids=[administratie_id])
    ]


@pytest.fixture
def accordeur_3(admin_engine: Engine, beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> uuid.UUID:  # noqa: F811
    return maak_accordeur(admin_engine, beheerder_id, administratie_id, "T. de Derde")


@pytest.fixture
def ronde_met_akkoord_laag_1(
    klaar_document: uuid.UUID,
    administratie_id: uuid.UUID,
    beheerder_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
    accordeur_1: uuid.UUID,
    accordeur_2: uuid.UUID,
    admin_engine: Engine,
) -> uuid.UUID:
    """Lagen [1: accordeur_1, 2: accordeur_2], aangeboden, laag 1 akkoord → wacht op laag 2."""
    zet_schema(
        administratie_id=administratie_id,
        beheerder_id=beheerder_id,
        lagen=[_laag(1, accordeur_1), _laag(2, accordeur_2)],
    )
    _bied_aan(administratie_id, klaar_document, gescoopte_gebruiker)
    tussen = service.geef_akkoord(administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1)
    assert tussen.alles_akkoord is False
    assert document_status(admin_engine, klaar_document) == "ter_accordering"
    return klaar_document


class TestAkkoordBehoudenLaagOpnieuwAangevraagd:
    def test_zelfde_laag_behouden_nieuwe_laag_aangevraagd_met_audit_en_tijdlijn(
        self,
        ronde_met_akkoord_laag_1: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
        accordeur_3: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        doc = ronde_met_akkoord_laag_1
        uitkomst = zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(1, accordeur_1), _laag(2, accordeur_3)],
        )
        assert (uitkomst.herberekend, uitkomst.vervallen) == (1, 0)
        # Document blijft bij de klant; de ronde blijft OPEN, geen tweede ronde.
        assert document_status(admin_engine, doc) == "ter_accordering"
        assert _ronde_statussen(admin_engine, doc) == [AccorderingStatus.OPEN.value]
        # Stand: laag 1 akkoord (behouden), laag 2 = de nieuwe accordeur, aan de beurt.
        assert _stappen(administratie_id, doc) == [(1, accordeur_1, "akkoord", False), (2, accordeur_3, None, True)]
        assert _wachtrij(accordeur_3, administratie_id) == [doc]
        assert _wachtrij(accordeur_2, administratie_id) == []
        assert _wachtrij(accordeur_1, administratie_id) == []
        # De oude stap van accordeur_2 staat als historie (vervallen, niet vereist) — geen DELETE.
        assert (2, StapBesluit.VERVALLEN.value, False) in _alle_stap_rijen(admin_engine, doc)
        # Tijdlijn: notitie zonder statusovergang, mét de samenvatting + reden, actor = de Beheerder.
        regels = _herberekend_regels(administratie_id, doc)
        assert len(regels) == 1
        regel = regels[0]
        assert regel.van_status.value == "ter_accordering" and regel.naar_status.value == "ter_accordering"
        assert regel.actor_id == beheerder_id
        assert regel.detail["reden"] == service.HERBEREKEND_REDEN
        samenvatting = regel.detail[service.HERBEREKEND_TIJDLIJN_SLEUTEL]
        assert samenvatting["akkoorden_behouden"] == 1
        assert samenvatting["akkoorden_vervallen"] == 0
        assert samenvatting["opnieuw_aangevraagd"] == [2]
        assert samenvatting["alles_akkoord"] is False
        assert [(lg["volgnummer"], lg["besluit"]) for lg in samenvatting["lagen"]] == [(1, "akkoord"), (2, None)]
        uuid.UUID(regel.detail["batch_id"])
        # Audit oud→nieuw per ronde + telling in het schema-audit-event; géén vervallen-audit/-melding.
        acties = _audit_acties(admin_engine, "document_accordering")
        assert service.HERBEREKEND_AUDIT_ACTIE in acties
        assert "accordering_vervallen" not in acties
        with admin_engine.connect() as conn:
            rij = conn.execute(
                text(
                    "SELECT oude_waarde, nieuwe_waarde FROM platform.audit_event WHERE actie = :a "
                    "ORDER BY tijdstip DESC LIMIT 1"
                ),
                {"a": service.HERBEREKEND_AUDIT_ACTIE},
            ).one()
            schema_audit = conn.execute(
                text(
                    "SELECT nieuwe_waarde FROM platform.audit_event "
                    "WHERE actie = 'accordering_schema_gewijzigd' ORDER BY tijdstip DESC LIMIT 1"
                )
            ).scalar_one()
        assert [(s["volgnummer"], s["besluit"]) for s in rij.oude_waarde["stappen"]] == [(1, "akkoord"), (2, None)]
        assert [(s["volgnummer"], s["accordeur"]) for s in rij.nieuwe_waarde["stappen"]] == [
            (1, str(accordeur_1)),
            (2, str(accordeur_3)),
        ]
        assert schema_audit["rondes_herberekend"] == 1 and schema_audit["rondes_vervallen"] == 0
        assert service.vervallen_meldingen(administratie_id=administratie_id) == []
        # Nieuwe accordeur kan gewoon door — en dan is alles akkoord (boeken start, hier zonder Boeken-toggle →
        # zichtbare boek_fout, nooit stil).
        resultaat = service.geef_akkoord(administratie_id=administratie_id, document_id=doc, actor_id=accordeur_3)
        assert resultaat.alles_akkoord is True

    def test_eerdere_laag_behouden_later_gezette_accordeur_opnieuw_gevraagd(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
        accordeur_3: uuid.UUID,
    ) -> None:
        """Lagen [1: a1, 2: a2, 3: a3], a1 én a2 akkoord. Nieuwe volgorde [1: a2, 2: a1, 3: a3]: a2 komt EERDER
        (akkoord blijft), a1 komt LATER (akkoord vervalt, laag opnieuw aangevraagd) — a1 is aan de beurt, a3 daarna."""
        doc = klaar_document
        zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(1, accordeur_1), _laag(2, accordeur_2), _laag(3, accordeur_3)],
        )
        _bied_aan(administratie_id, doc, gescoopte_gebruiker)
        service.geef_akkoord(administratie_id=administratie_id, document_id=doc, actor_id=accordeur_1)
        service.geef_akkoord(administratie_id=administratie_id, document_id=doc, actor_id=accordeur_2)
        uitkomst = zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(1, accordeur_2), _laag(2, accordeur_1), _laag(3, accordeur_3)],
        )
        assert (uitkomst.herberekend, uitkomst.vervallen) == (1, 0)
        assert _stappen(administratie_id, doc) == [
            (1, accordeur_2, "akkoord", False),
            (2, accordeur_1, None, True),
            (3, accordeur_3, None, False),
        ]
        regel = _herberekend_regels(administratie_id, doc)[0]
        assert regel.detail[service.HERBEREKEND_TIJDLIJN_SLEUTEL]["akkoorden_behouden"] == 1
        assert regel.detail[service.HERBEREKEND_TIJDLIJN_SLEUTEL]["akkoorden_vervallen"] == 1
        assert regel.detail[service.HERBEREKEND_TIJDLIJN_SLEUTEL]["opnieuw_aangevraagd"] == [2, 3]
        # Volgorde blijft sequentieel: accordeur_3 is nog niet aan de beurt.
        with pytest.raises(service.NietAanDeBeurt):
            service.geef_akkoord(administratie_id=administratie_id, document_id=doc, actor_id=accordeur_3)

    def test_accordeur_verwijderd_akkoord_van_de_ander_blijft(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
        accordeur_3: uuid.UUID,
    ) -> None:
        zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(1, accordeur_1), _laag(2, accordeur_2), _laag(3, accordeur_3)],
        )
        _bied_aan(administratie_id, klaar_document, gescoopte_gebruiker)
        service.geef_akkoord(administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1)
        service.geef_akkoord(administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_2)
        # accordeur_1 volledig verwijderd: zijn akkoord vervalt, dat van accordeur_2 (nu laag 1) blijft.
        uitkomst = zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(1, accordeur_2), _laag(2, accordeur_3)],
        )
        assert (uitkomst.herberekend, uitkomst.vervallen) == (1, 0)
        assert _stappen(administratie_id, klaar_document) == [
            (1, accordeur_2, "akkoord", False),
            (2, accordeur_3, None, True),
        ]

    def test_drempel_soepeler_maakt_laag_vereist_en_vraagt_die_aan(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
        accordeur_3: uuid.UUID,
    ) -> None:
        # € 121: laag 2 (> € 1.000) is niet vereist; laag 3 wacht.
        zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(1, accordeur_1), _laag(2, accordeur_2, "1000"), _laag(3, accordeur_3)],
        )
        _bied_aan(administratie_id, klaar_document, gescoopte_gebruiker)
        service.geef_akkoord(administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1)
        assert _wachtrij(accordeur_3, administratie_id) == [klaar_document]
        # Drempel laag 2 soepeler (> € 100): laag 2 geldt nu → accordeur_2 aan de beurt vóór accordeur_3.
        uitkomst = zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(1, accordeur_1), _laag(2, accordeur_2, "100"), _laag(3, accordeur_3)],
        )
        assert (uitkomst.herberekend, uitkomst.vervallen) == (1, 0)
        assert _stappen(administratie_id, klaar_document) == [
            (1, accordeur_1, "akkoord", False),
            (2, accordeur_2, None, True),
            (3, accordeur_3, None, False),
        ]
        assert _wachtrij(accordeur_2, administratie_id) == [klaar_document]
        assert _wachtrij(accordeur_3, administratie_id) == []
        # Strenger (> € 500) → laag 2 valt weer weg, akkoord laag 1 blijft, accordeur_3 weer aan de beurt.
        uitkomst = zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(1, accordeur_1), _laag(2, accordeur_2, "500"), _laag(3, accordeur_3)],
        )
        assert (uitkomst.herberekend, uitkomst.vervallen) == (1, 0)
        assert _wachtrij(accordeur_3, administratie_id) == [klaar_document]
        assert _stappen(administratie_id, klaar_document)[0] == (1, accordeur_1, "akkoord", False)

    def test_ongewijzigd_schema_raakt_niets(
        self,
        ronde_met_akkoord_laag_1: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
    ) -> None:
        uitkomst = zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(2, accordeur_2), _laag(1, accordeur_1)],
        )
        assert (uitkomst.herberekend, uitkomst.vervallen) == (0, 0)
        assert _herberekend_regels(administratie_id, ronde_met_akkoord_laag_1) == []


class TestAfrondingEnVervallen:
    def test_laatste_laag_verwijderd_alles_gedekt_boekt_via_de_afrondingsroute(
        self,
        ronde_met_akkoord_laag_1: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        accordeur_1: uuid.UUID,
        boeken_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
        doc = ronde_met_akkoord_laag_1
        uitkomst = zet_schema(
            administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)]
        )
        assert (uitkomst.herberekend, uitkomst.vervallen) == (1, 0)
        # Zelfde pad als een laatste akkoord: ronde AFGEROND, boekmotor mét harde checks, geboekt.
        assert _ronde_statussen(admin_engine, doc) == [AccorderingStatus.AFGEROND.value]
        assert document_status(admin_engine, doc) == "geboekt"
        assert len(fake.puts) == 1
        regel = _herberekend_regels(administratie_id, doc)[0]
        assert regel.detail[service.HERBEREKEND_TIJDLIJN_SLEUTEL]["alles_akkoord"] is True
        acties = _audit_acties(admin_engine, "document_accordering")
        assert "accordering_afgerond" in acties and service.HERBEREKEND_AUDIT_ACTIE in acties

    def test_laatste_laag_valt_weg_door_drempel_zonder_boeken_toggle_is_boekfout_zichtbaar(
        self,
        ronde_met_akkoord_laag_1: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        doc = ronde_met_akkoord_laag_1
        uitkomst = zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(1, accordeur_1), _laag(2, accordeur_2, "1000")],
        )
        assert (uitkomst.herberekend, uitkomst.vervallen) == (1, 0)
        data = service.accordering_van_document(administratie_id=administratie_id, document_id=doc)
        assert data is not None and data.status == AccorderingStatus.AFGEROND.value
        # Boeken staat uit → zichtbare boek_fout op de ronde, document blijft bij de klant-status (bugfix 28-08).
        assert data.boek_fout
        assert document_status(admin_engine, doc) == "ter_accordering"

    def test_geen_gegeven_akkoord_past_meer_vervallen_pad(
        self,
        ronde_met_akkoord_laag_1: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        accordeur_2: uuid.UUID,
        accordeur_3: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        doc = ronde_met_akkoord_laag_1
        # accordeur_1 (het enige akkoord) verdwijnt → geen enkel akkoord past → bestaand vervallen-pad.
        uitkomst = zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(1, accordeur_3), _laag(2, accordeur_2)],
        )
        assert (uitkomst.herberekend, uitkomst.vervallen) == (1, 1)
        assert document_status(admin_engine, doc) == "klaar_om_te_boeken"
        assert _ronde_statussen(admin_engine, doc) == [AccorderingStatus.VERVALLEN.value]
        detail = documenten_service.haal_document_op(administratie_id=administratie_id, document_id=doc)
        regels = [g for g in detail.gebeurtenissen if g.detail and g.detail.get("accordering_vervallen")]
        assert len(regels) == 1 and regels[0].detail["reden"] == service.VERVALLEN_REDEN
        assert _herberekend_regels(administratie_id, doc) == []
        assert "accordering_vervallen" in _audit_acties(admin_engine, "document_accordering")
        meldingen = service.vervallen_meldingen(administratie_id=administratie_id)
        assert len(meldingen) == 1 and meldingen[0].aantal == 1

    def test_zonder_gegeven_akkoord_wordt_herberekend_nooit_vervallen(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        _bied_aan(administratie_id, klaar_document, gescoopte_gebruiker)
        uitkomst = zet_schema(
            administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_2)]
        )
        assert (uitkomst.herberekend, uitkomst.vervallen) == (1, 0)
        assert document_status(admin_engine, klaar_document) == "ter_accordering"
        assert _wachtrij(accordeur_2, administratie_id) == [klaar_document]
        assert _wachtrij(accordeur_1, administratie_id) == []
        assert service.vervallen_meldingen(administratie_id=administratie_id) == []

    def test_toggle_uit_laat_alle_rondes_vervallen(
        self,
        ronde_met_akkoord_laag_1: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        uitkomst = zet_schema(
            administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[], ingeschakeld=False
        )
        assert (uitkomst.herberekend, uitkomst.vervallen) == (1, 1)
        assert document_status(admin_engine, ronde_met_akkoord_laag_1) == "klaar_om_te_boeken"

    def test_compleet_klant_akkoord_blijft_onaangeraakt(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        """Regel 28-08: een compleet klant-akkoord (ronde AFGEROND, boeking nog niet gelukt) wordt door een
        configuratiewijziging niet geraakt en kan nooit opnieuw ter accordering."""
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        _bied_aan(administratie_id, klaar_document, gescoopte_gebruiker)
        resultaat = service.geef_akkoord(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1
        )
        assert resultaat.alles_akkoord is True and resultaat.geboekt is False  # Boeken-toggle uit → boek_fout
        assert _ronde_statussen(admin_engine, klaar_document) == [AccorderingStatus.AFGEROND.value]
        stappen_vooraf = _alle_stap_rijen(admin_engine, klaar_document)

        uitkomst = zet_schema(
            administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_2)]
        )
        assert (uitkomst.herberekend, uitkomst.vervallen) == (0, 0)
        assert _ronde_statussen(admin_engine, klaar_document) == [AccorderingStatus.AFGEROND.value]
        assert _alle_stap_rijen(admin_engine, klaar_document) == stappen_vooraf
        assert _herberekend_regels(administratie_id, klaar_document) == []
        # Nooit opnieuw ter accordering: het document staat nog bij de klant (boek_fout) → geweigerd; stond het
        # weer op klaar_om_te_boeken dan weigert `KlantAkkoordAlCompleet` (zelfde poort, punt 24 opruimrun 28-08).
        with pytest.raises(service.OngeldigeAanbieding):
            _bied_aan(administratie_id, klaar_document, gescoopte_gebruiker)


class TestDrieIngangenEnPreview:
    def test_detail_tab_put_response_en_accordeur_venster_aanleiding(
        self,
        ronde_met_akkoord_laag_1: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_3: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        doc = ronde_met_akkoord_laag_1
        # Het accordeur-venster ("Verwijderen…") stuurt dezelfde PUT mét aanleiding — één pad.
        resp = client.put(
            f"/administraties/{administratie_id}/accordering/instellingen",
            json={
                "ingeschakeld": True,
                "lagen": [
                    {"volgnummer": 1, "accordeur_gebruiker_id": str(accordeur_1)},
                    {"volgnummer": 2, "accordeur_gebruiker_id": str(accordeur_3)},
                ],
                "aanleiding": "verwijderd via Klant-accordeurs",
            },
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["rondes_herberekend"] == 1
        assert resp.json()["rondes_vervallen"] == 0
        regel = _herberekend_regels(administratie_id, doc)[0]
        assert regel.detail["aanleiding"] == "verwijderd via Klant-accordeurs"
        assert document_status(admin_engine, doc) == "ter_accordering"
        # GET draagt de telling niet (alleen een uitkomst van de PUT).
        resp = client.get(
            f"/administraties/{administratie_id}/accordering/instellingen",
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.json()["rondes_herberekend"] == 0 and resp.json()["rondes_vervallen"] == 0

    def test_bulk_preview_telt_met_dezelfde_regel_en_toepassen_herberekent(
        self,
        ronde_met_akkoord_laag_1: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
        accordeur_3: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        doc = ronde_met_akkoord_laag_1
        # Preview A: akkoord laag 1 blijft → 1 herberekend, 0 vervallen.
        uitkomsten, _ = service.bulk_instellen_preview(
            administratie_ids=[administratie_id],
            lagen=[_laag(1, accordeur_1), _laag(2, accordeur_3)],
            scope_toevoegen=True,
            actor_id=beheerder_id,
            actor_rol="beheerder",
        )
        assert (uitkomsten[0].uitkomst, uitkomsten[0].rondes_herberekend, uitkomsten[0].rondes_vervallen) == (
            "vervangen",
            1,
            0,
        )
        # Preview B: accordeur_1 weg → geen akkoord past → 1 herberekend, waarvan 1 vervalt.
        uitkomsten, _ = service.bulk_instellen_preview(
            administratie_ids=[administratie_id],
            lagen=[_laag(1, accordeur_3), _laag(2, accordeur_2)],
            scope_toevoegen=True,
            actor_id=beheerder_id,
            actor_rol="beheerder",
        )
        assert (uitkomsten[0].rondes_herberekend, uitkomsten[0].rondes_vervallen) == (1, 1)
        # Preview schrijft niets.
        assert _stappen(administratie_id, doc) == [(1, accordeur_1, "akkoord", False), (2, accordeur_2, None, True)]
        assert _herberekend_regels(administratie_id, doc) == []
        # Toepassen A via de bulk = hetzelfde pad als de detail-tab.
        resultaat = service.bulk_instellen(
            administratie_ids=[administratie_id],
            lagen=[_laag(1, accordeur_1), _laag(2, accordeur_3)],
            scope_toevoegen=True,
            actor_id=beheerder_id,
            actor_rol="beheerder",
        )
        assert (resultaat[0].rondes_herberekend, resultaat[0].rondes_vervallen) == (1, 0)
        assert _stappen(administratie_id, doc) == [(1, accordeur_1, "akkoord", False), (2, accordeur_3, None, True)]
        assert document_status(admin_engine, doc) == "ter_accordering"
        # Ook via HTTP dragen preview én resultaat beide tellers.
        body = {
            "administratie_ids": [str(administratie_id)],
            "lagen": [
                {"volgnummer": 1, "accordeur_gebruiker_id": str(accordeur_3)},
                {"volgnummer": 2, "accordeur_gebruiker_id": str(accordeur_2)},
            ],
            "scope_toevoegen": True,
        }
        resp = client.post(
            "/accordering/bulk-instellen/preview", json=body, headers=_bearer(beheerder_id, rol="beheerder")
        )
        assert resp.status_code == 200, resp.text
        u = resp.json()["uitkomsten"][0]
        # Ná toepassen A is het akkoord van accordeur_1 het enige akkoord → B laat 'm vervallen.
        assert (u["rondes_herberekend"], u["rondes_vervallen"]) == (1, 1)


class TestMeldingHeropend:
    def test_accordeur_wiens_akkoord_verviel_en_opnieuw_gevraagd_wordt_wordt_opnieuw_gemeld(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
        accordeur_3: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        doc = klaar_document
        zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(1, accordeur_1), _laag(2, accordeur_2), _laag(3, accordeur_3)],
        )
        _bied_aan(administratie_id, doc, gescoopte_gebruiker)
        service.geef_akkoord(administratie_id=administratie_id, document_id=doc, actor_id=accordeur_1)
        service.geef_akkoord(administratie_id=administratie_id, document_id=doc, actor_id=accordeur_2)
        # Bundelmelding-log: alle drie zijn al 'verzonden' gemeld voor dit document.
        with admin_engine.begin() as conn:
            for g in (accordeur_1, accordeur_2, accordeur_3):
                conn.execute(
                    text(
                        "INSERT INTO platform.accordeur_nieuw_gemeld (id, gebruiker_id, document_id, status) "
                        "VALUES (:id, :g, :d, 'verzonden')"
                    ),
                    {"id": uuid.uuid4(), "g": g, "d": doc},
                )
        # accordeur_1 naar laag 2 (akkoord vervalt, opnieuw gevraagd); accordeur_2 naar laag 1 (akkoord blijft);
        # accordeur_3 blijft onbeslist (stap hergebruikt).
        zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(1, accordeur_2), _laag(2, accordeur_1), _laag(3, accordeur_3)],
        )
        with admin_engine.connect() as conn:
            rijen = conn.execute(
                text("SELECT gebruiker_id, status, detail FROM platform.accordeur_nieuw_gemeld WHERE document_id = :d"),
                {"d": doc},
            ).all()
        statussen = {r.gebruiker_id: r.status for r in rijen}
        assert statussen[accordeur_1] == "overgeslagen"  # heropend → volgende run meldt opnieuw zodra aan de beurt
        assert statussen[accordeur_2] == "verzonden"
        assert statussen[accordeur_3] == "verzonden"  # al gemeld, nog steeds dezelfde open vraag
        detail = next(r.detail for r in rijen if r.gebruiker_id == accordeur_1)
        assert detail["heropend"]["reden"] == service.HERBEREKEND_REDEN
