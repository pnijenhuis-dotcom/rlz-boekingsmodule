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
        # Activa fase 1 (21-09): register-seeds. `fixed_assets` = {id: RLZ-rij}, `depreciation_methods` default
        # "Lineair 5 jaar" (60) + "Lineair 3 jaar" (36), `administration_settings` = één rij mét FixedAssetAlertAmount,
        # `fixed_assets_403` = recht ontbreekt (casus Universal). Opname van élke PUT in `fixed_asset_puts`.
        self.fixed_assets: dict[str, dict[str, Any]] = {}
        self.depreciation_methods: list[dict[str, Any]] = [
            {
                "id": "aaaaaaaa-1111-4111-8111-000000000060",
                "Description": "Lineair 5 jaar",
                "NumberOfMonths": 60,
                "DepreciationBaseMethod": 1,
            },
            {
                "id": "aaaaaaaa-1111-4111-8111-000000000036",
                "Description": "Lineair 3 jaar",
                "NumberOfMonths": 36,
                "DepreciationBaseMethod": 1,
            },
        ]
        self.administration_settings: list[dict[str, Any]] = [{"FixedAssetAlertAmount": 450.0}]
        self.fixed_assets_403 = False
        self.fixed_asset_puts: list[dict[str, Any]] = []

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

    def find_purchase_invoices_kandidaten(self, *, vendor_ids, van, tot, **_: Any) -> list[dict[str, Any]]:
        """Zenvoices-casus 16-09: kandidaten in het datumvenster — de test zet `kandidaten` (RLZ-rijvorm mét
        `Reference`, `BaseInvoiceAmount`, `Date`, `Status`, `ReceiptNumber`, optioneel `Entity`); zonder `Entity` telt
        een rij voor élk gevraagd crediteurrecord. Datums worden gefilterd zoals RLZ dat zou doen."""
        ids = {str(v) for v in vendor_ids}
        uit = []
        for rij in getattr(self, "kandidaten", []):
            entity = (rij.get("Entity") or {}).get("id")
            if entity is not None and str(entity) not in ids:
                continue
            datum = str(rij.get("Date") or "")[:10]
            if datum and not (van.isoformat() <= datum <= tot.isoformat()):
                continue
            uit.append(rij)
        return uit

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

    def correct_purchase_invoice(self, invoice_id: uuid.UUID) -> SimpleNamespace:
        """Actie 19 (Corrigeren vanuit de module, 21-09): hetzelfde document terug naar concept (Status 1)."""
        if self.faal_op == "correct":
            raise RlzApiError(500, "POST", "Actions", "Storno mislukt (simulatie)")
        if str(invoice_id) not in self._invoices:
            raise RlzApiError(404, "POST", "Actions", "Niet gevonden (simulatie)")
        self.correcties = [*getattr(self, "correcties", []), invoice_id]
        self._invoices[str(invoice_id)]["Status"] = 1
        return SimpleNamespace(status_code=204)

    def book_purchase_invoice(self, invoice_id: uuid.UUID) -> SimpleNamespace:
        if self.faal_op == "book":
            raise RlzApiError(500, "POST", "Actions", "Boeken mislukt (simulatie)")
        self.geboekte_acties.append(invoice_id)
        self._invoices[str(invoice_id)]["Status"] = 2
        return SimpleNamespace(status_code=204)

    # --- activa / MVA (fase 1, 21-09) ---------------------------------------------------------------------------

    def get_fixed_assets(self, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if self.fixed_assets_403:
            raise RlzApiError(403, "GET", "FixedAssets", "Forbidden (simulatie: recht 'Vaste activa' ontbreekt)")
        if self.faal_op == "fixed_assets":
            raise RlzApiError(500, "GET", "FixedAssets", "FixedAssets mislukt (simulatie)")
        rijen = list(self.fixed_assets.values())
        top = int((params or {}).get("$top", len(rijen) or 1))
        skip = int((params or {}).get("$skip", 0))
        return rijen[skip : skip + top]

    def get_fixed_asset(self, asset_id: uuid.UUID | str) -> dict[str, Any] | None:
        if self.faal_op == "fixed_asset_readback":
            return None
        return self.fixed_assets.get(str(asset_id))

    def put_fixed_asset(self, asset_id: uuid.UUID, body: dict[str, Any]) -> SimpleNamespace:
        if self.fixed_assets_403:
            raise RlzApiError(403, "PUT", "FixedAssets", "Forbidden (simulatie: recht 'Vaste activa' ontbreekt)")
        if self.faal_op == "fixed_asset_put":
            raise RlzApiError(400, "PUT", "FixedAssets", "PUT FixedAssets mislukt (simulatie)")
        if self.faal_op == "fixed_asset_put_404":
            # Peter 23-09 (BLOw MK22507863): RLZ kent PUT FixedAssets/{client-guid} niet als aanmaakroute.
            raise RlzApiError(404, "PUT", f"FixedAssets/{asset_id}", '{"Message":"NotFound_FixedAsset"}')
        rij = {**body, "id": str(asset_id)}
        self.fixed_asset_puts.append(rij)
        methode = next((m for m in self.depreciation_methods if m["id"] == (body.get("DepreciationMethod") or {}).get("id")), None)
        self.fixed_assets[str(asset_id)] = {
            **rij,
            "ReceiptNumber": str(len(self.fixed_assets) + 1),
            "Status": 2,
            "CurrentBookValue": body.get("TotalAmountPurchase"),
            "CurrentDepreciationValue": 0.0,
            "DepreciationMethod": methode,
        }
        return SimpleNamespace(status_code=204)

    def get_depreciation_method_headers(self) -> list[dict[str, Any]]:
        if self.faal_op == "depreciation_methods":
            raise RlzApiError(500, "GET", "DepreciationMethodHeaders", "mislukt (simulatie)")
        return list(self.depreciation_methods)

    def get_administration_settings(self) -> list[dict[str, Any]]:
        return list(self.administration_settings)

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.faal_op == "bank_relations" and path.endswith("/BankRelations"):
            raise RlzApiError(500, "GET", path, "BankRelations mislukt (simulatie)")
        if path.endswith("/BankRelations"):
            return {"value": self.bank_relations}
        invoice_id = path.rsplit("/", 1)[-1]
        if invoice_id not in self._invoices:
            raise RlzApiError(404, "GET", path, "Niet gevonden (simulatie)")
        return self._invoices[invoice_id]
