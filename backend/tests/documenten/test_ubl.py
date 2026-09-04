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


def test_rlz_export_ubl_leest_partijnamen_uit_partyname() -> None:
    """Parser-gap 02-09: RLZ's eigen UBL-export (SI-UBL 1.1-vorm) zet de namen in cac:PartyName/cbc:Name
    en heeft in PartyLegalEntity alleen een KvK-CompanyID — 97 IC-facturen stonden daardoor zonder
    tenaamstelling in de verzamelbak. Fixture = geanonimiseerde échte export (structuur 1-op-1)."""
    from pathlib import Path

    from app.documenten.ubl import lees_ingesloten_pdf

    inhoud = (Path(__file__).parents[1] / "intake" / "fixtures" / "rlz_export_ubl.xml").read_bytes()
    voorstel = parseer_ubl_factuur(inhoud)
    assert voorstel.klant_naam == "BLOW B.V."
    assert voorstel.leverancier_naam == "Universal Nederland B.V."
    assert voorstel.factuurnummer == "RLZ-2080143001"
    assert voorstel.totaal_incl == "6655.00"
    assert voorstel.regelaantal == 1
    ingesloten = lees_ingesloten_pdf(inhoud)
    assert ingesloten is not None and ingesloten.bestandsnaam == "factuur.pdf"
    assert ingesloten.inhoud.startswith(b"%PDF")


def test_registrationname_wint_van_partyname() -> None:
    """EN 16931-vorm blijft leidend: staat er een RegistrationName, dan telt PartyName/Name niet mee
    (handelsnaam ≠ statutaire naam); Contact/Name is nooit een bron (dat is een persoon)."""
    ubl = _VOORBEELD_UBL.replace(
        b"<cac:PartyLegalEntity>",
        b"<cac:PartyName><cbc:Name>Bouwmaat</cbc:Name></cac:PartyName>"
        b"<cac:Contact><cbc:Name>J. Jansen</cbc:Name></cac:Contact><cac:PartyLegalEntity>",
    )
    assert parseer_ubl_factuur(ubl).leverancier_naam == "Bouwmaat Nederland B.V."
    alleen_contact = _VOORBEELD_UBL.replace(
        b"<cac:PartyLegalEntity>\n        <cbc:RegistrationName>Bouwmaat Nederland B.V.</cbc:RegistrationName>\n"
        b"      </cac:PartyLegalEntity>",
        b"<cac:Contact><cbc:Name>J. Jansen</cbc:Name></cac:Contact>",
    )
    assert parseer_ubl_factuur(alleen_contact).leverancier_naam is None


_KORTING_UBL = _VOORBEELD_UBL.replace(
    b"  <cac:LegalMonetaryTotal>",
    b"""  <cac:AllowanceCharge>
    <cbc:ChargeIndicator>false</cbc:ChargeIndicator>
    <cbc:AllowanceChargeReason>Korting 10%</cbc:AllowanceChargeReason>
    <cbc:Amount currencyID="EUR">56.44</cbc:Amount>
    <cac:TaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>21.00</cbc:Percent></cac:TaxCategory>
  </cac:AllowanceCharge>
  <cac:AllowanceCharge>
    <cbc:ChargeIndicator>true</cbc:ChargeIndicator>
    <cbc:Amount currencyID="EUR">12.50</cbc:Amount>
  </cac:AllowanceCharge>
  <cac:LegalMonetaryTotal>""",
)


def test_document_korting_wordt_negatieve_regel_en_toeslag_positief() -> None:
    """Bugfix 04-09 (Huvanco): een korting op documentniveau (cac:AllowanceCharge, ChargeIndicator
    false) is een eigen regel met negatief netto; een toeslag (true) een positieve regel."""
    voorstel = parseer_ubl_factuur(_KORTING_UBL)
    assert voorstel.regelaantal == 4
    korting, toeslag = voorstel.ubl_regels[2], voorstel.ubl_regels[3]
    assert korting["volgnummer"] == 3 and korting["soort"] == "korting"
    assert korting["omschrijving"] == "Korting 10%" and korting["netto_bedrag"] == "-56.44"
    assert korting["btw_categorie"] == "S" and korting["btw_percentage"] == "21.00"
    assert toeslag["volgnummer"] == 4 and toeslag["soort"] == "toeslag"
    assert toeslag["omschrijving"] == "Toeslag" and toeslag["netto_bedrag"] == "12.50"
    # Gewone regels blijven soort None (geen gedragsverandering voor bestaande consumenten).
    assert voorstel.ubl_regels[0]["soort"] is None


def test_regelniveau_korting_wordt_niet_dubbel_geteld() -> None:
    """LineExtensionAmount is per UBL-definitie al netto ná regelkorting — een AllowanceCharge bínnen
    een InvoiceLine mag dus nooit een extra regel worden (de RLZ-export-fixture heeft er zo één)."""
    from pathlib import Path

    inhoud = (Path(__file__).parents[1] / "intake" / "fixtures" / "rlz_export_ubl.xml").read_bytes()
    voorstel = parseer_ubl_factuur(inhoud)
    assert voorstel.regelaantal == 1
    assert all(r["soort"] is None for r in voorstel.ubl_regels)


def test_allowance_charge_zonder_bedrag_of_indicator_geeft_geen_regel() -> None:
    kapot = _VOORBEELD_UBL.replace(
        b"  <cac:LegalMonetaryTotal>",
        b"<cac:AllowanceCharge><cbc:ChargeIndicator>false</cbc:ChargeIndicator></cac:AllowanceCharge>"
        b"<cac:AllowanceCharge><cbc:Amount>5.00</cbc:Amount></cac:AllowanceCharge>"
        b"  <cac:LegalMonetaryTotal>",
    )
    assert parseer_ubl_factuur(kapot).regelaantal == 2
