"""Prefill-autosave bij het openen van het controlescherm (blok A10 07-09, opdracht Peter "stale check bij
geheugen-prefill, auto-first"): een 100 %-geheugenvoorstel toonde het grootboek gevuld terwijl de check
"grootboekrekening ontbreekt" zei, omdat het kop-niveau-geheugen alleen in de browser vulde en pas bij aanraken
werd opgeslagen. Sinds 07-09 (1) vult de server het leverancier-geheugen zelf in de prefill en (2) persisteert het
openen de prefill uit geheugen/template/default (`persisteer_prefill_bij_openen`, herkomst-snapshot in de tijdlijn):
checks en doorbelasten-blok zien wat de mens ziet; openen 2× persisteert niets opnieuw; een mens-waarde wordt nooit
overschreven; een verse extractie ná een onaangeraakte autosave leidt de prefill opnieuw af; AI-only prefills
blijven niet-opgeslagen. Regressiecasus: creditnota BOOT 202633199 (negatieve regel, geheugen 100 %)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import IntegrityError

from app.beheer import service as beheer_service
from app.config import settings
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import boekvoorstel, service
from app.documenten.models import Boekvoorstel, Document, DocumentGebeurtenis, DocumentStatus
from app.documenten.service import _schrijf_overgang
from app.documenten.storage import LokaleBestandsopslag
from app.doorbelasting import service as doorbelasting_service
from app.extractie.service import AiFactuurExtractie, AiRegel, AiVeld
from app.geheugen.models import BoekingObservatie
from app.security.tokens import create_access_token
from app.sync.models import TaxRateCache, VendorCache
from tests.sync.conftest import FakeRlzClient

VENDOR_BOOT = uuid.UUID("33333333-0000-0000-0000-00000000b007")
GB_KOSTEN = uuid.UUID("44444444-0000-0000-0000-000000004500")
GB_ANDERS = uuid.UUID("44444444-0000-0000-0000-000000004600")
HOOG_ID = uuid.UUID("55555555-0000-0000-0000-000000000021")
REFERENTIE_CREDITNOTA = "202633199"
OMSCHRIJVING = "Creditering retour steigermateriaal wk 34"


def _veld(waarde: str | None, zekerheid: float = 0.93) -> AiVeld:
    return AiVeld(waarde=waarde, zekerheid=zekerheid)


def _creditnota_extractie(*, netto: str = "-100.00", btw: str = "-21.00", incl: str = "-121.00") -> AiFactuurExtractie:
    """Creditnota BOOT 202633199: één NEGATIEVE regel, negatieve totalen — de scan leidt de btw-code gewoon af
    (−100 × 0,21 = −21, controle.leid_btw_af), het grootboek komt uit het leverancier-geheugen (100 %)."""
    return AiFactuurExtractie(
        kop={
            "leverancier_naam": _veld("BOOT"),
            "factuurnummer": _veld(REFERENTIE_CREDITNOTA),
            "factuurdatum": _veld("2026-08-28"),
            "vervaldatum": _veld(None, zekerheid=0.0),
            "valuta": _veld("EUR"),
            "totaal_excl": _veld(netto),
            "totaal_incl": _veld(incl),
            "btw_bedrag": _veld(btw),
        },
        regels=[
            AiRegel(omschrijving=OMSCHRIJVING, netto_bedrag=netto, btw_bedrag=btw, hoeveelheid="1", zekerheid=0.93)
        ],
        bsn_verwijderd=0,
        volledig=True,
    )


@pytest.fixture
def ai_gate_aan(administratie_id: uuid.UUID, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> None:
    beheer_service.zet_ai_extractie_ingeschakeld(
        actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
    )
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr("app.geheugen.regel_gb._client_voor", lambda *a, **k: None)


@pytest.fixture
def fake_extraheer(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake(pdf_bytes: bytes, *, client=None, verbruik_referentie=None, mail_context=None) -> AiFactuurExtractie:
        return _creditnota_extractie()

    monkeypatch.setattr("app.extractie.service.extraheer_inkoopfactuur", _fake)


@pytest.fixture
def stamgegevens(administratie_id: uuid.UUID) -> None:
    with scoped_session(administratie_id) as session:
        session.add(VendorCache(id=VENDOR_BOOT, administratie_id=administratie_id, naam="BOOT", brondata={}))
        session.add(
            TaxRateCache(
                id=HOOG_ID,
                administratie_id=administratie_id,
                naam="NL, Hoog Tarief",
                percentage=Decimal("0.2100"),
                brondata={},
            )
        )


@pytest.fixture
def geheugen_boot(administratie_id: uuid.UUID, stamgegevens: None) -> None:
    """Eén app-bevestigde observatie op leverancier-niveau = engine-voorstel 100 %, groen (chip "Geheugen 100%")."""
    with scoped_session(administratie_id) as session:
        session.add(
            BoekingObservatie(
                id=uuid.uuid4(),
                administratie_id=administratie_id,
                vendor_id=VENDOR_BOOT,
                regel_sleutel=None,
                gb_id=GB_KOSTEN,
                btw_id=HOOG_ID,
                project_id=None,
                bron="app",
                bron_datum=datetime.now(UTC).date(),
            )
        )


def _upload(administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag) -> uuid.UUID:
    return service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="boot-creditnota-202633199.pdf",
        inhoud=f"%PDF-1.4 {uuid.uuid4()}".encode(),
        actor_id=actor_id,
        opslag=opslag,
    ).document_id


def _open(
    administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID
) -> tuple[bool, boekvoorstel.BoekvoorstelData]:
    """Exact wat de GET-router doet bij het openen: eerst persisteren, dan lezen."""
    geschreven = boekvoorstel.persisteer_prefill_bij_openen(
        administratie_id=administratie_id, document_id=document_id, geopend_door=actor_id
    )
    return geschreven, boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)


def _snapshots(administratie_id: uuid.UUID, document_id: uuid.UUID) -> list[dict]:
    with scoped_session(administratie_id) as session:
        return [
            g.detail[boekvoorstel.PREFILL_SNAPSHOT_SLEUTEL]
            for g in session.scalars(
                select(DocumentGebeurtenis)
                .where(DocumentGebeurtenis.document_id == document_id)
                .order_by(DocumentGebeurtenis.tijdstip)
            )
            if g.detail and boekvoorstel.PREFILL_SNAPSHOT_SLEUTEL in g.detail
        ]


def _audit(admin_engine: Engine, document_id: uuid.UUID, actie: str) -> list[dict]:
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text(
                "SELECT actor_id, oude_waarde, nieuwe_waarde FROM platform.audit_event "
                "WHERE record_id = :id AND actie = :actie ORDER BY tijdstip"
            ),
            {"id": document_id, "actie": actie},
        ).all()
    return [{"actor_id": r[0], "oude_waarde": r[1], "nieuwe_waarde": r[2]} for r in rijen]


def _verplichte_velden(rapport) -> str:
    return next(r for r in rapport.resultaten if r.naam == "Verplichte velden").melding


def _mens_slaat_op(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    data: boekvoorstel.BoekvoorstelData,
    *,
    ledger_id: uuid.UUID,
    referentie: str | None = None,
) -> None:
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        vendor_id=data.vendor_id,
        referentie=referentie or data.referentie,
        factuurdatum=data.factuurdatum,
        totaalbedrag=data.totaalbedrag,
        regels=[
            boekvoorstel.BoekvoorstelRegelData(
                ledger_id=ledger_id,
                taxrate_id=r.taxrate_id,
                project_id=None,
                netto_bedrag=r.netto_bedrag,
                btw_bedrag=r.btw_bedrag,
                omschrijving=r.omschrijving,
            )
            for r in data.regels
        ],
    )


class TestCreditnotaBoot202633199:
    def test_geheugen_100pct_wordt_bij_openen_gepersisteerd_en_de_check_ontbreekt_zwijgt(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: None,
        geheugen_boot: None,
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)

        # Vóór het openen: de niet-opgeslagen prefill draagt het grootboek al server-side (stap 1 van de fix —
        # de checks zien dus ook zónder autosave hetzelfde als het scherm).
        prefill = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert prefill.opgeslagen is False and prefill.vendor_id == VENDOR_BOOT
        regels = boekvoorstel._effectieve_regels(prefill)
        assert len(regels) == 1
        assert regels[0].ledger_id == GB_KOSTEN and regels[0].netto_bedrag == Decimal("-100.00")
        assert regels[0].prefill_herkomst == {"grootboek": "leverancier_geheugen", "btw": "factuur"}
        assert regels[0].gb_bron is None  # kop-niveau-engine: de UI toont de GeheugenChipBlok op waarde-gelijkheid

        # Openen = persisteren (stap 2): het voorstel staat opgeslagen mét regel-id's, herkomst intact.
        geschreven, data = _open(administratie_id, document_id, gescoopte_gebruiker)
        assert geschreven is True
        assert data.opgeslagen is True and data.prefill_automatisch is True
        assert data.referentie == REFERENTIE_CREDITNOTA and data.totaalbedrag == Decimal("-121.00")
        (regel,) = data.regels
        assert regel.id is not None  # het doorbelasten-blok sleutelt hierop (bron_regel_id)
        assert regel.ledger_id == GB_KOSTEN and regel.taxrate_id == HOOG_ID
        assert regel.netto_bedrag == Decimal("-100.00") and regel.btw_bedrag == Decimal("-21.00")
        assert regel.btw_bron == "factuur"  # chip "uit factuur" hersteld uit het snapshot
        assert regel.prefill_herkomst == {"grootboek": "leverancier_geheugen", "btw": "factuur"}

        # De check "Verplichte velden" meldt geen ontbrekend grootboek meer.
        rapport = boekvoorstel.voer_checks_uit(
            administratie_id=administratie_id, document_id=document_id, client=FakeRlzClient({})
        )
        melding = _verplichte_velden(rapport)
        assert "grootboekrekening" not in melding and "btw-code" not in melding, melding
        assert next(r for r in rapport.resultaten if r.naam == "Verplichte velden").ok

        # Doorbelasten-blok: mét toggle aan wordt bij het openen de default-run klaargezet en de bron-regels
        # dragen id's — het blok kan direct verdelen, zonder eerst een veld aan te raken.
        beheer_service.zet_doorbelasting_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        run = doorbelasting_service.zet_run_default_klaar(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
        )
        assert run is not None and run.status == "klaargezet"

        # Tijdlijn: precies één notitie mét het snapshot; audit: één autosave-event onder de systeem-actor,
        # mét wie opende en de herkomst per regel (oud→nieuw).
        (snapshot,) = _snapshots(administratie_id, document_id)
        assert snapshot["geopend_door"] == str(gescoopte_gebruiker)
        assert "grootboek regel 1: leverancier_geheugen" in snapshot["triggers"]
        assert snapshot["regels"][0]["ledger_id"] == str(GB_KOSTEN)
        (event,) = _audit(admin_engine, document_id, "boekvoorstel_prefill_opgeslagen")
        assert event["actor_id"] == SYSTEEM_ACTOR_ID
        assert event["oude_waarde"] == {"opgeslagen": False}
        assert event["nieuwe_waarde"]["geopend_door"] == str(gescoopte_gebruiker)
        assert event["nieuwe_waarde"]["herkomst_per_regel"] == [
            {"volgnummer": 1, "grootboek": "leverancier_geheugen", "btw": "factuur"}
        ]
        # Geen gewoon "boekvoorstel_opgeslagen"-event: de autosave is geen menselijke opslag.
        assert _audit(admin_engine, document_id, "boekvoorstel_opgeslagen") == []

    def test_openen_tweemaal_persisteert_niet_opnieuw(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: None,
        geheugen_boot: None,
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        assert _open(administratie_id, document_id, gescoopte_gebruiker)[0] is True
        for _ in range(3):
            geschreven, data = _open(administratie_id, document_id, gescoopte_gebruiker)
            assert geschreven is False and data.prefill_automatisch is True
        assert len(_snapshots(administratie_id, document_id)) == 1
        assert len(_audit(admin_engine, document_id, "boekvoorstel_prefill_opgeslagen")) == 1

    def test_menselijke_wijziging_wint_en_verliest_de_herkomst_chip(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: None,
        geheugen_boot: None,
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        _, data = _open(administratie_id, document_id, gescoopte_gebruiker)
        # De controleur kiest een ander grootboek (de gewone PUT).
        _mens_slaat_op(administratie_id, document_id, gescoopte_gebruiker, data, ledger_id=GB_ANDERS)
        geschreven, opnieuw = _open(administratie_id, document_id, gescoopte_gebruiker)
        assert geschreven is False  # nooit over een mens heen
        (r2,) = opnieuw.regels
        assert r2.ledger_id == GB_ANDERS
        # Gewijzigd veld = geen herkomst meer; het ongewijzigde btw-veld houdt de zijne (herkomst is per veld).
        assert r2.gb_bron is None and r2.prefill_herkomst == {"btw": "factuur"}
        assert r2.btw_bron == "factuur"  # ongewijzigd veld houdt zijn chip
        assert opnieuw.prefill_automatisch is True  # kopvelden onaangeraakt → AI-kopchips mogen blijven

        # Wijzigt de mens een kopveld, dan is het voorstel niet meer "de automatische prefill".
        _mens_slaat_op(
            administratie_id, document_id, gescoopte_gebruiker, data, ledger_id=GB_ANDERS, referentie="CN-202633199"
        )
        _, derde = _open(administratie_id, document_id, gescoopte_gebruiker)
        assert derde.prefill_automatisch is False and derde.referentie == "CN-202633199"


class TestAutosavePoorten:
    def test_ai_only_prefill_blijft_niet_opgeslagen(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: None,
        stamgegevens: None,
    ) -> None:
        """Zonder geheugen/template/default is er niets deterministisch te persisteren: zoals voorheen."""
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        geschreven, data = _open(administratie_id, document_id, gescoopte_gebruiker)
        assert geschreven is False and data.opgeslagen is False and data.prefill_automatisch is False
        assert boekvoorstel._effectieve_regels(data)[0].ledger_id is None
        assert _snapshots(administratie_id, document_id) == []

    def test_zonder_veldvoorstel_wordt_niets_gepersisteerd(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        geheugen_boot: None,
    ) -> None:
        """AI-gate uit = geen extractie = geen veldvoorstel: een leeg voorstel persisteren zou een latere
        extractie stil verbergen."""
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        geschreven, data = _open(administratie_id, document_id, gescoopte_gebruiker)
        assert geschreven is False and data.opgeslagen is False and data.regels == []

    def test_niet_bewerkbare_status_persisteert_niets(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: None,
        geheugen_boot: None,
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            document = session.get(Document, document_id)
            assert document is not None
            _schrijf_overgang(session, document=document, naar=DocumentStatus.AFGEWEZEN, actor_id=gescoopte_gebruiker)
        geschreven, data = _open(administratie_id, document_id, gescoopte_gebruiker)
        assert geschreven is False and data.opgeslagen is False

    def test_verse_extractie_na_onaangeraakte_autosave_leidt_de_prefill_opnieuw_af(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: None,
        geheugen_boot: None,
    ) -> None:
        """"Opnieuw extraheren" ná het openen mag niet stil verdwijnen achter de autosave: zolang de mens niets
        aanraakte wint de verse extractie (nieuw snapshot); heeft de mens wél gewerkt, dan blijft zijn stand."""
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        assert _open(administratie_id, document_id, gescoopte_gebruiker)[0] is True

        def _nieuwe_extractie(incl: str) -> None:
            with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
                document = session.get(Document, document_id)
                assert document is not None
                oud = next(
                    g.detail["veldvoorstel"]
                    for g in reversed(boekvoorstel._gebeurtenissen_van(session, document_id))
                    if g.detail and "veldvoorstel" in g.detail
                )
                excl = str((Decimal(incl) / Decimal("1.21")).quantize(Decimal("0.01")))
                btw = str(Decimal(incl) - Decimal(excl))
                nieuw = {**oud, "totaal_incl": incl, "totaal_excl": excl, "btw_bedrag": btw}
                nieuw["regels"] = [{**oud["regels"][0], "netto_bedrag": excl, "btw_bedrag": btw}]
                session.add(
                    DocumentGebeurtenis(
                        document_id=document_id,
                        van_status=document.status,
                        naar_status=document.status,
                        actor_id=SYSTEEM_ACTOR_ID,
                        detail={"veldvoorstel": nieuw},
                    )
                )

        _nieuwe_extractie("-242.00")
        geschreven, data = _open(administratie_id, document_id, gescoopte_gebruiker)
        assert geschreven is True
        assert data.totaalbedrag == Decimal("-242.00") and data.prefill_automatisch is True
        assert data.regels[0].netto_bedrag == Decimal("-200.00") and data.regels[0].ledger_id == GB_KOSTEN
        assert len(_snapshots(administratie_id, document_id)) == 2
        events = _audit(admin_engine, document_id, "boekvoorstel_prefill_opgeslagen")
        assert len(events) == 2 and events[1]["oude_waarde"]["regels"][0]["netto_bedrag"] == "-100.00"

        # Mens raakt het voorstel aan → een nóg nieuwere extractie overschrijft niets meer.
        _mens_slaat_op(administratie_id, document_id, gescoopte_gebruiker, data, ledger_id=GB_ANDERS)
        _nieuwe_extractie("-363.00")
        geschreven, opnieuw = _open(administratie_id, document_id, gescoopte_gebruiker)
        assert geschreven is False
        assert opnieuw.totaalbedrag == Decimal("-242.00") and opnieuw.regels[0].ledger_id == GB_ANDERS

    def test_fout_in_de_autosave_blokkeert_het_openen_niet(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: None,
        geheugen_boot: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Parallelle GET (controlescherm + doorbelasten-blok) = PK-botsing; of een onverwachte fout: het openen
        werkt gewoon, het scherm toont dan de (server-side gevulde) niet-opgeslagen prefill."""
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)

        def _botst(**kwargs):
            raise IntegrityError("INSERT INTO boekhouding.boekvoorstel", {}, Exception("duplicate key"))

        monkeypatch.setattr(boekvoorstel, "sla_boekvoorstel_op", _botst)
        geschreven, data = _open(administratie_id, document_id, gescoopte_gebruiker)
        assert geschreven is False and data.opgeslagen is False
        assert boekvoorstel._effectieve_regels(data)[0].ledger_id == GB_KOSTEN
        with scoped_session(administratie_id) as session:
            assert session.get(Boekvoorstel, document_id) is None


def test_get_boekvoorstel_persisteert_bij_openen(
    gescoopte_gebruiker: uuid.UUID,
    administratie_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    ai_gate_aan: None,
    fake_extraheer: None,
    geheugen_boot: None,
) -> None:
    """De GET-router is de ingang van het controlescherm én van het doorbelasten-blok: ná één GET staan er
    regel-id's en `prefill_automatisch` in het antwoord."""
    from app.main import app  # lokaal: de app-import is zwaar en alleen hier nodig

    client = TestClient(app)
    document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
    headers = {"Authorization": f"Bearer {create_access_token(gescoopte_gebruiker, rol='boekhouding')}"}
    resp = client.get(f"/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["opgeslagen"] is True and body["prefill_automatisch"] is True
    assert body["regels"][0]["id"] is not None and body["regels"][0]["ledger_id"] == str(GB_KOSTEN)
    assert body["regels"][0]["btw_bron"] == "factuur"
    checks = client.post(
        f"/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel/checks", headers=headers
    )
    assert checks.status_code == 200, checks.text
    verplicht = next(r for r in checks.json()["resultaten"] if r["naam"] == "Verplichte velden")
    assert "grootboekrekening" not in verplicht["melding"]
