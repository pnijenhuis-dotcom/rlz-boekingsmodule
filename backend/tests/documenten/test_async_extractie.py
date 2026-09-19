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

    def _fake(pdf_bytes: bytes, *, client=None, verbruik_referentie=None, mail_context=None):
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
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Legacy klein-vs-groot-routing achter de seam `ai_extractie_in_request` (sinds blok 1c 08-09
        is de wachtrij de standaard voor élke AI-extractie): een kleine factuur komt met de seam aan
        direct als te_controleren terug, mét voorstel, zonder wachtrij-status in de tijdlijn."""
        monkeypatch.setattr(settings, "ai_extractie_in_request", True)
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
            # Sinds 31-08 draagt de overgang altijd een reden — de heraanbied-lus draait 'm
            # met de systeem-actor en élke ⚙-overgang vereist er een.
            "reden": "groot document — extractie via de wachtrij",
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
        monkeypatch.setattr(settings, "ai_extractie_in_request", True)  # legacy klein-vs-groot-seam
        monkeypatch.setattr(settings, "ai_extractie_sync_max_paginas", 3)
        wachtrij = FakeWachtrij()

        dikke_pdf = _echte_pdf(paginas=10)
        assert tel_paginas(dikke_pdf) == 10
        assert len(dikke_pdf) <= settings.ai_extractie_sync_max_bytes  # pagina's beslissen, niet bytes
        groot = _upload(administratie_id, gescoopte_gebruiker, opslag, inhoud=dikke_pdf, wachtrij=wachtrij)
        assert groot.status == DocumentStatus.EXTRACTIE_WACHTRIJ
        assert wachtrij.enqueued == [(administratie_id, groot.document_id)]

        klein = _upload(administratie_id, gescoopte_gebruiker, opslag, inhoud=_echte_pdf(paginas=2), wachtrij=wachtrij)
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
        beheer_service.zet_project_verplicht(actor_id=beheerder_id, administratie_id=administratie_id, verplicht=True)
        monkeypatch.setattr(
            "app.extractie.service.extraheer_inkoopfactuur",
            lambda pdf_bytes, *, client=None, verbruik_referentie=None, mail_context=None: _fake_extractie(
                volledig=False
            ),
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
        monkeypatch.setattr(settings, "ai_extractie_in_request", True)  # legacy klein-vs-groot-seam
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
                session,
                document=document,
                naar=DocumentStatus.EXTRACTIE_BEZIG,
                actor_id=SYSTEEM_ACTOR_ID,
                detail={"reden": "testopstelling: gestrande bezig-run nabootsen"},
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
        # Vangnet 28-08: élke systeem-overgang draagt óók een leesbare reden.
        assert laatste.detail == {
            "herstel": "achtergebleven_na_herstart",
            "reden": "opnieuw ingepland na een herstart van de verwerking",
        }

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

    def test_cloud_variant_laat_een_verse_bezig_run_van_de_job_staan(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: list[bytes],
    ) -> None:
        """Systeemfout BLOW 18-09 (tijdlijn c9ba6d8d): een opschalende service-instance zette documenten die een LOPENDE
        job-executie op bezig had terug naar de wachtrij ("opnieuw ingepland na een herstart") → driedubbele verwerking.
        Mét de cloud-wachtrij geldt dezelfde staleness-regel als in de job: een verse bezig-run blijft staan, een
        gestrande (ouder dan `stale_na`) gaat terug; wachtrij-documenten worden altijd (opnieuw) getriggerd."""
        from datetime import timedelta

        from app.documenten.wachtrij import CloudRunJobExtractieWachtrij

        verloren = FakeWachtrij()
        doc_wachtrij = _upload(administratie_id, gescoopte_gebruiker, opslag, inhoud=_PDF + b"w", wachtrij=verloren)
        doc_bezig = _upload(administratie_id, gescoopte_gebruiker, opslag, inhoud=_PDF + b"b", wachtrij=verloren)
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            document = session.get(Document, doc_bezig.document_id)
            assert document is not None
            service._schrijf_overgang(
                session,
                document=document,
                naar=DocumentStatus.EXTRACTIE_BEZIG,
                actor_id=SYSTEEM_ACTOR_ID,
                detail={"reden": "testopstelling: lopende job-executie nabootsen"},
            )
        triggers: list[str] = []
        cloud = CloudRunJobExtractieWachtrij(job_resource="x", trigger=triggers.append, spoor=lambda **kw: None)
        assert service.herstel_achtergebleven_extracties(wachtrij=cloud) == 1  # alleen het wachtrij-document
        assert triggers == ["x"]
        detail = service.haal_document_op(administratie_id=administratie_id, document_id=doc_bezig.document_id)
        assert detail.document.status == DocumentStatus.EXTRACTIE_BEZIG
        # Wél gestrand (ouder dan de drempel): terug de wachtrij in — zelfde regel als in de job.
        assert service.herstel_achtergebleven_extracties(wachtrij=cloud, stale_na=timedelta(seconds=0)) == 2
        detail = service.haal_document_op(administratie_id=administratie_id, document_id=doc_bezig.document_id)
        assert detail.document.status == DocumentStatus.EXTRACTIE_WACHTRIJ
        # Het wachtrij-document zelf: {doc_wachtrij} beide keren geteld.
        assert doc_wachtrij.document_id is not None


@pytest.fixture(autouse=True)
def _bundelvenster_leeg() -> None:
    """Het bundelvenster van de cloud-trigger is procesbreed (per job-resource): élke test begint schoon."""
    from app.documenten.wachtrij import reset_bundelvenster

    reset_bundelvenster()
    yield
    reset_bundelvenster()


class TestBundelvenster:
    """Trigger-bundeling (systeemfout BLOW-bulk 18-09: 180 uploads → 118 job-executies in één uur, 180 × 429 op de
    Jobs-API, dubbele verwerking). Eén geslaagde trigger dekt 30 s; daarbinnen = `gebundeld` (spoor, geen call);
    een mislukte trigger opent géén venster (de volgende upload probeert gewoon opnieuw)."""

    JOB = "projects/p/locations/europe-west4/jobs/rlz-extractie-wachtrij"

    def _wachtrij(self, klok: list[float], triggers: list[str], sporen: list[dict], *, trigger=None):  # noqa: ANN001, ANN202
        from app.documenten.wachtrij import CloudRunJobExtractieWachtrij

        return CloudRunJobExtractieWachtrij(
            job_resource=self.JOB,
            trigger=trigger or triggers.append,
            spoor=lambda **kw: sporen.append(kw),
            klok=lambda: klok[0],
        )

    def test_binnen_het_venster_geen_tweede_executie_wel_een_spoor(self) -> None:
        from app.documenten import wachtrij as wq

        klok, triggers, sporen = [1000.0], [], []
        w = self._wachtrij(klok, triggers, sporen)
        aid = uuid.uuid4()
        w.enqueue(administratie_id=aid, document_id=uuid.uuid4())
        klok[0] += 10
        w.enqueue(administratie_id=aid, document_id=uuid.uuid4())
        klok[0] += 19.9  # 29,9 s ná de trigger: nog binnen het venster
        w.enqueue(administratie_id=aid, document_id=uuid.uuid4())
        assert len(triggers) == 1
        assert [sp["uitkomst"] for sp in sporen] == [wq.UITKOMST_GESLAAGD, wq.UITKOMST_GEBUNDELD, wq.UITKOMST_GEBUNDELD]
        assert sporen[1]["gebundeld_na_s"] == 10.0 and sporen[2]["gebundeld_na_s"] == 29.9
        assert all(sp["fout"] is None for sp in sporen)
        # Ná het venster: opnieuw één executie.
        klok[0] += 0.2
        w.enqueue(administratie_id=aid, document_id=uuid.uuid4())
        assert len(triggers) == 2 and sporen[-1]["uitkomst"] == wq.UITKOMST_GESLAAGD
        assert wq.TRIGGER_BUNDEL_VENSTER_S == 30.0

    def test_venster_is_procesbreed_per_job_resource(self) -> None:
        """Twee uploads in hetzelfde proces (twee requests, twee wachtrij-objecten) delen één executie — precies de
        bulk-upload-casus (4 parallelle uploads per browser)."""
        klok, triggers, sporen = [50.0], [], []
        w1, w2 = self._wachtrij(klok, triggers, sporen), self._wachtrij(klok, triggers, sporen)
        w1.enqueue(administratie_id=uuid.uuid4(), document_id=uuid.uuid4())
        w2.enqueue(administratie_id=uuid.uuid4(), document_id=uuid.uuid4())
        assert len(triggers) == 1 and sporen[-1]["uitkomst"] == "gebundeld"

    def test_mislukte_trigger_opent_geen_venster(self) -> None:
        from app.documenten import wachtrij as wq

        klok, triggers, sporen = [0.0], [], []

        def faal(_: str) -> None:
            raise RuntimeError("429 Too Many Requests")

        kapot = self._wachtrij(klok, triggers, sporen, trigger=faal)
        kapot.enqueue(administratie_id=uuid.uuid4(), document_id=uuid.uuid4())  # geen exception: vangnet = scheduler
        assert sporen[-1]["uitkomst"] == wq.UITKOMST_MISLUKT and "429" in sporen[-1]["fout"]
        klok[0] += 1
        goed = self._wachtrij(klok, triggers, sporen)
        goed.enqueue(administratie_id=uuid.uuid4(), document_id=uuid.uuid4())
        assert triggers == [self.JOB] and sporen[-1]["uitkomst"] == wq.UITKOMST_GESLAAGD

    def test_gebundeld_spoor_landt_als_audit_event(self, administratie_id: uuid.UUID) -> None:
        from sqlalchemy import select

        from app.db.models import AuditEvent
        from app.documenten.wachtrij import TRIGGER_AUDIT_ACTIE, CloudRunJobExtractieWachtrij

        d1, d2 = uuid.uuid4(), uuid.uuid4()
        w = CloudRunJobExtractieWachtrij(job_resource=self.JOB, trigger=lambda _: None)
        w.enqueue(administratie_id=administratie_id, document_id=d1)
        w.enqueue(administratie_id=administratie_id, document_id=d2)
        with scoped_session(administratie_id) as session:
            rijen = {
                e.record_id: e.nieuwe_waarde
                for e in session.scalars(select(AuditEvent).where(AuditEvent.actie == TRIGGER_AUDIT_ACTIE)).all()
            }
        assert rijen[d1]["uitkomst"] == "geslaagd"
        assert rijen[d2]["uitkomst"] == "gebundeld" and rijen[d2]["fout"] is None and "gebundeld_na_s" in rijen[d2]

    def test_job_herhaalt_de_pas_zolang_er_werk_was(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """De lopende executie dekt uploads die binnen het venster binnenkomen: ná een pas mét werk nog een pas, tot een
        lege pas of het plafond (`WACHTRIJ_MAX_PASSEN`, dan het scheduler-vangnet)."""
        passen = iter([2, 1, 0, 7])
        aanroepen: list[int] = []

        def nep_pas(*, stale_na):  # noqa: ANN001, ANN202
            n = next(passen)
            aanroepen.append(n)
            return n

        monkeypatch.setattr(service, "_verwerk_extractie_wachtrij_pas", nep_pas)
        assert service.verwerk_extractie_wachtrij() == 3 and aanroepen == [2, 1, 0]
        aanroepen.clear()
        passen = iter([3, 3, 3, 3, 3, 3])
        assert service.verwerk_extractie_wachtrij(max_passen=2) == 6 and aanroepen == [3, 3]
        assert service.WACHTRIJ_MAX_PASSEN == 5


class TestWachtrijJob:
    """Feedbackronde 26-08 punt 4: op Cloud Run valt een in-process worker-thread buiten een
    request stil (request-based CPU) — grote uploads bleven 'in wachtrij'. De job-variant werkt
    de wachtrij synchroon af; de cloud-wachtrij triggert de job en laat de upload nooit falen."""

    def test_verwerk_extractie_wachtrij_maakt_wachtrij_documenten_af_met_systeem_actor(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: list[bytes],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "ai_extractie_sync_max_bytes", 10)
        verloren = FakeWachtrij()  # de thread die op Cloud Run nooit CPU kreeg
        resultaat = _upload(administratie_id, gescoopte_gebruiker, opslag, wachtrij=verloren)
        assert resultaat.status == DocumentStatus.EXTRACTIE_WACHTRIJ
        assert fake_extraheer == []

        monkeypatch.setattr(service, "_standaard_opslag", lambda: opslag)
        verwerkt = service.verwerk_extractie_wachtrij()

        assert verwerkt == 1
        assert fake_extraheer == [_PDF]
        detail = service.haal_document_op(administratie_id=administratie_id, document_id=resultaat.document_id)
        assert detail.document.status == DocumentStatus.TE_CONTROLEREN
        assert detail.gebeurtenissen[-1].actor_id == SYSTEEM_ACTOR_ID
        # Tweede run: niets meer te doen (idempotent via de statusmachine).
        assert service.verwerk_extractie_wachtrij() == 0

    def test_verse_bezig_run_wordt_niet_teruggezet_maar_een_gestrande_wel(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: list[bytes],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from datetime import timedelta

        monkeypatch.setattr(settings, "ai_extractie_sync_max_bytes", 10)
        monkeypatch.setattr(service, "_standaard_opslag", lambda: opslag)
        doc = _upload(administratie_id, gescoopte_gebruiker, opslag, wachtrij=FakeWachtrij())
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            document = session.get(Document, doc.document_id)
            assert document is not None
            service._schrijf_overgang(
                session,
                document=document,
                naar=DocumentStatus.EXTRACTIE_BEZIG,
                actor_id=SYSTEEM_ACTOR_ID,
                detail={"reden": "testopstelling: gestrande bezig-run nabootsen"},
            )
        # Verse bezig-run (van een overlappende job-uitvoering): overslaan.
        assert service.verwerk_extractie_wachtrij() == 0
        assert fake_extraheer == []
        # Gestrand (ouder dan de drempel): terug de wachtrij in en afmaken.
        assert service.verwerk_extractie_wachtrij(stale_na=timedelta(seconds=0)) == 1
        detail = service.haal_document_op(administratie_id=administratie_id, document_id=doc.document_id)
        assert detail.document.status == DocumentStatus.TE_CONTROLEREN
        assert any(
            (g.detail or {}).get("herstel") == "gestrand_op_bezig" and g.detail.get("reden")
            for g in detail.gebeurtenissen
        )

    def test_cloud_wachtrij_triggert_job_en_laat_upload_nooit_falen(self) -> None:
        from app.documenten.wachtrij import CloudRunJobExtractieWachtrij

        getriggerd: list[str] = []
        wachtrij = CloudRunJobExtractieWachtrij(
            job_resource="projects/p/locations/l/jobs/rlz-extractie-wachtrij", trigger=getriggerd.append
        )
        wachtrij.enqueue(administratie_id=uuid.uuid4(), document_id=uuid.uuid4())
        assert getriggerd == ["projects/p/locations/l/jobs/rlz-extractie-wachtrij"]

        def faal(_: str) -> None:
            raise RuntimeError("403 run.jobs.run")

        kapot = CloudRunJobExtractieWachtrij(job_resource="x", trigger=faal)
        kapot.enqueue(administratie_id=uuid.uuid4(), document_id=uuid.uuid4())  # geen exception: vangnet = scheduler

    def test_standaard_wachtrij_kiest_cloud_variant_bij_job_resource(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.documenten.wachtrij import CloudRunJobExtractieWachtrij

        monkeypatch.setattr(service, "_wachtrij", None)
        monkeypatch.setattr(settings, "extractie_wachtrij_job_resource", "projects/p/locations/l/jobs/j")
        assert isinstance(service._standaard_wachtrij(), CloudRunJobExtractieWachtrij)
        monkeypatch.setattr(service, "_wachtrij", None)
        monkeypatch.setattr(settings, "extractie_wachtrij_job_resource", None)
        assert isinstance(service._standaard_wachtrij(), InProcessExtractieWachtrij)
        monkeypatch.setattr(service, "_wachtrij", None)


def test_cloud_wachtrij_legt_trigger_uitkomst_vast_als_audit_spoor(administratie_id: uuid.UUID) -> None:
    """Herstelrun "Basis eerst" 08-09 blok 2: élke trigger laat een audit-event `extractie_wachtrij_trigger` achter
    (geslaagd/mislukt, systeem-actor, gescoopt op de administratie) — de bron van de teller in de reconciliatiemail.
    Een mislukte trigger laat de upload nog steeds nooit falen."""
    from sqlalchemy import select

    from app.db.models import AuditEvent
    from app.documenten.wachtrij import TRIGGER_AUDIT_ACTIE, CloudRunJobExtractieWachtrij

    job = "projects/p/locations/europe-west4/jobs/rlz-extractie-wachtrij"
    doc_ok, doc_fout = uuid.uuid4(), uuid.uuid4()
    CloudRunJobExtractieWachtrij(job_resource=job, trigger=lambda _: None).enqueue(
        administratie_id=administratie_id, document_id=doc_ok
    )

    def faal(_: str) -> None:
        raise RuntimeError("403 run.jobs.run")

    from app.documenten.wachtrij import reset_bundelvenster

    reset_bundelvenster()  # buiten het 30 s-bundelvenster van de geslaagde trigger (anders: `gebundeld`)
    CloudRunJobExtractieWachtrij(job_resource=job, trigger=faal).enqueue(
        administratie_id=administratie_id, document_id=doc_fout
    )  # geen exception

    with scoped_session(administratie_id) as session:
        rijen = {
            e.record_id: e
            for e in session.scalars(select(AuditEvent).where(AuditEvent.actie == TRIGGER_AUDIT_ACTIE)).all()
        }
    assert set(rijen) == {doc_ok, doc_fout}
    assert rijen[doc_ok].nieuwe_waarde == {"uitkomst": "geslaagd", "job": "rlz-extractie-wachtrij", "fout": None}
    assert rijen[doc_fout].nieuwe_waarde["uitkomst"] == "mislukt"
    assert "403 run.jobs.run" in rijen[doc_fout].nieuwe_waarde["fout"]
    assert all(e.actor_id == SYSTEEM_ACTOR_ID and e.administratie_id == administratie_id for e in rijen.values())
