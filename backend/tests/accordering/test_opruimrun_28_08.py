"""Opruimrun 28-08 — punt 24 (aanbieden weigert bij compleet klant-akkoord) + punt 23 (volumerem
vs klant-akkoord: teller-bug + noodrem-uitzondering voor het accorderingspad, autoboek-paden
onverkort onder de 20/dag-rem)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.accordering import service
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import boeken
from app.documenten import service as documenten_service
from app.documenten.models import Document, DocumentGebeurtenis, DocumentStatus
from app.documenten.service import _schrijf_overgang
from app.doorbelasting import boeken as doorbelasting_boeken
from tests.accordering.conftest import document_status, maak_klaar_document, zet_schema
from tests.accordering.test_doorbelasting_in_flow import klaargezet_op_klaar_document  # noqa: F401
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.doorbelasting.conftest import (  # noqa: F401 — fixtures via import geregistreerd
    FakeDoorbelastingClient,
    doel_administratie_id,
    doorbelasting_aan,
    haal_run,
    instelling_compleet,
)


def _laag(volgnummer: int, accordeur: uuid.UUID) -> service.LaagInput:
    return service.LaagInput(volgnummer=volgnummer, accordeur_gebruiker_id=accordeur, bedrag_drempel=None)


def _patch_rlz(monkeypatch: pytest.MonkeyPatch) -> FakeBoekClient:
    fake = FakeBoekClient()
    monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
    return fake


def _casus_van_vandaag(*, administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, klaar_document) -> None:
    """De casus 28-08: klant-akkoord compleet (laatste ronde afgerond) maar het document hangt op
    klaar_om_te_boeken (oude stille terugval — boeken stond destijds uit) en is niet geboekt."""
    zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
    service.bied_ter_accordering_aan(
        administratie_id=administratie_id,
        document_id=klaar_document,
        actor_id=gescoopte_gebruiker,
        actor_rol="boekhouding",
    )
    resultaat = service.geef_akkoord(
        administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1
    )
    assert resultaat.alles_akkoord and not resultaat.geboekt  # boeken_aan ontbreekt → boek_fout
    with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
        document = session.get(Document, klaar_document)
        _schrijf_overgang(
            session, document=document, naar=DocumentStatus.KLAAR_OM_TE_BOEKEN, actor_id=gescoopte_gebruiker
        )


class TestPunt24AanbiedenWeigertBijCompleetAkkoord:
    def test_losse_route_409_en_boeken_kan_wel(
        self,
        klaar_document,
        administratie_id,
        beheerder_id,
        gescoopte_gebruiker,
        accordeur_1,
        admin_engine: Engine,
        monkeypatch,
    ) -> None:
        fake = _patch_rlz(monkeypatch)
        _casus_van_vandaag(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            gescoopte_gebruiker=gescoopte_gebruiker,
            accordeur_1=accordeur_1,
            klaar_document=klaar_document,
        )
        assert document_status(admin_engine, klaar_document) == "klaar_om_te_boeken"

        # Aanbieden geweigerd — leesbare reden, eigen exceptie (router → 409), niets gewijzigd.
        with pytest.raises(service.KlantAkkoordAlCompleet, match="boek het direct"):
            service.bied_ter_accordering_aan(
                administratie_id=administratie_id,
                document_id=klaar_document,
                actor_id=gescoopte_gebruiker,
                actor_rol="boekhouding",
            )
        assert document_status(admin_engine, klaar_document) == "klaar_om_te_boeken"
        with scoped_session(administratie_id) as session:
            rondes = session.execute(
                text("SELECT count(*) FROM boekhouding.document_accordering WHERE document_id = :d"),
                {"d": klaar_document},
            ).scalar_one()
        assert rondes == 1  # geen tweede ronde

        # De documentenlijst markeert de rij (bulk-checkbox uit mét uitleg).
        rijen = documenten_service.lijst_documenten(administratie_id=administratie_id)
        rij = next(r for r in rijen if r.document.id == klaar_document)
        assert rij.klant_akkoord_compleet is True

        # Boeken kan wél (accorderingspoort staat open) — de casus van vandaag opgelost.
        from app.beheer import service as beheer_service

        beheer_service.zet_boeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        boek = boeken.boek_document(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
        )
        assert boek.status == DocumentStatus.GEBOEKT and len(fake.puts) == 1
        # Ná de boeking is het akkoord verzilverd — de lijstmarkering verdwijnt.
        rijen = documenten_service.lijst_documenten(administratie_id=administratie_id)
        assert next(r for r in rijen if r.document.id == klaar_document).klant_akkoord_compleet is False

    def test_bulk_slaat_over_met_reden(
        self,
        klaar_document,
        administratie_id,
        beheerder_id,
        gescoopte_gebruiker,
        accordeur_1,
        admin_engine: Engine,
        opslag,
        monkeypatch,
    ) -> None:
        _patch_rlz(monkeypatch)
        _casus_van_vandaag(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            gescoopte_gebruiker=gescoopte_gebruiker,
            accordeur_1=accordeur_1,
            klaar_document=klaar_document,
        )
        # Een tweede, gewoon boekklaar document gaat wél de ronde in.
        ander = maak_klaar_document(gescoopte_gebruiker, administratie_id, admin_engine, opslag, naam="ander.pdf")
        resultaten = service.bulk_aanbieden(
            administratie_id=administratie_id,
            document_ids=[klaar_document, ander],
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        per_id = {r.document_id: r for r in resultaten}
        assert per_id[klaar_document].uitkomst == "overgeslagen"
        assert "Klant-akkoord is al compleet" in (per_id[klaar_document].reden or "")
        assert per_id[ander].uitkomst == "aangeboden"
        assert document_status(admin_engine, klaar_document) == "klaar_om_te_boeken"
        assert document_status(admin_engine, ander) == "ter_accordering"

    def test_bedrag_gewijzigd_na_akkoord_mag_wel_opnieuw(
        self,
        klaar_document,
        administratie_id,
        beheerder_id,
        gescoopte_gebruiker,
        accordeur_1,
        admin_engine: Engine,
        monkeypatch,
    ) -> None:
        """Het bedrag is ná het akkoord gewijzigd → de boekpoort is dicht ('opnieuw aanbieden') en
        aanbieden moet dus juist WÉL kunnen — de weigering geldt alleen bij een open boekpoort."""
        _patch_rlz(monkeypatch)
        _casus_van_vandaag(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            gescoopte_gebruiker=gescoopte_gebruiker,
            accordeur_1=accordeur_1,
            klaar_document=klaar_document,
        )
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            session.execute(
                text("UPDATE boekhouding.boekvoorstel SET totaalbedrag = totaalbedrag + 1 WHERE document_id = :d"),
                {"d": klaar_document},
            )
        uitkomst = service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        assert uitkomst.alles_akkoord is False
        assert document_status(admin_engine, klaar_document) == "ter_accordering"


class TestPunt23VolumeremVsKlantAkkoord:
    def test_teller_telt_alleen_echte_overgangen_naar_geboekt(
        self, klaar_document, administratie_id, gescoopte_gebruiker, admin_engine: Engine
    ) -> None:
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            assert boeken._boekingen_vandaag(session, administratie_id=administratie_id) == 0
            document = session.get(Document, klaar_document)
            _schrijf_overgang(session, document=document, naar=DocumentStatus.GEBOEKT, actor_id=gescoopte_gebruiker)
            # Drie tijdlijn-notities ná het boeken (geboekt → geboekt: webhook/doorbelasting/notitie)
            for _ in range(3):
                session.add(
                    DocumentGebeurtenis(
                        id=uuid.uuid4(),
                        document_id=klaar_document,
                        van_status=DocumentStatus.GEBOEKT,
                        naar_status=DocumentStatus.GEBOEKT,
                        actor_id=SYSTEEM_ACTOR_ID,
                        detail={"reden": "notitie"},
                    )
                )
        with scoped_session(administratie_id) as session:
            # Vóór de fix: 4. Nu: precies de ene echte boeking.
            assert boeken._boekingen_vandaag(session, administratie_id=administratie_id) == 1

    def test_akkoordpad_boekt_ondanks_20_rem_op_nul(
        self,
        klaar_document,
        administratie_id,
        beheerder_id,
        gescoopte_gebruiker,
        accordeur_1,
        boeken_aan,
        admin_engine: Engine,
        monkeypatch,
    ) -> None:
        fake = _patch_rlz(monkeypatch)
        monkeypatch.setattr(boeken.settings, "max_boekingen_per_dag_per_administratie", 0)
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        resultaat = service.geef_akkoord(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1
        )
        assert resultaat.geboekt and resultaat.boek_fout is None
        assert document_status(admin_engine, klaar_document) == "geboekt" and len(fake.puts) == 1

    def test_autoboekpad_blijft_onder_de_20_rem(
        self, klaar_document, administratie_id, gescoopte_gebruiker, boeken_aan, admin_engine: Engine, monkeypatch
    ) -> None:
        """Zonder accordering (het gewone/autoboek-pad) bijt de 20/dag-rem onverkort — de noodrem
        speelt daar geen rol, ook niet als die ruim staat."""
        fake = _patch_rlz(monkeypatch)
        monkeypatch.setattr(boeken.settings, "max_boekingen_per_dag_per_administratie", 0)
        monkeypatch.setattr(boeken.settings, "max_boekingen_na_klant_akkoord_per_dag_per_administratie", 200)
        with pytest.raises(boeken.VolumeremBereikt, match="Dagelijkse limiet van 0"):
            boeken.boek_document(
                administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
            )
        assert fake.puts == [] and document_status(admin_engine, klaar_document) == "klaar_om_te_boeken"

    def test_doorbelasting_in_dezelfde_gang_valt_onder_de_noodrem(
        self,
        klaargezet_op_klaar_document: dict,  # noqa: F811
        klaar_document,
        administratie_id,
        beheerder_id,
        gescoopte_gebruiker,
        accordeur_1,
        boeken_aan,
        admin_engine: Engine,
        monkeypatch,
    ) -> None:
        _patch_rlz(monkeypatch)
        bron, doel = FakeDoorbelastingClient(), FakeDoorbelastingClient()
        monkeypatch.setattr(
            doorbelasting_boeken, "_rlz_client_voor", lambda aid: bron if aid == administratie_id else doel
        )
        # 20-rem op 0: de eigen doorbelasting-rem zou de spiegel/verkoop normaal blokkeren.
        monkeypatch.setattr(boeken.settings, "max_boekingen_per_dag_per_administratie", 0)
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        # Aanbieden als Beheerder (scope op de doel-administratie voor de doorbelasting-checks).
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=beheerder_id, actor_rol="beheerder"
        )
        resultaat = service.geef_akkoord(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1
        )
        assert resultaat.geboekt and resultaat.boek_fout is None, resultaat.boek_fout
        run = haal_run(administratie_id, klaargezet_op_klaar_document["run"].id)
        assert run.status == "geboekt"
