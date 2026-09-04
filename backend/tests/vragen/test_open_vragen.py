# ruff: noqa: F811 — pytest-fixtures als parameters
"""Open vragen kantoorbreed (design-ronde 03-09 blok B2, mockup inzicht-kantoorbreed.html ④): één
server-side lijst over álle administraties in scope — oudste eerst, filters aan-mij/ouderdom/administratie/
zoekterm, paginering, tellers + facet, en de scope-toets mét een echte niet-Beheerder MÉT scope (ziet
uitsluitend de eigen administratie; Platform conventies §RLS). Rolpoort: kantoorrol (matrix in
tests/security/test_rol_endpoint_gates.py)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service as auth_service
from app.db.models import GebruikerRol
from app.db.session import scoped_session
from app.documenten import service as documenten_service
from app.documenten import vragen as vragen_service
from app.documenten.models import Document, DocumentStatus
from app.documenten.storage import LokaleBestandsopslag
from app.main import app
from app.security.tokens import create_access_token
from app.vragen import service
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


@pytest.fixture
def tweede_administratie_id(admin_engine: Engine) -> uuid.UUID:
    """Administratie BUITEN de scope van `gescoopte_gebruiker` (alleen de Beheerder ziet 'm)."""
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Buiten scope B.V.', :rlz)"),
            {"id": aid, "rlz": f"rlz-{aid}"},
        )
    return aid


def _document(administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag, naam: str) -> uuid.UUID:
    resultaat = documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=naam,
        inhoud=uuid.uuid4().bytes,
        actor_id=actor_id,
        opslag=opslag,
    )
    assert resultaat.status == DocumentStatus.TE_CONTROLEREN
    return resultaat.document_id


def _vraag(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    *,
    actor_id: uuid.UUID,
    toegewezen_aan: uuid.UUID,
    tekst: str,
) -> uuid.UUID:
    data = vragen_service.stel_vraag(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        vraag_tekst=tekst,
        toegewezen_aan=toegewezen_aan,
    )
    return data.id


def _zet_gesteld_op(admin_engine: Engine, vraag_id: uuid.UUID, dagen_terug: int) -> None:
    """Testhulp: de vraag ouder maken (de kolom is server-default now(); de service leest 'm alleen)."""
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE boekhouding.vraag SET gesteld_op = now() - make_interval(days => :d) WHERE id = :id"),
            {"d": dagen_terug, "id": vraag_id},
        )


def _zet_referentie(admin_engine: Engine, document_id: uuid.UUID, referentie: str, bedrag: str) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.boekvoorstel (document_id, referentie, totaalbedrag) VALUES (:d, :r, :b)"
            ),
            {"d": document_id, "r": referentie, "b": bedrag},
        )


@pytest.fixture
def drie_vragen(
    admin_engine: Engine,
    administratie_id: uuid.UUID,
    tweede_administratie_id: uuid.UUID,
    beheerder_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
    opslag: LokaleBestandsopslag,
) -> dict[str, uuid.UUID]:
    """Twee open vragen in de gescoopte administratie (10 en 2 dagen oud; één aan de boekhouder, één aan
    de Beheerder) + één in de administratie buiten scope (5 dagen oud, aan de Beheerder). Daarnaast een
    afgehandelde vraag die NIET in de lijst mag verschijnen."""
    doc_oud = _document(administratie_id, gescoopte_gebruiker, opslag, "shell-tankbon.pdf")
    doc_jong = _document(administratie_id, gescoopte_gebruiker, opslag, "riwal-lift.pdf")
    doc_buiten = _document(tweede_administratie_id, beheerder_id, opslag, "buiten-scope.pdf")
    doc_dicht = _document(administratie_id, gescoopte_gebruiker, opslag, "al-afgehandeld.pdf")
    _zet_referentie(admin_engine, doc_oud, "04-9284", "96.20")
    _zet_referentie(admin_engine, doc_jong, "RW-2140", "2140.00")

    v_oud = _vraag(
        administratie_id,
        doc_oud,
        actor_id=beheerder_id,
        toegewezen_aan=gescoopte_gebruiker,
        tekst="Is dit privé of zakelijk getankt?",
    )
    v_jong = _vraag(
        administratie_id,
        doc_jong,
        actor_id=gescoopte_gebruiker,
        toegewezen_aan=beheerder_id,
        tekst="Welke kostenplaats voor deze lift?",
    )
    v_buiten = _vraag(
        tweede_administratie_id,
        doc_buiten,
        actor_id=beheerder_id,
        toegewezen_aan=beheerder_id,
        tekst="Vraag buiten scope",
    )
    v_dicht = _vraag(
        administratie_id,
        doc_dicht,
        actor_id=gescoopte_gebruiker,
        toegewezen_aan=beheerder_id,
        tekst="Al afgehandeld",
    )
    vragen_service.handel_vraag_af(
        administratie_id=administratie_id, vraag_id=v_dicht, actor_id=gescoopte_gebruiker, slotbericht=None
    )
    _zet_gesteld_op(admin_engine, v_oud, 10)
    _zet_gesteld_op(admin_engine, v_jong, 2)
    _zet_gesteld_op(admin_engine, v_buiten, 5)
    return {
        "v_oud": v_oud,
        "v_jong": v_jong,
        "v_buiten": v_buiten,
        "v_dicht": v_dicht,
        "doc_oud": doc_oud,
        "doc_jong": doc_jong,
    }


class TestServiceLijst:
    def test_beheerder_ziet_alle_open_vragen_oudste_eerst_met_kop_en_wachttijd(
        self, drie_vragen, beheerder_id, administratie_id, tweede_administratie_id, gescoopte_gebruiker
    ) -> None:
        lijst = service.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER)
        assert [r.vraag_id for r in lijst.rijen] == [drie_vragen["v_oud"], drie_vragen["v_buiten"], drie_vragen["v_jong"]]
        assert lijst.totaal == 3 and lijst.pagina == 1 and lijst.per_pagina == 25
        oud = lijst.rijen[0]
        assert oud.wacht_dagen == 10 and oud.referentie == "04-9284" and str(oud.totaalbedrag) == "96.20"
        assert oud.administratie_id == administratie_id and oud.document_bestandsnaam == "shell-tankbon.pdf"
        assert oud.aan_de_beurt_id == gescoopte_gebruiker and oud.aan_de_beurt_naam == "Boekhouder"
        assert oud.gesteld_door_naam == "Test-Beheerder" and oud.aan_mij is False
        assert oud.blokkeert_boeken is True and oud.document_status == "vraag_open"
        assert oud.laatste_bericht is None
        # De afgehandelde vraag hoort nergens in de lijst.
        assert drie_vragen["v_dicht"] not in {r.vraag_id for r in lijst.rijen}
        # Tellers + facet gaan over de hele scope-set.
        assert lijst.tellers == service.Tellers(open=3, aan_mij=2, blokkeert_boeken=3, administraties=2)
        assert [(f.administratie_id, f.aantal) for f in lijst.administraties] == [
            (tweede_administratie_id, 1),
            (administratie_id, 2),
        ]

    def test_filter_aan_mij_volgt_aan_de_beurt(self, drie_vragen, beheerder_id, gescoopte_gebruiker, administratie_id) -> None:
        mij = service.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, toegewezen="mij")
        assert {r.vraag_id for r in mij.rijen} == {drie_vragen["v_jong"], drie_vragen["v_buiten"]}
        assert all(r.aan_mij for r in mij.rijen)
        # Ná een bericht van de Beheerder wisselt de beurt naar de vraagsteller (dialoogmodel 25-08):
        # de vraag verdwijnt uit "aan mij" en het laatste bericht staat op de rij.
        vragen_service.plaats_bericht(
            administratie_id=administratie_id,
            vraag_id=drie_vragen["v_jong"],
            actor_id=beheerder_id,
            tekst="Kostenplaats 4010, denk ik — klopt dat?",
        )
        mij2 = service.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, toegewezen="mij")
        assert {r.vraag_id for r in mij2.rijen} == {drie_vragen["v_buiten"]}
        rij = next(r for r in service.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER).rijen if r.vraag_id == drie_vragen["v_jong"])
        assert rij.laatste_bericht == "Kostenplaats 4010, denk ik — klopt dat?"
        assert rij.laatste_bericht_door == "Test-Beheerder" and rij.aan_de_beurt_id == gescoopte_gebruiker
        # De tellers volgen mee: nog maar één "aan mij".
        assert service.tellers(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER).aan_mij == 1

    def test_filter_ouderdom_is_minstens_n_dagen(self, drie_vragen, beheerder_id) -> None:
        assert {r.vraag_id for r in service.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, ouder_dan_dagen=7).rijen} == {
            drie_vragen["v_oud"]
        }
        assert {r.vraag_id for r in service.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, ouder_dan_dagen=5).rijen} == {
            drie_vragen["v_oud"],
            drie_vragen["v_buiten"],
        }
        assert service.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, ouder_dan_dagen=0).totaal == 3
        assert service.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, ouder_dan_dagen=30).totaal == 0

    def test_filter_administratie_en_zoekterm_zijn_filters_op_de_scope_set(
        self, drie_vragen, beheerder_id, administratie_id, tweede_administratie_id
    ) -> None:
        een = service.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, administratie_id=administratie_id)
        assert [r.vraag_id for r in een.rijen] == [drie_vragen["v_oud"], drie_vragen["v_jong"]]
        # Tellers blijven de ongefilterde stand (chips in de paneelkop), totaal is de selectie.
        assert een.totaal == 2 and een.tellers.open == 3
        # Onbekende administratie = nul rijen, geen fout (filter, nooit poort).
        assert service.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, administratie_id=uuid.uuid4()).totaal == 0
        # Zoekterm over vraagtekst, referentie, bestandsnaam en administratienaam.
        assert [r.vraag_id for r in service.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, q="kostenplaats").rijen] == [
            drie_vragen["v_jong"]
        ]
        assert [r.vraag_id for r in service.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, q="04-9284").rijen] == [
            drie_vragen["v_oud"]
        ]
        assert [r.vraag_id for r in service.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, q="buiten scope b.v.").rijen] == [
            drie_vragen["v_buiten"]
        ]

    def test_paginering_snijdt_de_gesorteerde_selectie(self, drie_vragen, beheerder_id) -> None:
        p1 = service.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, per_pagina=2, pagina=1)
        p2 = service.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, per_pagina=2, pagina=2)
        p3 = service.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, per_pagina=2, pagina=3)
        assert [r.vraag_id for r in p1.rijen] == [drie_vragen["v_oud"], drie_vragen["v_buiten"]]
        assert [r.vraag_id for r in p2.rijen] == [drie_vragen["v_jong"]]
        assert p3.rijen == [] and p1.totaal == p2.totaal == p3.totaal == 3

    def test_ongeldige_filterwaarden_geven_een_leesbare_fout(self, beheerder_id) -> None:
        with pytest.raises(service.OpenVragenFout):
            service.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, toegewezen="iedereen")
        with pytest.raises(service.OpenVragenFout):
            service.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, ouder_dan_dagen=-1)
        with pytest.raises(service.OpenVragenFout):
            service.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, pagina=0)

    def test_vraag_op_terminaal_document_telt_niet_mee(
        self, drie_vragen, beheerder_id, administratie_id, gescoopte_gebruiker
    ) -> None:
        # Een verwijderd document mét nog-open vraag is geen werk meer (zelfde regel als de werkvoorraad-
        # tellers): de vraag valt uit lijst én tellers.
        documenten_service.verwijder_document(
            administratie_id=administratie_id,
            document_id=drie_vragen["doc_jong"],
            actor_id=gescoopte_gebruiker,
            reden="test: dubbel geüpload",
        )
        lijst = service.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER)
        assert drie_vragen["v_jong"] not in {r.vraag_id for r in lijst.rijen} and lijst.tellers.open == 2

    def test_wacht_dagen_helper(self) -> None:
        nu = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
        assert service._wacht_dagen(nu - timedelta(days=8, hours=3), nu) == 8
        assert service._wacht_dagen(nu - timedelta(hours=5), nu) == 0
        assert service._wacht_dagen(nu + timedelta(days=1), nu) == 0
        assert service._wacht_dagen(datetime(2026, 9, 1, 12, 0), nu) == 2  # naïef = UTC


class TestScopeEnRol:
    def test_niet_beheerder_met_scope_ziet_uitsluitend_eigen_administratie(
        self, drie_vragen, gescoopte_gebruiker, administratie_id, tweede_administratie_id
    ) -> None:
        """Echte niet-owner-roltest (conventies §RLS): boekhouder mét scope op één administratie."""
        lijst = service.lijst(actor_id=gescoopte_gebruiker, rol=GebruikerRol.BOEKHOUDING)
        assert [r.vraag_id for r in lijst.rijen] == [drie_vragen["v_oud"], drie_vragen["v_jong"]]
        assert {r.administratie_id for r in lijst.rijen} == {administratie_id}
        assert lijst.tellers == service.Tellers(open=2, aan_mij=1, blokkeert_boeken=2, administraties=1)
        assert [f.administratie_id for f in lijst.administraties] == [administratie_id]
        # "Aan mij" voor de boekhouder = de vraag die de Beheerder aan hem stelde.
        assert [r.vraag_id for r in lijst.rijen if r.aan_mij] == [drie_vragen["v_oud"]]
        # Expliciet filteren op de administratie buiten scope = nul rijen, nooit een lek of een fout.
        assert (
            service.lijst(
                actor_id=gescoopte_gebruiker, rol=GebruikerRol.BOEKHOUDING, administratie_id=tweede_administratie_id
            ).totaal
            == 0
        )

    def test_http_lijst_en_stand_voor_boekhouder_en_beheerder(
        self, drie_vragen, gescoopte_gebruiker, beheerder_id, administratie_id
    ) -> None:
        resp = client.get("/vragen", headers=_bearer(gescoopte_gebruiker, rol="boekhouding"))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert [r["vraag_id"] for r in body["rijen"]] == [str(drie_vragen["v_oud"]), str(drie_vragen["v_jong"])]
        assert body["tellers"] == {"open": 2, "aan_mij": 1, "blokkeert_boeken": 2, "administraties": 1}
        assert body["totaal"] == 2 and body["pagina"] == 1 and body["per_pagina"] == 25
        assert body["administraties"] == [
            {"administratie_id": str(administratie_id), "administratie_naam": "Scope-test", "aantal": 2}
        ]
        rij = body["rijen"][0]
        assert rij["wacht_dagen"] == 10 and rij["aan_mij"] is True and rij["referentie"] == "04-9284"
        assert rij["totaalbedrag"] == "96.20" and rij["aan_de_beurt_naam"] == "Boekhouder"

        stand = client.get("/vragen/stand", headers=_bearer(beheerder_id, rol="beheerder"))
        assert stand.status_code == 200 and stand.json() == {
            "open": 3,
            "aan_mij": 2,
            "blokkeert_boeken": 3,
            "administraties": 2,
        }

    def test_http_filters_lopen_door_naar_de_service(self, drie_vragen, beheerder_id, administratie_id) -> None:
        h = _bearer(beheerder_id, rol="beheerder")
        assert [r["vraag_id"] for r in client.get("/vragen?toegewezen=mij", headers=h).json()["rijen"]] == [
            str(drie_vragen["v_buiten"]),
            str(drie_vragen["v_jong"]),
        ]
        assert [r["vraag_id"] for r in client.get("/vragen?ouder_dan_dagen=7", headers=h).json()["rijen"]] == [
            str(drie_vragen["v_oud"])
        ]
        assert client.get(f"/vragen?administratie_id={administratie_id}", headers=h).json()["totaal"] == 2
        assert client.get("/vragen?q=lift", headers=h).json()["totaal"] == 1
        assert client.get("/vragen?pagina=2", headers=h).json()["rijen"] == []
        # Ongeldige waarden = 422, nooit stil "alle".
        assert client.get("/vragen?toegewezen=iedereen", headers=h).status_code == 422
        assert client.get("/vragen?ouder_dan_dagen=-1", headers=h).status_code == 422
        assert client.get("/vragen?pagina=0", headers=h).status_code == 422

    def test_zonder_token_401(self) -> None:
        assert client.get("/vragen").status_code == 401
        assert client.get("/vragen/stand").status_code == 401

    def test_externe_rol_403_ook_met_scope(self, admin_engine: Engine, beheerder_id, administratie_id) -> None:
        gid = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                    "VALUES (:id, 'Klant A.', :mail, 'klant_accordeur', 'actief')"
                ),
                {"id": gid, "mail": f"{gid}@test.local"},
            )
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=gid, administratie_id=administratie_id)
        assert client.get("/vragen", headers=_bearer(gid, rol="klant_accordeur")).status_code == 403
        assert client.get("/vragen/stand", headers=_bearer(gid, rol="klant_accordeur")).status_code == 403


class TestDefinitieKpi:
    def test_vraag_aan_accordeur_op_geboekt_document_telt_als_open_vraag_maar_blokkeert_niet(
        self, admin_engine: Engine, administratie_id, beheerder_id, gescoopte_gebruiker, opslag
    ) -> None:
        """Blok B5 (26-08): een vraag op een document dat bij de klant ligt/geboekt is laat de documentstatus
        staan. Zo'n vraag wacht wél op antwoord → in de lijst en in `open`, niet in `blokkeert_boeken`.
        Sinds G1 (03-09) telt de klantenlijst-kolom "Vragen" dezelfde definitie (zie test_tellers_gelijk.py)."""
        doc = _document(administratie_id, gescoopte_gebruiker, opslag, "geboekt-met-vraag.pdf")
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            document = session.get(Document, doc)
            assert document is not None
            # Testhulp: rechtstreeks naar geboekt via de statusmachine-schrijver (klaar → geboekt).
            documenten_service._schrijf_overgang(
                session, document=document, naar=DocumentStatus.KLAAR_OM_TE_BOEKEN, actor_id=gescoopte_gebruiker
            )
            documenten_service._schrijf_overgang(
                session, document=document, naar=DocumentStatus.GEBOEKT, actor_id=gescoopte_gebruiker
            )
        _vraag(administratie_id, doc, actor_id=gescoopte_gebruiker, toegewezen_aan=beheerder_id, tekst="Nog een bon?")
        lijst = service.lijst(actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER)
        assert lijst.totaal == 1
        rij = lijst.rijen[0]
        assert rij.document_status == "geboekt" and rij.blokkeert_boeken is False and rij.aan_mij is True
        assert lijst.tellers == service.Tellers(open=1, aan_mij=1, blokkeert_boeken=0, administraties=1)
