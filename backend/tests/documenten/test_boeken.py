from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.documenten import boeken, boekvoorstel, service
from app.documenten.models import DocumentStatus
from app.documenten.storage import LokaleBestandsopslag
from tests.documenten.fake_rlz_client import FakeBoekClient


def _regel(**overrides) -> boekvoorstel.BoekvoorstelRegelData:
    basis = dict(
        ledger_id=uuid.uuid4(),
        taxrate_id=uuid.uuid4(),
        project_id=None,
        netto_bedrag=Decimal("100.00"),
        btw_bedrag=Decimal("21.00"),
        omschrijving="Testregel",
    )
    basis.update(overrides)
    return boekvoorstel.BoekvoorstelRegelData(**basis)


@pytest.fixture
def klaar_document(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
) -> uuid.UUID:
    """Een geüpload document met een volledig, kloppend boekvoorstel — status te_controleren,
    klaar om door de checks te komen."""
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="factuur.pdf",
        inhoud=b"%PDF-1.4 testfactuur",
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    )
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=gescoopte_gebruiker,
        vendor_id=uuid.uuid4(),
        referentie=f"F-{resultaat.document_id}",
        factuurdatum=date(2026, 7, 1),
        totaalbedrag=Decimal("121.00"),
        regels=[_regel()],
    )
    return resultaat.document_id


@pytest.fixture
def boeken_aan(beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)


def _document_status(admin_engine: Engine, document_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}
        ).scalar_one()


class TestBoekDocumentGelukt:
    def test_zet_status_op_geboekt_en_vult_boekstuknummer(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake_client = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)

        resultaat = boeken.boek_document(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
        )

        assert resultaat.status == DocumentStatus.GEBOEKT
        assert resultaat.rlz_boekstuknummer == "RLZ-TEST-00001"
        assert _document_status(admin_engine, klaar_document) == "geboekt"
        assert len(fake_client.puts) == 1
        assert len(fake_client.uploads) == 1
        assert fake_client.geboekte_acties == [resultaat.rlz_document_id]

        with admin_engine.connect() as conn:
            boekstuk = conn.execute(
                text("SELECT rlz_boekstuknummer FROM boekhouding.boekvoorstel WHERE document_id = :id"),
                {"id": klaar_document},
            ).scalar_one()
        assert boekstuk == "RLZ-TEST-00001"

    def test_schrijft_webhook_outbox_rij(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake_client = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)

        boeken.boek_document(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
        )

        with admin_engine.connect() as conn:
            event, payload = conn.execute(
                text("SELECT event, payload FROM boekhouding.webhook_uitgaand WHERE document_id = :id"),
                {"id": klaar_document},
            ).one()
        assert event == "factuur_geboekt"
        assert payload["data"]["referentie"].startswith("F-")
        assert payload["handtekening"]

    def test_idempotent_client_guid_bij_retry(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Een tweede boekpoging op hetzelfde document (bv. na een eerdere mislukking) raakt
        hetzelfde RLZ-document, nooit een nieuw client-GUID (CLAUDE.md idempotentie-fundament)."""
        fake_client = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)

        eerste = boeken.boek_document(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
        )
        assert eerste.rlz_document_id == boeken.rlz_purchase_invoice_id(klaar_document)


class TestBoekDocumentRegelZonderBtw:
    def test_regel_zonder_btw_bedrag_boekt_toch(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Reproductie van de echte 500 uit de kliktest (correlatie-id 2764beb6-..., dev-database):
        een regel zonder btw_bedrag (verlegde btw/vrijgesteld — een geldige case, de harde checks
        eisen dit veld bewust niet af, zie checks.py::check_verplichte_velden) liet
        `float(regel.btw_bedrag)` op None crashen in _regels_naar_rlz_lines(). De vorige sessie's
        generieke except-fix zorgde al dat dit niet meer als kale 500/limbo eindigde, maar de
        onderliggende oorzaak stond nog open — dit is de fix + regressietest daarvoor."""
        fake_client = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)

        resultaat_upload = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="factuur-verlegd.pdf",
            inhoud=b"%PDF-1.4 verlegde btw",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=resultaat_upload.document_id,
            actor_id=gescoopte_gebruiker,
            vendor_id=uuid.uuid4(),
            referentie=f"F-{resultaat_upload.document_id}",
            factuurdatum=date(2026, 7, 1),
            totaalbedrag=Decimal("23.23"),
            regels=[_regel(netto_bedrag=Decimal("23.23"), btw_bedrag=None)],
        )

        resultaat = boeken.boek_document(
            administratie_id=administratie_id, document_id=resultaat_upload.document_id, actor_id=gescoopte_gebruiker
        )

        assert resultaat.status == DocumentStatus.GEBOEKT
        assert fake_client.puts[0]["lines"][0]["TaxAmount"] == 0.0
        assert fake_client.puts[0]["lines"][0]["NetAmount"] == 23.23


class TestBoekDocumentGeblokkeerdDoorChecks:
    def test_ontbrekende_velden_blokkeert_met_rapport(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="leeg.pdf",
            inhoud=b"%PDF-1.4 leeg",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        # Geen boekvoorstel opgeslagen -> alle verplichte velden ontbreken.
        with pytest.raises(boeken.BoekenGeblokkeerdDoorChecks) as excinfo:
            boeken.boek_document(
                administratie_id=administratie_id, document_id=resultaat.document_id, actor_id=gescoopte_gebruiker
            )
        assert excinfo.value.rapport.geblokkeerd

    def test_document_blijft_te_controleren_na_geblokkeerde_checks(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        boeken_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="leeg.pdf",
            inhoud=b"%PDF-1.4 leeg2",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        with pytest.raises(boeken.BoekenGeblokkeerdDoorChecks):
            boeken.boek_document(
                administratie_id=administratie_id, document_id=resultaat.document_id, actor_id=gescoopte_gebruiker
            )
        assert _document_status(admin_engine, resultaat.document_id) == "te_controleren"


class TestBoekDocumentFailsafes:
    def test_boeken_uitgeschakeld_per_administratie_blokkeert(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # boeken_aan-fixture NIET gebruikt -> default uit.
        fake_client = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)

        with pytest.raises(boeken.BoekenUitgeschakeld):
            boeken.boek_document(
                administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
            )
        assert fake_client.puts == []  # nooit bij RLZ terechtgekomen

    def test_klaarzetten_op_klaar_om_te_boeken_blijft_staan_na_geblokkeerde_failsafe(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """De checks zijn doorstaan, dus het document mag niet terugvallen naar te_controleren
        alleen omdat de failsafe blokkeert — een latere retry (na het aanzetten van de toggle)
        hoeft de checks niet opnieuw te doorstaan."""
        fake_client = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)

        with pytest.raises(boeken.BoekenUitgeschakeld):
            boeken.boek_document(
                administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
            )
        assert _document_status(admin_engine, klaar_document) == "klaar_om_te_boeken"

    def test_globale_kill_switch_blokkeert_ook_als_administratie_zelf_aan_staat(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        beheer_service.zet_globale_kill_switch(actor_id=beheerder_id, ingeschakeld=False)
        fake_client = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)

        with pytest.raises(boeken.BoekenUitgeschakeld):
            boeken.boek_document(
                administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
            )

    def test_volumerem_blokkeert_boven_de_dagelijkse_limiet(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.config import settings

        monkeypatch.setattr(settings, "max_boekingen_per_dag_per_administratie", 1)
        fake_client = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)

        def _nieuw_klaar_document() -> uuid.UUID:
            resultaat = service.upload_document(
                administratie_id=administratie_id,
                bestandsnaam=f"{uuid.uuid4()}.pdf",
                inhoud=uuid.uuid4().bytes,
                actor_id=gescoopte_gebruiker,
                opslag=opslag,
            )
            boekvoorstel.sla_boekvoorstel_op(
                administratie_id=administratie_id,
                document_id=resultaat.document_id,
                actor_id=gescoopte_gebruiker,
                vendor_id=uuid.uuid4(),
                referentie=f"F-{resultaat.document_id}",
                factuurdatum=date(2026, 7, 1),
                totaalbedrag=Decimal("121.00"),
                regels=[_regel()],
            )
            return resultaat.document_id

        eerste_document = _nieuw_klaar_document()
        boeken.boek_document(
            administratie_id=administratie_id, document_id=eerste_document, actor_id=gescoopte_gebruiker
        )

        tweede_document = _nieuw_klaar_document()
        with pytest.raises(boeken.VolumeremBereikt):
            boeken.boek_document(
                administratie_id=administratie_id, document_id=tweede_document, actor_id=gescoopte_gebruiker
            )


class TestBoekDocumentRlzFout:
    def test_rlz_fout_zet_boeken_mislukt_met_echte_foutmelding(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake_client = FakeBoekClient(faal_op="put")
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)

        with pytest.raises(boeken.RlzBoekingMislukt, match="PUT mislukt"):
            boeken.boek_document(
                administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
            )

        assert _document_status(admin_engine, klaar_document) == "boeken_mislukt"
        with admin_engine.connect() as conn:
            detail = conn.execute(
                text(
                    "SELECT detail FROM boekhouding.document_gebeurtenis "
                    "WHERE document_id = :id AND naar_status = 'boeken_mislukt'"
                ),
                {"id": klaar_document},
            ).scalar_one()
        assert "PUT mislukt" in detail["fout"]

    def test_retry_na_mislukking_kan_slagen(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        falende_client = FakeBoekClient(faal_op="book")
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: falende_client)
        with pytest.raises(boeken.RlzBoekingMislukt):
            boeken.boek_document(
                administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
            )

        werkende_client = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: werkende_client)
        resultaat = boeken.boek_document(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
        )
        assert resultaat.status == DocumentStatus.GEBOEKT


class TestBoekDocumentOnverwachteFout:
    def test_onverwachte_fout_zet_boeken_mislukt_en_wordt_doorgegeven(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Regressietest voor een kale 500 in de UI: een RuntimeError uit de RLZ-client (dus geen
        RlzApiError, bv. een netwerkfout die alle retries overleeft) mag het document niet in
        limbo laten — zelfde blokkerende afhandeling als een RlzApiError, alleen zonder de
        RlzBoekingMislukt-typering (die is voorbehouden aan écht bevestigde RLZ-fouten). De
        oorspronkelijke fout gaat ongewijzigd door, zodat de globale exception-handler
        (app/main.py) 'm kan loggen en er een nette melding + correlatie-id van kan maken."""
        fake_client = FakeBoekClient(faal_op="put_onverwacht")
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)

        with pytest.raises(RuntimeError, match="Onverwachte fout"):
            boeken.boek_document(
                administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
            )

        assert _document_status(admin_engine, klaar_document) == "boeken_mislukt"
        with admin_engine.connect() as conn:
            detail = conn.execute(
                text(
                    "SELECT detail FROM boekhouding.document_gebeurtenis "
                    "WHERE document_id = :id AND naar_status = 'boeken_mislukt'"
                ),
                {"id": klaar_document},
            ).scalar_one()
        assert "Onverwachte fout" in detail["fout"]

    def test_retry_na_onverwachte_fout_kan_slagen(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        falende_client = FakeBoekClient(faal_op="put_onverwacht")
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: falende_client)
        with pytest.raises(RuntimeError):
            boeken.boek_document(
                administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
            )

        werkende_client = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: werkende_client)
        resultaat = boeken.boek_document(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
        )
        assert resultaat.status == DocumentStatus.GEBOEKT


class TestBoekDocumentOngeldigeStatus:
    def test_al_geboekt_document_kan_niet_opnieuw(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake_client = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)
        boeken.boek_document(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
        )

        with pytest.raises(boeken.OngeldigeBoekpoging):
            boeken.boek_document(
                administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
            )

    def test_onbekend_document_geeft_documentnietgevonden(
        self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        with pytest.raises(service.DocumentNietGevonden):
            boeken.boek_document(
                administratie_id=administratie_id, document_id=uuid.uuid4(), actor_id=gescoopte_gebruiker
            )

    def test_verwijderd_document_kan_niet_geboekt_worden(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        boeken_aan: None,
    ) -> None:
        service.verwijder_document(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
        )

        with pytest.raises(boeken.OngeldigeBoekpoging):
            boeken.boek_document(
                administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
            )
