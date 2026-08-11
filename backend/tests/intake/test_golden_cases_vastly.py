"""Blok D grote opdracht 2026-08-10 — verificatie tegen de ÉCHTE Vastly-golden-case-UBL's
(aangeleverd door vastgoed in Platform/uitwisseling, 2026-08-09; gegenereerd met de
productie-generator en XSD- + SI-UBL-2.0-gevalideerd). Dit sluit het open punt "verificatie
tegen echte Vastly-UBL's" uit BESLISSINGEN (Vastly-verkoopfactuur-boekpad).

Deterministische laag (altijd draaiend): intake-routing (380 → verkoop-werkvoorraad; 381 achter
de creditnota_381-gate; consument/BR-NL-10-varianten), prefill + harde checks. De échte
RLZ-schrijfverificatie staat in tests/integration/test_golden_cases_write_integration.py."""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from app.config import settings
from app.db.models import Grootboekrekening
from app.db.session import scoped_session
from app.documenten.storage import LokaleBestandsopslag
from app.intake import verwerking
from app.sync.models import TaxRateCache
from app.verkoop import voorstel as voorstel_service
from app.verkoop.models import VerkoopBoeking, VerkoopBoekingStatus
from tests.intake.conftest import bouw_eml
from tests.verkoop.conftest import upload_verkoopfactuur

GOLDEN_DIR = Path(__file__).resolve().parents[3].parent / "Platform" / "uitwisseling"

pytestmark = pytest.mark.skipif(
    not GOLDEN_DIR.is_dir(), reason="Platform/uitwisseling (golden-cases van vastgoed) niet aanwezig"
)

FACTUREN_380 = [
    "factuur-380-golden-standaard.xml",
    "factuur-380-golden-gemengde-grootboekcodes.xml",
    "factuur-380-golden-servicekosten-afrekening.xml",
    # Consument-variant: schendt uitsluitend BR-NL-10 (particuliere huurder zonder KvK). De
    # RLZ-intake draait bewust een NLCIUS-kernvelden-proxy — dit stuk routeert dus gewoon de
    # omzet-werkvoorraad in; de zichtbare vlag "consument-afnemer" landt bij de
    # volledige-schematron-stap (koppelcontract §2d-nuance v1.10, genoteerd vervolg).
    "factuur-380-golden-consument-brnl10.xml",
]
CREDITNOTES_381 = [
    "creditnote-381-golden-standaard.xml",
    "creditnote-381-golden-consument-brnl10.xml",
]

LEDGER_8000 = uuid.UUID("33333333-3333-3333-3333-333333338000")
LEDGER_8100 = uuid.UUID("33333333-3333-3333-3333-333333338100")
TAXRATE_HOOG = uuid.UUID("44444444-4444-4444-4444-444444442100")
TAXRATE_VRIJGESTELD = uuid.UUID("44444444-4444-4444-4444-444444440000")


def _golden(naam: str) -> bytes:
    return (GOLDEN_DIR / naam).read_bytes()


@pytest.fixture
def administratie_heet_rubicon(administratie_id: uuid.UUID, admin_engine: Engine) -> uuid.UUID:
    """VASTLY-VERKOOP wijst toe op de LEVERANCIER (= onze entiteit): de golden-cases dragen
    'Rubicon Investments B.V.' als AccountingSupplierParty."""
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.administratie SET naam = 'Rubicon Investments B.V.' WHERE id = :id"),
            {"id": administratie_id},
        )
    return administratie_id


@pytest.fixture
def rubicon_cache(administratie_id: uuid.UUID) -> None:
    """Rekeningschema + btw-cache voor de golden-case-codes (8000/8100) — taxrates in
    BRONFORMAAT (fractie + echte-API-vorm brondata, verbeteringen.md 2026-08-09)."""
    with scoped_session(administratie_id) as session:
        session.add(
            Grootboekrekening(
                ledger_id=LEDGER_8000, administratie_id=administratie_id,
                code="8000", naam="Omzet verhuur", soort=1, is_totaalrekening=False,
            )
        )
        session.add(
            Grootboekrekening(
                ledger_id=LEDGER_8100, administratie_id=administratie_id,
                code="8100", naam="Omzet servicekosten", soort=1, is_totaalrekening=False,
            )
        )
        session.add(
            TaxRateCache(
                id=TAXRATE_HOOG, administratie_id=administratie_id,
                naam="NL, Hoog Tarief", percentage=Decimal("0.2100"),
                brondata={"Name": "NL, Hoog Tarief", "Percentage": 0.21,
                          "IsRelayed": False, "IsExcempt": False},
            )
        )
        session.add(
            TaxRateCache(
                id=TAXRATE_VRIJGESTELD, administratie_id=administratie_id,
                naam="NL, Geen BTW (Vrijgesteld)", percentage=Decimal("0.0000"),
                brondata={"Name": "NL, Geen BTW (Vrijgesteld)", "Percentage": 0.0,
                          "IsRelayed": False, "IsExcempt": True},
            )
        )


def _document_rij(admin_engine: Engine, document_id: uuid.UUID):
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT administratie_id, status, soort FROM boekhouding.document WHERE id = :id"),
            {"id": document_id},
        ).one()


class TestIntakeRouting380:
    @pytest.mark.parametrize("bestand", FACTUREN_380)
    def test_golden_380_routeert_naar_de_verkoop_werkvoorraad(
        self,
        bestand: str,
        administratie_heet_rubicon: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        eml = bouw_eml(
            afzender="boekhouding@vastly.nl",
            bijlagen=[(bestand, _golden(bestand), "application", "xml")],
        )
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)

        assert [r.uitkomst for r in resultaat.bijlagen] == ["toegewezen"], resultaat.bijlagen
        rij = _document_rij(admin_engine, resultaat.bijlagen[0].document_id)
        assert rij.administratie_id == administratie_heet_rubicon
        assert rij.soort == "verkoopfactuur"
        assert rij.status == "te_controleren"


class TestIntakeRouting381:
    @pytest.mark.parametrize("bestand", CREDITNOTES_381)
    def test_gate_dicht_381_valt_zichtbaar_in_de_verzamelbak(
        self,
        bestand: str,
        administratie_heet_rubicon: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "creditnota_381_ingeschakeld", False)
        eml = bouw_eml(bijlagen=[(bestand, _golden(bestand), "application", "xml")])
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)

        assert resultaat.bijlagen[0].uitkomst == "verzamelbak"
        assert "creditnote_381_gate_uit" in (resultaat.bijlagen[0].detail or "")

    @pytest.mark.parametrize("bestand", CREDITNOTES_381)
    def test_gate_open_381_wordt_herkend_met_herleiding(
        self,
        bestand: str,
        administratie_heet_rubicon: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "creditnota_381_ingeschakeld", True)
        eml = bouw_eml(bijlagen=[(bestand, _golden(bestand), "application", "xml")])
        resultaat = verwerking.verwerk_eml(eml, actor_id=gescoopte_gebruiker)

        assert resultaat.bijlagen[0].uitkomst == "toegewezen"
        document_id = resultaat.bijlagen[0].document_id
        assert document_id is not None
        rij = _document_rij(admin_engine, document_id)
        assert rij.soort == "verkoopfactuur"

        prefill = voorstel_service.haal_verkoop_voorstel_op(
            administratie_id=administratie_heet_rubicon, document_id=document_id
        )
        assert prefill.is_creditnota is True
        assert prefill.gecrediteerd_factuurnummer == "GC-2026-0001"


class TestPrefillEnChecks:
    def test_golden_380_standaard_prefilt_deterministisch_en_is_boekbaar(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        rubicon_cache: None,
    ) -> None:
        """De kern van blok D deel 1: huurregel (E, vrijgesteld) + servicekostenregel (S, 21%)
        resolven volledig deterministisch — GB via AccountingCost, btw via categorie+percentage
        (blok A, vergrendeld) — en de harde checks staan op groen (boekbaar)."""
        document_id = upload_verkoopfactuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            inhoud=_golden("factuur-380-golden-standaard.xml"),
            bestandsnaam="factuur-380-golden-standaard.xml",
        )
        prefill = voorstel_service.haal_verkoop_voorstel_op(
            administratie_id=administratie_id, document_id=document_id
        )
        assert prefill.factuurnummer == "RUB-2026-0001"
        assert prefill.debiteur_naam == "Tester Retail B.V."
        assert prefill.totaalbedrag_incl == Decimal("1242.00")
        huur, service = prefill.regels
        assert (huur.gb_code, huur.gb_code_status, huur.ledger_id) == ("8000", "bekend", LEDGER_8000)
        assert huur.btw_categorie == "E"
        assert huur.taxrate_id == TAXRATE_VRIJGESTELD
        assert huur.btw_vergrendeld is True
        assert service.btw_categorie == "S"
        assert service.taxrate_id == TAXRATE_HOOG
        assert service.btw_vergrendeld is True
        assert service.btw_bedrag == Decimal("42.00")

        voorstel_service.sla_verkoop_voorstel_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            debiteur_naam=prefill.debiteur_naam,
            factuurnummer=prefill.factuurnummer,
            factuurdatum=prefill.factuurdatum,
            totaalbedrag_incl=prefill.totaalbedrag_incl,
            regels=[
                voorstel_service.VerkoopRegelInput(
                    omschrijving=r.omschrijving, netto_bedrag=r.netto_bedrag, btw_bedrag=r.btw_bedrag,
                    gb_code=r.gb_code, ledger_id=r.ledger_id, taxrate_id=r.taxrate_id,
                )
                for r in prefill.regels
            ],
        )
        from tests.verkoop.conftest import FakeVerkoopClient

        rapport = voorstel_service.voer_verkoop_checks_uit(
            administratie_id=administratie_id, document_id=document_id, client=FakeVerkoopClient()
        )
        assert rapport.geblokkeerd is False, [(r.naam, r.melding) for r in rapport.resultaten if not r.ok]

    def test_golden_381_blokkeert_zonder_geboekt_origineel_en_is_boekbaar_met(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        rubicon_cache: None,
    ) -> None:
        """⚠️ Bevinding golden-set: de 381's crediteren GC-2026-0001, maar dat origineel zit
        NIET in de aangeleverde set — de creditnota-herleiding blokkeert dan terecht. Met een
        geboekt origineel (lokale registratie) wordt de creditboeking boekbaar."""
        document_id = upload_verkoopfactuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            inhoud=_golden("creditnote-381-golden-standaard.xml"),
            bestandsnaam="creditnote-381-golden-standaard.xml",
        )
        prefill = voorstel_service.haal_verkoop_voorstel_op(
            administratie_id=administratie_id, document_id=document_id
        )
        assert prefill.is_creditnota is True
        assert prefill.gecrediteerd_factuurnummer == "GC-2026-0001"
        voorstel_service.sla_verkoop_voorstel_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            debiteur_naam=prefill.debiteur_naam,
            factuurnummer=prefill.factuurnummer,
            factuurdatum=prefill.factuurdatum,
            totaalbedrag_incl=prefill.totaalbedrag_incl,
            regels=[
                voorstel_service.VerkoopRegelInput(
                    omschrijving=r.omschrijving, netto_bedrag=r.netto_bedrag, btw_bedrag=r.btw_bedrag,
                    gb_code=r.gb_code, ledger_id=r.ledger_id, taxrate_id=r.taxrate_id,
                )
                for r in prefill.regels
            ],
        )
        from tests.verkoop.conftest import FakeVerkoopClient

        rapport = voorstel_service.voer_verkoop_checks_uit(
            administratie_id=administratie_id, document_id=document_id, client=FakeVerkoopClient()
        )
        herleiding = next(r for r in rapport.resultaten if r.naam == "creditnota_herleiding")
        assert herleiding.ok is False
        assert "GC-2026-0001" in herleiding.melding

        # Met een geboekt origineel is de herleiding rond.
        with scoped_session(administratie_id) as session:
            session.add(
                VerkoopBoeking(
                    administratie_id=administratie_id,
                    document_id=document_id,  # willekeurig bestaand document als drager
                    factuurnummer="GC-2026-0001",
                    is_creditnota=False,
                    totaalbedrag_incl=Decimal("1045.20"),
                    debiteur_customer_id=uuid.uuid4(),
                    debiteur_naam="Tester Retail B.V.",
                    verkoop_rlz_id=uuid.uuid4(),
                    status=VerkoopBoekingStatus.GEBOEKT.value,
                    geboekt_door=gescoopte_gebruiker,
                )
            )
        rapport2 = voorstel_service.voer_verkoop_checks_uit(
            administratie_id=administratie_id, document_id=document_id, client=FakeVerkoopClient()
        )
        herleiding2 = next(r for r in rapport2.resultaten if r.naam == "creditnota_herleiding")
        assert herleiding2.ok is True
