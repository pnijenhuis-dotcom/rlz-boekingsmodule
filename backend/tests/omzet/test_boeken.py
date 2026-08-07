"""Omzet-boekmotor: één logische transactie over twee RLZ-documenten, met failsafes,
idempotente retries, het nummer-herstel en het half-geboekt-pad ("nooit stil een halve
boeking"). Fake RLZ-client simuleert het geverifieerde STAP 0-gedrag."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.documenten import boeken as documenten_boeken
from app.omzet import boeken
from app.omzet.models import OmzetBoekingStatus
from app.omzet.voorstel import memoriaal_referentie
from tests.omzet.conftest import (
    PERIODE_EIND,
    PERIODE_START,
    FakeOmzetClient,
    document_status,
    sla_compleet_voorstel_op,
)


@pytest.fixture
def boekbaar_document(
    kassarapport_document: uuid.UUID,
    administratie_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
    taxrate_vrijgesteld: uuid.UUID,
) -> uuid.UUID:
    sla_compleet_voorstel_op(
        administratie_id=administratie_id,
        document_id=kassarapport_document,
        actor_id=gescoopte_gebruiker,
        omzet_ledger_id=uuid.uuid4(),
        taxrate_id=taxrate_vrijgesteld,
        kostprijs_ledger_id=uuid.uuid4(),
        voorraad_ledger_id=uuid.uuid4(),
    )
    return kassarapport_document


def _patch_client(monkeypatch: pytest.MonkeyPatch, client: FakeOmzetClient) -> None:
    # De motor leent _rlz_client_voor uit documenten.boeken — dáár de credential-resolutie
    # vervangen dekt alle paden (checks krijgen dezelfde client doorgegeven).
    monkeypatch.setattr(documenten_boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: client)


class TestBoekOmzetGelukt:
    def test_boekt_verkoop_en_memoriaal_als_een_logische_transactie(
        self,
        boekbaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
        admin_engine: Engine,
    ) -> None:
        client = FakeOmzetClient()
        _patch_client(monkeypatch, client)

        resultaat = boeken.boek_omzet_document(
            administratie_id=administratie_id, document_id=boekbaar_document, actor_id=gescoopte_gebruiker
        )

        assert resultaat.status.value == "geboekt"
        assert document_status(administratie_id, boekbaar_document) == "geboekt"
        # Beide RLZ-documenten geboekt, elk mét de PDF-bijlage.
        verkoop = client.sales_invoices[str(resultaat.verkoop_rlz_id)]
        memoriaal = client.manual_journals[str(resultaat.memoriaal_rlz_id)]
        assert verkoop["Status"] == 2
        assert memoriaal["Status"] == 3
        assert {u["pad"] for u in client.uploads} == {"SalesInvoices", "ManualJournals"}
        # Systeemdebiteur idempotent aangemaakt; verkoopregels vrijgesteld (geen btw-splitsing).
        assert len(client.customers) == 1
        assert all(line["TaxAmount"] == 0.0 for line in verkoop["DocumentLineList"])
        assert sum(line["NetAmount"] for line in verkoop["DocumentLineList"]) == pytest.approx(22463.36)
        # Memoriaal sluit: debet kostprijs per categorie, credit voorraad totaal.
        debet = sum(line.get("DebitAmount") or 0 for line in memoriaal["DocumentLineList"])
        credit = sum(line.get("CreditAmount") or 0 for line in memoriaal["DocumentLineList"])
        assert debet == credit == pytest.approx(14017.29)
        assert memoriaal["Reference"] == memoriaal_referentie(PERIODE_START, PERIODE_EIND)

        with admin_engine.connect() as conn:
            rij = conn.execute(
                text(
                    "SELECT status, periode_start, periode_eind, verkoop_boekstuknummer, "
                    "memoriaal_boekstuknummer FROM boekhouding.omzet_boeking WHERE document_id = :d"
                ),
                {"d": boekbaar_document},
            ).one()
        assert rij.status == "geboekt"
        assert rij.periode_start == PERIODE_START and rij.periode_eind == PERIODE_EIND
        assert rij.verkoop_boekstuknummer and rij.memoriaal_boekstuknummer

    def test_btw_splitsing_bij_belaste_categorie(
        self,
        kassarapport_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.db.session import scoped_session
        from app.sync.models import TaxRateCache

        taxrate_21 = uuid.uuid4()
        with scoped_session(administratie_id) as session:
            session.add(
                TaxRateCache(
                    id=taxrate_21,
                    administratie_id=administratie_id,
                    naam="NL, Hoog tarief",
                    percentage=Decimal("0.21"),
                    brondata={},
                )
            )
        sla_compleet_voorstel_op(
            administratie_id=administratie_id,
            document_id=kassarapport_document,
            actor_id=gescoopte_gebruiker,
            omzet_ledger_id=uuid.uuid4(),
            taxrate_id=taxrate_21,
            kostprijs_ledger_id=uuid.uuid4(),
            voorraad_ledger_id=uuid.uuid4(),
        )
        client = FakeOmzetClient()
        _patch_client(monkeypatch, client)

        resultaat = boeken.boek_omzet_document(
            administratie_id=administratie_id, document_id=kassarapport_document, actor_id=gescoopte_gebruiker
        )
        verkoop = client.sales_invoices[str(resultaat.verkoop_rlz_id)]
        # Kassabedrag is inclusief btw: netto + btw = exact het rapportbedrag per regel.
        eerste = verkoop["DocumentLineList"][0]
        assert eerste["NetAmount"] + eerste["TaxAmount"] == pytest.approx(13655.33)
        # 13655.33 / 1.21 = 11285.40 netto (half-up), btw = rest — som per constructie exact.
        assert eerste["TaxAmount"] == pytest.approx(2369.93, abs=0.001)

    def test_retry_na_gelukte_eerdere_poging_is_idempotent(
        self,
        boekbaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
        admin_engine: Engine,
    ) -> None:
        """Verkoop + memoriaal stonden al geboekt in RLZ (eerdere poging strandde ná de RLZ-calls,
        bv. netwerk weg vóór de registratie): een retry boekt niets dubbel — GET-op-eigen-GUID is
        de inhaal (STAP 0 §2: de SalesInvoices-collectie is hier onbruikbaar)."""
        client = FakeOmzetClient()
        _patch_client(monkeypatch, client)
        from app.documenten.rlz_ids import rlz_kostprijs_memoriaal_id, rlz_sales_invoice_id

        verkoop_id = rlz_sales_invoice_id(boekbaar_document)
        memoriaal_id = rlz_kostprijs_memoriaal_id(boekbaar_document)
        client.put_sales_invoice(verkoop_id, customer_id=uuid.uuid4(), lines=[])
        client.sales_invoices[str(verkoop_id)]["Status"] = 2
        client.put_manual_journal(memoriaal_id, diary_id=uuid.uuid4(), lines=[], Reference="X")
        client.manual_journals[str(memoriaal_id)]["Status"] = 3
        puts_voor = len(client.uploads)

        resultaat = boeken.boek_omzet_document(
            administratie_id=administratie_id, document_id=boekbaar_document, actor_id=gescoopte_gebruiker
        )
        assert resultaat.status.value == "geboekt"
        assert len(client.uploads) == puts_voor  # geen nieuwe PUT/upload/boekactie
        with admin_engine.connect() as conn:
            aantal = conn.execute(
                text("SELECT count(*) FROM boekhouding.omzet_boeking WHERE document_id = :d"),
                {"d": boekbaar_document},
            ).scalar_one()
        assert aantal == 1

    def test_nummer_botsing_wordt_deterministisch_hersteld(
        self,
        boekbaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """STAP 0 §1: RLZ's auto-nummer kan botsen met import-historie ("Dit factuurnummer is al
        in gebruik") — herstel = expliciet InvoiceNumber max(collectie, lokaal) + 1, één keer."""
        client = FakeOmzetClient(nummer_botsing=True, collectie_max_nummer=371)
        _patch_client(monkeypatch, client)

        resultaat = boeken.boek_omzet_document(
            administratie_id=administratie_id, document_id=boekbaar_document, actor_id=gescoopte_gebruiker
        )
        verkoop = client.sales_invoices[str(resultaat.verkoop_rlz_id)]
        assert verkoop["InvoiceNumber"] == 372
        assert verkoop["Status"] == 2
        assert resultaat.verkoop_referentie == "RLZ-372"


class TestHalveBoekingNooitStil:
    def test_memoriaal_faalt_dan_wordt_verkoop_gestorneerd(
        self,
        boekbaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
        admin_engine: Engine,
    ) -> None:
        client = FakeOmzetClient(faal_op="memoriaal_boeken")
        _patch_client(monkeypatch, client)

        with pytest.raises(boeken.RlzBoekingMislukt, match="teruggedraaid"):
            boeken.boek_omzet_document(
                administratie_id=administratie_id, document_id=boekbaar_document, actor_id=gescoopte_gebruiker
            )
        # De verkoop is teruggedraaid (actie 19) — niets half; document zichtbaar op mislukt.
        assert len(client.correcties) == 1
        assert document_status(administratie_id, boekbaar_document) == "boeken_mislukt"
        with admin_engine.connect() as conn:
            aantal = conn.execute(
                text("SELECT count(*) FROM boekhouding.omzet_boeking WHERE document_id = :d"),
                {"d": boekbaar_document},
            ).scalar_one()
        assert aantal == 0  # periode blijft vrij voor een nieuwe poging

    def test_storno_faalt_ook_dan_zichtbaar_half_geboekt(
        self,
        boekbaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
        admin_engine: Engine,
    ) -> None:
        client = FakeOmzetClient(faal_op="memoriaal_boeken")
        origineel = client.correct_sales_invoice

        def storno_faalt(invoice_id: uuid.UUID) -> None:
            from app.rlz.client import RlzApiError

            raise RlzApiError(500, "POST", f"SalesInvoices/{invoice_id}/Actions", "Storno mislukt (simulatie)")

        client.correct_sales_invoice = storno_faalt  # type: ignore[method-assign]
        _patch_client(monkeypatch, client)

        with pytest.raises(boeken.HalfGeboekt, match="HALF GEBOEKT"):
            boeken.boek_omzet_document(
                administratie_id=administratie_id, document_id=boekbaar_document, actor_id=gescoopte_gebruiker
            )
        assert document_status(administratie_id, boekbaar_document) == "boeken_mislukt"
        with admin_engine.connect() as conn:
            rij = conn.execute(
                text("SELECT status, half_geboekt_detail FROM boekhouding.omzet_boeking WHERE document_id = :d"),
                {"d": boekbaar_document},
            ).one()
        assert rij.status == OmzetBoekingStatus.HALF_GEBOEKT.value
        assert "storno_verkoop_fout" in rij.half_geboekt_detail
        del origineel  # alleen ter verduidelijking dat het origineel bewust vervangen is


class TestFailsafes:
    def test_boeken_uit_blokkeert(
        self,
        boekbaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_client(monkeypatch, FakeOmzetClient())
        with pytest.raises(boeken.BoekenUitgeschakeld):
            boeken.boek_omzet_document(
                administratie_id=administratie_id, document_id=boekbaar_document, actor_id=gescoopte_gebruiker
            )

    def test_geblokkeerde_checks_stoppen_voor_elke_rlz_schrijfactie(
        self,
        kassarapport_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Geen opgeslagen voorstel → mapping/verplichte velden blokkeren.
        client = FakeOmzetClient()
        _patch_client(monkeypatch, client)
        with pytest.raises(boeken.BoekenGeblokkeerdDoorChecks):
            boeken.boek_omzet_document(
                administratie_id=administratie_id, document_id=kassarapport_document, actor_id=gescoopte_gebruiker
            )
        assert not client.sales_invoices and not client.manual_journals and not client.customers

    def test_volumerem_blokkeert(
        self,
        boekbaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.config import settings

        _patch_client(monkeypatch, FakeOmzetClient())
        monkeypatch.setattr(settings, "max_boekingen_per_dag_per_administratie", 0)
        with pytest.raises(boeken.VolumeremBereikt):
            boeken.boek_omzet_document(
                administratie_id=administratie_id, document_id=boekbaar_document, actor_id=gescoopte_gebruiker
            )

    def test_dubbel_boeken_geweigerd_na_geboekt(
        self,
        boekbaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = FakeOmzetClient()
        _patch_client(monkeypatch, client)
        boeken.boek_omzet_document(
            administratie_id=administratie_id, document_id=boekbaar_document, actor_id=gescoopte_gebruiker
        )
        with pytest.raises(boeken.OngeldigeBoekpoging):
            boeken.boek_omzet_document(
                administratie_id=administratie_id, document_id=boekbaar_document, actor_id=gescoopte_gebruiker
            )
