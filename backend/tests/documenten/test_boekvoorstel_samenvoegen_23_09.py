"""BUG 23-09 (Peter, BLOW, Van Rumpt 2025135 € 1.277,50, document 3405157f…): 7 opgeslagen regels mét netto/bruto, de
SCAN zonder regelbedragen → `samengevoegde_regel` None → geen vinkje "Samenvoegen", Peter kruiste 6 regels weg.
Regel: staan er ≥ 2 OPGESLAGEN regels, dan zijn díe de bron van de één-regel-variant (Σ netto, Σ btw — regel-btw leeg
= uit het tarief); niet berekenbaar = zichtbare reden (`samenvoegen_niet_mogelijk_reden`), nooit stil weg. De
regelsom-check (Σ = factuurtotaal) blijft de poort — dit is uitsluitend de weergave-/boekvorm."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.db.session import scoped_session
from app.documenten import boekvoorstel, service
from app.documenten.storage import LokaleBestandsopslag
from app.sync.models import TaxRateCache
from tests.documenten.test_ubl import _VOORBEELD_UBL

HOOG = uuid.uuid4()
LAAG = uuid.uuid4()
GB = uuid.uuid4()


def _regel(**overrides) -> boekvoorstel.BoekvoorstelRegelData:
    basis = dict(
        ledger_id=GB, taxrate_id=HOOG, project_id=None, netto_bedrag=Decimal("100.00"), btw_bedrag=Decimal("21.00"),
        omschrijving="regel",
    )
    basis.update(overrides)
    return boekvoorstel.BoekvoorstelRegelData(**basis)


PCT = {HOOG: Decimal("0.21"), LAAG: Decimal("0.09")}


class TestSamengevoegdeRegelUitOpgeslagenPuur:
    def test_zeven_regels_zonder_scanbedragen_geven_som_netto_en_btw(self) -> None:
        regels = [_regel(netto_bedrag=Decimal("150.83"), btw_bedrag=None, omschrijving=f"r{i}") for i in range(7)]
        regel, reden = boekvoorstel._samengevoegde_regel_uit_opgeslagen(regels, percentages=PCT, factuurnummer="2025135")
        assert reden is None and regel is not None
        assert regel.netto_bedrag == Decimal("1055.81")
        # btw per regel uit het tarief (150,83 × 21 % = 31,67 cent-exact), dan gesommeerd — geld = code, nooit een gok.
        assert regel.btw_bedrag == Decimal("221.69")
        assert (regel.taxrate_id, regel.ledger_id) == (HOOG, GB)
        assert regel.omschrijving == "Factuur 2025135 — samengevoegd (7 regels)"

    def test_opgeslagen_btw_bedragen_winnen_van_het_tarief(self) -> None:
        regels = [_regel(btw_bedrag=Decimal("21.00")), _regel(btw_bedrag=Decimal("20.99"))]
        regel, _ = boekvoorstel._samengevoegde_regel_uit_opgeslagen(regels, percentages=PCT, factuurnummer=None)
        assert regel is not None and regel.btw_bedrag == Decimal("41.99") and regel.omschrijving == "Samengevoegd (2 regels)"

    def test_verschillende_btw_codes_geeft_geen_regel_maar_een_reden(self) -> None:
        regels = [_regel(), _regel(taxrate_id=LAAG, btw_bedrag=Decimal("9.00"))]
        regel, reden = boekvoorstel._samengevoegde_regel_uit_opgeslagen(regels, percentages=PCT, factuurnummer=None)
        assert regel is None and reden == "verschillende btw-codes"

    def test_regel_zonder_btw_en_zonder_percentage_is_niet_berekenbaar(self) -> None:
        onbekend = uuid.uuid4()
        regels = [_regel(), _regel(taxrate_id=onbekend, btw_bedrag=None)]
        regel, reden = boekvoorstel._samengevoegde_regel_uit_opgeslagen(regels, percentages=PCT, factuurnummer=None)
        assert regel is None and reden == "btw-bedrag van regel 2 onbekend"
        regels = [_regel(), _regel(netto_bedrag=None)]
        regel, reden = boekvoorstel._samengevoegde_regel_uit_opgeslagen(regels, percentages=PCT, factuurnummer=None)
        assert regel is None and reden == "nettobedrag van regel 2 onbekend"

    def test_verschillende_grootboeken_geven_wel_een_regel_zonder_grootboek(self) -> None:
        regels = [_regel(), _regel(ledger_id=uuid.uuid4())]
        regel, reden = boekvoorstel._samengevoegde_regel_uit_opgeslagen(regels, percentages=PCT, factuurnummer=None)
        assert reden is None and regel is not None and regel.ledger_id is None and regel.taxrate_id == HOOG

    def test_een_regel_geeft_niets_en_geen_reden(self) -> None:
        assert boekvoorstel._samengevoegde_regel_uit_opgeslagen([_regel()], percentages=PCT, factuurnummer=None) == (
            None,
            None,
        )
        assert boekvoorstel._samengevoegde_regel_uit_opgeslagen([], percentages=PCT, factuurnummer=None) == (None, None)


class TestOpgeslagenRegelsZijnDeBron:
    def _upload(self, administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag, naam: str) -> uuid.UUID:
        return service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam=naam,
            inhoud=_VOORBEELD_UBL + f"<!-- {naam} -->".encode(),
            actor_id=actor_id,
            opslag=opslag,
        ).document_id

    def _tarieven(self, administratie_id: uuid.UUID) -> None:
        with scoped_session(administratie_id) as session:
            session.add(TaxRateCache(id=HOOG, administratie_id=administratie_id, naam="NL, Hoog tarief", percentage=Decimal("0.21"), brondata={}))
            session.add(TaxRateCache(id=LAAG, administratie_id=administratie_id, naam="NL, Laag tarief", percentage=Decimal("0.09"), brondata={}))

    def test_opgeslagen_regels_zonder_btw_bedrag_geven_toch_een_samengevoegde_regel(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        self._tarieven(administratie_id)
        document_id = self._upload(administratie_id, gescoopte_gebruiker, opslag, "vanrumpt.xml")
        regels = [_regel(netto_bedrag=Decimal("150.83"), btw_bedrag=None, omschrijving=f"regel {i}") for i in range(7)]
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            vendor_id=None,
            referentie="2025135",
            factuurdatum=date(2026, 9, 1),
            totaalbedrag=Decimal("1277.50"),
            regels=regels,
            regels_samenvoegen=False,
        )
        data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert data.opgeslagen and len(data.regels) == 7 and data.samenvoegen_toegestaan is True
        assert data.samenvoegen_niet_mogelijk_reden is None
        assert data.samengevoegde_regel is not None
        assert data.samengevoegde_regel.netto_bedrag == Decimal("1055.81")
        assert data.samengevoegde_regel.btw_bedrag == Decimal("221.69")
        assert data.samengevoegde_regel.taxrate_id == HOOG
        # De regelsom-check blijft leidend: het opgeslagen totaal is niet aangeraakt.
        assert data.totaalbedrag == Decimal("1277.50")

    def test_verschillende_btw_codes_opgeslagen_geeft_zichtbare_reden(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        self._tarieven(administratie_id)
        document_id = self._upload(administratie_id, gescoopte_gebruiker, opslag, "gemengd.xml")
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            vendor_id=None,
            referentie="G-1",
            factuurdatum=date(2026, 9, 1),
            totaalbedrag=Decimal("230.00"),
            regels=[_regel(), _regel(taxrate_id=LAAG, btw_bedrag=Decimal("9.00"))],
            regels_samenvoegen=False,
        )
        data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert data.samengevoegde_regel is None
        assert data.samenvoegen_niet_mogelijk_reden == "verschillende btw-codes"

    def test_een_opgeslagen_regel_geen_variant_en_geen_reden(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        document_id = self._upload(administratie_id, gescoopte_gebruiker, opslag, "een.xml")
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            vendor_id=None,
            referentie="E-1",
            factuurdatum=date(2026, 9, 1),
            totaalbedrag=Decimal("121.00"),
            regels=[_regel()],
            regels_samenvoegen=False,
        )
        data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert len(data.regels) == 1
        # Eén regel: de scan-variant (UBL-totalen) blijft de bron zoals vóór 23-09; geen reden (er is niets te splitsen).
        assert data.samenvoegen_niet_mogelijk_reden is None

    def test_scan_pad_ongewijzigd_bij_een_ubl_regel(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        """De A10-autosave persisteert bij het openen de ene UBL-regel (< 2 opgeslagen regels) → de scan-variant
        (UBL-totalen excl 1526,20 / btw 320,50) blijft exact als vóór 23-09."""
        document_id = self._upload(administratie_id, gescoopte_gebruiker, opslag, "scan.xml")
        data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert len(data.regels) == 1
        assert data.samengevoegde_regel is not None and data.samengevoegde_regel.netto_bedrag == Decimal("1526.20")
        assert data.samenvoegen_niet_mogelijk_reden is None


class TestScanZonderTotalenGeeftReden:
    def test_twee_gelezen_regels_zonder_bedragen_dragen_de_reden(self) -> None:
        """Puur op `_samenvoeg_velden` is niet te testen zonder sessie; de reden-constante is de bron van de chip-tekst."""
        assert boekvoorstel._samengevoegde_regel({"regels": [{"netto_bedrag": None}, {"netto_bedrag": None}]}) is None
        assert "onvolledig" in boekvoorstel.REDEN_SAMENVOEGEN_SCAN_ONVOLLEDIG
