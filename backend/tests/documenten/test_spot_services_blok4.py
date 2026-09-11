"""Blok 4 (bundel 08-09) — controlescherm Spot Services 2026-608 door de keten (upload → gestubde extractie → prefill →
openen/autosave → boeken): 4a nulregels geen boekingsregels (bron compleet, regelsom klopt), 4b het ene projectnummer
op regel 1 vult álle regels, 4c "btw verlegd" → verlegd-tarief oranje en wint van de administratie-default; geheugen
wint van verlegd; meerduidig verlegd = leeg; EU-verlegd telt niet mee."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.beheer import btw_default
from app.beheer import service as beheer_service
from app.config import settings
from app.db.session import scoped_session
from app.documenten import boekvoorstel, service
from app.documenten.models import DocumentGebeurtenis
from app.documenten.regel_prefill import BTW_BRON_FACTUUR_VERLEGD, verlegd_taxrate_voor
from app.documenten.storage import LokaleBestandsopslag
from app.geheugen.models import BoekingObservatie
from app.sync.models import ProjectCache, TaxRateCache, VendorCache
from app.tijd import vandaag_nl
from tests.extractie.test_nulregels_spot_services import spot_services_extractie

VENDOR_SPOT = uuid.UUID("33333333-0000-0000-0000-00000000570b")
HOOG_ID = uuid.UUID("55555555-0000-0000-0000-000000000021")
NUL_ID = uuid.UUID("55555555-0000-0000-0000-000000000000")
VERLEGD_HOOG_ID = uuid.UUID("55555555-0000-0000-0000-000000000009")
VERLEGD_LAAG_ID = uuid.UUID("55555555-0000-0000-0000-000000000010")
VERLEGD_EU_ID = uuid.UUID("55555555-0000-0000-0000-000000000011")
GB_ID = uuid.UUID("44444444-0000-0000-0000-000000007006")
P_26049 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000026049")
P_ANDER = uuid.UUID("aaaaaaaa-0000-0000-0000-000000026050")


class Scenario:
    kop_proj: str | None = None
    regel1_proj: str | None = "26049"
    volgnummer: int = 0


def _extractie():
    Scenario.volgnummer += 1
    extractie = spot_services_extractie(kop_proj=Scenario.kop_proj, regel1_proj=Scenario.regel1_proj)
    extractie.kop["factuurnummer"] = type(extractie.kop["factuurnummer"])(
        waarde=f"2026-608-{Scenario.volgnummer}", zekerheid=0.93
    )
    return extractie


def _taxrate(id_: uuid.UUID, naam: str, *, verlegd: bool = False, favoriet: bool = False) -> TaxRateCache:
    return TaxRateCache(
        id=id_,
        administratie_id=None,  # gezet in de fixture
        naam=naam,
        percentage=Decimal("0.2100") if "Hoog Tarief" in naam else Decimal("0"),
        brondata={"IsRelayed": verlegd, "IsFavorite": favoriet},
    )


@pytest.fixture
def omgeving(administratie_id: uuid.UUID, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> None:
    """AI-gate aan, projectplicht aan, crediteur + tarieven (hoog, nul, NL verlegd hoog) + twee projecten."""
    Scenario.kop_proj = None
    Scenario.regel1_proj = "26049"
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
        for rij in (
            _taxrate(HOOG_ID, "NL, Hoog Tarief", favoriet=True),
            _taxrate(NUL_ID, "NL, Nul tarief"),
            _taxrate(VERLEGD_HOOG_ID, "NL, BTW verlegd (hoog)", verlegd=True),
        ):
            rij.administratie_id = administratie_id
            session.add(rij)
        for pid, naam in ((P_26049, "26049 Hoofddorp (Dura Vermeer)"), (P_ANDER, "26050 Almere (BAM)")):
            session.add(ProjectCache(id=pid, administratie_id=administratie_id, naam=naam, is_actief=True, brondata={}))


def _voeg_tarief_toe(administratie_id: uuid.UUID, rij: TaxRateCache) -> None:
    with scoped_session(administratie_id) as session:
        rij.administratie_id = administratie_id
        session.add(rij)


def _upload(administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag) -> uuid.UUID:
    return service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=f"spot-608-{uuid.uuid4()}.pdf",
        inhoud=f"%PDF-1.4 {uuid.uuid4()}".encode(),
        actor_id=actor_id,
        opslag=opslag,
    ).document_id


def _prefill(administratie_id: uuid.UUID, document_id: uuid.UUID) -> boekvoorstel.BoekvoorstelData:
    return boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)


def _veldvoorstel(administratie_id: uuid.UUID, document_id: uuid.UUID) -> dict:
    with scoped_session(administratie_id) as session:
        vv = boekvoorstel._laatste_veldvoorstel(session, document_id)
    assert vv is not None
    return vv


class TestNulregels4a:
    def test_drie_boekingsregels_bron_twaalf_regelsom_klopt(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        data = _prefill(administratie_id, document_id)
        assert data.vendor_id == VENDOR_SPOT
        assert [r.omschrijving for r in data.regels] == [
            "Inhuur montage steiger week 35",
            "Inhuur demontage steiger week 35",
            "Transport materieel",
        ]
        assert sum((r.netto_bedrag or Decimal(0)) for r in data.regels) == Decimal("4320.00") == data.totaalbedrag
        # De bron blijft compleet: 12 gelezen regels, 9 gemarkeerd — voor tariefkaart/self-billing.
        vv = _veldvoorstel(administratie_id, document_id)
        assert len(vv["regels"]) == 12 and vv["tariefstaffel_aantal"] == 9
        # Kop-omschrijving: meerdere echte regels, geen betreft → leverancier + factuurnummer (blok 9-regel).
        assert data.omschrijving and data.omschrijving.startswith("Spot Services")

    def test_regeltelling_check_groen_na_het_filter(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        rapport = boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_id)
        per_naam = {r.naam: r for r in rapport.resultaten}
        regeltelling = per_naam["Regeltelling vs totaal"]
        assert regeltelling.ok, regeltelling.melding
        # Verplichte velden: geaggregeerd per veld over de 3 (niet 12) regels.
        verplicht = per_naam["Verplichte velden"]
        assert not verplicht.ok
        assert "grootboekrekening (alle 3 regels)" in verplicht.melding
        assert "project" not in verplicht.melding  # 26049 staat op alle drie de regels


class TestProject4b:
    def test_projectnummer_op_regel_1_vult_alle_drie_regels_groen(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        data = _prefill(administratie_id, document_id)
        assert [r.project_id for r in data.regels] == [P_26049, P_26049, P_26049]
        assert all(r.project_bron == "factuur" for r in data.regels)
        # Openen persisteert (project uit de factuur triggert de A10-autosave) — de checks zien hetzelfde project.
        geschreven = boekvoorstel.persisteer_prefill_bij_openen(
            administratie_id=administratie_id, document_id=document_id, geopend_door=gescoopte_gebruiker
        )
        assert geschreven is True
        data = _prefill(administratie_id, document_id)
        assert data.opgeslagen and [r.project_id for r in data.regels] == [P_26049, P_26049, P_26049]
        assert [r.project_bron for r in data.regels] == ["factuur"] * 3

    def test_regel_met_eigen_afwijkend_nummer_houdt_dat(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        # Kop noemt 26049, regel 1 noemt 26050 → regel 1 = 26050, de rest = kop.
        Scenario.kop_proj = "26049"
        Scenario.regel1_proj = "26050"
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        data = _prefill(administratie_id, document_id)
        assert [r.project_id for r in data.regels] == [P_ANDER, P_26049, P_26049]


class TestBtwVerlegd4c:
    def test_verlegd_vermelding_geeft_verlegd_tarief_oranje_op_alle_regels(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        data = _prefill(administratie_id, document_id)
        assert data.btw_verlegd_vermelding == "BTW verlegd"
        assert [r.taxrate_id for r in data.regels] == [VERLEGD_HOOG_ID] * 3
        assert all(r.btw_bron == BTW_BRON_FACTUUR_VERLEGD for r in data.regels)
        assert all((r.prefill_herkomst or {}).get("btw") == BTW_BRON_FACTUUR_VERLEGD for r in data.regels)

    def test_verlegd_wint_van_administratie_default_0pct(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        omgeving: None,
    ) -> None:
        """De productie-stand Universal (screenshot): default = "0 % · NL" → tot 08-09 kregen de regels de default mét
        chip "standaard administratie". Nu wint de verleggings-vermelding op de factuur."""
        btw_default.zet_btw_default(actor_id=beheerder_id, administratie_id=administratie_id, taxrate_id=NUL_ID)
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        data = _prefill(administratie_id, document_id)
        assert [r.taxrate_id for r in data.regels] == [VERLEGD_HOOG_ID] * 3
        assert all(r.btw_bron == BTW_BRON_FACTUUR_VERLEGD for r in data.regels)

    def test_leverancier_geheugen_wint_van_verlegd(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        with scoped_session(administratie_id) as session:
            session.add(
                BoekingObservatie(
                    id=uuid.uuid4(),
                    administratie_id=administratie_id,
                    vendor_id=VENDOR_SPOT,
                    regel_sleutel=None,
                    gb_id=GB_ID,
                    btw_id=NUL_ID,
                    project_id=None,
                    bron="app",
                    bron_datum=vandaag_nl(),
                )
            )
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        data = _prefill(administratie_id, document_id)
        assert [r.taxrate_id for r in data.regels] == [NUL_ID] * 3
        assert all(r.btw_bron is None for r in data.regels)  # geheugen: GeheugenChipBlok op waarde-gelijkheid

    def test_hoog_en_laag_verlegd_zonder_favoriet_is_meerduidig_leeg(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        _voeg_tarief_toe(administratie_id, _taxrate(VERLEGD_LAAG_ID, "NL, BTW verlegd (laag)", verlegd=True))
        with scoped_session(administratie_id) as session:
            assert verlegd_taxrate_voor(session, administratie_id=administratie_id) is None
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        data = _prefill(administratie_id, document_id)
        assert all(r.taxrate_id is None and r.btw_bron is None for r in data.regels)  # de mens kiest; hint-chip blijft
        assert all(r.btw_bewust_leeg for r in data.regels[:2])

    def test_favoriet_beslist_bij_hoog_en_laag(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        _voeg_tarief_toe(
            administratie_id, _taxrate(VERLEGD_LAAG_ID, "NL, BTW verlegd (laag)", verlegd=True, favoriet=True)
        )
        with scoped_session(administratie_id) as session:
            assert verlegd_taxrate_voor(session, administratie_id=administratie_id) == VERLEGD_LAAG_ID

    def test_eu_verlegd_telt_niet_mee(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        _voeg_tarief_toe(administratie_id, _taxrate(VERLEGD_EU_ID, "EU, Diensten verlegd", verlegd=True))
        with scoped_session(administratie_id) as session:
            assert verlegd_taxrate_voor(session, administratie_id=administratie_id) == VERLEGD_HOOG_ID

    def test_zonder_vermelding_geen_verlegd_voorstel(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        omgeving: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _zonder():
            extractie = _extractie()
            extractie.kop.pop("btw_verlegd_vermelding")
            return extractie

        monkeypatch.setattr(
            "app.extractie.service.extraheer_inkoopfactuur",
            lambda pdf_bytes, *, client=None, verbruik_referentie=None, mail_context=None: _zonder(),
        )
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        data = _prefill(administratie_id, document_id)
        assert all(r.taxrate_id is None for r in data.regels)

    def test_snapshot_herstelt_verlegd_chip_na_openen(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, omgeving: None
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        assert boekvoorstel.persisteer_prefill_bij_openen(
            administratie_id=administratie_id, document_id=document_id, geopend_door=gescoopte_gebruiker
        )
        data = _prefill(administratie_id, document_id)
        assert data.opgeslagen
        assert [r.taxrate_id for r in data.regels] == [VERLEGD_HOOG_ID] * 3
        assert [r.btw_bron for r in data.regels] == [BTW_BRON_FACTUUR_VERLEGD] * 3
        with scoped_session(administratie_id) as session:
            snaps = [
                g.detail[boekvoorstel.PREFILL_SNAPSHOT_SLEUTEL]
                for g in session.scalars(
                    select(DocumentGebeurtenis).where(DocumentGebeurtenis.document_id == document_id)
                )
                if g.detail and boekvoorstel.PREFILL_SNAPSHOT_SLEUTEL in g.detail
            ]
        (snapshot,) = snaps
        assert len(snapshot["regels"]) == 3
        assert all(r["btw_bron"] == BTW_BRON_FACTUUR_VERLEGD for r in snapshot["regels"])


class TestSamengevoegdZonderProjectplicht:
    """Samenvoegen bestaat alleen zónder projectplicht (`_samenvoeg_velden`): de ene regel telt de 3 echte regels,
    draagt het volledige bedrag én het verlegd-voorstel."""

    def test_samengevoegde_regel_telt_drie_regels_en_is_verlegd(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        omgeving: None,
    ) -> None:
        beheer_service.zet_project_verplicht(actor_id=beheerder_id, administratie_id=administratie_id, verplicht=False)
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        data = _prefill(administratie_id, document_id)
        assert data.samengevoegde_regel is not None
        assert data.samengevoegde_regel.netto_bedrag == Decimal("4320.00")
        assert data.samengevoegde_regel.btw_bedrag == Decimal("0.00")
        assert "3 regels" in (data.samengevoegde_regel.omschrijving or "")
        assert data.samengevoegde_regel.taxrate_id == VERLEGD_HOOG_ID
        assert data.samengevoegde_regel.btw_bron == BTW_BRON_FACTUUR_VERLEGD
        assert len(data.regels) == 3
