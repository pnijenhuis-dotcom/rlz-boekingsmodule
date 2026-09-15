"""Cent-fix aan de bron in de RLZ-adapter (reconciliatie-nazorg 15-09, punt 2): `regels_naar_rlz_lines` en
`tegenboek_lines` sturen btw per regel zó dat Σ(NetAmount + TaxAmount) cent-exact het factuurtotaal is; de module-
regels zelf blijven ongewijzigd (alleen wat naar RLZ gaat)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.backends import rlz_inkoop
from app.documenten.boekvoorstel import BoekvoorstelData, BoekvoorstelRegelData


def _regel(netto: str, btw: str | None) -> BoekvoorstelRegelData:
    return BoekvoorstelRegelData(
        ledger_id=uuid.uuid4(),
        taxrate_id=uuid.uuid4(),
        project_id=None,
        netto_bedrag=Decimal(netto),
        btw_bedrag=Decimal(btw) if btw is not None else None,
        omschrijving=None,
    )


def _voorstel(regels: list[BoekvoorstelRegelData], totaal: str | None) -> BoekvoorstelData:
    return BoekvoorstelData(
        document_id=uuid.uuid4(),
        vendor_id=uuid.uuid4(),
        referentie="L-2026-1",
        factuurdatum=date(2026, 9, 1),
        totaalbedrag=Decimal(totaal) if totaal is not None else None,
        rlz_boekstuknummer=None,
        opgeslagen=True,
        regels=regels,
    )


def _som(lines: list[dict]) -> Decimal:
    return sum((Decimal(str(line["NetAmount"])) + Decimal(str(line["TaxAmount"])) for line in lines), Decimal(0))


class TestRegelsNaarRlzLinesCentExact:
    def test_lusso_patroon_laatste_btw_regel_draagt_de_cent(self) -> None:
        voorstel = _voorstel([_regel("15.55", "3.27"), _regel("15.55", "3.27")], "37.63")
        lines = rlz_inkoop.regels_naar_rlz_lines(voorstel)
        assert [line["TaxAmount"] for line in lines] == [3.27, 3.26]
        assert _som(lines) == Decimal("37.63")
        # de module-regels zijn niet aangeraakt
        assert [r.btw_bedrag for r in voorstel.regels] == [Decimal("3.27"), Decimal("3.27")]

    def test_sluitend_of_groot_verschil_stuurt_de_regels_letterlijk(self) -> None:
        exact = _voorstel([_regel("100.00", "21.00")], "121.00")
        assert rlz_inkoop.regels_naar_rlz_lines(exact)[0]["TaxAmount"] == 21.0
        groot = _voorstel([_regel("100.00", "21.00")], "121.90")  # blokkeert al in de checks; hier niet raden
        assert rlz_inkoop.regels_naar_rlz_lines(groot)[0]["TaxAmount"] == 21.0
        zonder_totaal = _voorstel([_regel("100.00", "21.00")], None)
        assert rlz_inkoop.regels_naar_rlz_lines(zonder_totaal)[0]["TaxAmount"] == 21.0

    def test_verlegd_regel_none_blijft_nul_en_wordt_nooit_de_drager(self) -> None:
        voorstel = _voorstel([_regel("100.00", "21.00"), _regel("23.23", None)], "144.26")
        lines = rlz_inkoop.regels_naar_rlz_lines(voorstel)
        assert [line["TaxAmount"] for line in lines] == [21.03, 0.0]
        assert _som(lines) == Decimal("144.26")

    def test_tegenboeking_spiegelt_dezelfde_sluitende_reeks(self) -> None:
        voorstel = _voorstel([_regel("15.55", "3.27"), _regel("15.55", "3.27")], "37.63")
        lines = rlz_inkoop.tegenboek_lines(voorstel, "storno")
        assert [line["TaxAmount"] for line in lines] == [-3.27, -3.26]
        assert _som(lines) == Decimal("-37.63")
