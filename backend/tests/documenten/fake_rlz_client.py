from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

from app.rlz.client import RlzApiError


class FakeBoekClient:
    """Duck-typed vervanger van RlzClient voor de boek-actie/reconciliatie-unittests (geen
    echte HTTP) — implementeert het contextmanager-protocol (`with client as c:`) omdat
    app/documenten/boeken.py::_rlz_client_voor die vorm gebruikt."""

    def __init__(
        self,
        *,
        duplicaten: list[dict[str, Any]] | None = None,
        faal_op: str | None = None,
        bestaande_invoices: dict[str, dict[str, Any]] | None = None,
        bank_relations: list[dict[str, Any]] | None = None,
        aangiften: list[dict[str, Any]] | None = None,
    ) -> None:
        self.duplicaten = duplicaten or []
        self.faal_op = faal_op
        self.puts: list[dict[str, Any]] = []
        self.uploads: list[dict[str, Any]] = []
        self.geboekte_acties: list[uuid.UUID] = []
        self.gesloten = False
        self._invoices: dict[str, dict[str, Any]] = dict(bestaande_invoices or {})
        # RLZ-seed voor de IBAN-wissel-check (Vendors/{id}/BankRelations) — default leeg: een
        # crediteur zonder bankrelaties, zodat bestaande boek-tests ongewijzigd blijven werken.
        self.bank_relations = bank_relations or []
        # TaxDeclarations-seed voor de aangifte-poort (tegenboek-pad) — default leeg: geen
        # ingediende aangiften, storno vrij.
        self.aangiften = aangiften or []

    def __enter__(self) -> FakeBoekClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self.gesloten = True

    def for_administration(self, admin_id: str) -> FakeBoekClient:
        return self

    def find_purchase_invoices_by_reference(
        self,
        *,
        vendor_id: uuid.UUID | str | None,
        reference: str,
        total_amount: float | None = None,
        expand_entity: bool = False,
    ) -> list[dict[str, Any]]:
        # Punt 14: zonder vendor_id (over crediteuren heen) de aparte lijst `duplicaten_andere_crediteur`
        # (treffers mét Entity) — de gewone `duplicaten` blijven het zelfde-crediteur-domein.
        if vendor_id is None:
            return list(getattr(self, "duplicaten_andere_crediteur", []))
        return self.duplicaten

    def put_purchase_invoice(
        self,
        invoice_id: uuid.UUID,
        *,
        vendor_id: uuid.UUID,
        lines: list[dict],
        reference: str | None = None,
        **extra: Any,
    ) -> SimpleNamespace:
        if self.faal_op == "put":
            raise RlzApiError(500, "PUT", "PurchaseInvoices", "PUT mislukt (simulatie)")
        if self.faal_op == "put_onverwacht":
            raise RuntimeError("Onverwachte fout (simulatie, geen RlzApiError)")
        self.puts.append({"id": invoice_id, "vendor_id": vendor_id, "lines": lines, "reference": reference, **extra})
        bedrag = sum(line["NetAmount"] + line["TaxAmount"] for line in lines)
        self._invoices.setdefault(
            str(invoice_id),
            {
                "Status": 1,
                "ReceiptNumber": f"RLZ-TEST-{len(self.puts):05d}",
                "BaseInvoiceAmount": round(bedrag, 2),
                # Date zoals RLZ 'm teruggeeft (ISO-datetime) — de aangifte-poort toetst erop.
                "Date": extra.get("Date"),
            },
        )
        return SimpleNamespace(status_code=204)

    # Betaalstatus (blok 3 bundel 08-09): RLZ's QuickPaymentSelections per document — vaste labels, keuze wordt op de
    # invoice bewaard zodat een test `client.betaalstatus_gezet` en de readback kan toetsen.
    QUICK_PAYMENT_SELECTIONS: list[dict[str, Any]] = [
        {"id": "d23b7073-16ae-4d9d-9074-40838d6249be", "Description": "Nog te betalen"},
        {"id": "1a7732dc-053c-4ea1-87b9-2e0cb863ea19", "Description": "Wordt automatisch ge\u00efncasseerd"},
        {"id": "6b541fa5-d3ca-4aac-ac8d-9af47bc8aa44", "Description": "Betaald per bank"},
        {"id": "e36aa80c-b13c-4518-a64a-8e0d18bc37f9", "Description": "Betaald met PIN"},
        {"id": "9e5826c0-260c-4e8c-9b65-92da1941b450", "Description": "Betaald met Creditcard"},
        {"id": "739b0ff3-0cac-472f-a081-5cff1f7c06eb", "Description": "Betaald - contant"},
        {"id": "4e13b2db-3522-454f-aa22-1135bd64b0df", "Description": "Verrekend met prive"},
        {"id": "2a51bd39-25c5-44d1-8201-778de9bd055d", "Description": "Verrekend met Rekening Courant"},
    ]

    def list_quick_payment_selections(self, invoice_id: uuid.UUID | str) -> list[dict[str, Any]]:
        if self.faal_op == "quick_payment_selections":
            raise RlzApiError(500, "GET", "QuickPaymentSelections", "Keuzelijst mislukt (simulatie)")
        return list(getattr(self, "quick_payment_selections", self.QUICK_PAYMENT_SELECTIONS))

    def set_quick_payment_selection(
        self, invoice_id: uuid.UUID | str, selection_id: uuid.UUID | str
    ) -> SimpleNamespace:
        if self.faal_op == "quick_payment_selection_put":
            raise RlzApiError(400, "PUT", "PurchaseInvoices", "Betaalstatus zetten mislukt (simulatie)")
        if not hasattr(self, "betaalstatus_gezet"):
            self.betaalstatus_gezet: list[dict[str, Any]] = []
        self.betaalstatus_gezet.append({"id": str(invoice_id), "selection_id": str(selection_id)})
        invoice = self._invoices.get(str(invoice_id))
        if invoice is not None:
            invoice["QuickPaymentSelection"] = {"id": str(selection_id)}
        return SimpleNamespace(status_code=204)

    def list_tax_declarations(self) -> list[dict[str, Any]]:
        if self.faal_op == "aangiften":
            raise RlzApiError(500, "GET", "TaxDeclarations", "Aangiften mislukt (simulatie)")
        return self.aangiften

    def upload_bijlage(
        self, entity_path: str, entity_id: uuid.UUID, *, upload_id: uuid.UUID, filename: str, content_base64: str
    ) -> SimpleNamespace:
        if self.faal_op == "upload":
            raise RlzApiError(500, "PUT", "Uploads", "Upload mislukt (simulatie)")
        self.uploads.append({"entity_id": entity_id, "upload_id": upload_id, "filename": filename})
        return SimpleNamespace(status_code=204)

    def book_purchase_invoice(self, invoice_id: uuid.UUID) -> SimpleNamespace:
        if self.faal_op == "book":
            raise RlzApiError(500, "POST", "Actions", "Boeken mislukt (simulatie)")
        self.geboekte_acties.append(invoice_id)
        self._invoices[str(invoice_id)]["Status"] = 2
        return SimpleNamespace(status_code=204)

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.faal_op == "bank_relations" and path.endswith("/BankRelations"):
            raise RlzApiError(500, "GET", path, "BankRelations mislukt (simulatie)")
        if path.endswith("/BankRelations"):
            return {"value": self.bank_relations}
        invoice_id = path.rsplit("/", 1)[-1]
        if invoice_id not in self._invoices:
            raise RlzApiError(404, "GET", path, "Niet gevonden (simulatie)")
        return self._invoices[invoice_id]
