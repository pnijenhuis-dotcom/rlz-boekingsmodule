"""Blok 1 spoedrun 08-09 (1c) — uploads mogen andere requests niet verdringen.

Cloud Logging 07-09 (BESLISSINGEN rij 12c): een synchrone `POST …/documenten` van 23,9 s en een
`POST /intake/bestand` van 21,5 s lieten triviale routes (`/auth/administraties`, normaal 0,05 s)
14,7 s doen. Wortel: beide routes zijn `async def` en riepen de blokkerende servicelaag (opslag,
sha, extractie incl. Claude-call tot 120 s) rechtstreeks op de event-loop aan — dan staat de héle
uvicorn-loop stil, óók voor sync-routes (die worden vanuit de loop naar de threadpool gedispatcht).
Fix: het blokkerende werk draait via `run_in_threadpool`.

Bewijs: één gedeelde event-loop (`with TestClient(app)` = één portal, zoals uvicorn in productie),
een trage upload (servicelaag geblokkeerd op een Event) en tegelijk een lees-request — die moet
binnenkomen terwijl de upload nog loopt. Op de oude `async def`-vorm zonder threadpool wacht de
lees-request tot de upload klaar is (gecontroleerd 08-09 tegen de HEAD-router: test rood)."""

from __future__ import annotations

import threading
import time
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.documenten import service
from app.documenten.models import DocumentStatus
from app.main import app
from app.security.tokens import create_access_token


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _wachtrij_leeg(admin_engine: Engine) -> None:
    with admin_engine.connect() as conn:
        conn.execute(text("SELECT 1")).scalar_one()


def test_trage_upload_blokkeert_een_gelijktijdige_leesroute_niet(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, monkeypatch, admin_engine: Engine
) -> None:
    _wachtrij_leeg(admin_engine)
    upload_begonnen = threading.Event()
    upload_mag_door = threading.Event()

    def trage_upload(**kwargs):  # noqa: ANN003, ANN202 — zelfde handtekening als de service
        upload_begonnen.set()
        assert upload_mag_door.wait(timeout=10), "testopzet: upload nooit vrijgegeven"
        return service.UploadResultaat(
            document_id=uuid.uuid4(),
            status=DocumentStatus.TE_CONTROLEREN,
            mogelijk_duplicaat_van_id=None,
            mogelijk_duplicaat_van=None,
        )

    monkeypatch.setattr(service, "upload_document", trage_upload)
    headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
    uitkomst: dict[str, object] = {}

    with TestClient(app) as client:  # één event-loop voor álle requests, zoals uvicorn

        def upload() -> None:
            uitkomst["upload"] = client.post(
                f"/administraties/{administratie_id}/documenten",
                files={"bestand": ("factuur.pdf", b"%PDF-1.4 traag", "application/pdf")},
                headers=headers,
            )

        t = threading.Thread(target=upload)
        t.start()
        assert upload_begonnen.wait(timeout=5), "upload kwam niet bij de servicelaag"
        # De upload hangt nu in de servicelaag. Een lees-request moet gewoon antwoorden.
        t0 = time.perf_counter()
        resp = client.get("/auth/administraties", headers=headers)
        duur = time.perf_counter() - t0
        upload_mag_door.set()
        t.join(timeout=10)

    assert resp.status_code == 200, resp.text
    assert duur < 2.0, f"leesroute wachtte {duur:.2f} s op de upload — event-loop geblokkeerd"
    assert upload_mag_door.is_set()
    upload_resp = uitkomst["upload"]
    assert upload_resp.status_code == 201, upload_resp.text  # type: ignore[attr-defined]


def test_upload_route_gebruikt_de_threadpool(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, monkeypatch
) -> None:
    """Directe borging naast de timing: de servicelaag draait NIET op de event-loop-thread."""
    gezien: dict[str, object] = {}

    def registreer(**kwargs):  # noqa: ANN003, ANN202
        gezien["thread"] = threading.current_thread()
        return service.UploadResultaat(
            document_id=uuid.uuid4(),
            status=DocumentStatus.TE_CONTROLEREN,
            mogelijk_duplicaat_van_id=None,
            mogelijk_duplicaat_van=None,
        )

    monkeypatch.setattr(service, "upload_document", registreer)
    with TestClient(app) as client:
        loop_thread: dict[str, object] = {}

        async def _pak_loop_thread() -> None:
            loop_thread["thread"] = threading.current_thread()

        client.portal.call(_pak_loop_thread)
        resp = client.post(
            f"/administraties/{administratie_id}/documenten",
            files={"bestand": ("factuur.pdf", b"%PDF-1.4 threadpool", "application/pdf")},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
    assert resp.status_code == 201, resp.text
    assert gezien["thread"] is not loop_thread["thread"], "servicelaag draaide op de event-loop-thread"


class _Verzamelaar:
    """Wachtrij-stub: registreert enqueue-aanroepen, voert niets uit (de test speelt zelf de worker)."""

    def __init__(self) -> None:
        self.taken: list[tuple[uuid.UUID, uuid.UUID]] = []

    def enqueue(self, *, administratie_id: uuid.UUID, document_id: uuid.UUID) -> None:
        self.taken.append((administratie_id, document_id))


def _trage_fake_extractie(aanroepen: list[bytes], wacht_s: float):
    from tests.documenten.test_ai_extractie import _fake_extractie

    def _fake(pdf_bytes: bytes, *, client=None, verbruik_referentie=None, mail_context=None):  # noqa: ANN001, ANN202
        aanroepen.append(pdf_bytes)
        time.sleep(wacht_s)
        return _fake_extractie()

    return _fake


def test_upload_met_ai_extractie_keert_binnen_2s_terug_en_de_worker_maakt_het_af(
    gescoopte_gebruiker: uuid.UUID,
    administratie_id: uuid.UUID,
    beheerder_id: uuid.UUID,
    monkeypatch,
    tmp_path,
) -> None:
    """1c verbreed (08-09): live deed POST …/documenten 28–51 s (extractie in de request) → browser-
    timeout terwijl de upload slaagde. Nu: 201 + document-id + status extractie_wachtrij BINNEN 2 s,
    zonder één AI-aanroep in de request; de wachtrij-taak (Cloud Run-job in productie) doet de
    extractie + na-extractie-hook daarna en zet het document op te_controleren."""
    from app.beheer import service as beheer_service
    from app.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "document_opslag_basismap", str(tmp_path / "documenten"))
    beheer_service.zet_ai_extractie_ingeschakeld(
        actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
    )
    aanroepen: list[bytes] = []
    monkeypatch.setattr("app.extractie.service.extraheer_inkoopfactuur", _trage_fake_extractie(aanroepen, 5.0))
    verzamelaar = _Verzamelaar()
    monkeypatch.setattr(service, "_wachtrij", verzamelaar)

    client = TestClient(app)
    t0 = time.perf_counter()
    resp = client.post(
        f"/administraties/{administratie_id}/documenten",
        files={"bestand": ("factuur.pdf", b"%PDF-1.4 ai-achtergrond", "application/pdf")},
        headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
    )
    duur = time.perf_counter() - t0
    assert resp.status_code == 201, resp.text
    assert duur < 2.0, f"upload-route deed {duur:.2f} s — extractie zit nog in de request"
    body = resp.json()
    assert body["status"] == "extractie_wachtrij"
    assert aanroepen == [], "AI-extractie werd in de request aangeroepen"
    document_id = uuid.UUID(body["document_id"])
    assert verzamelaar.taken == [(administratie_id, document_id)]

    tijdlijn = service.haal_document_op(administratie_id=administratie_id, document_id=document_id)
    wachtrij_stap = next(g for g in tijdlijn.gebeurtenissen if g.naar_status == DocumentStatus.EXTRACTIE_WACHTRIJ)
    assert wachtrij_stap.detail["reden"] == "upload — verwerking op de achtergrond"
    assert wachtrij_stap.actor_id == gescoopte_gebruiker  # de overgang draagt de menselijke actor

    # De worker (in productie de Cloud Run-job `rlz-extractie-wachtrij`) maakt het af.
    service.verwerk_extractie_taak(administratie_id=administratie_id, document_id=document_id)
    assert len(aanroepen) == 1
    na = service.haal_document_op(administratie_id=administratie_id, document_id=document_id)
    assert na.document.status == DocumentStatus.TE_CONTROLEREN


def test_verzamelbak_toewijzing_start_extractie_op_de_achtergrond(
    gescoopte_gebruiker: uuid.UUID,
    administratie_id: uuid.UUID,
    beheerder_id: uuid.UUID,
    monkeypatch,
    opslag,
) -> None:
    """Zelfde route voor de tweede helft van een verzamelbak-toewijzing (`start_extractie_na_toewijzing`,
    ook de ingang van /intake/bestand ná toewijzing): geen AI in de request, wachtrij-status terug."""
    from app.beheer import service as beheer_service
    from app.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    beheer_service.zet_ai_extractie_ingeschakeld(
        actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
    )
    aanroepen: list[bytes] = []
    monkeypatch.setattr("app.extractie.service.extraheer_inkoopfactuur", _trage_fake_extractie(aanroepen, 0.0))
    verzamelaar = _Verzamelaar()
    # Eerst een document zónder extractie (gate stond nog uit tijdens de upload = te_controleren) —
    # dan de her-toewijzingsroute simuleren via start_extractie_na_toewijzing op een ONTVANGEN-document.
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="toegewezen.pdf",
        inhoud=b"%PDF-1.4 toegewezen",
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    )
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    from app.db.session import scoped_session
    from app.documenten.models import Document

    with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
        document = session.get(Document, resultaat.document_id)
        service._schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.ONTVANGEN,
            actor_id=gescoopte_gebruiker,
            detail={"reden": "test: terug naar ontvangen"},
        )
    status = service.start_extractie_na_toewijzing(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
        wachtrij=verzamelaar,
    )
    assert status == DocumentStatus.EXTRACTIE_WACHTRIJ
    assert aanroepen == []
    assert verzamelaar.taken == [(administratie_id, resultaat.document_id)]
