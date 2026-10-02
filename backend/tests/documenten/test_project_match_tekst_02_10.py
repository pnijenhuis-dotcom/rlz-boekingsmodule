"""Run D 02-10 blok B (casussen 29-09, screenshots Peter): projectmatch op plaats + opdrachtgever uit de HÉLE
factuurtekst, één project per document, werknummer in de volledige tekst.

- Hoogwerkservice: kop "500zzp - walterpark - hoogvliet / Weboma / Troubadourlaan Hoogvliet" → vóór 02-10 kreeg regel 1
  een project op fuzzy en regels 2–4 "voorstel uit historie" (25013 Deurne). Nu: niveau 3 deterministisch op
  document-niveau → álle regels 25170 Hoogvliet, Troubadourlaan (Weboma), ORANJE `factuur_plaats_opdrachtgever`; nooit
  per regel.
- Huvanco: zeven facturen mét hetzelfde werknummer in de betreft-regel (niet in `proj`) → factuur 1 leeg, de mens kiest
  en boekt (boeken = bevestiging, mapping `factuur`/bevestigd), facturen 2–7 groen `factuur`.
- Eén project per document: het kop-project geldt voor alle regels; alleen een regel met een eigen code/werknummer wijkt
  af.
- Meerdere kandidaten op niveau 3 = niets + `project_kandidaten` in de DTO; alleen plaats óf alleen opdrachtgever =
  niets.
- Autoboek-pad: een oranje project-voorstel boekt nooit automatisch (afwezig-pad-guard)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select, text

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

VENDOR = uuid.UUID("33333333-0000-0000-0000-000000000b02")
HOOG_ID = uuid.UUID("55555555-0000-0000-0000-000000000b22")
GB_KOSTEN = uuid.UUID("44444444-0000-0000-0000-000000004b01")
P_HOOGVLIET = uuid.UUID("aaaaaaaa-0000-0000-0000-000000025170")
P_DEURNE = uuid.UUID("aaaaaaaa-0000-0000-0000-000000025013")
P_TILBURG = uuid.UUID("aaaaaaaa-0000-0000-0000-000000026127")
P_TILBURG_NOORD = uuid.UUID("aaaaaaaa-0000-0000-0000-000000026141")
P_KONING = uuid.UUID("aaaaaaaa-0000-0000-0000-000000026140")

HOOGWERKSERVICE_BETREFT = "500zzp - walterpark - hoogvliet / Weboma / Troubadourlaan Hoogvliet"
HUVANCO_BETREFT = "Betreft: project 2025-0117 steigerwerk Rhoon"


def _veld(waarde: str | None, zekerheid: float = 0.93) -> AiVeld:
    return AiVeld(waarde=waarde, zekerheid=zekerheid)


class Scenario:
    leverancier: str = "Hoogwerkservice"
    kop_proj: str | None = None
    betreft: str | None = None
    omschrijvingen: tuple[str, ...] = ("Hoogwerker 18 m huur", "Transport heen", "Transport terug", "Brandstof")
    regel_proj: dict[int, str] = {}
    volgnummer: int = 0

    @classmethod
    def reset(cls) -> None:
        cls.leverancier = "Hoogwerkservice"
        cls.kop_proj = None
        cls.betreft = None
        cls.omschrijvingen = ("Hoogwerker 18 m huur", "Transport heen", "Transport terug", "Brandstof")
        cls.regel_proj = {}


def _extractie() -> AiFactuurExtractie:
    n = len(Scenario.omschrijvingen)
    regels = [
        AiRegel(
            omschrijving=oms,
            netto_bedrag="100.00",
            btw_bedrag="21.00",
            hoeveelheid="1",
            zekerheid=0.93,
            project_tekst=Scenario.regel_proj.get(i),
        )
        for i, oms in enumerate(Scenario.omschrijvingen)
    ]
    Scenario.volgnummer += 1
    return AiFactuurExtractie(
        kop={
            "leverancier_naam": _veld(Scenario.leverancier),
            "factuurnummer": _veld(f"HWS-2026-{Scenario.volgnummer:04d}"),
            "factuurdatum": _veld("2026-09-29"),
            "valuta": _veld("EUR"),
            "totaal_excl": _veld(f"{100 * n}.00"),
            "totaal_incl": _veld(f"{121 * n}.00"),
            "btw_bedrag": _veld(f"{21 * n}.00"),
            "betreft": _veld(Scenario.betreft, zekerheid=0.9 if Scenario.betreft else 0.0),
            "project_tekst": _veld(Scenario.kop_proj, zekerheid=0.9 if Scenario.kop_proj else 0.0),
        },
        regels=regels,
        bsn_verwijderd=0,
        volledig=True,
    )


@pytest.fixture
def omgeving(administratie_id: uuid.UUID, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> None:
    Scenario.reset()
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
        session.add(VendorCache(id=VENDOR, administratie_id=administratie_id, naam="Hoogwerkservice", brondata={}))
        session.add(
            TaxRateCache(
                id=HOOG_ID,
                administratie_id=administratie_id,
                naam="NL, Hoog Tarief",
                percentage=Decimal("0.2100"),
                brondata={},
            )
        )
        for pid, naam in (
            (P_HOOGVLIET, "25170 Hoogvliet, Troubadourlaan (Weboma)"),
            (P_DEURNE, "25013 Deurne (Van Wijnen)"),
            (P_TILBURG, "26127 Tilburg (Heijmans)"),
            (P_TILBURG_NOORD, "26141 Tilburg Noord (Heijmans)"),
            (P_KONING, "26140 Koningstraat (Confide)"),
        ):
            session.add(ProjectCache(id=pid, administratie_id=administratie_id, naam=naam, is_actief=True, brondata={}))


def _geheugen(administratie_id: uuid.UUID, project_id: uuid.UUID, *, n: int = 3) -> None:
    with scoped_session(administratie_id) as session:
        for i in range(n):
            session.add(
                BoekingObservatie(
                    id=uuid.uuid4(),
                    administratie_id=administratie_id,
                    vendor_id=VENDOR,
                    regel_sleutel=None,
                    gb_id=GB_KOSTEN,
                    btw_id=HOOG_ID,
                    project_id=project_id,
                    bron="app",
                    bron_datum=vandaag_nl(),
                    boekstuk_ref=f"RLZ-04-0001{i}",
                )
            )


def _upload(administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag) -> uuid.UUID:
    return service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=f"hws-{uuid.uuid4()}.pdf",
        inhoud=f"%PDF-1.4 {uuid.uuid4()}".encode(),
        actor_id=actor_id,
        opslag=opslag,
    ).document_id


def _prefill(administratie_id: uuid.UUID, document_id: uuid.UUID) -> boekvoorstel.BoekvoorstelData:
    return boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)


def _sla_op_met_project(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    data: boekvoorstel.BoekvoorstelData,
    project_id: uuid.UUID,
) -> None:
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        vendor_id=data.vendor_id,
        referentie=data.referentie,
        factuurdatum=data.factuurdatum,
        totaalbedrag=data.totaalbedrag,
        regels=[
            boekvoorstel.BoekvoorstelRegelData(
                ledger_id=GB_KOSTEN,
                taxrate_id=HOOG_ID,
                project_id=project_id,
                netto_bedrag=r.netto_bedrag,
                btw_bedrag=r.btw_bedrag,
                omschrijving=r.omschrijving,
            )
            for r in data.regels
        ],
        regels_samenvoegen=False,
    )


def _werknummers(administratie_id: uuid.UUID) -> list[LeverancierWerknummer]:
    with scoped_session(administratie_id) as session:
        rijen = session.scalars(select(LeverancierWerknummer).order_by(LeverancierWerknummer.werknummer)).all()
        session.expunge_all()
        return list(rijen)


class TestHoogwerkservicePlaatsOpdrachtgever:
    def test_alle_regels_een_project_op_plaats_plus_opdrachtgever_oranje(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        """Vóór 02-10: regel 1 → Hoogvliet (fuzzy), regels 2–4 → Deurne uit de historie. Nu: één project, oranje."""
        _geheugen(administratie_id, P_DEURNE)
        Scenario.betreft = HOOGWERKSERVICE_BETREFT
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        p = _prefill(administratie_id, document_id)
        assert [r.project_id for r in p.regels] == [P_HOOGVLIET] * 4
        assert all(r.project_bron == project_match.HERKOMST_FACTUUR_PLAATS_OPDRACHTGEVER for r in p.regels)
        assert all((r.prefill_herkomst or {}).get("project") == "factuur_plaats_opdrachtgever" for r in p.regels)
        detail = p.regels[0].project_bron_detail or ""
        assert "hoogvliet" in detail and "weboma" in detail and "25170" in detail
        assert all(r.project_kandidaten is None for r in p.regels)
        # Persistent bij openen (A10, oranje triggert óók) mét herstelde chip uit het snapshot.
        geschreven = boekvoorstel.persisteer_prefill_bij_openen(
            administratie_id=administratie_id, document_id=document_id, geopend_door=gescoopte_gebruiker
        )
        data = _prefill(administratie_id, document_id)
        assert geschreven is True and data.opgeslagen is True
        assert [r.project_id for r in data.regels] == [P_HOOGVLIET] * 4
        assert all(r.project_bron == "factuur_plaats_opdrachtgever" for r in data.regels)

    def test_alleen_plaats_of_alleen_opdrachtgever_vult_niets(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        Scenario.betreft = "Levering hoogwerker Hoogvliet"
        p = _prefill(administratie_id, _upload(administratie_id, gescoopte_gebruiker, opslag))
        assert all(r.project_id is None and r.project_bron is None for r in p.regels)
        Scenario.betreft = "Opdrachtgever Weboma"
        p = _prefill(administratie_id, _upload(administratie_id, gescoopte_gebruiker, opslag))
        assert all(r.project_id is None and r.project_bron is None for r in p.regels)

    def test_meerdere_kandidaten_vult_niets_en_draagt_de_kandidaten_in_de_dto(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        Scenario.betreft = "Steigerwerk Tilburg voor Heijmans"
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        p = _prefill(administratie_id, document_id)
        assert all(r.project_id is None and r.project_bron == "factuur_meerduidig" for r in p.regels)
        assert p.regels[0].project_kandidaten == [
            {"id": str(P_TILBURG), "naam": "26127 Tilburg (Heijmans)"},
            {"id": str(P_TILBURG_NOORD), "naam": "26141 Tilburg Noord (Heijmans)"},
        ]
        # Ná het persisteren komen chip én kandidaten terug zolang het veld leeg is.
        boekvoorstel.persisteer_prefill_bij_openen(
            administratie_id=administratie_id, document_id=document_id, geopend_door=gescoopte_gebruiker
        )
        data = _prefill(administratie_id, document_id)
        assert data.regels[0].project_bron == "factuur_meerduidig"
        assert data.regels[0].project_kandidaten is not None and len(data.regels[0].project_kandidaten) == 2

    def test_leveranciersnaam_is_nooit_een_match_token(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        """De afzender "Weboma Hoogvliet B.V." zou als tekst alle tokens dragen — de leveranciersnaam telt niet mee."""
        with scoped_session(administratie_id) as session:
            vendor = session.get(VendorCache, (VENDOR, administratie_id))
            assert vendor is not None
            vendor.naam = "Weboma Hoogvliet B.V."
        Scenario.leverancier = "Weboma Hoogvliet B.V."
        Scenario.betreft = "Factuur van Weboma Hoogvliet B.V. — huur hoogwerker"
        p = _prefill(administratie_id, _upload(administratie_id, gescoopte_gebruiker, opslag))
        assert p.vendor_id == VENDOR
        assert all(r.project_id is None for r in p.regels)


class TestEenProjectPerDocument:
    def test_kopproject_geldt_voor_alle_regels_behalve_een_regel_met_eigen_code(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        Scenario.betreft = HOOGWERKSERVICE_BETREFT
        Scenario.omschrijvingen = ("Hoogwerker 18 m huur", "Transport werk 26127", "Transport terug", "Brandstof")
        p = _prefill(administratie_id, _upload(administratie_id, gescoopte_gebruiker, opslag))
        assert [r.project_id for r in p.regels] == [P_HOOGVLIET, P_TILBURG, P_HOOGVLIET, P_HOOGVLIET]
        assert [r.project_bron for r in p.regels] == [
            "factuur_plaats_opdrachtgever",
            "factuur",
            "factuur_plaats_opdrachtgever",
            "factuur_plaats_opdrachtgever",
        ]

    def test_kop_code_geldt_voor_alle_regels_en_regel_werknummer_wijkt_af(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        with scoped_session(administratie_id) as session:
            session.add(
                LeverancierWerknummer(
                    administratie_id=administratie_id,
                    project_id=P_KONING,
                    vendor_id=VENDOR,
                    werknummer="HWS-77",
                    bron="factuur",
                    bevestigd=True,
                    aangemaakt_door=gescoopte_gebruiker,
                )
            )
        Scenario.kop_proj = "26127"
        Scenario.omschrijvingen = ("Hoogwerker 18 m huur", "Transport (HWS-77)", "Transport terug", "Brandstof")
        p = _prefill(administratie_id, _upload(administratie_id, gescoopte_gebruiker, opslag))
        assert [r.project_id for r in p.regels] == [P_TILBURG, P_KONING, P_TILBURG, P_TILBURG]
        assert all(r.project_bron == "factuur" for r in p.regels)

    def test_niveau3_nooit_per_regel(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        """Twee regels noemen elk een andere plaats + opdrachtgever: het document is dan meerduidig op niveau 3 — géén
        project per regel op plaats/opdrachtgever (dat was precies de Hoogwerkservice-fout)."""
        Scenario.omschrijvingen = ("Hoogwerker Hoogvliet (Weboma)", "Transport Deurne (Van Wijnen)")
        p = _prefill(administratie_id, _upload(administratie_id, gescoopte_gebruiker, opslag))
        assert all(r.project_id is None and r.project_bron == "factuur_meerduidig" for r in p.regels)
        assert {k["id"] for k in p.regels[0].project_kandidaten or []} == {str(P_HOOGVLIET), str(P_DEURNE)}


class TestHuvancoWerknummerInBetreft:
    def test_zeven_facturen_zelfde_werknummer_eerste_boeking_leert_de_rest_is_groen(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,
        omgeving: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        beheer_service.zet_boeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
        # De casus is van Huvanco; de crediteur in deze fixture heet Hoogwerkservice — de naam doet er niet toe, de
        # (leverancier, werknummer)-mapping wel.
        Scenario.betreft = HUVANCO_BETREFT  # werknummer alleen in de betreft-regel, géén `proj`
        Scenario.omschrijvingen = ("Steigerwerk week 38", "Transport")
        _geheugen(administratie_id, P_DEURNE)  # historie wijst ergens anders heen — vult niets (punt 4 02-10)

        doc1 = _upload(administratie_id, gescoopte_gebruiker, opslag)
        p1 = _prefill(administratie_id, doc1)
        assert all(r.project_id is None for r in p1.regels)
        assert all(r.project_bron == "geheugen" for r in p1.regels)  # zichtbaar, niet ingevuld
        # De mens kiest het project en boekt — boeken ís de bevestiging (app_bevestigd-patroon).
        _sla_op_met_project(administratie_id, doc1, gescoopte_gebruiker, p1, P_KONING)
        resultaat = boeken.boek_document(
            administratie_id=administratie_id, document_id=doc1, actor_id=gescoopte_gebruiker
        )
        assert resultaat.status.value == "geboekt"
        (rij,) = _werknummers(administratie_id)
        assert (rij.werknummer, rij.project_id, rij.bron, rij.bevestigd) == ("2025-0117", P_KONING, "factuur", True)

        # Facturen 2 t/m 7: zelfde werknummer in de betreft-regel → groen, zonder één klik.
        for _ in range(6):
            p = _prefill(administratie_id, _upload(administratie_id, gescoopte_gebruiker, opslag))
            assert [r.project_id for r in p.regels] == [P_KONING, P_KONING]
            assert all(r.project_bron == "factuur" for r in p.regels)
            assert "2025-0117" in (p.regels[0].project_bron_detail or "")
        with admin_engine.connect() as conn:
            acties = (
                conn.execute(
                    text("SELECT actie FROM platform.audit_event WHERE record_id = :id ORDER BY tijdstip"),
                    {"id": rij.id},
                )
                .scalars()
                .all()
            )
        assert acties == ["werknummer_geleerd_uit_factuur"]

    def test_onbevestigd_voorstel_uit_de_kantoormodule_is_oranje_tot_de_boeking(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        omgeving: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        beheer_service.zet_boeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
        with scoped_session(administratie_id) as session:
            session.add(
                LeverancierWerknummer(
                    administratie_id=administratie_id,
                    project_id=P_KONING,
                    vendor_id=VENDOR,
                    werknummer="2025-0117",
                    bron="factuur",
                    bevestigd=False,
                    aangemaakt_door=beheerder_id,
                )
            )
        Scenario.betreft = HUVANCO_BETREFT
        Scenario.omschrijvingen = ("Steigerwerk week 38", "Transport")
        doc = _upload(administratie_id, gescoopte_gebruiker, opslag)
        p = _prefill(administratie_id, doc)
        assert [r.project_id for r in p.regels] == [P_KONING, P_KONING]
        assert all(r.project_bron == "factuur_onbevestigd" for r in p.regels)
        _sla_op_met_project(administratie_id, doc, gescoopte_gebruiker, p, P_KONING)
        boeken.boek_document(administratie_id=administratie_id, document_id=doc, actor_id=gescoopte_gebruiker)
        (rij,) = _werknummers(administratie_id)
        assert rij.bevestigd is True
        p2 = _prefill(administratie_id, _upload(administratie_id, gescoopte_gebruiker, opslag))
        assert all(r.project_bron == "factuur" for r in p2.regels)


class TestAutoboekOranjeProjectWeigert:
    def test_plaats_opdrachtgever_voorstel_boekt_nooit_automatisch(
        self,
        monkeypatch: pytest.MonkeyPatch,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        omgeving: None,
    ) -> None:
        """Afwezig-pad-guard: alle harde velden uit het geheugen, projectplicht, autoboek aan — het ORANJE
        project-voorstel (plaats + opdrachtgever) is een voorstel voor een mens, dus weigeren mét reden (audit
        `autoboeken_geweigerd`)."""
        beheer_service.zet_boeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        autoboeken.zet_leverancier_autoboeken(
            administratie_id=administratie_id, vendor_id=VENDOR, actor_id=beheerder_id, ingeschakeld=True
        )
        _geheugen(administratie_id, P_HOOGVLIET, n=3)
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
        Scenario.betreft = HOOGWERKSERVICE_BETREFT
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
        assert any("factuur_plaats_opdrachtgever" in r and "mens bevestigt" in r for r in redenen), redenen
