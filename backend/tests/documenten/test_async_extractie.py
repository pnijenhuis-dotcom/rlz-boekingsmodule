"""Async extractie (2026-07-10): klein-vs-groot-routing, wachtrij + worker, systeem-actor.

Gemockte AI (nooit echte API-calls in de kale run); de wachtrij zelf draait waar relevant écht
(in-process threadpool) zodat de test de asynchrone flow bewijst: upload keert terug met
extractie_wachtrij, de worker maakt het af met de systeem-actor in tijdlijn én audit_event."""

from __future__ import annotations

import io
import uuid

import pytest
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.config import settings
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import service
from app.documenten.models import Document, DocumentStatus
from app.documenten.pdf import tel_paginas
from app.documenten.storage import LokaleBestandsopslag
from app.documenten.wachtrij import InProcessExtractieWachtrij
from tests.documenten.test_ai_extractie import _fake_extractie

_PDF = b"%PDF-1.4 async-extractie-test"  # geen echte PDF: paginatelling faalt -> byte-routing


class FakeWachtrij:
    """Registreert alleen wat er ge-enqueued wordt — voor routing-tests zonder verwerking."""

    def __init__(self) -> None:
        self.enqueued: list[tuple[uuid.UUID, uuid.UUID]] = []

    def enqueue(self, *, administratie_id: uuid.UUID, document_id: uuid.UUID) -> None:
        self.enqueued.append((administratie_id, document_id))


def _echte_pdf(paginas: int) -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(paginas):
        writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.fixture
def ai_gate_aan(administratie_id: uuid.UUID, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> None:
    beheer_service.zet_ai_extractie_ingeschakeld(
        actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
    )
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")


@pytest.fixture
def fake_extraheer(monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    aanroepen: list[bytes] = []

    def _fake(pdf_bytes: bytes, *, client=None):
        aanroepen.append(pdf_bytes)
        return _fake_extractie()

    monkeypatch.setattr("app.extractie.service.extraheer_inkoopfactuur", _fake)
    return aanroepen


def _upload(
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    *,
    inhoud: bytes = _PDF,
    wachtrij=None,
):
    return service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="factuur.pdf",
        inhoud=inhoud,
        actor_id=actor_id,
        opslag=opslag,
        wachtrij=wachtrij,
    )


class TestRouting:
    def test_klein_document_houdt_de_snelle_synchrone_route(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: list[bytes],
    ) -> None:
        """De normale factuur merkt niets van de async-route: upload komt direct als
        te_controleren terug, mét voorstel, zonder wachtrij-status in de tijdlijn."""
        wachtrij = FakeWachtrij()
        resultaat = _upload(administratie_id, gescoopte_gebruiker, opslag, wachtrij=wachtrij)

        assert resultaat.status == DocumentStatus.TE_CONTROLEREN
        assert wachtrij.enqueued == []
        assert fake_extraheer == [_PDF]
        detail = service.haal_document_op(administratie_id=administratie_id, document_id=resultaat.document_id)
        assert DocumentStatus.EXTRACTIE_WACHTRIJ not in {g.naar_status for g in detail.gebeurtenissen}
        assert detail.veldvoorstel is not None

    def test_byte_drempel_routeert_naar_wachtrij(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: list[bytes],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "ai_extractie_sync_max_bytes", 10)
        wachtrij = FakeWachtrij()
        resultaat = _upload(administratie_id, gescoopte_gebruiker, opslag, wachtrij=wachtrij)

        assert resultaat.status == DocumentStatus.EXTRACTIE_WACHTRIJ
        assert wachtrij.enqueued == [(administratie_id, resultaat.document_id)]
        assert fake_extraheer == []  # nog niets verwerkt — dat is aan de worker
        detail = service.haal_document_op(administratie_id=administratie_id, document_id=resultaat.document_id)
        wachtrij_gebeurtenis = next(
            g for g in detail.gebeurtenissen if g.naar_status == DocumentStatus.EXTRACTIE_WACHTRIJ
        )
        assert wachtrij_gebeurtenis.detail == {
            "extractie_wachtrij": "groot_document",
            "paginas": None,  # _PDF is geen echte PDF — telling faalt, bytes besliste
            "bytes": len(_PDF),
        }
        assert wachtrij_gebeurtenis.actor_id == gescoopte_gebruiker  # de upload is een menselijke handeling

    def test_pagina_drempel_routeert_naar_wachtrij(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: list[bytes],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "ai_extractie_sync_max_paginas", 3)
        wachtrij = FakeWachtrij()

        dikke_pdf = _echte_pdf(paginas=10)
        assert tel_paginas(dikke_pdf) == 10
        assert len(dikke_pdf) <= settings.ai_extractie_sync_max_bytes  # pagina's beslissen, niet bytes
        groot = _upload(administratie_id, gescoopte_gebruiker, opslag, inhoud=dikke_pdf, wachtrij=wachtrij)
        assert groot.status == DocumentStatus.EXTRACTIE_WACHTRIJ
        assert wachtrij.enqueued == [(administratie_id, groot.document_id)]

        klein = _upload(
            administratie_id, gescoopte_gebruiker, opslag, inhoud=_echte_pdf(paginas=2), wachtrij=wachtrij
        )
        assert klein.status == DocumentStatus.TE_CONTROLEREN
        assert len(wachtrij.enqueued) == 1

    def test_zonder_ai_route_blijft_ook_een_groot_document_synchroon(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        fake_extraheer: list[bytes],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AVG-gate uit (default): er gaat toch niets naar de AI, dus "achtergrond" zou alleen
        een tragere no-op zijn — de upload rondt direct af met het overgeslagen-detail."""
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        monkeypatch.setattr(settings, "ai_extractie_sync_max_bytes", 10)
        wachtrij = FakeWachtrij()
        resultaat = _upload(administratie_id, gescoopte_gebruiker, opslag, wachtrij=wachtrij)

        assert resultaat.status == DocumentStatus.TE_CONTROLEREN
        assert wachtrij.enqueued == []
        assert fake_extraheer == []


class TestAsyncFlow:
    def test_upload_wachtrij_worker_klaar_met_systeem_actor(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: list[bytes],
        monkeypatch: pytest.MonkeyPatch,
        admin_engine: Engine,
    ) -> None:
        """De hele asynchrone flow: upload keert direct terug (wachtrij), de échte in-process
        worker verwerkt, en elke worker-overgang draagt de systeem-actor in tijdlijn + audit."""
        monkeypatch.setattr(settings, "ai_extractie_sync_max_bytes", 10)
        wachtrij = InProcessExtractieWachtrij(taak=service.verwerk_extractie_taak, max_workers=1)

        resultaat = _upload(administratie_id, gescoopte_gebruiker, opslag, wachtrij=wachtrij)
        assert resultaat.status == DocumentStatus.EXTRACTIE_WACHTRIJ

        wachtrij.wacht_tot_leeg()

        detail = service.haal_document_op(administratie_id=administratie_id, document_id=resultaat.document_id)
        assert detail.document.status == DocumentStatus.TE_CONTROLEREN
        assert detail.veldvoorstel is not None  # het AI-voorstel is er gewoon, ook via de worker
        assert fake_extraheer == [_PDF]

        # Tijdlijn: mens tot en met de wachtrij, systeem vanaf het oppakken.
        per_status = {g.naar_status: g for g in detail.gebeurtenissen}
        assert per_status[DocumentStatus.ONTVANGEN].actor_id == gescoopte_gebruiker
        assert per_status[DocumentStatus.EXTRACTIE_WACHTRIJ].actor_id == gescoopte_gebruiker
        assert per_status[DocumentStatus.EXTRACTIE_BEZIG].actor_id == SYSTEEM_ACTOR_ID
        assert per_status[DocumentStatus.TE_CONTROLEREN].actor_id == SYSTEEM_ACTOR_ID

        # Audit_event: zelfde verdeling, via het uniforme schema.
        with admin_engine.connect() as conn:
            audit = {
                rij.actie: rij.actor_id
                for rij in conn.execute(
                    text("SELECT actie, actor_id FROM platform.audit_event WHERE record_id = :id"),
                    {"id": str(resultaat.document_id)},
                )
            }
        assert audit["status_extractie_wachtrij"] == gescoopte_gebruiker
        assert audit["status_extractie_bezig"] == SYSTEEM_ACTOR_ID
        assert audit["status_te_controleren"] == SYSTEEM_ACTOR_ID

    def test_projectwaarborg_geldt_onverkort_via_de_worker(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Projectplicht + onvolledige regelset → handmatig_afmaken, ook op de async-route:
        de waarborg zit in _rond_extractie_af en is voor worker en synchroon pad identiek."""
        monkeypatch.setattr(settings, "ai_extractie_sync_max_bytes", 10)
        beheer_service.zet_project_verplicht(
            actor_id=beheerder_id, administratie_id=administratie_id, verplicht=True
        )
        monkeypatch.setattr(
            "app.extractie.service.extraheer_inkoopfactuur",
            lambda pdf_bytes, *, client=None: _fake_extractie(volledig=False),
        )
        wachtrij = InProcessExtractieWachtrij(taak=service.verwerk_extractie_taak, max_workers=1)

        resultaat = _upload(administratie_id, gescoopte_gebruiker, opslag, wachtrij=wachtrij)
        assert resultaat.status == DocumentStatus.EXTRACTIE_WACHTRIJ
        wachtrij.wacht_tot_leeg()

        detail = service.haal_document_op(administratie_id=administratie_id, document_id=resultaat.document_id)
        assert detail.document.status == DocumentStatus.HANDMATIG_AFMAKEN
        assert detail.veldvoorstel is None  # bewust géén totalen-only voorstel

    def test_herextractie_van_groot_document_gaat_ook_async(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: list[bytes],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """De aanleiding van deze hele sessie: juist een hér-extractie van een monsterfactuur
        hield het scherm vast — die gaat nu ook via de wachtrij."""
        resultaat = _upload(administratie_id, gescoopte_gebruiker, opslag)
        assert resultaat.status == DocumentStatus.TE_CONTROLEREN  # klein bij upload

        monkeypatch.setattr(settings, "ai_extractie_sync_max_bytes", 10)  # nu telt hij als groot
        wachtrij = FakeWachtrij()
        status = service.herextraheer_document(
            administratie_id=administratie_id,
            document_id=resultaat.document_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            wachtrij=wachtrij,
        )
        assert status == DocumentStatus.EXTRACTIE_WACHTRIJ
        assert wachtrij.enqueued == [(administratie_id, resultaat.document_id)]

    def test_worker_fout_laat_document_nooit_op_bezig_hangen(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: list[bytes],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        monkeypatch.setattr(settings, "ai_extractie_sync_max_bytes", 10)
        resultaat = _upload(administratie_id, gescoopte_gebruiker, opslag, wachtrij=FakeWachtrij())

        # De worker krijgt een opslag zonder het bestand — een onverwachte fout buiten het
        # AI-vangnet. Het document eindigt zichtbaar op te_controleren, nooit stil op bezig.
        lege_opslag = LokaleBestandsopslag(tmp_path / "lege-opslag")
        service.verwerk_extractie_taak(
            administratie_id=administratie_id, document_id=resultaat.document_id, opslag=lege_opslag
        )

        detail = service.haal_document_op(administratie_id=administratie_id, document_id=resultaat.document_id)
        assert detail.document.status == DocumentStatus.TE_CONTROLEREN
        laatste = detail.gebeurtenissen[-1]
        assert laatste.actor_id == SYSTEEM_ACTOR_ID
        assert laatste.detail is not None and "ai_extractie_fout" in laatste.detail

    def test_worker_slaat_intussen_verwijderd_document_over(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: list[bytes],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Statusmachine-idempotentie: wie een wachtend document verwijdert, wint van de taak —
        de worker raakt het niet meer aan (ook geen dubbele verwerking bij een dubbele taak)."""
        monkeypatch.setattr(settings, "ai_extractie_sync_max_bytes", 10)
        resultaat = _upload(administratie_id, gescoopte_gebruiker, opslag, wachtrij=FakeWachtrij())
        service.verwijder_document(
            administratie_id=administratie_id, document_id=resultaat.document_id, actor_id=gescoopte_gebruiker
        )

        service.verwerk_extractie_taak(administratie_id=administratie_id, document_id=resultaat.document_id)

        detail = service.haal_document_op(administratie_id=administratie_id, document_id=resultaat.document_id)
        assert detail.document.status == DocumentStatus.VERWIJDERD
        assert fake_extraheer == []


class TestHerstelNaHerstart:
    def test_achtergebleven_wachtrij_en_bezig_documenten_worden_opnieuw_ingepland(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: list[bytes],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Simuleert een proces-herstart: één document bleef in de wachtrij (taak verloren), één
        strandde midden in een worker-run op bezig. Beide worden opnieuw ingepland; het
        bezig-document eerst zichtbaar terug de wachtrij in (systeem-actor + herkenbaar detail)."""
        monkeypatch.setattr(settings, "ai_extractie_sync_max_bytes", 10)
        verloren_wachtrij = FakeWachtrij()  # verwerkt nooit — de "verloren" queue van vóór de herstart
        doc_wachtrij = _upload(administratie_id, gescoopte_gebruiker, opslag, wachtrij=verloren_wachtrij)
        doc_bezig = _upload(
            administratie_id, gescoopte_gebruiker, opslag, inhoud=_PDF + b"2", wachtrij=verloren_wachtrij
        )
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            document = session.get(Document, doc_bezig.document_id)
            assert document is not None
            service._schrijf_overgang(
                session, document=document, naar=DocumentStatus.EXTRACTIE_BEZIG, actor_id=SYSTEEM_ACTOR_ID
            )

        herstel_wachtrij = FakeWachtrij()
        hersteld = service.herstel_achtergebleven_extracties(wachtrij=herstel_wachtrij)

        assert hersteld == 2
        assert {doc_id for _, doc_id in herstel_wachtrij.enqueued} == {
            doc_wachtrij.document_id,
            doc_bezig.document_id,
        }
        detail = service.haal_document_op(administratie_id=administratie_id, document_id=doc_bezig.document_id)
        assert detail.document.status == DocumentStatus.EXTRACTIE_WACHTRIJ
        laatste = detail.gebeurtenissen[-1]
        assert laatste.actor_id == SYSTEEM_ACTOR_ID
        assert laatste.detail == {"herstel": "achtergebleven_na_herstart"}

    def test_niets_te_herstellen_is_een_nul_operatie(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: list[bytes],
    ) -> None:
        _upload(administratie_id, gescoopte_gebruiker, opslag)  # klein: eindigt op te_controleren
        wachtrij = FakeWachtrij()
        assert service.herstel_achtergebleven_extracties(wachtrij=wachtrij) == 0
        assert wachtrij.enqueued == []
