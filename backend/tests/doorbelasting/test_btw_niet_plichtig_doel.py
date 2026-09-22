"""Doorbelasting-spiegel in een NIET-btw-plichtige doel-administratie (BUG Peter 22-09, casus VGG / Lacy Lion): de spec
gaat incl. btw als kosten (netto := netto + btw, btw 0) — één spec voor RLZ-regels én webhook — en de regels dragen de
"geen btw"-code van het doel of géén TaxRate. Btw-plichtig doel = ongewijzigd. Puur, geen DB."""

from __future__ import annotations

import uuid
from decimal import Decimal as D

from app.doorbelasting.boeken import _spec_voor_doel, _spiegel_lines_van_spec

LEDGER = uuid.uuid4()
PROJECT = uuid.uuid4()
VRIJ = uuid.uuid4()
HOOG = uuid.uuid4()
SPEC = [
    (LEDGER, D("1000.00"), D("210.00"), "Huur steiger — regel 1", PROJECT),
    (LEDGER, D("50.00"), D("10.50"), "Provisie 5% over nettobedrag", None),
]


def test_btw_plichtig_doel_ongewijzigd() -> None:
    assert _spec_voor_doel(SPEC, doel_btw_plichtig=True) == SPEC
    lines = _spiegel_lines_van_spec(SPEC, btw_taxrate_id=HOOG)
    assert (
        lines[0]["TaxRate"] == {"id": str(HOOG)}
        and lines[0]["TaxAmount"] == 210.0
        and lines[0]["Project"] == {"id": str(PROJECT)}
    )


def test_niet_plichtig_doel_bruto_met_geen_btw_code_of_zonder_taxrate() -> None:
    spec = _spec_voor_doel(SPEC, doel_btw_plichtig=False)
    assert spec == [
        (LEDGER, D("1210.00"), D("0.00"), "Huur steiger — regel 1", PROJECT),
        (LEDGER, D("60.50"), D("0.00"), "Provisie 5% over nettobedrag", None),
    ]
    lines = _spiegel_lines_van_spec(spec, btw_taxrate_id=VRIJ)
    assert lines[0]["NetAmount"] == 1210.0 and lines[0]["TaxAmount"] == 0.0 and lines[0]["TaxRate"] == {"id": str(VRIJ)}
    assert "Project" not in lines[1]
    zonder = _spiegel_lines_van_spec(spec, btw_taxrate_id=None)
    assert all("TaxRate" not in line for line in zonder) and zonder[1]["NetAmount"] == 60.5
