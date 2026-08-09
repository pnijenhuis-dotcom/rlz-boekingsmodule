"""Autoboeken-opt-in per leverancier (blok 2): het pad boekt uitsluitend wanneer élk oordeel al
door een mens geveld is — elke weiger-reden getest, plus de opt-in-beheerlaag."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import autoboeken, boeken, service
from app.documenten.storage import LokaleBestandsopslag
from app.geheugen.models import BoekingObservatie
from app.sync.models import VendorCache
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.documenten.test_ubl import _VOORBEELD_UBL

VENDOR_ID = uuid.UUID("33333333-3333-3333-3333-333333333331")
GB_ID = uuid.UUID("44444444-4444-4444-4444-444444444441")
BTW_ID = uuid.UUID("55555555-5555-5555-5555-555555555551")


@pytest.fixture
def vendor_bouwmaat(administratie_id: uuid.UUID) -> uuid.UUID:
    """De leverancier uit _VOORBEELD_UBL in de vendor-cache — de vendor-raad-stap (exacte
    naammatch) herkent 'm dan bij de upload."""
    with scoped_session(administratie_id) as session:
        session.add(
            VendorCache(
                id=VENDOR_ID,
                administratie_id=administratie_id,
                naam="Bouwmaat Nederland B.V.",
                brondata={},
            )
        )
    return VENDOR_ID


def _observatie(administratie_id: uuid.UUID, *, bron: str) -> BoekingObservatie:
    return BoekingObservatie(
        id=uuid.uuid4(),
        administratie_id=administratie_id,
        vendor_id=VENDOR_ID,
        regel_sleutel=None,
        gb_id=GB_ID,
        btw_id=BTW_ID,
        project_id=None,
        bron=bron,
        bron_datum=datetime.now(UTC).date(),
    )


@pytest.fixture
def bevestigd_geheugen(administratie_id: uuid.UUID) -> None:
    """Twee app-observaties (door een mens bevestigde boekingen) — het geheugen-voorstel is
    daarmee groen én app-bevestigd op leverancier-niveau."""
    with scoped_session(administratie_id) as session:
        session.add(_observatie(administratie_id, bron="app"))
        session.add(_observatie(administratie_id, bron="app"))


@pytest.fixture
def boeken_aan(beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)


@pytest.fixture
def optin_aan(beheerder_id: uuid.UUID, administratie_id: uuid.UUID, vendor_bouwmaat: uuid.UUID) -> None:
    autoboeken.zet_leverancier_autoboeken(
        administratie_id=administratie_id, vendor_id=VENDOR_ID, actor_id=beheerder_id, ingeschakeld=True
    )


def _upload(
    administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag, suffix: bytes = b""
) -> uuid.UUID:
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="factuur.xml",
        inhoud=_VOORBEELD_UBL + suffix,
        actor_id=actor_id,
        opslag=opslag,
    )
    return resultaat.document_id


def _status(admin_engine: Engine, document_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}
        ).scalar_one()


def _audit_redenen(admin_engine: Engine, document_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text(
                "SELECT nieuwe_waarde->>'reden' FROM platform.audit_event "
                "WHERE actie = 'autoboeken_geweigerd' AND record_id = :id"
            ),
            {"id": document_id},
        ).all()
    return [r[0] for r in rijen]


class TestOptInBeheer:
    def test_zetten_audit_en_lijst(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, vendor_bouwmaat: uuid.UUID, admin_engine: Engine
    ) -> None:
        assert autoboeken.zet_leverancier_autoboeken(
            administratie_id=administratie_id, vendor_id=VENDOR_ID, actor_id=beheerder_id, ingeschakeld=True
        )
        [rij] = autoboeken.lijst_leverancier_autoboeken(administratie_id=administratie_id)
        assert rij.vendor_id == VENDOR_ID and rij.autoboeken_ingeschakeld is True
        with admin_engine.connect() as conn:
            acties = conn.execute(
                text("SELECT count(*) FROM platform.audit_event WHERE actie = 'leverancier_autoboeken_gewijzigd'")
            ).scalar_one()
        assert acties == 1

    def test_default_uit(self, administratie_id: uuid.UUID, vendor_bouwmaat: uuid.UUID) -> None:
        [rij] = autoboeken.lijst_leverancier_autoboeken(administratie_id=administratie_id)
        assert rij.autoboeken_ingeschakeld is False


class TestAutoboekPad:
    def test_happy_path_boekt_automatisch_met_zichtbare_herkomst(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        boeken_aan: None,
        optin_aan: None,
        bevestigd_geheugen: None,
    ) -> None:
        fake_client = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)
        # De upload-hook probeert autoboeken zelf al (post-commit).
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)

        assert _status(admin_engine, document_id) == "geboekt"
        with admin_engine.connect() as conn:
            detail, actor = conn.execute(
                text(
                    "SELECT detail, actor_id FROM boekhouding.document_gebeurtenis "
                    "WHERE document_id = :id AND naar_status = 'geboekt'"
                ),
                {"id": document_id},
            ).one()
            assert detail["automatisch_geboekt"] is True
            assert str(actor) == str(SYSTEEM_ACTOR_ID)
            audit = conn.execute(
                text(
                    "SELECT count(*) FROM platform.audit_event "
                    "WHERE actie = 'automatisch_geboekt' AND record_id = :id"
                ),
                {"id": document_id},
            ).scalar_one()
            assert audit == 1
            # Boekvoorstel gevuld uit het bevestigde geheugen.
            gb = conn.execute(
                text("SELECT ledger_id FROM boekhouding.boekvoorstel_regel WHERE document_id = :id"),
                {"id": document_id},
            ).scalar_one()
            assert str(gb) == str(GB_ID)
        # Werkvoorraad-lijst draagt de markering.
        items = service.lijst_documenten(administratie_id=administratie_id)
        item = next(i for i in items if i.document.id == document_id)
        assert item.automatisch_geboekt is True

    def test_optin_uit_doet_niets_en_audit_stil(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        boeken_aan: None,
        vendor_bouwmaat: uuid.UUID,
        bevestigd_geheugen: None,
    ) -> None:
        fake_client = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        assert _status(admin_engine, document_id) == "te_controleren"
        assert _audit_redenen(admin_engine, document_id) == []

    def test_seed_only_geheugen_weigert(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        boeken_aan: None,
        optin_aan: None,
    ) -> None:
        with scoped_session(administratie_id) as session:
            session.add(_observatie(administratie_id, bron="rlz_seed"))
        fake_client = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        assert _status(admin_engine, document_id) == "te_controleren"
        [reden] = _audit_redenen(admin_engine, document_id)
        assert "app-bevestigd" in reden

    def test_geen_geheugen_weigert(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        boeken_aan: None,
        optin_aan: None,
    ) -> None:
        fake_client = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        assert _status(admin_engine, document_id) == "te_controleren"
        [reden] = _audit_redenen(admin_engine, document_id)
        assert "geen voorstel" in reden

    def test_harde_check_blokkeert_autoboeken(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        boeken_aan: None,
        optin_aan: None,
        bevestigd_geheugen: None,
    ) -> None:
        # RLZ-side duplicaat: de fake geeft een bestaand document met dezelfde referentie terug.
        fake_client = FakeBoekClient(duplicaten=[{"id": str(uuid.uuid4())}])
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        assert _status(admin_engine, document_id) == "te_controleren"
        [reden] = _audit_redenen(admin_engine, document_id)
        assert "harde checks blokkeren" in reden and "Duplicaat" in reden

    def test_mogelijk_duplicaat_signaal_weigert(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        boeken_aan: None,
        optin_aan: None,
        bevestigd_geheugen: None,
    ) -> None:
        fake_client = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)
        eerste = _upload(administratie_id, gescoopte_gebruiker, opslag)
        assert _status(admin_engine, eerste) == "geboekt"
        # Zelfde bytes opnieuw → mogelijk-duplicaat-vlag → autoboeken weigert, mens beoordeelt.
        tweede = _upload(administratie_id, gescoopte_gebruiker, opslag)
        assert _status(admin_engine, tweede) == "te_controleren"
        [reden] = _audit_redenen(admin_engine, tweede)
        assert "mogelijk-duplicaat" in reden

    def test_volumerem_weigert(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        boeken_aan: None,
        optin_aan: None,
        bevestigd_geheugen: None,
    ) -> None:
        from app.config import settings

        monkeypatch.setattr(settings, "max_boekingen_per_dag_per_administratie", 0)
        fake_client = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        assert _status(admin_engine, document_id) != "geboekt"
        [reden] = _audit_redenen(admin_engine, document_id)
        assert "limiet" in reden.lower()

    def test_accordering_aan_weigert_direct_autoboeken(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        boeken_aan: None,
        optin_aan: None,
        bevestigd_geheugen: None,
    ) -> None:
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET accordering_ingeschakeld = true WHERE id = :id"),
                {"id": administratie_id},
            )
        fake_client = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        assert _status(admin_engine, document_id) != "geboekt"
        [reden] = _audit_redenen(admin_engine, document_id)
        assert "accordering" in reden.lower()

    def test_rlz_boekfout_zichtbaar_op_boeken_mislukt(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        boeken_aan: None,
        optin_aan: None,
        bevestigd_geheugen: None,
    ) -> None:
        fake_client = FakeBoekClient(faal_op="book")
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        assert _status(admin_engine, document_id) == "boeken_mislukt"
        [reden] = _audit_redenen(admin_engine, document_id)
        assert "boeken_mislukt" in reden
