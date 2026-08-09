from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text

from app.db.session import scoped_session
from app.documenten import service as documenten_service
from app.documenten.models import DocumentGebeurtenis, DocumentSoort, DocumentStatus
from app.documenten.storage import LokaleBestandsopslag
from app.omzet import voorstel as voorstel_service
from app.rlz.client import RlzApiError
from tests.auth.conftest import actieve_gebruiker, administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401

# BLOW-achtig margerapport (mockup #omzetreview) — de vaste testdata voor de omzet-tests.
RAPPORT_VELDVOORSTEL: dict[str, Any] = {
    "soort": "kassarapport",
    "rapport_titel": "Margerapport",
    "entiteit_naam": "BLOW B.V.",
    "periode_start": "2025-09-15",
    "periode_eind": "2025-09-21",
    "totaal_omzet": "22463.36",
    "totaal_kostprijs": "14017.29",
    "marge_pct": "160.3",
    "zekerheden": {"periode_start": 0.98, "periode_eind": 0.98, "totaal_omzet": 0.99, "totaal_kostprijs": 0.99},
    "regels": [
        {"categorie": "1. Weed", "omzet_bedrag": "13655.33", "kostprijs_bedrag": "8585.32", "zekerheid": 0.99},
        {"categorie": "2. Hash", "omzet_bedrag": "4706.97", "kostprijs_bedrag": "2668.82", "zekerheid": 0.99},
        {"categorie": "3. Joints", "omzet_bedrag": "2345.68", "kostprijs_bedrag": "1627.90", "zekerheid": 0.98},
        {"categorie": "4. Edibles", "omzet_bedrag": "315.00", "kostprijs_bedrag": "280.85", "zekerheid": 0.97},
        {"categorie": "Weed Prepacked", "omzet_bedrag": "1440.38", "kostprijs_bedrag": "854.40", "zekerheid": 0.98},
    ],
    "regelsom_omzet": {
        "vergelijkbaar": True, "som": "22463.36", "totaal": "22463.36", "verschil": "0.00", "sluit": True,
    },
    "regelsom_kostprijs": {
        "vergelijkbaar": True, "som": "14017.29", "totaal": "14017.29", "verschil": "0.00", "sluit": True,
    },
    "onparseerbaar": [],
    "bsn_verwijderd": 0,
}

PERIODE_START = date(2025, 9, 15)
PERIODE_EIND = date(2025, 9, 21)


@pytest.fixture
def kassarapport_document(
    gescoopte_gebruiker: uuid.UUID,  # noqa: F811
    administratie_id: uuid.UUID,  # noqa: F811
    opslag: LokaleBestandsopslag,  # noqa: F811
) -> uuid.UUID:
    """Een geüpload kassarapport met het vaste veldvoorstel in de tijdlijn (de AVG-gate staat in
    tests uit — de AI-extractie draait dus niet; het voorstel wordt hier rechtstreeks als
    tijdlijn-gebeurtenis toegevoegd, zoals de rapport-extractie dat zou doen)."""
    resultaat = documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="MargeRapport-wk38.pdf",
        inhoud=b"%PDF-1.4 kassarapport",
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
        soort=DocumentSoort.KASSARAPPORT,
    )
    voeg_veldvoorstel_toe(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=gescoopte_gebruiker,
        veldvoorstel=RAPPORT_VELDVOORSTEL,
    )
    return resultaat.document_id


def voeg_veldvoorstel_toe(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, veldvoorstel: dict  # noqa: F811
) -> None:
    """Simuleert de rapport-extractie-uitkomst: een tijdlijn-rij met het veldvoorstel-detail
    (zelfde sleutel als de echte extractie), zonder statuswijziging."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        session.add(
            DocumentGebeurtenis(
                id=uuid.uuid4(),
                document_id=document_id,
                van_status=DocumentStatus.TE_CONTROLEREN,
                naar_status=DocumentStatus.TE_CONTROLEREN,
                actor_id=actor_id,
                detail={"veldvoorstel": veldvoorstel},
            )
        )


def sla_compleet_voorstel_op(
    *,
    administratie_id: uuid.UUID,  # noqa: F811
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    omzet_ledger_id: uuid.UUID,
    taxrate_id: uuid.UUID,
    kostprijs_ledger_id: uuid.UUID,
    voorraad_ledger_id: uuid.UUID,
) -> voorstel_service.OmzetVoorstelData:
    """Volledig gemapt voorstel (alle vijf de BLOW-categorieën op dezelfde GB/btw/kostprijs) —
    de kortste route naar een boekbaar document in de motor-tests."""
    prefill = voorstel_service.haal_omzet_voorstel_op(
        administratie_id=administratie_id, document_id=document_id
    )
    return voorstel_service.sla_omzet_voorstel_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        periode_start=prefill.periode_start,
        periode_eind=prefill.periode_eind,
        rapport_totaal_omzet=prefill.rapport_totaal_omzet,
        rapport_totaal_kostprijs=prefill.rapport_totaal_kostprijs,
        regels=[
            voorstel_service.OmzetRegelInput(
                categorie=r.categorie,
                omzet_bedrag=r.omzet_bedrag,
                kostprijs_bedrag=r.kostprijs_bedrag,
                omzet_ledger_id=omzet_ledger_id,
                taxrate_id=taxrate_id,
                kostprijs_ledger_id=kostprijs_ledger_id,
            )
            for r in prefill.regels
        ],
        voorraad_ledger_id=voorraad_ledger_id,
    )


class FakeOmzetClient:
    """Duck-typed vervanger van RlzClient voor de omzet-boekmotor-tests (geen echte HTTP).
    Simuleert het geverifieerde STAP 0- en Receipts-verkenning-gedrag: SalesInvoice-PUT kent
    auto-InvoiceNumbers toe (te laag startend = de nummer-botsing uit de PoC), entity-loos
    boeken kan (Receipt), de Receipts-collectie ziet API-documenten en is op Description
    filterbaar, boeken van een niet-sluitend memoriaal weigert, actie 19 zet Status terug
    naar 1."""

    # Read-only geverifieerd 2026-08-09: 4 DocumentType-10-categorieën per administratie,
    # naam "Verkoopfactuur (Omzet)" is daarbinnen uniek.
    DOCUMENT_CATEGORIES = [
        {"id": "1e2fb935-08b3-4547-aee7-07a6c3c160a2", "Name": "Diverse opbrengsten", "DocumentType": 10},
        {"id": "1b65bc7a-6af1-492a-a8db-f1ae75dbdf2a", "Name": "Door te belasten kosten", "DocumentType": 10},
        {"id": "9138fa50-d8be-4b6f-9d39-ce5bb2e67f86", "Name": "Verkoopfactuur (Omzet)", "DocumentType": 10},
        {"id": "f86654c6-bc80-421c-b0ce-2dcae4c0a491", "Name": "Kasomzet", "DocumentType": 19},
    ]

    def __init__(
        self,
        *,
        faal_op: str | None = None,
        nummer_botsing: bool = False,
        collectie_max_nummer: int = 371,
        memoriaal_duplicaten: list[dict[str, Any]] | None = None,
        receipt_duplicaten: list[dict[str, Any]] | None = None,
    ) -> None:
        self.faal_op = faal_op
        self.nummer_botsing = nummer_botsing
        self.collectie_max_nummer = collectie_max_nummer
        self.memoriaal_duplicaten = memoriaal_duplicaten or []
        self.receipt_duplicaten = receipt_duplicaten or []
        self.customers: dict[str, dict[str, Any]] = {}
        self.sales_invoices: dict[str, dict[str, Any]] = {}
        self.manual_journals: dict[str, dict[str, Any]] = {}
        self.uploads: list[dict[str, Any]] = []
        self.correcties: list[str] = []
        self._auto_nummer = 0
        self.gesloten = False

    # -- contextmanager/verbinding ---------------------------------------------------------------
    def __enter__(self) -> FakeOmzetClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self.gesloten = True

    def for_administration(self, admin_id: str) -> FakeOmzetClient:
        return self

    # -- debiteur (niet meer door de omzetmotor gebruikt — entity-loze Receipts sinds besluit
    # 2026-08-08; blijft voor de Vastly-verkooproute die wél een debiteur kent) -------------------
    def put_customer(self, customer_id: uuid.UUID, *, name: str) -> None:
        if self.faal_op == "customer":
            raise RlzApiError(500, "PUT", f"Customers/{customer_id}", "Onverwachte fout (simulatie)")
        self.customers[str(customer_id)] = {"id": str(customer_id), "Name": name}

    # -- verkoopboeking (SalesInvoice mét debiteur of entity-loze Receipt) ------------------------
    def list_document_categories(self) -> list[dict[str, Any]]:
        if self.faal_op == "categorieen":
            raise RlzApiError(500, "GET", "DocumentCategories", "Onverwachte fout (simulatie)")
        return list(self.DOCUMENT_CATEGORIES)

    def put_sales_invoice(
        self,
        invoice_id: uuid.UUID,
        *,
        customer_id: uuid.UUID | None,
        lines: list[dict],
        document_category_id: uuid.UUID | None = None,
        **extra: Any,
    ) -> None:
        if self.faal_op == "verkoop_put":
            raise RlzApiError(500, "PUT", f"SalesInvoices/{invoice_id}", "Onverwachte fout (simulatie)")
        nummer = extra.get("InvoiceNumber")
        if nummer is None:
            self._auto_nummer += 1
            nummer = self._auto_nummer
        bestaand = self.sales_invoices.get(str(invoice_id)) or {}
        self.sales_invoices[str(invoice_id)] = {
            "id": str(invoice_id),
            "Status": bestaand.get("Status", 1),
            "InvoiceNumber": nummer,
            "Reference": f"RLZ-{nummer}",
            "ReceiptNumber": "RLZ-01-00000393",
            "Entity": {"id": str(customer_id)} if customer_id is not None else None,
            "DocumentCategory": {"id": str(document_category_id)} if document_category_id is not None else None,
            # Verkoop-STAP-0 (2026-08-09): RLZ negeert de document-Description en leidt 'm af
            # uit de éérste regel-Description — de fake bootst dat gedrag exact na.
            "Description": (lines[0].get("Description") if lines else None),
            "DocumentLineList": lines,
            "Date": extra.get("Date"),
        }

    def get_sales_invoice(self, invoice_id: uuid.UUID | str) -> dict[str, Any]:
        record = self.sales_invoices.get(str(invoice_id))
        if record is None:
            raise RlzApiError(404, "GET", f"SalesInvoices/{invoice_id}", "Niet gevonden (simulatie)")
        return record

    def book_sales_invoice(self, invoice_id: uuid.UUID) -> None:
        if self.faal_op == "verkoop_boeken":
            raise RlzApiError(500, "POST", f"SalesInvoices/{invoice_id}/Actions", "Onverwachte fout (simulatie)")
        record = self.sales_invoices[str(invoice_id)]
        if self.nummer_botsing and record["InvoiceNumber"] <= self.collectie_max_nummer:
            raise RlzApiError(
                400,
                "POST",
                f"SalesInvoices/{invoice_id}/Actions",
                '{"Message":"Dit factuurnummer is al in gebruik"}',
            )
        record["Status"] = 2

    def correct_sales_invoice(self, invoice_id: uuid.UUID) -> None:
        if self.faal_op == "storno_verkoop":
            raise RlzApiError(500, "POST", f"SalesInvoices/{invoice_id}/Actions", "Storno mislukt (simulatie)")
        self.correcties.append(str(invoice_id))
        self.sales_invoices[str(invoice_id)]["Status"] = 1

    def max_sales_invoice_number(self) -> int:
        return self.collectie_max_nummer

    # -- memoriaal --------------------------------------------------------------------------------
    def list_journal_entry_diaries(self) -> list[dict[str, Any]]:
        return [
            {"id": "469b9437-72f8-4cf9-be16-8a20967e5388", "Description": "Afschrijvingen van vaste activa"},
            {
                "id": "b4407a30-6f3d-f7f6-be6c-e2a8ba43ab1e",
                "Description": "Systeemboek voor Algemene Memoriaalboekingen",
            },
        ]

    def put_manual_journal(
        self, journal_id: uuid.UUID, *, diary_id: uuid.UUID, lines: list[dict], auto_correct: bool = False, **extra: Any
    ) -> None:
        if self.faal_op == "memoriaal_put":
            raise RlzApiError(500, "PUT", f"ManualJournals/{journal_id}", "Onverwachte fout (simulatie)")
        debet = sum(r.get("DebitAmount") or 0 for r in lines)
        credit = sum(r.get("CreditAmount") or 0 for r in lines)
        bestaand = self.manual_journals.get(str(journal_id)) or {}
        self.manual_journals[str(journal_id)] = {
            "id": str(journal_id),
            "Status": bestaand.get("Status", 1),
            "Reference": extra.get("Reference"),
            "ReceiptNumber": "RLZ-06-00000502",
            "BalanceAmount": credit - debet,
            "JournalEntryDiary": {"id": str(diary_id)},
            "DocumentLineList": lines,
            "Date": extra.get("Date"),
        }

    def get_manual_journal(self, journal_id: uuid.UUID | str) -> dict[str, Any]:
        record = self.manual_journals.get(str(journal_id))
        if record is None:
            raise RlzApiError(404, "GET", f"ManualJournals/{journal_id}", "Niet gevonden (simulatie)")
        return record

    def book_manual_journal(self, journal_id: uuid.UUID) -> None:
        if self.faal_op == "memoriaal_boeken":
            raise RlzApiError(500, "POST", f"ManualJournals/{journal_id}/Actions", "Onverwachte fout (simulatie)")
        record = self.manual_journals[str(journal_id)]
        if record["BalanceAmount"] != 0:
            # STAP 0 §4: RLZ weigert een niet-sluitend memoriaal bij actie 17.
            raise RlzApiError(
                400,
                "POST",
                f"ManualJournals/{journal_id}/Actions",
                '{"Message":"De credit- en debetbedragen van de regels zijn niet aan elkaar gelijk"}',
            )
        record["Status"] = 3

    def correct_manual_journal(self, journal_id: uuid.UUID) -> None:
        self.correcties.append(str(journal_id))
        self.manual_journals[str(journal_id)]["Status"] = 1

    def find_manual_journals_by_reference(self, *, reference: str) -> list[dict[str, Any]]:
        if self.faal_op == "duplicaatcheck":
            raise RlzApiError(500, "GET", "ManualJournals", "Onverwachte fout (simulatie)")
        eigen = [m for m in self.manual_journals.values() if m.get("Reference") == reference]
        return self.memoriaal_duplicaten + eigen

    def find_receipts_by_description_prefix(self, *, prefix: str) -> list[dict[str, Any]]:
        """Receipts-verkenning §1 + verkoop-STAP-0 (2026-08-09): de collectie ziet óók
        API-aangemaakte documenten en is op Description filterbaar (incl. startswith); RLZ
        leidt de document-Description af uit de éérste regel-Description — deze fake bootst
        dat af in put_sales_invoice."""
        if self.faal_op == "receipts_duplicaatcheck":
            raise RlzApiError(500, "GET", "Receipts", "Onverwachte fout (simulatie)")
        eigen = [s for s in self.sales_invoices.values() if (s.get("Description") or "").startswith(prefix)]
        vooraf = [r for r in self.receipt_duplicaten if (r.get("Description") or "").startswith(prefix)]
        return vooraf + eigen

    # -- gedeeld ----------------------------------------------------------------------------------
    def upload_bijlage(
        self, entity_path: str, entity_id: uuid.UUID, *, upload_id: uuid.UUID, filename: str, content_base64: str
    ) -> None:
        if self.faal_op == f"upload_{entity_path}":
            raise RlzApiError(500, "PUT", f"{entity_path}/{entity_id}/Uploads", "Upload mislukt (simulatie)")
        self.uploads.append({"pad": entity_path, "entity_id": str(entity_id), "upload_id": str(upload_id)})

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Voor de reconciliatie (raw GET op SalesInvoices/{id} / ManualJournals/{id})."""
        soort, _, doc_id = path.partition("/")
        bron = self.sales_invoices if soort == "SalesInvoices" else self.manual_journals
        record = bron.get(doc_id)
        if record is None:
            raise RlzApiError(404, "GET", path, "Niet gevonden (simulatie)")
        return record


@pytest.fixture
def taxrate_vrijgesteld(administratie_id: uuid.UUID) -> uuid.UUID:  # noqa: F811
    """Een btw-code zonder percentage (vrijgesteld — BLOW-case): geen btw-splitsing."""
    taxrate_id = uuid.uuid4()
    with scoped_session(administratie_id) as session:
        from app.sync.models import TaxRateCache

        session.add(
            TaxRateCache(
                id=taxrate_id,
                administratie_id=administratie_id,
                naam="NL, Geen BTW (Vrijgesteld)",
                percentage=Decimal("0"),
                brondata={},
            )
        )
    return taxrate_id


@pytest.fixture
def boeken_aan(beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:  # noqa: F811
    from app.beheer import service as beheer_service

    beheer_service.zet_boeken_ingeschakeld(
        actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
    )


def document_status(administratie_id: uuid.UUID, document_id: uuid.UUID) -> str:  # noqa: F811
    with scoped_session(administratie_id) as session:
        return session.execute(
            text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}
        ).scalar_one()
