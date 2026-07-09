from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.documenten.checks import (
    CheckRegel,
    check_duplicaat,
    check_regeltelling,
    check_verplichte_velden,
    voer_harde_checks_uit,
)


class _NepRlzClient:
    """Stub voor de duplicaatcheck — geen echte HTTP-aanroep, alleen de vorm die
    check_duplicaat() nodig heeft (find_purchase_invoices_by_reference)."""

    def __init__(self, gevonden: list[dict]) -> None:
        self.gevonden = gevonden
        self.aanroepen: list[dict] = []

    def find_purchase_invoices_by_reference(self, *, vendor_id, reference, total_amount=None):
        self.aanroepen.append({"vendor_id": vendor_id, "reference": reference, "total_amount": total_amount})
        return self.gevonden


def _regel(**overrides) -> CheckRegel:
    basis = dict(
        ledger_id=uuid.uuid4(), taxrate_id=uuid.uuid4(), netto_bedrag=Decimal("100.00"), btw_bedrag=Decimal("21.00")
    )
    basis.update(overrides)
    return CheckRegel(**basis)


class TestVerplichteVelden:
    def test_alles_ingevuld_is_ok(self) -> None:
        resultaat = check_verplichte_velden(
            vendor_id=uuid.uuid4(),
            referentie="F-1",
            factuurdatum=date.today(),
            totaalbedrag=Decimal("121.00"),
            regels=[_regel()],
        )
        assert resultaat.ok

    def test_geen_regels_blokkeert(self) -> None:
        resultaat = check_verplichte_velden(
            vendor_id=uuid.uuid4(),
            referentie="F-1",
            factuurdatum=date.today(),
            totaalbedrag=Decimal("121.00"),
            regels=[],
        )
        assert not resultaat.ok
        assert "minstens één boekingsregel" in resultaat.melding

    def test_ontbrekende_crediteur_en_regelvelden_blokkeert(self) -> None:
        resultaat = check_verplichte_velden(
            vendor_id=None,
            referentie=None,
            factuurdatum=None,
            totaalbedrag=None,
            regels=[_regel(ledger_id=None, taxrate_id=None, netto_bedrag=None)],
        )
        assert not resultaat.ok
        for verwacht in [
            "crediteur",
            "referentie",
            "factuurdatum",
            "totaalbedrag",
            "grootboekrekening",
            "btw-code",
            "netto bedrag",
        ]:
            assert verwacht in resultaat.melding


class TestRegeltelling:
    def test_som_gelijk_aan_totaal_is_ok(self) -> None:
        resultaat = check_regeltelling(totaalbedrag=Decimal("121.00"), regels=[_regel()])
        assert resultaat.ok

    def test_klein_afrondingsverschil_is_nog_ok(self) -> None:
        resultaat = check_regeltelling(
            totaalbedrag=Decimal("121.01"),
            regels=[_regel(netto_bedrag=Decimal("100.00"), btw_bedrag=Decimal("21.00"))],
        )
        assert resultaat.ok

    def test_groot_verschil_blokkeert(self) -> None:
        resultaat = check_regeltelling(
            totaalbedrag=Decimal("200.00"),
            regels=[_regel(netto_bedrag=Decimal("100.00"), btw_bedrag=Decimal("21.00"))],
        )
        assert not resultaat.ok
        assert "wijkt" in resultaat.melding

    def test_meerdere_regels_worden_gesommeerd(self) -> None:
        resultaat = check_regeltelling(
            totaalbedrag=Decimal("242.00"),
            regels=[_regel(netto_bedrag=Decimal("100.00"), btw_bedrag=Decimal("21.00")) for _ in range(2)],
        )
        assert resultaat.ok

    def test_geen_totaalbedrag_blokkeert(self) -> None:
        resultaat = check_regeltelling(totaalbedrag=None, regels=[_regel()])
        assert not resultaat.ok


class TestDuplicaat:
    def test_geen_hits_is_ok(self) -> None:
        client = _NepRlzClient(gevonden=[])
        resultaat = check_duplicaat(
            client=client,
            vendor_id=uuid.uuid4(),
            referentie="F-1",
            totaalbedrag=Decimal("121.00"),
            eigen_rlz_document_id=uuid.uuid4(),
        )
        assert resultaat.ok

    def test_hit_van_ander_document_blokkeert(self) -> None:
        ander_id = str(uuid.uuid4())
        client = _NepRlzClient(gevonden=[{"id": ander_id}])
        resultaat = check_duplicaat(
            client=client,
            vendor_id=uuid.uuid4(),
            referentie="F-1",
            totaalbedrag=Decimal("121.00"),
            eigen_rlz_document_id=uuid.uuid4(),
        )
        assert not resultaat.ok

    def test_hit_van_eigen_client_guid_is_geen_duplicaat(self) -> None:
        """Een retry na boeken_mislukt vindt het EIGEN, al eerder gelukte PUT-document terug —
        dat mag de duplicaatcheck niet laten blokkeren (anders kan een idempotente retry nooit
        meer slagen)."""
        eigen_id = uuid.uuid4()
        client = _NepRlzClient(gevonden=[{"id": str(eigen_id)}])
        resultaat = check_duplicaat(
            client=client,
            vendor_id=uuid.uuid4(),
            referentie="F-1",
            totaalbedrag=Decimal("121.00"),
            eigen_rlz_document_id=eigen_id,
        )
        assert resultaat.ok

    def test_zonder_vendor_of_referentie_blokkeert_zonder_aanroep(self) -> None:
        client = _NepRlzClient(gevonden=[])
        resultaat = check_duplicaat(
            client=client,
            vendor_id=None,
            referentie=None,
            totaalbedrag=Decimal("121.00"),
            eigen_rlz_document_id=uuid.uuid4(),
        )
        assert not resultaat.ok
        assert client.aanroepen == []

    def test_filtert_op_afgekapte_referentie_en_bedrag(self) -> None:
        client = _NepRlzClient(gevonden=[])
        lange_referentie = "F" * 40
        check_duplicaat(
            client=client,
            vendor_id=uuid.uuid4(),
            referentie=lange_referentie,
            totaalbedrag=Decimal("121.00"),
            eigen_rlz_document_id=uuid.uuid4(),
        )
        assert client.aanroepen[0]["reference"] == lange_referentie  # afkappen zit in RlzClient zelf
        assert client.aanroepen[0]["total_amount"] == 121.0


class TestVoerHardeChecksUit:
    def test_alle_checks_ok_geeft_niet_geblokkeerd(self) -> None:
        client = _NepRlzClient(gevonden=[])
        rapport = voer_harde_checks_uit(
            client=client,
            vendor_id=uuid.uuid4(),
            referentie="F-1",
            factuurdatum=date.today(),
            totaalbedrag=Decimal("121.00"),
            regels=[_regel()],
            eigen_rlz_document_id=uuid.uuid4(),
        )
        assert not rapport.geblokkeerd
        assert [r.naam for r in rapport.resultaten] == ["Verplichte velden", "Regeltelling vs totaal", "Duplicaatcheck"]
        assert all(r.ok for r in rapport.resultaten)

    def test_een_falende_check_blokkeert_het_hele_rapport(self) -> None:
        client = _NepRlzClient(gevonden=[])
        rapport = voer_harde_checks_uit(
            client=client,
            vendor_id=uuid.uuid4(),
            referentie="F-1",
            factuurdatum=date.today(),
            totaalbedrag=Decimal("999.00"),
            regels=[_regel()],
            eigen_rlz_document_id=uuid.uuid4(),
        )
        assert rapport.geblokkeerd
        assert not any(r.naam == "Regeltelling vs totaal" and r.ok for r in rapport.resultaten)

    def test_alle_drie_checks_draaien_ook_als_de_eerste_al_faalt(self) -> None:
        """Geen stille kortsluiting — de UI moet alle drie de rijen kunnen tonen (CLAUDE.md,
        mockup-stijl groen/blokkerend per check)."""
        client = _NepRlzClient(gevonden=[])
        rapport = voer_harde_checks_uit(
            client=client,
            vendor_id=None,
            referentie=None,
            factuurdatum=None,
            totaalbedrag=None,
            regels=[],
            eigen_rlz_document_id=uuid.uuid4(),
        )
        assert len(rapport.resultaten) == 3
