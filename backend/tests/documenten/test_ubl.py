from __future__ import annotations

import pytest

from app.documenten.ubl import GeenGeldigeUbl, parseer_ubl_factuur

_VOORBEELD_UBL = b"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
  <cbc:ID>2026-0642</cbc:ID>
  <cbc:IssueDate>2026-06-29</cbc:IssueDate>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyLegalEntity>
        <cbc:RegistrationName>Bouwmaat Nederland B.V.</cbc:RegistrationName>
      </cac:PartyLegalEntity>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:LegalMonetaryTotal>
    <cbc:TaxExclusiveAmount currencyID="EUR">1526.20</cbc:TaxExclusiveAmount>
    <cbc:PayableAmount currencyID="EUR">1846.70</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  <cac:InvoiceLine><cbc:ID>1</cbc:ID></cac:InvoiceLine>
  <cac:InvoiceLine><cbc:ID>2</cbc:ID></cac:InvoiceLine>
</Invoice>
"""


def test_parseert_volledige_ubl_factuur() -> None:
    voorstel = parseer_ubl_factuur(_VOORBEELD_UBL)
    assert voorstel.factuurnummer == "2026-0642"
    assert voorstel.factuurdatum == "2026-06-29"
    assert voorstel.valuta == "EUR"
    assert voorstel.totaal_excl == "1526.20"
    assert voorstel.totaal_incl == "1846.70"
    assert voorstel.leverancier_naam == "Bouwmaat Nederland B.V."
    assert voorstel.regelaantal == 2


def test_als_dict_geeft_platte_dict() -> None:
    voorstel = parseer_ubl_factuur(_VOORBEELD_UBL)
    d = voorstel.als_dict()
    assert d["factuurnummer"] == "2026-0642"
    assert d["regelaantal"] == 2


def test_ongeldige_xml_faalt() -> None:
    with pytest.raises(GeenGeldigeUbl, match="Geen geldige XML"):
        parseer_ubl_factuur(b"dit is geen xml")


def test_xml_zonder_ubl_velden_faalt() -> None:
    with pytest.raises(GeenGeldigeUbl, match="Geen UBL-Invoice-velden"):
        parseer_ubl_factuur(b"<root><iets>anders</iets></root>")


def test_doctype_wordt_geweigerd() -> None:
    kwaadaardig = (
        b'<?xml version="1.0"?><!DOCTYPE Invoice [<!ENTITY x "bom">]>'
        b'<Invoice xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">'
        b"<cbc:ID>&x;</cbc:ID></Invoice>"
    )
    with pytest.raises(GeenGeldigeUbl, match="DOCTYPE"):
        parseer_ubl_factuur(kwaadaardig)
