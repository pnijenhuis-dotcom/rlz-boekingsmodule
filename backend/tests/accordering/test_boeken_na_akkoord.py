"""Bugfix-run 28-08 — auto-boeken ná het laatste klant-akkoord (casus Kempen Facilities 27-08:
±34 documenten om 15:40 + gouden casus 226181551.pdf / Van Happen om 17:57 vielen stil terug naar
klaar_om_te_boeken zonder boeking, boek_fout of reden).

Root cause (code): `_rond_af_en_boek` zette het document éérst op klaar_om_te_boeken en draaide
dán de boekmotor; élke mislukking (toggle uit, volumerem, checks, RLZ, onverwachte fout) leefde
uitsluitend in de HTTP-response aan de accordeur (die 'm niet toont) — geen tijdlijn, geen status,
geen audit. Regressietests (a)–(d) uit de opdracht + de aangrenzende gaten (poort telt alleen de
laatste ronde; bedrag gewijzigd ná akkoord; intrekken ná boekfout) + de herstelroute."""

from __future__ import annotations

import threading
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.accordering import herstel, service
from app.accordering.models import AccorderingStatus
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import boeken
from app.documenten import boekvoorstel as boekvoorstel_service
from app.documenten.checks import CheckRapport, CheckResultaat
from app.doorbelasting import boeken as doorbelasting_boeken
from tests.accordering.conftest import TOTAAL, VENDOR_ID, document_status, maak_klaar_document, zet_schema
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


def _tijdlijn(admin_engine: Engine, document_id: uuid.UUID) -> list[tuple[str | None, str, uuid.UUID, dict | None]]:
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text(
                "SELECT van_status, naar_status, actor_id, detail FROM boekhouding.document_gebeurtenis "
                "WHERE document_id = :id ORDER BY tijdstip, id"
            ),
            {"id": document_id},
        ).all()
    return [(r[0], r[1], r[2], r[3]) for r in rijen]


def _audit_teller(admin_engine: Engine, actie: str) -> int:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM platform.audit_event WHERE actie = :actie"), {"actie": actie}
        ).scalar_one()


def _aanbieden(administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    service.bied_ter_accordering_aan(
        administratie_id=administratie_id, document_id=document_id, actor_id=actor_id, actor_rol="boekhouding"
    )


class TestLaatsteAkkoordBoekt:
    def test_a_zonder_doorbelasting_geboekt_met_reden_op_de_tijdlijn(
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
        fake = _patch_rlz(monkeypatch)
        zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(1, accordeur_1), _laag(2, accordeur_2)],
        )
        _aanbieden(administratie_id, klaar_document, gescoopte_gebruiker)
        service.geef_akkoord(administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1)
        assert document_status(admin_engine, klaar_document) == "ter_accordering"
        resultaat = service.geef_akkoord(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_2
        )
        assert resultaat.alles_akkoord and resultaat.geboekt and resultaat.boek_fout is None
        assert resultaat.accordering.boek_fout is None
        assert document_status(admin_engine, klaar_document) == "geboekt"
        assert len(fake.puts) == 1

        tijdlijn = _tijdlijn(admin_engine, klaar_document)
        # Notitie "alle lagen akkoord" zónder statusovergang, dan de motor-overgangen — élke
        # systeem-regel draagt een reden (vangnet 2c).
        notities = [g for g in tijdlijn if g[3] and g[3].get("alle_lagen_akkoord")]
        assert len(notities) == 1 and notities[0][0] == notities[0][1] == "ter_accordering"
        systeem = [g for g in tijdlijn if g[2] == SYSTEEM_ACTOR_ID]
        assert systeem and all(isinstance((g[3] or {}).get("reden"), str) and g[3]["reden"] for g in systeem)
        overgangen = [(g[0], g[1]) for g in tijdlijn if g[0] != g[1]]
        assert overgangen[-2:] == [("ter_accordering", "klaar_om_te_boeken"), ("klaar_om_te_boeken", "geboekt")]

    def test_b_met_klaargezette_doorbelasting_draait_de_orkestratie(
        self,
        klaargezet_op_klaar_document: dict,  # noqa: F811
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        accordeur_1: uuid.UUID,
        boeken_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        inkoop = _patch_rlz(monkeypatch)
        bron, doel = FakeDoorbelastingClient(), FakeDoorbelastingClient()
        monkeypatch.setattr(
            doorbelasting_boeken, "_rlz_client_voor", lambda aid: bron if aid == administratie_id else doel
        )
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=beheerder_id, actor_rol="beheerder"
        )
        resultaat = service.geef_akkoord(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1
        )
        assert resultaat.geboekt and resultaat.boek_fout is None
        assert document_status(admin_engine, klaar_document) == "geboekt"
        assert len(inkoop.puts) == 1
        assert len(bron.sales_invoices) == 1 and len(doel.purchase_invoices) == 1
        assert haal_run(administratie_id, klaargezet_op_klaar_document["run"].id).status == "geboekt"


class TestBoekenGeblokkeerdNooitStil:
    """(c) Laatste akkoord terwijl boeken geblokkeerd is → ter_accordering + boek_fout mét reden,
    NOOIT klaar_om_te_boeken — voor élke poort-laag (toggle vóór/ná de checks, checks, onverwacht)."""

    def _setup(self, administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, klaar_document):
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        _aanbieden(administratie_id, klaar_document, gescoopte_gebruiker)

    def _assert_zichtbaar_geblokkeerd(self, admin_engine, klaar_document, administratie_id, resultaat, fragment):
        assert resultaat.alles_akkoord is True
        assert resultaat.geboekt is False
        assert resultaat.boek_fout and fragment in resultaat.boek_fout
        assert document_status(admin_engine, klaar_document) == "ter_accordering"
        # persistent op de ronde
        data = service.accordering_van_document(administratie_id=administratie_id, document_id=klaar_document)
        assert data is not None and data.status == "afgerond" and fragment in (data.boek_fout or "")
        assert data.boek_fout_op is not None
        # reden op de tijdlijn (systeem-regel mét accordering_boek_fout)
        tijdlijn = _tijdlijn(admin_engine, klaar_document)
        fout_regels = [g for g in tijdlijn if g[3] and "accordering_boek_fout" in g[3]]
        assert len(fout_regels) == 1
        assert fout_regels[0][2] == SYSTEEM_ACTOR_ID
        assert fragment in fout_regels[0][3]["reden"]
        assert fout_regels[0][1] == "ter_accordering"
        # audit
        assert _audit_teller(admin_engine, "accordering_boek_fout") >= 1
        # nergens een stille klaar_om_te_boeken-eindstand: elke systeem-overgang heeft een reden
        for g in tijdlijn:
            if g[2] == SYSTEEM_ACTOR_ID:
                assert (g[3] or {}).get("reden")

    def test_toggle_uit_poort_voor_de_checks(
        self,
        klaar_document,
        administratie_id,
        beheerder_id,
        gescoopte_gebruiker,
        accordeur_1,
        admin_engine,
        monkeypatch,
    ) -> None:
        # boeken_aan ontbreekt bewust: administratie-toggle UIT (de meest waarschijnlijke trigger
        # van de casus: alle 34 + de gouden casus faalden op dezelfde manier, geen enkele boeking)
        _patch_rlz(monkeypatch)
        self._setup(administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, klaar_document)
        resultaat = service.geef_akkoord(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1
        )
        self._assert_zichtbaar_geblokkeerd(
            admin_engine, klaar_document, administratie_id, resultaat, "Boeken staat uit"
        )
        # De checks waren groen → het document ging tijdens de poging via klaar_om_te_boeken en
        # is expliciet TERUGgezet (overgang mét reden), niet blijven hangen.
        overgangen = [(g[0], g[1]) for g in _tijdlijn(admin_engine, klaar_document) if g[0] != g[1]]
        assert overgangen[-2:] == [("ter_accordering", "klaar_om_te_boeken"), ("klaar_om_te_boeken", "ter_accordering")]

    def test_volumerem(
        self,
        klaar_document,
        administratie_id,
        beheerder_id,
        gescoopte_gebruiker,
        accordeur_1,
        boeken_aan,
        admin_engine,
        monkeypatch,
    ) -> None:
        # Punt 23 (28-08): ná een compleet klant-akkoord geldt de NOODREM (200/dag), niet de
        # 20/dag-automatiseringsrem — de 20-rem op 0 mag dit pad dus níét meer blokkeren …
        _patch_rlz(monkeypatch)
        monkeypatch.setattr(boeken.settings, "max_boekingen_per_dag_per_administratie", 0)
        monkeypatch.setattr(boeken.settings, "max_boekingen_na_klant_akkoord_per_dag_per_administratie", 0)
        self._setup(administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, klaar_document)
        resultaat = service.geef_akkoord(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1
        )
        # … maar de noodrem op 0 wél, mét exact dezelfde zichtbare boek_fout-afhandeling.
        self._assert_zichtbaar_geblokkeerd(admin_engine, klaar_document, administratie_id, resultaat, "Noodrem")

    def test_harde_check_rood(
        self,
        klaar_document,
        administratie_id,
        beheerder_id,
        gescoopte_gebruiker,
        accordeur_1,
        boeken_aan,
        admin_engine,
        monkeypatch,
    ) -> None:
        fake = _patch_rlz(monkeypatch)
        self._setup(administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, klaar_document)
        rood = CheckRapport(
            resultaten=(CheckResultaat(naam="duplicaat", ok=False, melding="Mogelijk duplicaat in RLZ"),)
        )
        monkeypatch.setattr(boeken, "voer_checks_uit", lambda **kwargs: rood)
        resultaat = service.geef_akkoord(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1
        )
        self._assert_zichtbaar_geblokkeerd(
            admin_engine, klaar_document, administratie_id, resultaat, "Mogelijk duplicaat in RLZ"
        )
        assert fake.puts == []
        # Poort vóór de checks-overgang: ná het aanbieden heeft het document klaar_om_te_boeken
        # nooit meer gezien (geen stille tussenstand).
        tijdlijn = _tijdlijn(admin_engine, klaar_document)
        na_aanbieden = tijdlijn[next(i for i, g in enumerate(tijdlijn) if g[1] == "ter_accordering") + 1 :]
        assert na_aanbieden and all(g[1] != "klaar_om_te_boeken" for g in na_aanbieden)

    def test_onverwachte_fout_is_geen_500_en_niet_stil(
        self,
        klaar_document,
        administratie_id,
        beheerder_id,
        gescoopte_gebruiker,
        accordeur_1,
        boeken_aan,
        admin_engine,
        monkeypatch,
    ) -> None:
        """Bv. credentials/netwerk/bug vóór de RLZ-call: vóór de fix een 500 naar de accordeur
        (verzendrij-retry → idempotent 200 zónder boeking) en het document stil op klaar_om_te_boeken."""

        def kapot(rlz_admin_id):
            raise RuntimeError("credential-store onbereikbaar (simulatie)")

        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", kapot)
        self._setup(administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, klaar_document)
        resultaat = service.geef_akkoord(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1
        )
        self._assert_zichtbaar_geblokkeerd(
            admin_engine, klaar_document, administratie_id, resultaat, "credential-store onbereikbaar"
        )

    def test_rlz_fout_landt_op_boeken_mislukt_met_boek_fout_op_de_ronde(
        self,
        klaar_document,
        administratie_id,
        beheerder_id,
        gescoopte_gebruiker,
        accordeur_1,
        boeken_aan,
        admin_engine,
        monkeypatch,
    ) -> None:
        """RLZ-fout tijdens de PUT: het bestaande zichtbare pad (boeken_mislukt mét reden + retry)
        blijft — plús de boek_fout op de ronde, zodat de accorderingssectie 'm toont."""
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient(faal_op="put"))
        self._setup(administratie_id, beheerder_id, gescoopte_gebruiker, accordeur_1, klaar_document)
        resultaat = service.geef_akkoord(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1
        )
        assert resultaat.geboekt is False and "PUT mislukt" in (resultaat.boek_fout or "")
        assert document_status(admin_engine, klaar_document) == "boeken_mislukt"
        data = service.accordering_van_document(administratie_id=administratie_id, document_id=klaar_document)
        assert data is not None and "PUT mislukt" in (data.boek_fout or "")
        # Retry door het kantoor mag: de poort ziet de afgeronde ronde.
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
        boeken.boek_document(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
        )
        assert document_status(admin_engine, klaar_document) == "geboekt"


class TestBulkEnRace:
    """(d) Bulk-akkoorden kort na elkaar (verzendrij-patroon) → zelfde uitkomsten, geen race."""

    def test_verzendrij_patroon_drie_documenten_twee_lagen(
        self,
        gescoopte_gebruiker,
        administratie_id,
        beheerder_id,
        accordeur_1,
        accordeur_2,
        boeken_aan,
        admin_engine,
        opslag,
        monkeypatch,
    ) -> None:
        fake = _patch_rlz(monkeypatch)
        zet_schema(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(1, accordeur_1), _laag(2, accordeur_2)],
        )
        docs = [
            maak_klaar_document(gescoopte_gebruiker, administratie_id, admin_engine, opslag, naam=f"f{i}.pdf")
            for i in range(3)
        ]
        for d in docs:
            _aanbieden(administratie_id, d, gescoopte_gebruiker)
        # Laag 1 tikt alles achter elkaar af, dan laag 2 — exact de app-verzendrij (FIFO).
        for d in docs:
            r = service.geef_akkoord(administratie_id=administratie_id, document_id=d, actor_id=accordeur_1)
            assert not r.alles_akkoord and document_status(admin_engine, d) == "ter_accordering"
        for d in docs:
            r = service.geef_akkoord(administratie_id=administratie_id, document_id=d, actor_id=accordeur_2)
            assert r.alles_akkoord and r.geboekt and r.boek_fout is None
        assert all(document_status(admin_engine, d) == "geboekt" for d in docs)
        assert len(fake.puts) == 3
        # Verzendrij-retry ná een verloren response: idempotent, geen tweede boeking, geen fout.
        for d in docs:
            r = service.geef_akkoord(administratie_id=administratie_id, document_id=d, actor_id=accordeur_2)
            assert r.geboekt and r.alles_akkoord
        assert len(fake.puts) == 3

    def test_gelijktijdig_laatste_akkoord_boekt_precies_een_keer(
        self,
        klaar_document,
        administratie_id,
        beheerder_id,
        gescoopte_gebruiker,
        accordeur_1,
        boeken_aan,
        admin_engine,
        monkeypatch,
    ) -> None:
        """Dubbeltik/retry die de eerste request inhaalt: de ronde wordt FOR UPDATE gelezen —
        één boeking, één afgerond-audit, beide aanroepen slagen."""
        fake = _patch_rlz(monkeypatch)
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        _aanbieden(administratie_id, klaar_document, gescoopte_gebruiker)
        voor = _audit_teller(admin_engine, "accordering_afgerond")

        start = threading.Barrier(2)
        uitkomsten: list[object] = []

        def akkoord() -> None:
            start.wait(timeout=10)
            try:
                uitkomsten.append(
                    service.geef_akkoord(
                        administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1
                    )
                )
            except Exception as exc:  # noqa: BLE001 — zichtbaar in de assert
                uitkomsten.append(exc)

        threads = [threading.Thread(target=akkoord) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert len(uitkomsten) == 2
        assert all(isinstance(u, service.AkkoordResultaat) for u in uitkomsten), uitkomsten
        assert document_status(admin_engine, klaar_document) == "geboekt"
        assert len(fake.puts) == 1
        assert _audit_teller(admin_engine, "accordering_afgerond") == voor + 1


class TestAangrenzendeGaten:
    def test_poort_telt_alleen_de_laatste_ronde_en_intrekken_na_boekfout(
        self,
        klaar_document,
        administratie_id,
        beheerder_id,
        gescoopte_gebruiker,
        accordeur_1,
        admin_engine,
        monkeypatch,
    ) -> None:
        _patch_rlz(monkeypatch)
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        _aanbieden(administratie_id, klaar_document, gescoopte_gebruiker)
        service.geef_akkoord(administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1)
        assert document_status(admin_engine, klaar_document) == "ter_accordering"  # boeken uit → boek_fout
        # Kantoor haalt het terug (nieuw toegestaan op een afgeronde ronde mét boekfout) …
        service.trek_accordering_in(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        assert document_status(admin_engine, klaar_document) == "klaar_om_te_boeken"
        data = service.accordering_van_document(administratie_id=administratie_id, document_id=klaar_document)
        assert data is not None and data.status == AccorderingStatus.INGETROKKEN.value
        # … en de oude "afgeronde ronde" is géén bypass meer: boeken vraagt opnieuw aanbieden.
        from app.beheer import service as beheer_service

        beheer_service.zet_boeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        with pytest.raises(boeken.AccorderingVereist, match="opnieuw ter accordering"):
            boeken.boek_document(
                administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
            )

    def test_bedrag_gewijzigd_na_akkoord_blokkeert_boeken(
        self,
        klaar_document,
        administratie_id,
        beheerder_id,
        gescoopte_gebruiker,
        accordeur_1,
        admin_engine,
        monkeypatch,
    ) -> None:
        _patch_rlz(monkeypatch)
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        _aanbieden(administratie_id, klaar_document, gescoopte_gebruiker)
        service.geef_akkoord(administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1)
        # Voorstel wijzigt ná het akkoord (€ 121 → € 242): het akkoord dekt dat bedrag niet.
        boekvoorstel_service.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            vendor_id=VENDOR_ID,
            referentie="F-gewijzigd",
            factuurdatum=__import__("datetime").date(2026, 7, 1),
            totaalbedrag=TOTAAL * 2,
            regels=[
                boekvoorstel_service.BoekvoorstelRegelData(
                    ledger_id=uuid.uuid4(),
                    taxrate_id=uuid.uuid4(),
                    project_id=None,
                    netto_bedrag=Decimal("200.00"),
                    btw_bedrag=Decimal("42.00"),
                    omschrijving="Testregel",
                )
            ],
        )
        from app.beheer import service as beheer_service

        beheer_service.zet_boeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        with pytest.raises(boeken.AccorderingVereist, match="totaalbedrag is gewijzigd"):
            boeken.boek_document(
                administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
            )


class TestHerstelroute:
    def test_dry_run_toont_kandidaat_met_diagnose_en_wijzigt_niets(
        self,
        klaar_document,
        administratie_id,
        beheerder_id,
        gescoopte_gebruiker,
        accordeur_1,
        admin_engine,
        monkeypatch,
    ) -> None:
        fake = _patch_rlz(monkeypatch)
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        _aanbieden(administratie_id, klaar_document, gescoopte_gebruiker)
        service.geef_akkoord(administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1)
        # Legacy-vorm van de casus nabootsen: het document hangt op klaar_om_te_boeken mét een
        # afgeronde ronde (zoals de ±42 documenten Kempen Facilities nu in de cloud-DB staan).
        from app.db.session import scoped_session
        from app.documenten.models import Document, DocumentStatus
        from app.documenten.service import _schrijf_overgang

        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            document = session.get(Document, klaar_document)
            _schrijf_overgang(
                session, document=document, naar=DocumentStatus.KLAAR_OM_TE_BOEKEN, actor_id=gescoopte_gebruiker
            )

        resultaat = herstel.herstel_boeken(dry_run=True, administratie_id=administratie_id)
        assert [k.document_id for k in resultaat.kandidaten] == [klaar_document]
        k = resultaat.kandidaten[0]
        assert k.documentstatus == "klaar_om_te_boeken" and k.leverancier == "Energieleverancier B.V."
        assert k.totaalbedrag == TOTAAL and k.doorbelasting_klaargezet is False
        assert "Boeken staat uit" in (k.laatste_boek_fout or "")
        assert any("boeken staat UIT" in b for b in resultaat.diagnose[klaar_document])
        assert fake.puts == [] and document_status(admin_engine, klaar_document) == "klaar_om_te_boeken"
        # Andere administratie-filter → geen kandidaten
        assert herstel.herstel_boeken(dry_run=True, administratie_id=uuid.uuid4()).kandidaten == []

    def test_uitvoering_boekt_via_het_gefixte_pad_en_respecteert_max(
        self,
        gescoopte_gebruiker,
        administratie_id,
        beheerder_id,
        accordeur_1,
        admin_engine,
        opslag,
        monkeypatch,
    ) -> None:
        fake = _patch_rlz(monkeypatch)
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        docs = [
            maak_klaar_document(gescoopte_gebruiker, administratie_id, admin_engine, opslag, naam=f"h{i}.pdf")
            for i in range(2)
        ]
        for d in docs:
            _aanbieden(administratie_id, d, gescoopte_gebruiker)
            service.geef_akkoord(administratie_id=administratie_id, document_id=d, actor_id=accordeur_1)
        assert all(document_status(admin_engine, d) == "ter_accordering" for d in docs)  # boeken uit
        from app.beheer import service as beheer_service

        beheer_service.zet_boeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )

        proef = herstel.herstel_boeken(dry_run=False, administratie_id=administratie_id, max_aantal=1)
        assert len(proef.geboekt) == 1 and len(proef.overgeslagen) == 1 and not proef.mislukt
        assert len(fake.puts) == 1
        rest = herstel.herstel_boeken(dry_run=False, administratie_id=administratie_id)
        assert len(rest.kandidaten) == 1 and len(rest.geboekt) == 1
        assert all(document_status(admin_engine, d) == "geboekt" for d in docs)
        assert herstel.kandidaten(administratie_id=administratie_id) == []

    def test_volumerem_stopt_de_run_zichtbaar_zonder_boekfouten(
        self,
        klaar_document,
        administratie_id,
        beheerder_id,
        gescoopte_gebruiker,
        accordeur_1,
        boeken_aan,
        admin_engine,
        monkeypatch,
    ) -> None:
        fake = _patch_rlz(monkeypatch)
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        _aanbieden(administratie_id, klaar_document, gescoopte_gebruiker)
        # Punt 23: de herstel-CLI boekt ná klant-akkoord → de noodrem geldt (de 20-rem niet meer).
        monkeypatch.setattr(boeken.settings, "max_boekingen_na_klant_akkoord_per_dag_per_administratie", 0)
        service.geef_akkoord(administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1)
        voor = _audit_teller(admin_engine, "accordering_boek_fout")
        resultaat = herstel.herstel_boeken(dry_run=False, administratie_id=administratie_id)
        assert len(resultaat.kandidaten) == 1 and not resultaat.geboekt and not resultaat.mislukt
        assert "noodrem ná klant-akkoord" in resultaat.overgeslagen[klaar_document]
        assert "MAX_BOEKINGEN_NA_KLANT_AKKOORD" in resultaat.overgeslagen[klaar_document]
        assert fake.puts == [] and _audit_teller(admin_engine, "accordering_boek_fout") == voor
