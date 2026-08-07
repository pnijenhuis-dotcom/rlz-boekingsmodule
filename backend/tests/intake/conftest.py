from __future__ import annotations

import io
import uuid
from email.message import EmailMessage

import pytest
from pypdf import PdfWriter
from sqlalchemy import Engine, text

from tests.auth.conftest import actieve_gebruiker, administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401


def bouw_ubl(
    *,
    factuurnummer: str = "F-2026-001",
    leverancier: str = "Bouwmaat Nederland B.V.",
    klant: str | None = "BLOW B.V.",
    adr_id: str | None = None,
    buyer_reference: str | None = None,
    datum: str = "2026-08-01",
    totaal: str = "121.00",
    regels: int = 1,
) -> bytes:
    adr = (
        f"<cac:AdditionalDocumentReference><cbc:ID>{adr_id}</cbc:ID></cac:AdditionalDocumentReference>"
        if adr_id
        else ""
    )
    buyer = f"<cbc:BuyerReference>{buyer_reference}</cbc:BuyerReference>" if buyer_reference else ""
    klant_xml = (
        f"<cac:AccountingCustomerParty><cac:Party><cac:PartyLegalEntity>"
        f"<cbc:RegistrationName>{klant}</cbc:RegistrationName>"
        f"</cac:PartyLegalEntity></cac:Party></cac:AccountingCustomerParty>"
        if klant
        else ""
    )
    regel_xml = "".join(f'<cac:InvoiceLine><cbc:ID>{i}</cbc:ID></cac:InvoiceLine>' for i in range(1, regels + 1))
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
  <cbc:ID>{factuurnummer}</cbc:ID>
  <cbc:IssueDate>{datum}</cbc:IssueDate>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  {buyer}
  {adr}
  <cac:AccountingSupplierParty><cac:Party><cac:PartyLegalEntity>
    <cbc:RegistrationName>{leverancier}</cbc:RegistrationName>
  </cac:PartyLegalEntity></cac:Party></cac:AccountingSupplierParty>
  {klant_xml}
  <cac:LegalMonetaryTotal>
    <cbc:TaxExclusiveAmount currencyID="EUR">100.00</cbc:TaxExclusiveAmount>
    <cbc:PayableAmount currencyID="EUR">{totaal}</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  {regel_xml}
</Invoice>"""
    return xml.encode()


def bouw_pdf(paginas: int = 1) -> bytes:
    schrijver = PdfWriter()
    for _ in range(paginas):
        schrijver.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    schrijver.write(buffer)
    return buffer.getvalue()


def bouw_eml(
    *,
    afzender: str = "administratie@bouwmaat.nl",
    onderwerp: str = "Factuur",
    message_id: str | None = None,
    bijlagen: list[tuple[str, bytes, str, str]] | None = None,
) -> bytes:
    """bijlagen: (bestandsnaam, inhoud, maintype, subtype)."""
    mail = EmailMessage()
    mail["From"] = f"Bouwmaat <{afzender}>"
    mail["To"] = "facturen@kempengroep.nl"
    mail["Subject"] = onderwerp
    mail["Date"] = "Thu, 07 Aug 2026 09:00:00 +0200"
    mail["Message-ID"] = message_id or f"<{uuid.uuid4()}@test.local>"
    mail.set_content("Bijgaand de factuur.")
    for naam, inhoud, maintype, subtype in bijlagen or []:
        mail.add_attachment(inhoud, maintype=maintype, subtype=subtype, filename=naam)
    return mail.as_bytes()


@pytest.fixture
def intake_ai_aan(admin_engine: Engine) -> None:
    """Zet de intake-AI-gate AAN via de platform-instelling (migratie 0029) — de DB-rij is
    leidend, dus een settings-monkeypatch volstaat sinds die migratie niet meer."""
    with admin_engine.begin() as conn:
        conn.execute(text("UPDATE platform.intake_instelling SET ai_ingeschakeld = true"))


@pytest.fixture
def administratie_heet_blow(administratie_id: uuid.UUID, admin_engine: Engine) -> uuid.UUID:  # noqa: F811
    """De testadministratie heet 'BLOW B.V.' — de exacte tenaamstelling-match uit de fixtures."""
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.administratie SET naam = 'BLOW B.V.' WHERE id = :id"),
            {"id": administratie_id},
        )
    return administratie_id
