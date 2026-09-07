"""Factuurperiode op weekniveau (blok 11 vervolgrun 07-09; vraag Peter: kosten op weekniveau voor project-
administraties — alleen de datalaag). (1) Pure normalisatie van de voorgelezen tekst naar ISO-weken (alle vormen,
onherkenbaar, jaar-afleiding met de factuurdatum als anker); (2) terugval = ISO-week van de factuurdatum mét eigen
herkomst; (3) prefill via het A10-pad — een periode uit de factuur triggert de autosave, de kolommen (0120) dragen de
stand; (4) de mens corrigeert via de PUT (`sla_boekvoorstel_op(periode=)`): afwijkend van de afleiding = `mens`
(wint, audit oud→nieuw), gelijk = automatisch; (5) een voorstel van vóór 0120 krijgt de afleiding live."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.config import settings
from app.db.session import scoped_session
from app.documenten import boekvoorstel, service
from app.documenten.models import Boekvoorstel
from app.documenten.periode import (
    HERKOMST_AFGELEID_FACTUURDATUM,
    HERKOMST_FACTUUR,
    HERKOMST_FACTUUR_MAAND,
    HERKOMST_MENS,
    HERKOMSTEN_UIT_FACTUUR,
    FactuurPeriode,
    OngeldigePeriode,
    bepaal_periode,
    label,
    maak_periode,
    normaliseer_periode,
    terugval_van_factuurdatum,
)
from app.documenten.storage import LokaleBestandsopslag
from app.extractie.service import AiFactuurExtractie, AiRegel, AiVeld

FACTUURDATUM = date(2026, 9, 1)  # ISO-week 36 van 2026
GB_ID = uuid.UUID("44444444-0000-0000-0000-000000004500")
BTW_ID = uuid.UUID("55555555-0000-0000-0000-000000000021")


# --- puur: normalisatie ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tekst", "verwacht"),
    [
        ("week 34", (2026, 34, 34, HERKOMST_FACTUUR)),
        ("wk 34", (2026, 34, 34, HERKOMST_FACTUUR)),
        ("wk. 34", (2026, 34, 34, HERKOMST_FACTUUR)),
        ("wk34", (2026, 34, 34, HERKOMST_FACTUUR)),
        ("Weeknummer 34", (2026, 34, 34, HERKOMST_FACTUUR)),
        ("W34", (2026, 34, 34, HERKOMST_FACTUUR)),
        ("wk 34-35", (2026, 34, 35, HERKOMST_FACTUUR)),
        ("week 34 t/m 35", (2026, 34, 35, HERKOMST_FACTUUR)),
        ("weken 34 en 35", (2026, 34, 35, HERKOMST_FACTUUR)),
        ("week 34 tot en met 35", (2026, 34, 35, HERKOMST_FACTUUR)),
        ("week 35-34", (2026, 34, 35, HERKOMST_FACTUUR)),  # omgekeerd bereik rechtgezet
        ("week 34 2026", (2026, 34, 34, HERKOMST_FACTUUR)),
        ("week 34 van 2026", (2026, 34, 34, HERKOMST_FACTUUR)),
        ("wk 34 (2026)", (2026, 34, 34, HERKOMST_FACTUUR)),
        ("week 34, 2026", (2026, 34, 34, HERKOMST_FACTUUR)),
        ("wk 34-35 2026", (2026, 34, 35, HERKOMST_FACTUUR)),
        ("34/2026", (2026, 34, 34, HERKOMST_FACTUUR)),
        ("34-35/2026", (2026, 34, 35, HERKOMST_FACTUUR)),
        ("2026-W34", (2026, 34, 34, HERKOMST_FACTUUR)),
        ("2026W34", (2026, 34, 34, HERKOMST_FACTUUR)),
        ("2026-W34-35", (2026, 34, 35, HERKOMST_FACTUUR)),
        ("W34 2026", (2026, 34, 34, HERKOMST_FACTUUR)),
        ("Periode: week 34", (2026, 34, 34, HERKOMST_FACTUUR)),  # label vóór de waarde
        ("18-08-2026 t/m 22-08-2026", (2026, 34, 34, HERKOMST_FACTUUR)),
        ("18/08/2026 - 22/08/2026", (2026, 34, 34, HERKOMST_FACTUUR)),
        ("2026-08-18 tot 2026-08-22", (2026, 34, 34, HERKOMST_FACTUUR)),
        ("18-08 t/m 22-08-2026", (2026, 34, 34, HERKOMST_FACTUUR)),  # begindatum zonder jaar → jaar einddatum
        ("17-08-2026 t/m 28-08-2026", (2026, 34, 35, HERKOMST_FACTUUR)),  # twee weken
        ("18-08-2026", (2026, 34, 34, HERKOMST_FACTUUR)),  # één datum → die week
        ("augustus 2026", (2026, 31, 36, HERKOMST_FACTUUR_MAAND)),
        ("aug. 2026", (2026, 31, 36, HERKOMST_FACTUUR_MAAND)),
        ("augustus", (2026, 31, 36, HERKOMST_FACTUUR_MAAND)),  # jaar → factuurjaar
        ("december 2025", (2025, 49, 52, HERKOMST_FACTUUR_MAAND)),  # 29–31 dec = 2026-W01 → gekapt
        ("januari 2027", (2027, 1, 4, HERKOMST_FACTUUR_MAAND)),  # 1–3 jan 2027 = 2026-W53 → begint op 1
        ("week 36", (2026, 36, 36, HERKOMST_FACTUUR)),  # gelijk aan de factuurweek: dit jaar
    ],
)
def test_normalisatie_herkent_alle_vormen(tekst: str, verwacht: tuple[int, int, int, str]) -> None:
    periode = normaliseer_periode(tekst, factuurdatum=FACTUURDATUM)
    assert periode is not None, tekst
    assert (periode.jaar, periode.week_van, periode.week_tot, periode.herkomst) == verwacht
    assert periode.tekst == " ".join(tekst.split())  # ruwe tekst blijft bewaard


@pytest.mark.parametrize("tekst", ["", "   ", None, "onzin", "week 0", "week 54", "week", "34-35", "week 53 2027", "maart 20"])
def test_onherkenbaar_is_none(tekst: str | None) -> None:
    # "34-35" zonder label of jaar is te ambigu (weken? datum?); week 53 bestaat niet in 2027 (52-wekenjaar).
    assert normaliseer_periode(tekst, factuurdatum=FACTUURDATUM) is None


class TestJaarAfleiding:
    def test_zonder_jaar_is_het_factuurjaar_het_anker(self) -> None:
        assert normaliseer_periode("week 34", factuurdatum=date(2025, 9, 1)).jaar == 2025

    def test_weeknummer_na_de_factuurweek_is_vorig_jaar(self) -> None:
        # Factuur van 5 januari 2026 (ISO-week 2) voor "week 52": dat kan alleen 2025 zijn.
        periode = normaliseer_periode("week 52", factuurdatum=date(2026, 1, 5))
        assert (periode.jaar, periode.week_van) == (2025, 52)
        # Een bereik neemt week_van als toets.
        periode = normaliseer_periode("wk 51-52", factuurdatum=date(2026, 1, 5))
        assert (periode.jaar, periode.week_van, periode.week_tot) == (2025, 51, 52)

    def test_maand_na_de_factuurmaand_is_vorig_jaar(self) -> None:
        periode = normaliseer_periode("december", factuurdatum=date(2026, 1, 5))
        assert (periode.jaar, periode.week_van, periode.week_tot) == (2025, 49, 52)

    def test_expliciet_jaar_wint_altijd(self) -> None:
        assert normaliseer_periode("week 52 2026", factuurdatum=date(2026, 1, 5)).jaar == 2026

    def test_zonder_factuurdatum_geldt_vandaag_als_anker(self) -> None:
        periode = normaliseer_periode("week 10", factuurdatum=None, vandaag=date(2026, 3, 30))  # week 14
        assert periode.jaar == 2026
        periode = normaliseer_periode("week 20", factuurdatum=None, vandaag=date(2026, 3, 30))
        assert periode.jaar == 2025


class TestDatumbereikOverJaargrens:
    def test_bereik_over_de_jaargrens_houdt_het_beginjaar_en_kapt_op_de_laatste_week(self) -> None:
        # 22-12-2025 (2025-W52) t/m 09-01-2026 (2026-W02): jaar 2025, weken 52–52 (week 1/2 van 2026 vallen weg —
        # de ruwe tekst blijft bewaard; beslispunt Peter).
        periode = normaliseer_periode("22-12-2025 t/m 09-01-2026", factuurdatum=date(2026, 1, 15))
        assert (periode.jaar, periode.week_van, periode.week_tot) == (2025, 52, 52)
        assert periode.tekst == "22-12-2025 t/m 09-01-2026"

    def test_bereik_dat_geheel_in_week_1_van_het_nieuwe_jaar_valt(self) -> None:
        periode = normaliseer_periode("29-12-2025 t/m 02-01-2026", factuurdatum=date(2026, 1, 15))
        assert (periode.jaar, periode.week_van, periode.week_tot) == (2026, 1, 1)


class TestTerugvalEnHulpen:
    def test_terugval_is_de_iso_week_van_de_factuurdatum_met_eigen_herkomst(self) -> None:
        periode = terugval_van_factuurdatum(FACTUURDATUM)
        assert periode == FactuurPeriode(2026, 36, 36, HERKOMST_AFGELEID_FACTUURDATUM, None)
        assert terugval_van_factuurdatum(None) is None
        # Onherkenbare tekst: terugval mét de ruwe tekst erbij (niets verdwijnt stil).
        periode = bepaal_periode("periode onbekend", factuurdatum=FACTUURDATUM)
        assert periode.herkomst == HERKOMST_AFGELEID_FACTUURDATUM and periode.tekst == "periode onbekend"
        assert bepaal_periode("week 34", factuurdatum=FACTUURDATUM).herkomst == HERKOMST_FACTUUR
        assert bepaal_periode(None, factuurdatum=None) is None

    def test_maak_periode_valideert(self) -> None:
        with pytest.raises(OngeldigePeriode):
            maak_periode(2027, 53, None, herkomst=HERKOMST_MENS, tekst=None)
        with pytest.raises(OngeldigePeriode):
            maak_periode(2026, 1, 1, herkomst="onzin", tekst=None)
        assert maak_periode(2026, 53, None, herkomst=HERKOMST_MENS, tekst=None).week_tot == 53  # 2026 heeft 53 weken

    def test_label_en_weken(self) -> None:
        assert label(FactuurPeriode(2026, 34, 34, HERKOMST_FACTUUR)) == "wk 34 · 2026"
        assert label(FactuurPeriode(2026, 34, 35, HERKOMST_FACTUUR)) == "wk 34–35 · 2026"
        assert FactuurPeriode(2026, 34, 36, HERKOMST_FACTUUR).weken == ((2026, 34), (2026, 35), (2026, 36))
        assert {HERKOMST_FACTUUR, HERKOMST_FACTUUR_MAAND} == HERKOMSTEN_UIT_FACTUUR


# --- via het boekvoorstel (DB): prefill + persist, mens wint, oud voorstel --------------------------------------


def _extractie(*, periode: str | None) -> AiFactuurExtractie:
    def veld(waarde: str | None, zekerheid: float = 0.93) -> AiVeld:
        return AiVeld(waarde=waarde, zekerheid=zekerheid)

    return AiFactuurExtractie(
        kop={
            "leverancier_naam": veld("Boot Steigers B.V."),
            "factuurnummer": veld("2026-0841"),
            "factuurdatum": veld(FACTUURDATUM.isoformat()),
            "valuta": veld("EUR"),
            "totaal_excl": veld("100.00"),
            "totaal_incl": veld("121.00"),
            "btw_bedrag": veld("21.00"),
            "periode": veld(periode, zekerheid=0.9 if periode else 0.0),
        },
        regels=[AiRegel(omschrijving="Steigerhuur", netto_bedrag="100.00", btw_bedrag="21.00", hoeveelheid="1", zekerheid=0.9)],
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


def _fake_extractie(monkeypatch: pytest.MonkeyPatch, extractie: AiFactuurExtractie) -> None:
    def _fake(pdf_bytes: bytes, *, client=None, verbruik_referentie=None, mail_context=None) -> AiFactuurExtractie:
        return extractie

    monkeypatch.setattr("app.extractie.service.extraheer_inkoopfactuur", _fake)


def _upload(administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag) -> uuid.UUID:
    return service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=f"factuur-{uuid.uuid4()}.pdf",
        inhoud=f"%PDF-1.4 {uuid.uuid4()}".encode(),
        actor_id=actor_id,
        opslag=opslag,
    ).document_id


def _open(administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID) -> tuple[bool, boekvoorstel.BoekvoorstelData]:
    geschreven = boekvoorstel.persisteer_prefill_bij_openen(
        administratie_id=administratie_id, document_id=document_id, geopend_door=actor_id
    )
    return geschreven, boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)


def _kolommen(administratie_id: uuid.UUID, document_id: uuid.UUID) -> tuple | None:
    with scoped_session(administratie_id) as session:
        rij = session.get(Boekvoorstel, document_id)
        if rij is None:
            return None
        return (rij.periode_jaar, rij.periode_week_van, rij.periode_week_tot, rij.periode_herkomst, rij.periode_tekst)


def _audit(admin_engine: Engine, document_id: uuid.UUID, actie: str) -> list[dict]:
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text(
                "SELECT oude_waarde, nieuwe_waarde FROM platform.audit_event "
                "WHERE record_id = :id AND actie = :actie ORDER BY tijdstip"
            ),
            {"id": document_id, "actie": actie},
        ).all()
    return [{"oude_waarde": r[0], "nieuwe_waarde": r[1]} for r in rijen]


def _mens_slaat_op(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    data: boekvoorstel.BoekvoorstelData,
    *,
    periode: tuple[int, int, int] | None,
) -> boekvoorstel.BoekvoorstelData:
    regels = boekvoorstel._effectieve_regels(data) if not data.opgeslagen else data.regels
    return boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        vendor_id=data.vendor_id,
        referentie=data.referentie,
        factuurdatum=data.factuurdatum,
        totaalbedrag=data.totaalbedrag,
        regels=[
            boekvoorstel.BoekvoorstelRegelData(
                ledger_id=GB_ID,
                taxrate_id=BTW_ID,
                project_id=None,
                netto_bedrag=r.netto_bedrag,
                btw_bedrag=r.btw_bedrag,
                omschrijving=r.omschrijving,
            )
            for r in regels
        ],
        periode=periode,
    )


class TestPrefillEnPersist:
    def test_periode_uit_de_factuur_wordt_bij_openen_gepersisteerd(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _fake_extractie(monkeypatch, _extractie(periode="Periode: week 34-35"))
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        with scoped_session(administratie_id) as session:
            veldvoorstel = boekvoorstel._laatste_veldvoorstel(session, document_id)
        assert veldvoorstel["periode_tekst"] == "Periode: week 34-35"  # ruw doorgegeven, normalisatie bij de prefill

        prefill = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert prefill.opgeslagen is False
        assert prefill.periode == FactuurPeriode(2026, 34, 35, HERKOMST_FACTUUR, "Periode: week 34-35")

        # Openen = persisteren (A10-pad): de periode uit de factuur is een trigger; de kolommen dragen de stand.
        geschreven, data = _open(administratie_id, document_id, gescoopte_gebruiker)
        assert geschreven is True and data.opgeslagen is True
        assert data.periode == FactuurPeriode(2026, 34, 35, HERKOMST_FACTUUR, "Periode: week 34-35")
        assert _kolommen(administratie_id, document_id) == (2026, 34, 35, HERKOMST_FACTUUR, "Periode: week 34-35")
        with scoped_session(administratie_id) as session:
            snapshot = boekvoorstel._laatste_prefill_snapshot(boekvoorstel._gebeurtenissen_van(session, document_id))
            detail = snapshot.detail[boekvoorstel.PREFILL_SNAPSHOT_SLEUTEL]
        assert "periode: factuur" in detail["triggers"]
        assert detail["kop"]["periode"] == {"jaar": 2026, "week_van": 34, "week_tot": 35, "herkomst": "factuur", "tekst": "Periode: week 34-35"}
        # Idempotent: opnieuw openen schrijft niets.
        assert _open(administratie_id, document_id, gescoopte_gebruiker)[0] is False

    def test_terugval_factuurdatum_persisteert_niet_bij_openen_maar_wel_bij_opslaan(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _fake_extractie(monkeypatch, _extractie(periode=None))
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        geschreven, prefill = _open(administratie_id, document_id, gescoopte_gebruiker)
        # AI-only prefill: de terugval is altijd live af te leiden en triggert de autosave niet (A10-beslispunt 1).
        assert geschreven is False and prefill.opgeslagen is False
        assert prefill.periode == FactuurPeriode(2026, 36, 36, HERKOMST_AFGELEID_FACTUURDATUM, None)

        # De mens slaat op zonder de periode aan te raken (periode=None, oude client): de afleiding wordt gepersisteerd,
        # zonder mens-audit (geen mens-handeling op de periode).
        data = _mens_slaat_op(administratie_id, document_id, gescoopte_gebruiker, prefill, periode=None)
        assert data.periode == FactuurPeriode(2026, 36, 36, HERKOMST_AFGELEID_FACTUURDATUM, None)
        assert _kolommen(administratie_id, document_id) == (2026, 36, 36, HERKOMST_AFGELEID_FACTUURDATUM, None)
        assert _audit(admin_engine, document_id, "boekvoorstel_periode_gewijzigd") == []


class TestMensWint:
    def test_correctie_wordt_mens_met_audit_en_wint_bij_heropenen_en_herextractie(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _fake_extractie(monkeypatch, _extractie(periode="week 34"))
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        _, data = _open(administratie_id, document_id, gescoopte_gebruiker)
        assert data.periode.herkomst == HERKOMST_FACTUUR

        # De mens corrigeert naar week 35: herkomst `mens`, ruwe factuurtekst blijft, audit oud→nieuw.
        na = _mens_slaat_op(administratie_id, document_id, gescoopte_gebruiker, data, periode=(2026, 35, 35))
        assert na.periode == FactuurPeriode(2026, 35, 35, HERKOMST_MENS, "week 34")
        (event,) = _audit(admin_engine, document_id, "boekvoorstel_periode_gewijzigd")
        assert event["oude_waarde"]["periode"]["herkomst"] == HERKOMST_FACTUUR
        assert event["oude_waarde"]["periode"]["week_van"] == 34
        assert event["nieuwe_waarde"]["periode"] == {"jaar": 2026, "week_van": 35, "week_tot": 35, "herkomst": "mens", "tekst": "week 34"}

        # Heropenen: nooit over de mens heen; de kopvelden gelden als aangeraakt (prefill_automatisch False).
        geschreven, opnieuw = _open(administratie_id, document_id, gescoopte_gebruiker)
        assert geschreven is False and opnieuw.periode.herkomst == HERKOMST_MENS and opnieuw.prefill_automatisch is False

        # Herhaald opslaan met dezelfde waarde (elke gedebouncede PUT) = geen nieuwe audit.
        _mens_slaat_op(administratie_id, document_id, gescoopte_gebruiker, opnieuw, periode=(2026, 35, 35))
        assert len(_audit(admin_engine, document_id, "boekvoorstel_periode_gewijzigd")) == 1
        # Opslaan zonder het veld (oude client/autoboeken): de mens-stand blijft.
        assert _mens_slaat_op(administratie_id, document_id, gescoopte_gebruiker, opnieuw, periode=None).periode.herkomst == HERKOMST_MENS

        # Terug naar exact de afleiding = weer automatisch (chip "uit factuur"), óók geaudit.
        terug = _mens_slaat_op(administratie_id, document_id, gescoopte_gebruiker, opnieuw, periode=(2026, 34, 34))
        assert terug.periode == FactuurPeriode(2026, 34, 34, HERKOMST_FACTUUR, "week 34")
        assert len(_audit(admin_engine, document_id, "boekvoorstel_periode_gewijzigd")) == 2

    def test_ongeldige_week_is_een_boekvoorstelfout(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _fake_extractie(monkeypatch, _extractie(periode="week 34"))
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        _, data = _open(administratie_id, document_id, gescoopte_gebruiker)
        with pytest.raises(boekvoorstel.BoekvoorstelFout, match="Ongeldige periode"):
            _mens_slaat_op(administratie_id, document_id, gescoopte_gebruiker, data, periode=(2027, 53, 53))


class TestVoorstelVanVoor0120:
    def test_lege_kolommen_krijgen_de_afleiding_live(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            vendor_id=None,
            referentie="F-1",
            factuurdatum=FACTUURDATUM,
            totaalbedrag=Decimal("121.00"),
            regels=[],
        )
        # Simuleer een voorstel van vóór de migratie: kolommen leeg.
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE boekhouding.boekvoorstel SET periode_jaar = NULL, periode_week_van = NULL, "
                    "periode_week_tot = NULL, periode_herkomst = NULL, periode_tekst = NULL WHERE document_id = :id"
                ),
                {"id": document_id},
            )
        gelezen = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert gelezen.opgeslagen is True
        assert gelezen.periode == FactuurPeriode(2026, 36, 36, HERKOMST_AFGELEID_FACTUURDATUM, None)
        assert _kolommen(administratie_id, document_id)[0] is None  # lezen persisteert niets
