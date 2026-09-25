"""Blok 3 feedbackrun A 25-09 (FV-02): bronvolgorde voor het PROJECT — (1) factuur/werknummer (bestaand),
(2) klant-loze projectcode in de factuurtekst op het formaat van de administratie (uit de projectcache, nooit
hardcoded), (3) het leverancier-geheugen als LAATSTE bron, altijd zichtbaar (`project_bron` = "geheugen"); noemt de
factuur een ánder nummer dan het geheugen-project, dan wordt er niets ingevuld (`factuur_conflict`). Afgesloten/
inactieve projecten alleen bij een exacte verwijzing; meerduidig = niets; geen bron + geen geheugen + projectplicht =
leeg (harde check rood). Het autoboek-pad boekt nooit automatisch bij een factuur-conflict."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.config import settings
from app.db.session import scoped_session
from app.documenten import autoboeken, boeken, boekvoorstel, service
from app.documenten.storage import LokaleBestandsopslag
from app.extractie.service import AiFactuurExtractie, AiRegel, AiVeld
from app.geheugen.models import BoekingObservatie
from app.projecten import match as project_match
from app.projecten.models import LeverancierWerknummer
from app.sync.models import ProjectCache, TaxRateCache, VendorCache
from app.tijd import vandaag_nl
from tests.documenten.fake_rlz_client import FakeBoekClient

VENDOR_SPOT = uuid.UUID("33333333-0000-0000-0000-00000000570b")
HOOG_ID = uuid.UUID("55555555-0000-0000-0000-000000000022")
GB_KOSTEN = uuid.UUID("44444444-0000-0000-0000-000000004501")
P_TILBURG = uuid.UUID("aaaaaaaa-0000-0000-0000-000000126127")
P_KONING = uuid.UUID("aaaaaaaa-0000-0000-0000-000000126140")
P_LEGACY = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000105")
P_INACTIEF = uuid.UUID("aaaaaaaa-0000-0000-0000-000000125001")


def _veld(waarde: str | None, zekerheid: float = 0.93) -> AiVeld:
    return AiVeld(waarde=waarde, zekerheid=zekerheid)


class Scenario:
    kop_proj: str | None = None
    omschrijvingen: tuple[str, str] = ("Steigerhuur week 34", "Transport")
    volgnummer: int = 0


def _extractie() -> AiFactuurExtractie:
    regels = [
        AiRegel(
            omschrijving=Scenario.omschrijvingen[0],
            netto_bedrag="1000.00",
            btw_bedrag="210.00",
            hoeveelheid="1",
            zekerheid=0.93,
        ),
        AiRegel(
            omschrijving=Scenario.omschrijvingen[1],
            netto_bedrag="150.00",
            btw_bedrag="31.50",
            hoeveelheid="1",
            zekerheid=0.93,
        ),
    ]
    Scenario.volgnummer += 1
    return AiFactuurExtractie(
        kop={
            "leverancier_naam": _veld("Spot Services"),
            "factuurnummer": _veld(f"SSB-2026-{Scenario.volgnummer:04d}"),
            "factuurdatum": _veld("2026-08-28"),
            "valuta": _veld("EUR"),
            "totaal_excl": _veld("1150.00"),
            "totaal_incl": _veld("1391.50"),
            "btw_bedrag": _veld("241.50"),
            "project_tekst": _veld(Scenario.kop_proj, zekerheid=0.9 if Scenario.kop_proj else 0.0),
        },
        regels=regels,
        bsn_verwijderd=0,
        volledig=True,
    )


@pytest.fixture
def omgeving(administratie_id: uuid.UUID, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> None:
    Scenario.kop_proj = None
    Scenario.omschrijvingen = ("Steigerhuur week 34", "Transport")
    beheer_service.zet_ai_extractie_ingeschakeld(
        actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
    )
    beheer_service.zet_project_verplicht(actor_id=beheerder_id, administratie_id=administratie_id, verplicht=True)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr("app.geheugen.regel_gb._client_voor", lambda *a, **k: None)
    monkeypatch.setattr(
        "app.extractie.service.extraheer_inkoopfactuur",
        lambda pdf_bytes, *, client=None, verbruik_referentie=None, mail_context=None: _extractie(),
    )
    with scoped_session(administratie_id) as session:
        session.add(VendorCache(id=VENDOR_SPOT, administratie_id=administratie_id, naam="Spot Services", brondata={}))
        session.add(
            TaxRateCache(
                id=HOOG_ID,
                administratie_id=administratie_id,
                naam="NL, Hoog Tarief",
                percentage=Decimal("0.2100"),
                brondata={},
            )
        )
        for pid, naam, actief in (
            (P_TILBURG, "26127 Tilburg (Heijmans)", True),
            (P_KONING, "26140 Koningstraat (Confide)", True),
            (P_LEGACY, "105 Legacy werk (Oud)", True),
            (P_INACTIEF, "25001 Afgerond werk (Oud)", False),
        ):
            session.add(
                ProjectCache(id=pid, administratie_id=administratie_id, naam=naam, is_actief=actief, brondata={})
            )


def _geheugen(administratie_id: uuid.UUID, project_id: uuid.UUID, *, n: int = 2) -> None:
    """n app-observaties op leverancier-niveau mét dit project (groen + app-bevestigd)."""
    with scoped_session(administratie_id) as session:
        for i in range(n):
            session.add(
                BoekingObservatie(
                    id=uuid.uuid4(),
                    administratie_id=administratie_id,
                    vendor_id=VENDOR_SPOT,
                    regel_sleutel=None,
                    gb_id=GB_KOSTEN,
                    btw_id=HOOG_ID,
                    project_id=project_id,
                    bron="app",
                    bron_datum=vandaag_nl(),
                    boekstuk_ref=f"RLZ-04-0000{i}",
                )
            )


def _werknummer(administratie_id: uuid.UUID, actor_id: uuid.UUID, project_id: uuid.UUID, werknummer: str) -> None:
    with scoped_session(administratie_id) as session:
        session.add(
            LeverancierWerknummer(
                administratie_id=administratie_id,
                project_id=project_id,
                vendor_id=VENDOR_SPOT,
                werknummer=werknummer,
                bron="factuur",
                bevestigd=True,
                aangemaakt_door=actor_id,
            )
        )


def _upload(administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag) -> uuid.UUID:
    return service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=f"spot-{uuid.uuid4()}.pdf",
        inhoud=f"%PDF-1.4 {uuid.uuid4()}".encode(),
        actor_id=actor_id,
        opslag=opslag,
    ).document_id


def _prefill(administratie_id: uuid.UUID, document_id: uuid.UUID) -> boekvoorstel.BoekvoorstelData:
    return boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)


class TestFormaatUitDeCache:
    def test_formaat_afgeleid_uit_de_projectnamen_nooit_hardcoded(self) -> None:
        k = [
            project_match.ProjectKandidaat(uuid.uuid4(), "26127 Tilburg (Heijmans)"),
            project_match.ProjectKandidaat(uuid.uuid4(), "25001 Afgerond werk"),
            project_match.ProjectKandidaat(uuid.uuid4(), "105 Legacy werk"),
            project_match.ProjectKandidaat(uuid.uuid4(), "Afgesloten 26064 Apeldoorn"),
            project_match.ProjectKandidaat(uuid.uuid4(), "OVH Overhead"),
        ]
        f = project_match.ProjectcodeFormaat.uit_kandidaten(k)
        assert f.lengtes == frozenset({3, 5}) and f.jaar_prefixen == frozenset({"25", "26"})
        assert f.past("26140") and f.past("25999") and f.past("105")
        assert not f.past("2026") and not f.past("27001") and not f.past("1150") and not f.past("261400")
        assert f.nummers_in("huur 26140 en levering 26-08-2026, totaal 1.150,00 werk 105") == ("26140", "105")
        assert project_match.ProjectcodeFormaat.uit_kandidaten([]).leeg

    def test_tekstmotor_exact_meerduidig_en_leeg(self) -> None:
        a, b = uuid.uuid4(), uuid.uuid4()
        k = [
            project_match.ProjectKandidaat(a, "26127 Tilburg"),
            project_match.ProjectKandidaat(b, "26140 Koningstraat"),
        ]
        f = project_match.ProjectcodeFormaat.uit_kandidaten(k)
        assert project_match.bepaal_project_uit_tekst(f, k, "Steigerhuur 26140 Koningstraat").project_id == b
        m = project_match.bepaal_project_uit_tekst(f, k, "26127 en 26140")
        assert m.project_id is None and {x.id for x in m.meerduidig} == {a, b}
        assert project_match.bepaal_project_uit_tekst(f, k, "Steigerhuur week 34").herkomst is None
        assert project_match.factuur_noemt_ander_project(f, a, "werk 26140") == "26140"
        assert project_match.factuur_noemt_ander_project(f, a, "werk 26127") is None
        assert project_match.factuur_noemt_ander_project(f, a, "week 34") is None
        assert project_match.factuur_noemt_ander_project(f, None, "werk 26140") is None


class TestBronvolgorde:
    def test_werknummer_op_de_factuur_wint_van_het_geheugen(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        _geheugen(administratie_id, P_TILBURG)
        _werknummer(administratie_id, gescoopte_gebruiker, P_KONING, "SPOT-4711")
        Scenario.kop_proj = "SPOT-4711"
        p = _prefill(administratie_id, _upload(administratie_id, gescoopte_gebruiker, opslag))
        assert [r.project_id for r in p.regels] == [P_KONING, P_KONING]
        assert all(r.project_bron == "factuur" for r in p.regels)
        assert all((r.prefill_herkomst or {}).get("project") == "factuur" for r in p.regels)

    def test_klantloze_code_in_de_regeltekst_wint_van_het_geheugen(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        _geheugen(administratie_id, P_TILBURG)
        Scenario.omschrijvingen = ("Steigerhuur 26140 Koningstraat wk 34", "Levering werk 105")
        p = _prefill(administratie_id, _upload(administratie_id, gescoopte_gebruiker, opslag))
        assert [r.project_id for r in p.regels] == [P_KONING, P_LEGACY]
        assert all(r.project_bron == "factuur" for r in p.regels)
        assert "26140" in (p.regels[0].project_bron_detail or "") and "105" in (p.regels[1].project_bron_detail or "")

    def test_conflict_factuur_noemt_ander_nummer_dan_geheugen_vult_niets(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        _geheugen(administratie_id, P_TILBURG)
        Scenario.omschrijvingen = ("Steigerhuur werk 26999", "Transport")
        p = _prefill(administratie_id, _upload(administratie_id, gescoopte_gebruiker, opslag))
        conflict, gewoon = p.regels
        assert conflict.project_id is None and conflict.project_bron == "factuur_conflict"
        assert "26999" in (conflict.project_bron_detail or "")
        assert conflict.prefill_herkomst is None or "project" not in conflict.prefill_herkomst
        # De andere regel noemt niets → het geheugen vult 'm, zichtbaar.
        assert gewoon.project_id == P_TILBURG and gewoon.project_bron == "geheugen"

    def test_geen_bron_op_de_factuur_dan_geheugen_zichtbaar_als_voorstel_uit_historie(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        _geheugen(administratie_id, P_TILBURG)
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        p = _prefill(administratie_id, document_id)
        assert [r.project_id for r in p.regels] == [P_TILBURG, P_TILBURG]
        assert all(r.project_bron == "geheugen" for r in p.regels)
        assert all((r.prefill_herkomst or {}).get("project") == "leverancier_geheugen" for r in p.regels)
        assert "historie" in (p.regels[0].project_bron_detail or "")
        # Persistent bij openen (A10) mét herstelde chip uit het snapshot.
        boekvoorstel.persisteer_prefill_bij_openen(
            administratie_id=administratie_id, document_id=document_id, geopend_door=gescoopte_gebruiker
        )
        data = _prefill(administratie_id, document_id)
        assert data.opgeslagen is True and [r.project_bron for r in data.regels] == ["geheugen", "geheugen"]

    def test_geen_bron_en_geen_geheugen_bij_projectplicht_is_leeg_en_de_check_is_rood(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        p = _prefill(administratie_id, document_id)
        assert all(r.project_id is None and r.project_bron is None for r in p.regels)
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            vendor_id=VENDOR_SPOT,
            referentie=p.referentie,
            factuurdatum=p.factuurdatum,
            totaalbedrag=p.totaalbedrag,
            regels=[
                boekvoorstel.BoekvoorstelRegelData(
                    ledger_id=GB_KOSTEN,
                    taxrate_id=HOOG_ID,
                    project_id=None,
                    netto_bedrag=r.netto_bedrag,
                    btw_bedrag=r.btw_bedrag,
                    omschrijving=r.omschrijving,
                )
                for r in p.regels
            ],
            regels_samenvoegen=False,
        )
        rapport = boekvoorstel.voer_checks_uit(
            administratie_id=administratie_id, document_id=document_id, client=FakeBoekClient()
        )
        verplicht = next(r for r in rapport.resultaten if r.naam == "Verplichte velden")
        assert verplicht.ok is False and "project" in verplicht.melding.lower()

    def test_afgesloten_project_alleen_bij_exacte_verwijzing_op_de_factuur(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        # (a) de factuur verwijst expliciet → voorgesteld (het oranje signaal "project afgesloten" blijft de
        #     waarschuwing)
        Scenario.omschrijvingen = ("Nagekomen huur werk 25001", "Transport")
        p = _prefill(administratie_id, _upload(administratie_id, gescoopte_gebruiker, opslag))
        assert p.regels[0].project_id == P_INACTIEF and p.regels[0].project_bron == "factuur"
        # (b) alleen de historie wijst ernaar → niet voorgesteld, zichtbaar leeg
        _geheugen(administratie_id, P_INACTIEF)
        Scenario.omschrijvingen = ("Steigerhuur week 35", "Transport")
        p = _prefill(administratie_id, _upload(administratie_id, gescoopte_gebruiker, opslag))
        assert all(r.project_id is None and r.project_bron == "geheugen_afgesloten" for r in p.regels)

    def test_meerdere_nummers_op_een_regel_vult_niets(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        _geheugen(administratie_id, P_TILBURG)
        Scenario.omschrijvingen = ("Werk 26140 en 26127 gecombineerd", "Transport")
        p = _prefill(administratie_id, _upload(administratie_id, gescoopte_gebruiker, opslag))
        assert p.regels[0].project_id is None and p.regels[0].project_bron == "factuur_meerduidig"
        assert (
            "Koningstraat" in (p.regels[0].project_bron_detail or "") and "Tilburg" in p.regels[0].project_bron_detail
        )


class TestAutoboekConflict:
    def test_factuur_conflict_boekt_nooit_automatisch(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        omgeving: None,
    ) -> None:
        beheer_service.zet_boeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        autoboeken.zet_leverancier_autoboeken(
            administratie_id=administratie_id, vendor_id=VENDOR_SPOT, actor_id=beheerder_id, ingeschakeld=True
        )
        _geheugen(administratie_id, P_TILBURG, n=3)
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
        Scenario.omschrijvingen = ("Steigerhuur werk 26140", "Transport")
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        with admin_engine.connect() as conn:
            status = conn.execute(
                text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}
            ).scalar_one()
            redenen = (
                conn.execute(
                    text(
                        "SELECT nieuwe_waarde->>'reden' FROM platform.audit_event "
                        "WHERE actie = 'autoboeken_geweigerd' AND record_id = :id"
                    ),
                    {"id": document_id},
                )
                .scalars()
                .all()
            )
        assert status != "geboekt"
        assert any("26140" in r and "mens kiest" in r for r in redenen), redenen
