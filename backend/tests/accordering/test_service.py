"""Geldlogica van de klant-accorderingsflow (mockup #autorisatie, migratie 0033): statusmachine,
sequentiële lagen + bedragdrempels, staande goedkeuring, en de harde-checks-hercheck bij het
automatische boeken na het laatste akkoord."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.accordering import service
from app.documenten import boeken
from tests.accordering.conftest import TOTAAL, VENDOR_ID, document_status, zet_schema
from tests.documenten.fake_rlz_client import FakeBoekClient


def _patch_rlz(monkeypatch: pytest.MonkeyPatch) -> FakeBoekClient:
    fake = FakeBoekClient()
    monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
    return fake


def _laag(volgnummer: int, accordeur: uuid.UUID, drempel: str | None = None) -> service.LaagInput:
    return service.LaagInput(
        volgnummer=volgnummer,
        accordeur_gebruiker_id=accordeur,
        bedrag_drempel=Decimal(drempel) if drempel else None,
    )


class TestInstellingen:
    def test_aanzetten_zonder_lagen_geweigerd(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID
    ) -> None:
        with pytest.raises(service.GeenLagenIngesteld):
            zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[])

    def test_accordeur_mag_geen_instellingen_wijzigen(
        self, administratie_id: uuid.UUID, accordeur_1: uuid.UUID
    ) -> None:
        with pytest.raises(service.KantoorActieVereist):
            service.instellingen_opslaan(
                administratie_id=administratie_id,
                actor_id=accordeur_1,
                actor_rol="klant_accordeur",
                ingeschakeld=True,
                lagen=[_laag(1, accordeur_1)],
            )

    def test_schema_opslaan_en_lezen(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, accordeur_1: uuid.UUID, accordeur_2: uuid.UUID
    ) -> None:
        zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(1, accordeur_1), _laag(2, accordeur_2, "1000.00")],
        )
        ingeschakeld, lagen, namen = service.instellingen_ophalen(administratie_id=administratie_id)
        assert ingeschakeld is True
        assert [(laag.volgnummer, laag.bedrag_drempel) for laag in lagen] == [(1, None), (2, Decimal("1000.00"))]
        assert namen[accordeur_1] == "S. Bakker"


class TestAanbiedenEnSequentie:
    def test_direct_boeken_geweigerd_bij_accordering_aan(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """CLAUDE.md hard: de boekknop wordt "Ter accordering" — en server-side is direct boeken
        écht dicht, niet alleen in de UI."""
        _patch_rlz(monkeypatch)
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        with pytest.raises(boeken.AccorderingVereist):
            boeken.boek_document(
                administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
            )

    def test_aanbieden_bevriest_stappen_met_drempel(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        # Laag 2 geldt alleen boven € 1.000 — dit document is € 121 → laag 2 niet vereist.
        zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(1, accordeur_1), _laag(2, accordeur_2, "1000.00")],
        )
        resultaat = service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        assert document_status(admin_engine, klaar_document) == "ter_accordering"
        assert [(s.volgnummer, s.vereist) for s in resultaat.accordering.stappen] == [(1, True), (2, False)]
        assert resultaat.accordering.stappen[0].aan_de_beurt is True
        assert resultaat.alles_akkoord is False

    def test_accordeur_mag_niet_aanbieden(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        accordeur_1: uuid.UUID,
    ) -> None:
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        with pytest.raises(service.KantoorActieVereist):
            service.bied_ter_accordering_aan(
                administratie_id=administratie_id,
                document_id=klaar_document,
                actor_id=accordeur_1,
                actor_rol="klant_accordeur",
            )

    def test_tweede_laag_niet_voor_de_eerste(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
    ) -> None:
        zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(1, accordeur_1), _laag(2, accordeur_2)],
        )
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        with pytest.raises(service.NietAanDeBeurt):
            service.geef_akkoord(
                administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_2
            )


class TestAkkoordEnBoeken:
    def test_laatste_akkoord_boekt_automatisch_met_harde_checks(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
        boeken_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """End-to-end: twee lagen akkoord → de échte boekmotor draait (checks + failsafes) en
        het document staat geboekt in de fake-RLZ."""
        fake = _patch_rlz(monkeypatch)
        zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(1, accordeur_1), _laag(2, accordeur_2)],
        )
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        tussen = service.geef_akkoord(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1
        )
        assert tussen.alles_akkoord is False
        assert document_status(admin_engine, klaar_document) == "ter_accordering"

        resultaat = service.geef_akkoord(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_2
        )
        assert resultaat.alles_akkoord is True
        assert resultaat.geboekt is True
        assert document_status(admin_engine, klaar_document) == "geboekt"
        assert len(fake.puts) == 1  # de echte motor deed de RLZ-write

    def test_boekfout_na_akkoord_is_zichtbaar_nooit_stil(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Boeken staat UIT (failsafe) — het akkoord is dan wél afgerond, maar de boekpoging
        faalt zichtbaar (boek_fout) en het document blijft in de kantoorbak."""
        _patch_rlz(monkeypatch)
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
        assert resultaat.alles_akkoord is True
        assert resultaat.geboekt is False
        assert resultaat.boek_fout is not None
        assert document_status(admin_engine, klaar_document) == "klaar_om_te_boeken"


class TestAfwijzenEnIntrekken:
    def test_afwijzen_vereist_reden_en_komt_terug_in_de_werkvoorraad(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        with pytest.raises(service.RedenVerplicht):
            service.wijs_af(
                administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1, reden="  "
            )
        data = service.wijs_af(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=accordeur_1,
            reden="Bedrag klopt niet met de offerte",
        )
        assert data.status == "afgewezen"
        assert document_status(admin_engine, klaar_document) == "afgewezen"
        with admin_engine.connect() as conn:
            reden = conn.execute(
                text("SELECT reden FROM boekhouding.afwijzing WHERE document_id = :d ORDER BY afgewezen_op DESC"),
                {"d": klaar_document},
            ).scalar()
        assert reden is not None and "Bedrag klopt niet" in reden

    def test_intrekken_door_kantoor(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        data = service.trek_accordering_in(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        assert data.status == "ingetrokken"
        assert document_status(admin_engine, klaar_document) == "klaar_om_te_boeken"


class TestStaandeGoedkeuring:
    def _tweede_document(
        self, administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag, bedrag: Decimal
    ) -> uuid.UUID:
        import uuid as uuid_mod
        from datetime import date

        from app.db.session import scoped_session
        from app.documenten import boekvoorstel
        from app.documenten import service as documenten_service
        from app.documenten.models import Document, DocumentStatus
        from app.documenten.service import _schrijf_overgang

        resultaat = documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="factuur-2.pdf",
            inhoud=b"%PDF-1.4 tweede factuur",
            actor_id=actor_id,
            opslag=opslag,
        )
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=resultaat.document_id,
            actor_id=actor_id,
            vendor_id=VENDOR_ID,
            referentie=f"F2-{resultaat.document_id}",
            factuurdatum=date(2026, 8, 1),
            totaalbedrag=bedrag,
            regels=[
                boekvoorstel.BoekvoorstelRegelData(
                    ledger_id=uuid_mod.uuid4(),
                    taxrate_id=uuid_mod.uuid4(),
                    project_id=None,
                    netto_bedrag=bedrag - Decimal("21.00"),
                    btw_bedrag=Decimal("21.00"),
                    omschrijving="Tweede regel",
                )
            ],
        )
        with scoped_session(administratie_id, actor_id=actor_id) as session:
            document = session.get(Document, resultaat.document_id)
            _schrijf_overgang(
                session, document=document, naar=DocumentStatus.KLAAR_OM_TE_BOEKEN, actor_id=actor_id
            )
        return resultaat.document_id

    def test_staande_regel_geeft_automatisch_akkoord_bij_exact_bedrag(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        boeken_aan: None,
        admin_engine: Engine,
        opslag,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_rlz(monkeypatch)
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        # Akkoord mét staande regel: zelfde leverancier + exact dit bedrag voortaan automatisch.
        resultaat = service.geef_akkoord(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=accordeur_1,
            staande_regel_aanmaken=True,
        )
        assert resultaat.staande_regel_id is not None
        assert resultaat.geboekt is True

        # Volgend document, zelfde leverancier + exact hetzelfde bedrag → automatisch akkoord
        # (bron staande_regel) en direct geboekt — mét audit-spoor.
        tweede = self._tweede_document(administratie_id, gescoopte_gebruiker, opslag, TOTAAL)
        resultaat2 = service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=tweede,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        assert resultaat2.alles_akkoord is True
        assert resultaat2.geboekt is True
        assert resultaat2.accordering.stappen[0].besluit_bron == "staande_regel"
        assert document_status(admin_engine, tweede) == "geboekt"
        with admin_engine.connect() as conn:
            audit = conn.execute(
                text(
                    "SELECT COUNT(*) FROM platform.audit_event "
                    "WHERE actie = 'accordering_automatisch_akkoord_staande_regel'"
                )
            ).scalar_one()
        assert audit == 1

    def test_afwijkend_bedrag_gaat_gewoon_ter_accordering(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        boeken_aan: None,
        admin_engine: Engine,
        opslag,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_rlz(monkeypatch)
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        service.geef_akkoord(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=accordeur_1,
            staande_regel_aanmaken=True,
        )
        ander_bedrag = self._tweede_document(
            administratie_id, gescoopte_gebruiker, opslag, TOTAAL + Decimal("0.01")
        )
        resultaat = service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=ander_bedrag,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        assert resultaat.alles_akkoord is False
        assert document_status(admin_engine, ander_bedrag) == "ter_accordering"

    def test_ingetrokken_regel_geeft_geen_automatisch_akkoord(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        boeken_aan: None,
        admin_engine: Engine,
        opslag,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_rlz(monkeypatch)
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        resultaat = service.geef_akkoord(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=accordeur_1,
            staande_regel_aanmaken=True,
        )
        assert resultaat.staande_regel_id is not None
        service.trek_staande_regel_in(
            administratie_id=administratie_id, regel_id=resultaat.staande_regel_id, actor_id=gescoopte_gebruiker
        )
        tweede = self._tweede_document(administratie_id, gescoopte_gebruiker, opslag, TOTAAL)
        resultaat2 = service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=tweede,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        assert resultaat2.alles_akkoord is False
        assert document_status(admin_engine, tweede) == "ter_accordering"


class TestWachtrij:
    def test_wachtrij_toont_alleen_wie_aan_de_beurt_is(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
    ) -> None:
        zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(1, accordeur_1), _laag(2, accordeur_2)],
        )
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        wachtrij_1 = service.wachtrij_voor_accordeur(actor_id=accordeur_1, administratie_ids=[administratie_id])
        wachtrij_2 = service.wachtrij_voor_accordeur(actor_id=accordeur_2, administratie_ids=[administratie_id])
        assert [item.document_id for item in wachtrij_1] == [klaar_document]
        assert wachtrij_1[0].leverancier_naam == "Energieleverancier B.V."
        assert wachtrij_1[0].totaalbedrag == TOTAAL
        assert wachtrij_2 == []
        # Na akkoord laag 1 verschuift de beurt naar laag 2.
        service.geef_akkoord(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1
        )
        assert service.wachtrij_voor_accordeur(actor_id=accordeur_1, administratie_ids=[administratie_id]) == []
        assert [
            item.document_id
            for item in service.wachtrij_voor_accordeur(actor_id=accordeur_2, administratie_ids=[administratie_id])
        ] == [klaar_document]


class TestIdempotenteBesluitHerhaling:
    """Snelheidslaag PWA (2026-08-17): de client verstuurt besluiten optimistisch op de
    achtergrond mét retry — een herhaalde POST (response verloren) moet idempotent slagen,
    zonder dubbele doorwerking (staande regel, boekronde, audit)."""

    def _audit_teller(self, admin_engine: Engine, actie: str) -> int:
        with admin_engine.connect() as conn:
            return conn.execute(
                text("SELECT count(*) FROM platform.audit_event WHERE actie = :a"), {"a": actie}
            ).scalar_one()

    def test_herhaald_tussenakkoord_is_idempotent(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(1, accordeur_1), _laag(2, accordeur_2)],
        )
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        eerste = service.geef_akkoord(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1
        )
        assert eerste.alles_akkoord is False
        voor = self._audit_teller(admin_engine, "accordering_akkoord")

        # De retry loopt vroeger stuk op NietAanDeBeurt (laag 2 is aan de beurt) — nu idempotent.
        herhaald = service.geef_akkoord(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1
        )
        assert herhaald.alles_akkoord is False
        assert herhaald.geboekt is False
        assert [s.besluit for s in herhaald.accordering.stappen] == ["akkoord", None]
        assert self._audit_teller(admin_engine, "accordering_akkoord") == voor

    def test_herhaald_laatste_akkoord_boekt_niet_opnieuw(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        boeken_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Realistische verloren response: het laatste akkoord boekt (RLZ-call in de request)
        en de client timet uit — de retry moet succes melden zónder tweede boekronde."""
        fake = _patch_rlz(monkeypatch)
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        eerste = service.geef_akkoord(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1
        )
        assert eerste.geboekt is True
        voor_afgerond = self._audit_teller(admin_engine, "accordering_afgerond")

        herhaald = service.geef_akkoord(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1
        )
        assert herhaald.alles_akkoord is True
        assert herhaald.geboekt is True  # uit de werkelijke documentstatus
        assert document_status(admin_engine, klaar_document) == "geboekt"
        assert len(fake.puts) == 1  # géén tweede RLZ-write
        assert self._audit_teller(admin_engine, "accordering_afgerond") == voor_afgerond

    def test_herhaald_akkoord_dupliceert_geen_staande_regel(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        boeken_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_rlz(monkeypatch)
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        eerste = service.geef_akkoord(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=accordeur_1,
            staande_regel_aanmaken=True,
        )
        assert eerste.staande_regel_id is not None

        herhaald = service.geef_akkoord(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=accordeur_1,
            staande_regel_aanmaken=True,
        )
        assert herhaald.staande_regel_id == eerste.staande_regel_id
        with admin_engine.connect() as conn:
            aantal = conn.execute(
                text("SELECT count(*) FROM boekhouding.staande_goedkeuring WHERE bron_document_id = :d"),
                {"d": klaar_document},
            ).scalar_one()
        assert aantal == 1

    def test_herhaald_afwijzen_is_idempotent_eerste_reden_staat(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        service.wijs_af(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=accordeur_1,
            reden="Bedrag klopt niet",
        )
        voor = self._audit_teller(admin_engine, "accordering_afgewezen")

        herhaald = service.wijs_af(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=accordeur_1,
            reden="Bedrag klopt niet",
        )
        assert herhaald.status == "afgewezen"
        assert herhaald.stappen[0].reden == "Bedrag klopt niet"
        assert self._audit_teller(admin_engine, "accordering_afgewezen") == voor
        with admin_engine.connect() as conn:
            aantal_afwijzingen = conn.execute(
                text("SELECT count(*) FROM boekhouding.afwijzing WHERE document_id = :d"),
                {"d": klaar_document},
            ).scalar_one()
        assert aantal_afwijzingen == 1

    def test_verse_ronde_na_intrekken_vraagt_gewoon_een_nieuw_besluit(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
    ) -> None:
        """De idempotentie kijkt uitsluitend naar de LAATSTE ronde: na intrekken + opnieuw
        aanbieden telt het oude akkoord niet — de verse ronde vraagt een nieuwe klik."""
        zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(1, accordeur_1), _laag(2, accordeur_2)],
        )
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        service.geef_akkoord(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1
        )
        service.trek_accordering_in(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        # De verse ronde staat open op laag 1 — een akkoord van accordeur_1 besluit de NIEUWE
        # stap (geen short-circuit op de oude ronde).
        resultaat = service.geef_akkoord(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1
        )
        assert resultaat.alles_akkoord is False
        assert [s.besluit for s in resultaat.accordering.stappen] == ["akkoord", None]
        assert resultaat.accordering.stappen[1].aan_de_beurt is True


class TestAccordeurAanDeBeurtInDocumentenlijst:
    """C2 (26-08): de documentenlijst draagt bij status ter_accordering wie aan de beurt is (naam +
    laag) — de kolom "Toegewezen" toont dát i.p.v. "—"; ná het akkoord van laag 1 wisselt het naar
    laag 2, en een document dat niet bij de klant ligt draagt niets."""

    def test_lijst_toont_accordeur_en_laag_en_wisselt_na_akkoord(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        from app.documenten import service as documenten_service

        def item():
            return next(
                d for d in documenten_service.lijst_documenten(administratie_id=administratie_id) if d.document.id == klaar_document
            )

        assert item().accordeur_aan_de_beurt is None  # nog niet bij de klant
        zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(1, accordeur_1), _laag(2, accordeur_2, "100.00")],  # € 121 → beide lagen vereist
        )
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker, actor_rol="boekhouding"
        )
        beurt = item().accordeur_aan_de_beurt
        assert beurt is not None and beurt.gebruiker_id == accordeur_1 and beurt.laag == 1
        with admin_engine.connect() as conn:
            naam = conn.execute(text("SELECT naam FROM platform.gebruiker WHERE id = :id"), {"id": accordeur_1}).scalar_one()
        assert beurt.naam == naam

        service.geef_akkoord(administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1)
        beurt2 = item().accordeur_aan_de_beurt
        assert beurt2 is not None and beurt2.gebruiker_id == accordeur_2 and beurt2.laag == 2
