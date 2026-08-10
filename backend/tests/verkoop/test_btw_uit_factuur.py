"""Blok A 2026-08-10 — btw altijd uit de factuur: deterministische resolutie op
(ClassifiedTaxCategory.ID + Percent), vergrendeling in het voorstel, onthouden keuze bij echte
ambiguïteit en de harde check `btw_uit_factuur`. Fixtures dragen het BRONFORMAAT (fractie) —
de regressie van de bevinding 2026-08-09 (cache 0.2100 vs UBL 21.00)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.session import scoped_session
from app.documenten.storage import LokaleBestandsopslag
from app.sync.models import TaxRateCache
from app.verkoop import checks as verkoop_checks
from app.verkoop import voorstel as voorstel_service
from app.verkoop.models import VerkoopBtwVoorkeur
from tests.verkoop.conftest import (
    TAXRATE_0_ID,
    TAXRATE_21_ID,
    bouw_vastly_verkoop_ubl,
    upload_verkoopfactuur,
)

TAXRATE_21_VOORUIT_ID = uuid.UUID("22222222-2222-2222-2222-222222222229")
TAXRATE_VERLEGD_ID = uuid.UUID("22222222-2222-2222-2222-222222222228")


def _upload(administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag, **kwargs) -> uuid.UUID:
    return upload_verkoopfactuur(
        administratie_id=administratie_id, actor_id=actor_id, opslag=opslag,
        inhoud=bouw_vastly_verkoop_ubl(**kwargs),
    )


def _regel_input(r, **overrides) -> voorstel_service.VerkoopRegelInput:
    velden = {
        "omschrijving": r.omschrijving,
        "netto_bedrag": r.netto_bedrag,
        "btw_bedrag": r.btw_bedrag,
        "gb_code": r.gb_code,
        "ledger_id": r.ledger_id,
        "taxrate_id": r.taxrate_id,
    }
    velden.update(overrides)
    return voorstel_service.VerkoopRegelInput(**velden)


def _sla_op(administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, regels) -> None:
    prefill = voorstel_service.haal_verkoop_voorstel_op(
        administratie_id=administratie_id, document_id=document_id
    )
    voorstel_service.sla_verkoop_voorstel_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        debiteur_naam=prefill.debiteur_naam,
        factuurnummer=prefill.factuurnummer,
        factuurdatum=prefill.factuurdatum,
        totaalbedrag_incl=prefill.totaalbedrag_incl,
        regels=regels,
    )


@pytest.fixture
def tweede_21_tarief(administratie_id: uuid.UUID, rekeningschema: None) -> None:
    """De échte BLOW/Universal-situatie: twee actieve 21%-standaardtarieven ("NL, Hoog Tarief"
    + "(vooruit)") — identieke categorie + percentage = echte ambiguïteit."""
    with scoped_session(administratie_id) as session:
        session.add(
            TaxRateCache(
                id=TAXRATE_21_VOORUIT_ID, administratie_id=administratie_id,
                naam="NL, Hoog Tarief (vooruit)", percentage=Decimal("0.2100"),
                brondata={"Name": "NL, Hoog Tarief (vooruit)", "Percentage": 0.21,
                          "IsRelayed": False, "IsExcempt": False},
            )
        )


class TestDeterministischeResolutie:
    def test_s_21_resolvet_en_vergrendelt_tegen_bronformaat_cache(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
    ) -> None:
        """DE kliktest-regressie: met échte syncdata (fractie 0.2100) resolvet S+21.00 nu wél —
        en de code is vergrendeld (geen vrije menselijke waardekeuze meer)."""
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        [regel] = voorstel_service.haal_verkoop_voorstel_op(
            administratie_id=administratie_id, document_id=document_id
        ).regels
        assert regel.taxrate_id == TAXRATE_21_ID
        assert regel.btw_vergrendeld is True
        assert regel.btw_bron == "factuur"
        assert regel.btw_categorie == "S"
        assert regel.btw_percentage_ubl == Decimal("21.00")

    def test_e_vrijgesteld_resolvet_op_categorie_niet_percentage_alleen(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
    ) -> None:
        """Een E-regel (0%) moet het vrijgesteld-tarief pakken — nooit zomaar 'iets met 0%'."""
        with scoped_session(administratie_id) as session:
            session.add(
                TaxRateCache(
                    id=TAXRATE_VERLEGD_ID, administratie_id=administratie_id,
                    naam="NL, BTW verlegd (hoog)", percentage=Decimal("0.0000"),
                    brondata={"Name": "NL, BTW verlegd (hoog)", "Percentage": 0.0,
                              "IsRelayed": True, "IsExcempt": False},
                )
            )
        document_id = _upload(
            administratie_id, gescoopte_gebruiker, opslag,
            regels=[{"naam": "Huur woonruimte", "netto": "800.00", "pct": "0.00",
                     "categorie": "E", "gb_code": "8000"}],
        )
        [regel] = voorstel_service.haal_verkoop_voorstel_op(
            administratie_id=administratie_id, document_id=document_id
        ).regels
        # Twee 0%-tarieven actief (vrijgesteld + verlegd) — de categorie beslist, eenduidig.
        assert regel.taxrate_id == TAXRATE_0_ID
        assert regel.btw_vergrendeld is True
        assert regel.btw_bron == "factuur"

    def test_geen_dekkend_tarief_blijft_mens_kiest(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
    ) -> None:
        document_id = _upload(
            administratie_id, gescoopte_gebruiker, opslag,
            regels=[{"naam": "Huur", "netto": "1000.00", "pct": "9.00",
                     "categorie": "S", "gb_code": "8000"}],
        )
        [regel] = voorstel_service.haal_verkoop_voorstel_op(
            administratie_id=administratie_id, document_id=document_id
        ).regels
        assert regel.taxrate_id is None
        assert regel.btw_vergrendeld is False
        assert regel.btw_kandidaten == ()


class TestVergrendeling:
    def test_andere_taxrate_op_vergrendelde_regel_wordt_geweigerd(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        prefill = voorstel_service.haal_verkoop_voorstel_op(
            administratie_id=administratie_id, document_id=document_id
        )
        with pytest.raises(voorstel_service.VerkoopVoorstelFout, match="vergrendeld"):
            _sla_op(
                administratie_id, document_id, gescoopte_gebruiker,
                regels=[_regel_input(prefill.regels[0], taxrate_id=TAXRATE_0_ID)],
            )

    def test_opgeslagen_voorstel_toont_altijd_het_geresolvede_tarief(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
    ) -> None:
        """Ook een ouder opgeslagen voorstel (van vóór de vergrendeling, met een afwijkende of
        lege btw-keuze) toont bij het lezen het factuur-tarief — de UBL blijft de bron."""
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        prefill = voorstel_service.haal_verkoop_voorstel_op(
            administratie_id=administratie_id, document_id=document_id
        )
        _sla_op(
            administratie_id, document_id, gescoopte_gebruiker,
            regels=[_regel_input(prefill.regels[0], taxrate_id=None)],
        )
        # Simuleer een legacy-rij met een fout tarief (rechtstreeks in de DB, zoals een oud
        # voorstel van vóór blok A dat kon dragen).
        from app.verkoop.models import VerkoopVoorstelRegel

        with scoped_session(administratie_id) as session:
            rij = session.scalars(
                select(VerkoopVoorstelRegel).where(VerkoopVoorstelRegel.document_id == document_id)
            ).one()
            rij.taxrate_id = TAXRATE_0_ID
        [regel] = voorstel_service.haal_verkoop_voorstel_op(
            administratie_id=administratie_id, document_id=document_id
        ).regels
        assert regel.taxrate_id == TAXRATE_21_ID
        assert regel.btw_vergrendeld is True


class TestAmbiguiteitOnthouden:
    def test_ambigue_match_vraagt_keuze_en_onthoudt_per_administratie(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        tweede_21_tarief: None,
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        prefill = voorstel_service.haal_verkoop_voorstel_op(
            administratie_id=administratie_id, document_id=document_id
        )
        [regel] = prefill.regels
        assert regel.taxrate_id is None
        assert regel.btw_vergrendeld is False
        assert set(regel.btw_kandidaten) == {TAXRATE_21_ID, TAXRATE_21_VOORUIT_ID}

        # De mens kiest één keer — de keuze wordt onthouden.
        _sla_op(
            administratie_id, document_id, gescoopte_gebruiker,
            regels=[_regel_input(regel, taxrate_id=TAXRATE_21_ID)],
        )
        with scoped_session(administratie_id) as session:
            voorkeur = session.get(
                VerkoopBtwVoorkeur, (administratie_id, "S", Decimal("0.2100"))
            )
            assert voorkeur is not None
            assert voorkeur.taxrate_id == TAXRATE_21_ID

        # De volgende factuur met dezelfde categorie+percentage vult automatisch én vergrendeld.
        volgend_document = _upload(
            administratie_id, gescoopte_gebruiker, opslag, factuurnummer="VF-2026-0043"
        )
        [volgende_regel] = voorstel_service.haal_verkoop_voorstel_op(
            administratie_id=administratie_id, document_id=volgend_document
        ).regels
        assert volgende_regel.taxrate_id == TAXRATE_21_ID
        assert volgende_regel.btw_vergrendeld is True
        assert volgende_regel.btw_bron == "onthouden"

    def test_keuze_buiten_kandidatenset_wordt_geweigerd(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        tweede_21_tarief: None,
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        prefill = voorstel_service.haal_verkoop_voorstel_op(
            administratie_id=administratie_id, document_id=document_id
        )
        with pytest.raises(voorstel_service.VerkoopVoorstelFout, match="dekt de factuur-btw"):
            _sla_op(
                administratie_id, document_id, gescoopte_gebruiker,
                regels=[_regel_input(prefill.regels[0], taxrate_id=TAXRATE_0_ID)],
            )


class TestHardeCheckBtwUitFactuur:
    """Unit-niveau op primitieven (app/verkoop/checks.py) — elke weiger-reden apart."""

    @staticmethod
    def _regel(**overrides) -> verkoop_checks.VerkoopCheckRegel:
        velden = dict(
            volgnummer=1, omschrijving="Huur", netto_bedrag=Decimal("1000.00"),
            btw_bedrag=Decimal("210.00"), gb_code="8000", ledger_id_bekend=True,
            taxrate_id_bekend=True, gb_code_status="bekend",
            btw_categorie="S", btw_percentage_ubl=Decimal("21.00"),
            taxrate_percentage=Decimal("0.2100"), taxrate_is_verlegd=False,
            taxrate_is_vrijgesteld=False, taxrate_in_cache=True,
        )
        velden.update(overrides)
        return verkoop_checks.VerkoopCheckRegel(**velden)

    def test_ok_bij_exacte_categorie_en_bedrag(self) -> None:
        resultaat = verkoop_checks.check_btw_uit_factuur(regels=[self._regel()])
        assert resultaat.ok is True

    def test_blokkeert_bij_categorie_mismatch(self) -> None:
        resultaat = verkoop_checks.check_btw_uit_factuur(
            regels=[self._regel(taxrate_is_vrijgesteld=True, taxrate_percentage=Decimal("0"))]
        )
        assert resultaat.ok is False
        assert "dekt de factuur-btw niet" in resultaat.melding

    def test_blokkeert_bij_bedrag_afwijking(self) -> None:
        resultaat = verkoop_checks.check_btw_uit_factuur(
            regels=[self._regel(btw_bedrag=Decimal("200.00"))]
        )
        assert resultaat.ok is False
        assert "wijkt af" in resultaat.melding

    def test_blokkeert_bij_taxrate_buiten_cache(self) -> None:
        resultaat = verkoop_checks.check_btw_uit_factuur(
            regels=[self._regel(taxrate_in_cache=False)]
        )
        assert resultaat.ok is False
        assert "niet (meer) in de actieve" in resultaat.melding

    def test_nvt_zonder_factuur_btw_informatie(self) -> None:
        resultaat = verkoop_checks.check_btw_uit_factuur(
            regels=[self._regel(btw_categorie=None, btw_percentage_ubl=None,
                                taxrate_percentage=Decimal("0"), taxrate_is_vrijgesteld=True)]
        )
        assert resultaat.ok is True

    def test_regel_zonder_taxrate_valt_onder_verplichte_velden(self) -> None:
        resultaat = verkoop_checks.check_btw_uit_factuur(
            regels=[self._regel(taxrate_id_bekend=False)]
        )
        assert resultaat.ok is True  # geen dubbele melding — verplichte velden blokkeert al

    def test_tolerantie_van_een_cent(self) -> None:
        resultaat = verkoop_checks.check_btw_uit_factuur(
            regels=[self._regel(btw_bedrag=Decimal("210.01"))]
        )
        assert resultaat.ok is True


class TestChecksEndToEnd:
    def test_checks_rapport_bevat_btw_uit_factuur_en_is_groen(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        prefill = voorstel_service.haal_verkoop_voorstel_op(
            administratie_id=administratie_id, document_id=document_id
        )
        _sla_op(administratie_id, document_id, gescoopte_gebruiker,
                regels=[_regel_input(prefill.regels[0])])
        from tests.verkoop.conftest import FakeVerkoopClient

        rapport = voorstel_service.voer_verkoop_checks_uit(
            administratie_id=administratie_id, document_id=document_id,
            client=FakeVerkoopClient(),
        )
        btw_check = next(r for r in rapport.resultaten if r.naam == "btw_uit_factuur")
        assert btw_check.ok is True

    def test_fout_btw_bedrag_blokkeert_boeken_via_checks(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        prefill = voorstel_service.haal_verkoop_voorstel_op(
            administratie_id=administratie_id, document_id=document_id
        )
        # De mens verminkt het btw-bedrag (regelsom blijft kloppend door het totaal mee te
        # verlagen zou hier niet eens hoeven — de btw-check toetst tegen de fáctuur).
        _sla_op(administratie_id, document_id, gescoopte_gebruiker,
                regels=[_regel_input(prefill.regels[0], btw_bedrag=Decimal("100.00"))])
        from tests.verkoop.conftest import FakeVerkoopClient

        rapport = voorstel_service.voer_verkoop_checks_uit(
            administratie_id=administratie_id, document_id=document_id,
            client=FakeVerkoopClient(),
        )
        btw_check = next(r for r in rapport.resultaten if r.naam == "btw_uit_factuur")
        assert btw_check.ok is False
        assert rapport.geblokkeerd is True
