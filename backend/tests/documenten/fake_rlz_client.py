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

    def __enter__(self) -> FakeBoekClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self.gesloten = True

    def for_administration(self, admin_id: str) -> FakeBoekClient:
        return self

    def find_purchase_invoices_by_reference(
        self, *, vendor_id: uuid.UUID | str, reference: str, total_amount: float | None = None
    ) -> list[dict[str, Any]]:
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
            {"Status": 1, "ReceiptNumber": f"RLZ-TEST-{len(self.puts):05d}", "BaseInvoiceAmount": round(bedrag, 2)},
        )
        return SimpleNamespace(status_code=204)

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
