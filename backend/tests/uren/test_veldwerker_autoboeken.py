"""Factuurmatch fase 4 — autoboek-slot per veldwerker-koppeling (besluit 4 Peter 2026-08-21,
bouwopdracht 22-08): opt-in Beheerder-only + default UIT, het slot vuurt uitsluitend bij een
GROENE match inclusief bedrag (tarief verplicht) bovenop álle bestaande poorten van het
inkoop-autoboekpad (app-bevestigd geheugen, harde checks, accorderingspoort, volumerem), met
'automatisch'-markering + audit en de staten-verrekening ín de boek-transactie. Twee triggers:
ná extractie én ná een weekstaat-goedkeuring die de match groen maakt."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import autoboeken, boeken
from app.documenten.storage import LokaleBestandsopslag
from app.geheugen.models import BoekingObservatie
from app.main import app
from app.security.tokens import create_access_token
from app.uren import service as uren_service
from app.uren.service import NietGevonden
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.uren.conftest import maak_gebruiker
from tests.uren.test_factuurmatch import koppel_crediteur, maak_goedgekeurde_staat
from tests.uren.test_factuurmatch_pipeline import maak_boekbare_factuur

client = TestClient(app)

GB_ID = uuid.UUID("44444444-4444-4444-4444-444444444442")
BTW_ID = uuid.UUID("55555555-5555-5555-5555-555555555552")


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


@pytest.fixture(autouse=True)
def _opslag_naar_tmp(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "document_opslag_basismap", str(tmp_path / "documenten"))


@pytest.fixture
def opslag(tmp_path) -> LokaleBestandsopslag:
    return LokaleBestandsopslag(tmp_path / "documenten")


@pytest.fixture
def boeken_aan(beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)


@pytest.fixture
def fake_rlz(monkeypatch: pytest.MonkeyPatch) -> FakeBoekClient:
    fake = FakeBoekClient()
    monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
    return fake


def _geheugen(administratie_id: uuid.UUID, vendor_id: uuid.UUID, *, bron: str = "app") -> None:
    """Twee observaties voor deze crediteur op regel-niveau ("Uren" — de regelomschrijving van
    maak_boekbare_factuur; btw op leverancier-fallback is per definitie oranje) — bron 'app' =
    groen én app-bevestigd; bron 'rlz_seed' = seed-only (blijft oranje, autoboekt dus nooit)."""
    from app.geheugen.normalisatie import normaliseer_regel_sleutel

    with scoped_session(administratie_id) as session:
        for _ in range(2):
            session.add(
                BoekingObservatie(
                    id=uuid.uuid4(),
                    administratie_id=administratie_id,
                    vendor_id=vendor_id,
                    regel_sleutel=normaliseer_regel_sleutel("Uren"),
                    gb_id=GB_ID,
                    btw_id=BTW_ID,
                    project_id=None,
                    bron=bron,
                    bron_datum=datetime.now(UTC).date(),
                )
            )


def _status(admin_engine: Engine, document_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}
        ).scalar_one()


def _weiger_redenen(admin_engine: Engine, document_id: uuid.UUID) -> list[str]:
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
    def test_zonder_koppeling_niet_te_zetten(self, administratie_id, zzper, beheerder_id):
        with pytest.raises(NietGevonden, match="crediteur-koppeling"):
            uren_service.zet_veldwerker_autoboeken(
                administratie_id=administratie_id, gebruiker_id=zzper, ingeschakeld=True, actor_id=beheerder_id
            )

    def test_zetten_audit_en_overzicht(self, administratie_id, gekoppelde_zzper, beheerder_id, admin_engine):
        koppel_crediteur(administratie_id, gekoppelde_zzper, uuid.uuid4(), beheerder_id, uurtarief="50")
        assert (
            uren_service.zet_veldwerker_autoboeken(
                administratie_id=administratie_id,
                gebruiker_id=gekoppelde_zzper,
                ingeschakeld=True,
                actor_id=beheerder_id,
            )
            is True
        )
        from app.uren import overzichten

        kaart = next(
            k for k in overzichten.veldgebruikers_overzicht(actor_id=beheerder_id) if k.gebruiker_id == gekoppelde_zzper
        )
        [koppeling] = kaart.crediteuren
        assert koppeling.autoboeken_ingeschakeld is True
        with admin_engine.connect() as conn:
            acties = conn.execute(
                text("SELECT count(*) FROM platform.audit_event WHERE actie = 'veldwerker_autoboeken_gewijzigd'")
            ).scalar_one()
        assert acties == 1

    def test_endpoint_is_beheerder_only(self, administratie_id, gekoppelde_zzper, beheerder_id, admin_engine):
        koppel_crediteur(administratie_id, gekoppelde_zzper, uuid.uuid4(), beheerder_id, uurtarief="50")
        payload = {
            "administratie_id": str(administratie_id),
            "gebruiker_id": str(gekoppelde_zzper),
            "ingeschakeld": True,
        }
        medewerker = maak_gebruiker(admin_engine, "boekhouding", "Geen Beheerder")
        resp = client.post(
            "/uren/beheer/veldwerkercrediteuren/autoboeken",
            json=payload,
            headers=_bearer(medewerker, rol="boekhouding"),
        )
        assert resp.status_code == 403
        resp = client.post(
            "/uren/beheer/veldwerkercrediteuren/autoboeken",
            json=payload,
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 204, resp.text


class TestAutoboekSlot:
    def _setup(
        self,
        administratie_id,
        project_id,
        zzper,
        uitvoerder,
        beheerder_id,
        opslag,
        *,
        netto: str,
        uurtarief: str | None = "50",
        met_staat: bool = True,
        opt_in: bool = True,
        geheugen_bron: str = "app",
    ) -> uuid.UUID:
        """Standaard-opstelling: getekende staat 16 u × € 50 (= € 800), koppeling + opt-in,
        app-bevestigd geheugen — het `netto`-bedrag bepaalt de matchuitkomst."""
        if met_staat:
            maak_goedgekeurde_staat(administratie_id, zzper, project_id, uitvoerder)
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, zzper, vendor_id, beheerder_id, uurtarief=uurtarief)
        if opt_in:
            uren_service.zet_veldwerker_autoboeken(
                administratie_id=administratie_id, gebruiker_id=zzper, ingeschakeld=True, actor_id=beheerder_id
            )
        _geheugen(administratie_id, vendor_id, bron=geheugen_bron)
        return maak_boekbare_factuur(administratie_id, beheerder_id, opslag, vendor_id, nettos=(netto,))

    def test_groene_match_boekt_automatisch_met_markering_en_verrekening(
        self,
        administratie_id,
        project_id,
        gekoppelde_zzper,
        gekoppelde_uitvoerder,
        beheerder_id,
        opslag,
        boeken_aan,
        fake_rlz,
        admin_engine,
    ):
        document_id = self._setup(
            administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag,
            netto="800.00",
        )
        besluit = autoboeken.probeer_autoboeken_na_extractie(
            administratie_id=administratie_id, document_id=document_id
        )
        assert besluit is not None and besluit.geboekt is True
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
            assert detail["bron"] == "veldwerker_opt_in"
            assert str(actor) == str(SYSTEEM_ACTOR_ID)
            audit_bron = conn.execute(
                text(
                    "SELECT nieuwe_waarde->>'bron' FROM platform.audit_event "
                    "WHERE actie = 'automatisch_geboekt' AND record_id = :id"
                ),
                {"id": document_id},
            ).scalar_one()
            assert audit_bron == "veldwerker_opt_in"
            verrekend = conn.execute(
                text("SELECT count(*) FROM boekhouding.weekstaat WHERE verrekend_met_document_id = :id"),
                {"id": document_id},
            ).scalar_one()
        assert verrekend == 1

    def test_afwijking_autoboekt_nooit(
        self,
        administratie_id,
        project_id,
        gekoppelde_zzper,
        gekoppelde_uitvoerder,
        beheerder_id,
        opslag,
        boeken_aan,
        fake_rlz,
        admin_engine,
    ):
        document_id = self._setup(
            administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag,
            netto="900.00",  # 16 u × € 50 = € 800 → afwijking van € 100
        )
        besluit = autoboeken.probeer_autoboeken_na_extractie(
            administratie_id=administratie_id, document_id=document_id
        )
        assert besluit is not None and besluit.geboekt is False
        assert _status(admin_engine, document_id) == "te_controleren"
        assert any("urenmatch niet groen" in r for r in _weiger_redenen(admin_engine, document_id))
        assert not fake_rlz.puts  # geweigerd vóór enige RLZ-schrijfactie

    def test_zonder_tarief_niet_toetsbaar_autoboekt_nooit(
        self,
        administratie_id,
        project_id,
        gekoppelde_zzper,
        gekoppelde_uitvoerder,
        beheerder_id,
        opslag,
        boeken_aan,
        fake_rlz,
        admin_engine,
    ):
        """Besluit 2/4: het slot is strikt groen INCLUSIEF bedrag — zonder tarief is het bedrag
        niet toetsbaar (match_alleen_uren/niet_toetsbaar) en blijft het mensenwerk."""
        document_id = self._setup(
            administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag,
            netto="800.00", uurtarief=None,
        )
        besluit = autoboeken.probeer_autoboeken_na_extractie(
            administratie_id=administratie_id, document_id=document_id
        )
        assert besluit is not None and besluit.geboekt is False
        assert _status(admin_engine, document_id) == "te_controleren"

    def test_match_zonder_staten_autoboekt_nooit(
        self,
        administratie_id,
        project_id,
        gekoppelde_zzper,
        gekoppelde_uitvoerder,
        beheerder_id,
        opslag,
        boeken_aan,
        fake_rlz,
        admin_engine,
    ):
        """Randgeval: € 0-factuur zonder getekende staten telt als 'bedrag klopt' (0 = 0) maar
        er valt niets te verrekenen — geen autoboek."""
        document_id = self._setup(
            administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag,
            netto="0.00", met_staat=False,
        )
        besluit = autoboeken.probeer_autoboeken_na_extractie(
            administratie_id=administratie_id, document_id=document_id
        )
        assert besluit is not None and besluit.geboekt is False
        assert any("zonder getekende weekstaten" in r for r in _weiger_redenen(admin_engine, document_id))

    def test_opt_in_uit_doet_niets(
        self,
        administratie_id,
        project_id,
        gekoppelde_zzper,
        gekoppelde_uitvoerder,
        beheerder_id,
        opslag,
        boeken_aan,
        fake_rlz,
        admin_engine,
    ):
        """Default UIT (besluit 4): koppeling zónder opt-in = geen poging, geen audit-ruis."""
        document_id = self._setup(
            administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag,
            netto="800.00", opt_in=False,
        )
        assert (
            autoboeken.probeer_autoboeken_na_extractie(administratie_id=administratie_id, document_id=document_id)
            is None
        )
        assert _status(admin_engine, document_id) == "te_controleren"
        assert _weiger_redenen(admin_engine, document_id) == []

    def test_seed_only_geheugen_weigert(
        self,
        administratie_id,
        project_id,
        gekoppelde_zzper,
        gekoppelde_uitvoerder,
        beheerder_id,
        opslag,
        boeken_aan,
        fake_rlz,
        admin_engine,
    ):
        """De bestaande inkoop-autoboekpoorten gelden onverkort: seed-only geheugen (alleen
        RLZ-historie) blijft oranje en boekt nooit automatisch — óók niet bij een groene match."""
        document_id = self._setup(
            administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag,
            netto="800.00", geheugen_bron="rlz_seed",
        )
        besluit = autoboeken.probeer_autoboeken_na_extractie(
            administratie_id=administratie_id, document_id=document_id
        )
        assert besluit is not None and besluit.geboekt is False
        assert _status(admin_engine, document_id) == "te_controleren"
        assert any("app-bevestigd" in r for r in _weiger_redenen(admin_engine, document_id))

    def test_accorderingspoort_geldt_onverkort(
        self,
        administratie_id,
        project_id,
        gekoppelde_zzper,
        gekoppelde_uitvoerder,
        beheerder_id,
        opslag,
        boeken_aan,
        fake_rlz,
        admin_engine,
    ):
        document_id = self._setup(
            administratie_id, project_id, gekoppelde_zzper, gekoppelde_uitvoerder, beheerder_id, opslag,
            netto="800.00",
        )
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET accordering_ingeschakeld = true WHERE id = :id"),
                {"id": administratie_id},
            )
        besluit = autoboeken.probeer_autoboeken_na_extractie(
            administratie_id=administratie_id, document_id=document_id
        )
        assert besluit is not None and besluit.geboekt is False
        assert _status(admin_engine, document_id) == "te_controleren"


class TestTriggerNaWeekstaatGoedkeuring:
    def test_goedkeuring_maakt_match_groen_en_boekt_automatisch(
        self,
        administratie_id,
        project_id,
        gekoppelde_zzper,
        gekoppelde_uitvoerder,
        beheerder_id,
        opslag,
        boeken_aan,
        fake_rlz,
        admin_engine,
    ):
        """De ZZP-factuur ligt er vaak eerder dan de goedgekeurde week: bij binnenkomst is de
        match een afwijking (0 staten-uren), ná keur_week_goed wordt hij groen en vuurt het
        autoboek-slot direct — geen aparte cron of mensklik nodig."""
        vendor_id = uuid.uuid4()
        koppel_crediteur(administratie_id, gekoppelde_zzper, vendor_id, beheerder_id, uurtarief="50")
        uren_service.zet_veldwerker_autoboeken(
            administratie_id=administratie_id, gebruiker_id=gekoppelde_zzper, ingeschakeld=True, actor_id=beheerder_id
        )
        _geheugen(administratie_id, vendor_id)
        document_id = maak_boekbare_factuur(administratie_id, beheerder_id, opslag, vendor_id, nettos=("800.00",))
        assert _status(admin_engine, document_id) == "te_controleren"  # afwijking — nog geen staat

        maak_goedgekeurde_staat(administratie_id, gekoppelde_zzper, project_id, gekoppelde_uitvoerder)

        assert _status(admin_engine, document_id) == "geboekt"
        with admin_engine.connect() as conn:
            detail = conn.execute(
                text(
                    "SELECT detail FROM boekhouding.document_gebeurtenis "
                    "WHERE document_id = :id AND naar_status = 'geboekt'"
                ),
                {"id": document_id},
            ).scalar_one()
        assert detail["bron"] == "veldwerker_opt_in"
