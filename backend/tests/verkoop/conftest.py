"""Fixtures voor het Vastly-verkoopfactuur-boekpad (koppelcontract §2d v1.10/v1.11).

De UBL-builders hier zijn GOLDEN-CASE-testinput exact conform §2d: markering
`VASTLY-VERKOOP` + DocumentDescription, `cbc:AccountingCost` per regel (BT-133, optioneel
BT-19 op documentniveau), `cac:ClassifiedTaxCategory` per regel, en voor de creditnota (381)
een eigen CreditNote-root mét `cac:BillingReference`-herleiding. NB: échte Vastly-UBL's lagen
bij de bouw nog niet in Platform/uitwisseling — verificatie tegen echte golden-cases van
vastgoed is een genoteerd open punt (zie docs/BESLISSINGEN.md)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest

from app.db.models import Grootboekrekening
from app.db.session import scoped_session
from app.documenten import service as documenten_service
from app.documenten.models import DocumentSoort
from app.documenten.storage import LokaleBestandsopslag
from app.sync.models import TaxRateCache
from tests.auth.conftest import actieve_gebruiker, administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401
from tests.omzet.conftest import FakeOmzetClient, boeken_aan  # noqa: F401

OMZET_LEDGER_ID = uuid.UUID("11111111-1111-1111-1111-111111111101")
TOTAAL_LEDGER_ID = uuid.UUID("11111111-1111-1111-1111-111111111102")
TAXRATE_21_ID = uuid.UUID("22222222-2222-2222-2222-222222222221")
TAXRATE_0_ID = uuid.UUID("22222222-2222-2222-2222-222222222220")


def _regel_xml(
    *, element: str, volgnummer: int, naam: str, netto: str, pct: str, categorie: str, gb_code: str | None
) -> str:
    hoeveelheid = "cbc:CreditedQuantity" if element == "CreditNoteLine" else "cbc:InvoicedQuantity"
    gb = f"<cbc:AccountingCost>{gb_code}</cbc:AccountingCost>" if gb_code else ""
    return f"""<cac:{element}>
    <cbc:ID>{volgnummer}</cbc:ID>
    <{hoeveelheid} unitCode="C62">1</{hoeveelheid}>
    <cbc:LineExtensionAmount currencyID="EUR">{netto}</cbc:LineExtensionAmount>
    {gb}
    <cac:Item>
      <cbc:Name>{naam}</cbc:Name>
      <cac:ClassifiedTaxCategory>
        <cbc:ID>{categorie}</cbc:ID>
        <cbc:Percent>{pct}</cbc:Percent>
        <cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>
      </cac:ClassifiedTaxCategory>
    </cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="EUR">{netto}</cbc:PriceAmount></cac:Price>
  </cac:{element}>"""


def bouw_vastly_verkoop_ubl(
    *,
    factuurnummer: str = "VF-2026-0042",
    leverancier: str = "Rubicon Investments B.V.",
    huurder: str = "J. van den Berg",
    datum: str = "2026-08-01",
    regels: list[dict[str, Any]] | None = None,
    markering: str | None = "VASTLY-VERKOOP",
    document_gb_code: str | None = None,
) -> bytes:
    """UBL 2.1 Invoice (380) exact conform §2d: markering in AdditionalDocumentReference,
    AccountingCost per regel (BT-133). Default: één huurregel € 1.000 + 21% = € 1.210."""
    regels = regels if regels is not None else [
        {"naam": "Huur augustus 2026", "netto": "1000.00", "pct": "21.00", "categorie": "S", "gb_code": "8000"},
    ]
    netto_som = sum(Decimal(r["netto"]) for r in regels)
    btw_som = sum((Decimal(r["netto"]) * Decimal(r["pct"]) / 100).quantize(Decimal("0.01")) for r in regels)
    adr = (
        f"""<cac:AdditionalDocumentReference>
    <cbc:ID>{markering}</cbc:ID>
    <cbc:DocumentDescription>Verkoopfactuur uit Vastly (omzet); geen VGB-inkoopdocument</cbc:DocumentDescription>
  </cac:AdditionalDocumentReference>"""
        if markering
        else ""
    )
    doc_gb = f"<cbc:AccountingCost>{document_gb_code}</cbc:AccountingCost>" if document_gb_code else ""
    regel_xml = "".join(
        _regel_xml(element="InvoiceLine", volgnummer=i, **r) for i, r in enumerate(regels, start=1)
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
  <cbc:ID>{factuurnummer}</cbc:ID>
  <cbc:IssueDate>{datum}</cbc:IssueDate>
  <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  {doc_gb}
  {adr}
  <cac:AccountingSupplierParty><cac:Party><cac:PartyLegalEntity>
    <cbc:RegistrationName>{leverancier}</cbc:RegistrationName>
  </cac:PartyLegalEntity></cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party><cac:PartyLegalEntity>
    <cbc:RegistrationName>{huurder}</cbc:RegistrationName>
  </cac:PartyLegalEntity></cac:Party></cac:AccountingCustomerParty>
  <cac:TaxTotal><cbc:TaxAmount currencyID="EUR">{btw_som}</cbc:TaxAmount></cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:TaxExclusiveAmount currencyID="EUR">{netto_som}</cbc:TaxExclusiveAmount>
    <cbc:PayableAmount currencyID="EUR">{netto_som + btw_som}</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  {regel_xml}
</Invoice>"""
    return xml.encode()


def bouw_vastly_creditnote_ubl(
    *,
    factuurnummer: str = "VF-2026-0042-C1",
    gecrediteerd_factuurnummer: str | None = "VF-2026-0042",
    leverancier: str = "Rubicon Investments B.V.",
    huurder: str = "J. van den Berg",
    datum: str = "2026-08-05",
    regels: list[dict[str, Any]] | None = None,
    markering: str | None = "VASTLY-VERKOOP",
) -> bytes:
    """UBL 2.1 CreditNote (documenttype 381, §2d-creditnota's v1.11): apart CreditNote-document
    mét dezelfde VASTLY-VERKOOP-markering + BillingReference zonder IssueDate (BR-NL-24)."""
    regels = regels if regels is not None else [
        {"naam": "Correctie huur augustus 2026", "netto": "1000.00", "pct": "21.00", "categorie": "S",
         "gb_code": "8000"},
    ]
    netto_som = sum(Decimal(r["netto"]) for r in regels)
    btw_som = sum((Decimal(r["netto"]) * Decimal(r["pct"]) / 100).quantize(Decimal("0.01")) for r in regels)
    adr = (
        f"""<cac:AdditionalDocumentReference>
    <cbc:ID>{markering}</cbc:ID>
    <cbc:DocumentDescription>Verkoopfactuur uit Vastly (omzet); geen VGB-inkoopdocument</cbc:DocumentDescription>
  </cac:AdditionalDocumentReference>"""
        if markering
        else ""
    )
    billing = (
        f"""<cac:BillingReference><cac:InvoiceDocumentReference>
    <cbc:ID>{gecrediteerd_factuurnummer}</cbc:ID>
  </cac:InvoiceDocumentReference></cac:BillingReference>"""
        if gecrediteerd_factuurnummer
        else ""
    )
    regel_xml = "".join(
        _regel_xml(element="CreditNoteLine", volgnummer=i, **r) for i, r in enumerate(regels, start=1)
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<CreditNote xmlns="urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
            xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
            xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
  <cbc:ID>{factuurnummer}</cbc:ID>
  <cbc:IssueDate>{datum}</cbc:IssueDate>
  <cbc:CreditNoteTypeCode>381</cbc:CreditNoteTypeCode>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  {billing}
  {adr}
  <cac:AccountingSupplierParty><cac:Party><cac:PartyLegalEntity>
    <cbc:RegistrationName>{leverancier}</cbc:RegistrationName>
  </cac:PartyLegalEntity></cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party><cac:PartyLegalEntity>
    <cbc:RegistrationName>{huurder}</cbc:RegistrationName>
  </cac:PartyLegalEntity></cac:Party></cac:AccountingCustomerParty>
  <cac:TaxTotal><cbc:TaxAmount currencyID="EUR">{btw_som}</cbc:TaxAmount></cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:TaxExclusiveAmount currencyID="EUR">{netto_som}</cbc:TaxExclusiveAmount>
    <cbc:PayableAmount currencyID="EUR">{netto_som + btw_som}</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  {regel_xml}
</CreditNote>"""
    return xml.encode()


@pytest.fixture
def rekeningschema(administratie_id: uuid.UUID) -> None:  # noqa: F811
    """Rekeningschema + btw-cache voor de GB-code- en btw-resolutie: code 8000 (opbrengsten,
    boekbaar), code 0800 (totaalrekening — nooit boekbaar), 21% (uniek) en 0%."""
    with scoped_session(administratie_id) as session:
        session.add(
            Grootboekrekening(
                ledger_id=OMZET_LEDGER_ID, administratie_id=administratie_id,
                code="8000", naam="Omzet 1", soort=1, is_totaalrekening=False,
            )
        )
        session.add(
            Grootboekrekening(
                ledger_id=TOTAAL_LEDGER_ID, administratie_id=administratie_id,
                code="0800", naam="Totaal omzet", soort=1, is_totaalrekening=True,
            )
        )
        session.add(
            TaxRateCache(
                id=TAXRATE_21_ID, administratie_id=administratie_id,
                naam="21% NL", percentage=Decimal("21.00"), brondata={},
            )
        )
        session.add(
            TaxRateCache(
                id=TAXRATE_0_ID, administratie_id=administratie_id,
                naam="NL, Geen BTW (Vrijgesteld)", percentage=Decimal("0.00"), brondata={},
            )
        )


def upload_verkoopfactuur(
    *,
    administratie_id: uuid.UUID,  # noqa: F811
    actor_id: uuid.UUID,
    opslag: LokaleBestandsopslag,  # noqa: F811
    inhoud: bytes,
    bestandsnaam: str = "vastly-verkoop.xml",
) -> uuid.UUID:
    """Upload als verkoopfactuur — de echte UBL-parser draait in de synchrone extractie en zet
    het veldvoorstel (incl. ubl_regels/is_creditnota) in de tijdlijn."""
    resultaat = documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=bestandsnaam,
        inhoud=inhoud,
        actor_id=actor_id,
        opslag=opslag,
        soort=DocumentSoort.VERKOOPFACTUUR,
    )
    return resultaat.document_id


class FakeVerkoopClient(FakeOmzetClient):
    """FakeOmzetClient + de debiteur-leesroute van het verkooppad."""

    def __init__(self, *, bestaande_customers: list[dict[str, Any]] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.bestaande_customers = bestaande_customers or []

    def find_customers_by_name(self, *, name: str) -> list[dict[str, Any]]:
        if self.faal_op == "customer_lookup":
            from app.rlz.client import RlzApiError

            raise RlzApiError(500, "GET", "Customers", "Onverwachte fout (simulatie)")
        vooraf = [c for c in self.bestaande_customers if c.get("Name") == name]
        eigen = [c for c in self.customers.values() if c.get("Name") == name]
        return vooraf + eigen
