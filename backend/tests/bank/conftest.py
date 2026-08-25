from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import Engine, text

from app.rlz.client import RlzApiError
from tests.auth.conftest import actieve_gebruiker, administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import gescoopte_gebruiker  # noqa: F401


class FakeBankClient:
    """Duck-typed vervanger van RlzClient voor de bankmodule-unittests (geen echte HTTP).
    `transacties` is de per-id-staat die zowel de lijst- als de per-id-GET voedt; PUT's op
    BankMutationDirectBookings muteren die staat zoals RLZ dat blijkens de schrijf-PoC doet
    (OpenAmount → 0, PaymentReference naar het nieuwe document, document Status 3)."""

    def __init__(
        self,
        *,
        accounts: list[dict[str, Any]] | None = None,
        last_imports: dict[str, dict | None | Exception] | None = None,
        transacties: dict[str, dict[str, Any]] | None = None,
        items: list[dict[str, Any]] | None = None,
        invoices: dict[str, dict[str, Any]] | None = None,
        faal_op: str | None = None,
        item_documenten: dict[str, str] | None = None,
        aangiften: list[dict[str, Any]] | None = None,
    ) -> None:
        self.accounts = accounts or []
        self.last_imports = last_imports or {}
        # Btw-aangiften voor de storno-aangifte-poort (default: géén ingediende aangiften).
        self.aangiften = aangiften or []
        self.transacties = {str(k): v for k, v in (transacties or {}).items()}
        self.items = items or []
        self.invoices = {str(k): v for k, v in (invoices or {}).items()}
        self.faal_op = faal_op
        self.direct_bookings: dict[str, dict[str, Any]] = {}
        self.correcties: list[str] = []
        self.import_probes: list[str] = []
        self.lijst_params: list[dict[str, Any] | None] = []
        self.gesloten = False
        # Afletteren via de betaal-kant (replay-STAP-0 2026-08-09): item-id -> document-id
        # voor het PaymentReferenceList-leesspoor dat link_payment_item opbouwt.
        self.item_documenten = {str(k): str(v) for k, v in (item_documenten or {}).items()}
        self.links: list[dict[str, Any]] = []
        # Deel 4 (25-08): aanbetalingsdocumenten (inkoop/verkoop) + debiteuren voor het relatie-pad.
        self.aanbetalingen: dict[str, dict[str, Any]] = {}
        self.customers: dict[str, dict[str, Any]] = {}
        self.factuur_correcties: list[str] = []

    # -- contextmanager + verbinding ------------------------------------------------------------
    def __enter__(self) -> FakeBankClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self.gesloten = True

    def for_administration(self, admin_id: str) -> FakeBankClient:
        return self

    # -- leeskant --------------------------------------------------------------------------------
    def list_payment_accounts(self) -> list[dict[str, Any]]:
        return self.accounts

    def get_last_bank_import(self, account_id: Any) -> dict | None:
        self.import_probes.append(str(account_id))
        waarde = self.last_imports.get(str(account_id))
        if isinstance(waarde, Exception):
            raise waarde
        return waarde

    def list_payment_transactions(self, *, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self.lijst_params.append(params)
        rijen = sorted(self.transacties.values(), key=lambda r: str(r.get("CreateDate") or ""))
        filter_expr = (params or {}).get("$filter") or ""
        if filter_expr.startswith("CreateDate ge "):
            grens = filter_expr.removeprefix("CreateDate ge ")
            rijen = [r for r in rijen if str(r.get("CreateDate") or "") >= grens]
        top = (params or {}).get("$top")
        return rijen[: int(top)] if top else rijen

    def get_payment_transaction(self, tx_id: Any, *, expand: str | None = None) -> dict[str, Any]:
        record = self.transacties.get(str(tx_id))
        if record is None:
            raise RlzApiError(404, "GET", f"PaymentTransactions/{tx_id}", "Niet gevonden (simulatie)")
        return record

    def list_payment_items(self, *, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filter_expr = (params or {}).get("$filter") or ""
        if filter_expr.startswith("Document/id eq "):
            doc_id = filter_expr.removeprefix("Document/id eq ").strip()
            doc = self.aanbetalingen.get(doc_id)
            if doc is not None and doc.get("Status") == 2 and doc.get("_item"):
                return [doc["_item"]]
            return [i for i in self.items if str((i.get("Document") or {}).get("id")) == doc_id]
        return self.items + [
            d["_item"] for d in self.aanbetalingen.values() if d.get("Status") == 2 and d.get("_item")
        ]

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        entiteit_id = path.rsplit("/", 1)[-1]
        if path.startswith("PurchaseInvoices/") or path.startswith("SalesInvoices/"):
            if entiteit_id in self.aanbetalingen:
                return self.aanbetalingen[entiteit_id]
            if entiteit_id not in self.invoices:
                raise RlzApiError(404, "GET", path, "Niet gevonden (simulatie)")
            return self.invoices[entiteit_id]
        if path.startswith("Customers/"):
            if entiteit_id not in self.customers:
                raise RlzApiError(404, "GET", path, "Niet gevonden (simulatie)")
            return self.customers[entiteit_id]
        raise RlzApiError(404, "GET", path, "Onbekend pad (simulatie)")

    def link_payment_item(
        self,
        transaction_id: Any,
        *,
        payment_item_id: Any,
        linked_amount: float,
        is_completely_paid: bool = False,
        payment_correction_method: int = 1,
    ) -> None:
        """Gedrag exact conform de replay-STAP-0 (2026-08-09): OpenAmount daalt met het
        gekoppelde bedrag, het leesspoor krijgt een echte document-referentie; een verouderd
        item-id geeft 404 _NotFound (restant kreeg bij RLZ een nieuw id)."""
        if self.faal_op == "link":
            raise RlzApiError(400, "POST", f"PaymentTransactions/{transaction_id}/Actions", "_InvalidData (simulatie)")
        if self.faal_op == "link_stale_item":
            raise RlzApiError(404, "POST", f"PaymentTransactions/{transaction_id}/Actions", "_NotFound (simulatie)")
        record = self.transacties.get(str(transaction_id))
        if record is None:
            raise RlzApiError(404, "POST", f"PaymentTransactions/{transaction_id}/Actions", "Niet gevonden (simulatie)")
        self.links.append({
            "transaction_id": str(transaction_id), "payment_item_id": str(payment_item_id),
            "linked_amount": linked_amount, "is_completely_paid": is_completely_paid,
            "payment_correction_method": payment_correction_method,
        })
        if self.faal_op == "link_zonder_effect":
            return  # 204-zonder-effect (bekend RLZ-gedrag bij een niet-passende body)
        open_amount = float(record.get("OpenAmount") or 0)
        record["OpenAmount"] = round(open_amount - linked_amount, 2)
        refs = record.setdefault("PaymentReferenceList", [])
        refs.append({
            "id": str(uuid.uuid4()),
            "Sequence": len(refs) + 1,
            "Amount": -linked_amount,
            "PaymentReconciliationSource": 2,
            "Document": {
                "id": self.item_documenten.get(str(payment_item_id), str(uuid.uuid4())),
                "ReceiptNumber": "RLZ-04-TEST",
                "DocumentType": 1,
                "Status": 3,
                "IsSystemGenerated": False,
            },
        })

    # -- schrijfkant -----------------------------------------------------------------------------
    def put_bank_mutation_direct_booking(
        self,
        booking_id: Any,
        *,
        payment_transaction_id: Any,
        lines: list[dict[str, Any]],
        description: str | None = None,
    ) -> None:
        if self.faal_op == "put_direct":
            raise RlzApiError(500, "PUT", f"BankMutationDirectBookings/{booking_id}", "PUT mislukt (simulatie)")
        document = {
            "id": str(booking_id),
            "Status": 3,
            "ReceiptNumber": f"RLZ-07-{len(self.direct_bookings) + 1:08d}",
            "DocumentType": 19,
            "DocumentLineList": lines,
            "Description": description,
            # RLZ leidt de documentdatum af van de transactie (schrijf-PoC §3) — de
            # aangifte-poort toetst dáárop.
            "Date": self.transacties.get(str(payment_transaction_id), {}).get("Date") or "2026-08-10T00:00:00",
        }
        if self.faal_op == "put_zonder_effect" or str(booking_id) in self.direct_bookings:
            # STAP-0 25-08 §2.6: her-PUT op een gestorneerd BMDB = 204 zónder effect (document blijft
            # concept, mutatie ongewijzigd) — óók wat een echte 204-zonder-effect doet.
            self.direct_bookings.setdefault(str(booking_id), {**document, "Status": 1})
            return
        self.direct_bookings[str(booking_id)] = document
        tx = self.transacties[str(payment_transaction_id)]
        som = round(sum(float(l.get("NetAmount") or 0) + float(l.get("TaxAmount") or 0) for l in lines), 2)
        # Deelbedrag (STAP-0 §2.2): OpenAmount daalt met de som van de regels; volledig = 0.
        tx["OpenAmount"] = round(float(tx.get("OpenAmount") or 0) - som, 2)
        refs = tx.setdefault("PaymentReferenceList", [])
        refs.append({"id": str(uuid.uuid4()), "Sequence": len(refs) + 1, "Amount": som, "Document": document})

    def get_bank_mutation_direct_booking(self, booking_id: Any) -> dict[str, Any]:
        record = self.direct_bookings.get(str(booking_id))
        if record is None:
            raise RlzApiError(404, "GET", f"BankMutationDirectBookings/{booking_id}", "Niet gevonden (simulatie)")
        return record

    def list_tax_declarations(self) -> list[dict[str, Any]]:
        if self.faal_op == "aangiften":
            raise RlzApiError(500, "GET", "TaxDeclarations", "Niet leesbaar (simulatie)")
        return self.aangiften

    def correct_bank_mutation_direct_booking(self, booking_id: Any) -> None:
        if self.faal_op == "correct":
            raise RlzApiError(500, "POST", "Actions", "Storno mislukt (simulatie)")
        self.correcties.append(str(booking_id))
        document = self.direct_bookings[str(booking_id)]
        document["Status"] = 1
        for tx in self.transacties.values():
            refs = tx.get("PaymentReferenceList") or []
            for ref in refs:
                if (ref.get("Document") or {}).get("id") == str(booking_id):
                    # Schrijf-PoC §6 / STAP-0 25-08 §2.4: het deel komt terug op de mutatie, de
                    # referentie blijft naar het (nu concept-)document wijzen (huls-rol).
                    tx["OpenAmount"] = round(float(tx.get("OpenAmount") or 0) + float(ref.get("Amount") or 0), 2)

    # -- aanbetalingsdocumenten (deel 4 punt 3) ---------------------------------------------------
    def _put_aanbetaling(self, pad: str, invoice_id: Any, entity_id: Any, lines: list[dict[str, Any]], extra: dict) -> None:
        if self.faal_op == "put_aanbetaling":
            raise RlzApiError(500, "PUT", f"{pad}/{invoice_id}", "PUT mislukt (simulatie)")
        bestaand = self.aanbetalingen.get(str(invoice_id))
        self.aanbetalingen[str(invoice_id)] = {
            "id": str(invoice_id), "Entity": {"id": str(entity_id)}, "DocumentLineList": lines,
            "Status": 1, "ReceiptNumber": (bestaand or {}).get("ReceiptNumber") or f"RLZ-04-{len(self.aanbetalingen) + 1:08d}",
            "Reference": extra.get("Reference"), "Date": "2026-08-25T00:00:00", "_pad": pad,
            # Her-PUT op hetzelfde GUID ná storno: géén nieuw item meer (STAP-0 H5).
            "_herboekt": bestaand is not None,
        }

    def put_purchase_invoice(self, invoice_id: Any, *, vendor_id: Any, lines: list[dict[str, Any]], reference: str | None = None, **extra: Any) -> None:
        self._put_aanbetaling("PurchaseInvoices", invoice_id, vendor_id, lines, {"Reference": reference, **extra})

    def put_sales_invoice(self, invoice_id: Any, *, customer_id: Any, lines: list[dict[str, Any]], document_category_id: Any = None, **extra: Any) -> None:
        self._put_aanbetaling("SalesInvoices", invoice_id, customer_id, lines, extra)

    def _book(self, invoice_id: Any) -> None:
        doc = self.aanbetalingen[str(invoice_id)]
        doc["Status"] = 2
        som = round(sum(float(l.get("NetAmount") or 0) + float(l.get("TaxAmount") or 0) for l in doc["DocumentLineList"]), 2)
        doc["BaseInvoiceAmount"] = som
        doc["BaseRemainingAmount"] = som
        if not doc.get("_herboekt") and self.faal_op != "aanbetaling_zonder_item":
            item_id = str(uuid.uuid4())
            doc["_item"] = {"id": item_id, "Amount": -som if doc["_pad"] == "PurchaseInvoices" else som,
                            "PaymentStatus": 1, "Document": {"id": str(invoice_id)}}
            self.item_documenten[item_id] = str(invoice_id)
        else:
            doc["_item"] = None

    def book_purchase_invoice(self, invoice_id: Any) -> None:
        self._book(invoice_id)

    def book_sales_invoice(self, invoice_id: Any) -> None:
        self._book(invoice_id)

    def get_sales_invoice(self, invoice_id: Any) -> dict[str, Any]:
        return self.get(f"SalesInvoices/{invoice_id}")

    def _correct_factuur(self, invoice_id: Any) -> None:
        if self.faal_op == "correct_aanbetaling":
            raise RlzApiError(500, "POST", "Actions", "Storno mislukt (simulatie)")
        self.factuur_correcties.append(str(invoice_id))
        doc = self.aanbetalingen.get(str(invoice_id))
        if doc is None:
            return
        doc["Status"] = 1
        doc["_item"] = None
        for tx in self.transacties.values():
            for ref in tx.get("PaymentReferenceList") or []:
                if (ref.get("Document") or {}).get("id") == str(invoice_id) and not ref.get("_gestorneerd"):
                    ref["_gestorneerd"] = True
                    ref["Document"]["Status"] = 1
                    tx["OpenAmount"] = round(float(tx.get("OpenAmount") or 0) - float(ref.get("Amount") or 0), 2)

    def correct_purchase_invoice(self, invoice_id: Any) -> None:
        self._correct_factuur(invoice_id)

    def correct_sales_invoice(self, invoice_id: Any) -> None:
        self._correct_factuur(invoice_id)

    def find_customers_by_name(self, *, name: str) -> list[dict[str, Any]]:
        return [c for c in self.customers.values() if name.lower() in (c.get("Name") or "").lower()]


def maak_relatie_referentiedata(
    admin_engine: Engine,
    *,
    administratie_id: uuid.UUID,  # noqa: F811
    vendor_id: uuid.UUID | None = None,
    vendor_naam: str = "Steigerhout Import B.V.",
    met_1806: bool = True,
    extra_nul_tarief: bool = False,
) -> dict[str, uuid.UUID]:
    """Grootboek 1403/1806 + het ene 'Nul tarief' + een crediteur — wat `relatie.bepaal_instelling`
    deterministisch nodig heeft (deel 4 punt 3)."""
    vendor_id = vendor_id or uuid.uuid4()
    gb_1403, gb_1806, nul = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.grootboekrekening (ledger_id, administratie_id, code, naam, soort, is_totaalrekening) "
                 "VALUES (:id, :aid, '1403', 'Vooruit betaalde inkoopfacturen', 3, false)"),
            {"id": gb_1403, "aid": administratie_id},
        )
        if met_1806:
            conn.execute(
                text("INSERT INTO platform.grootboekrekening (ledger_id, administratie_id, code, naam, soort, is_totaalrekening) "
                     "VALUES (:id, :aid, '1806', 'Vooruitbetaalde verkoopfacturen', 4, false)"),
                {"id": gb_1806, "aid": administratie_id},
            )
        rates = [
            (nul, "NL, Nul tarief", {"IsRelayed": False, "IsExcempt": False, "IsMixed": False, "TaxKind": 1}, "0"),
            (uuid.uuid4(), "NL, Geen BTW (Vrijgesteld)", {"IsRelayed": False, "IsExcempt": True, "IsMixed": False, "TaxKind": 1}, "0"),
            (uuid.uuid4(), "NL, BTW verlegd (hoog)", {"IsRelayed": True, "IsExcempt": False, "IsMixed": False, "TaxKind": 1}, "0"),
            (uuid.uuid4(), "NL, Hoog", {"IsRelayed": False, "IsExcempt": False, "IsMixed": False, "TaxKind": 1}, "0.21"),
        ]
        if extra_nul_tarief:
            rates.append((uuid.uuid4(), "NL, Nul tarief (dubbel)", {"IsRelayed": False, "IsExcempt": False, "IsMixed": False, "TaxKind": 1}, "0"))
        for rid, naam, brondata, pct in rates:
            conn.execute(
                text("INSERT INTO boekhouding.taxrate_cache (id, administratie_id, naam, percentage, brondata) "
                     "VALUES (:id, :aid, :naam, :pct, CAST(:bron AS jsonb))"),
                {"id": rid, "aid": administratie_id, "naam": naam, "pct": pct, "bron": json.dumps(brondata)},
            )
        conn.execute(
            text("INSERT INTO boekhouding.vendor_cache (id, administratie_id, naam, is_gearchiveerd, brondata) "
                 "VALUES (:id, :aid, :naam, false, '{}')"),
            {"id": vendor_id, "aid": administratie_id, "naam": vendor_naam},
        )
    return {"vendor_id": vendor_id, "gb_1403": gb_1403, "gb_1806": gb_1806, "nul_tarief": nul}


def maak_bank_mutatie(
    admin_engine: Engine,
    *,
    administratie_id: uuid.UUID,  # noqa: F811 — bewust gelijk aan de fixture-naam (leesbare tests)
    bedrag: str = "-121.00",
    open_bedrag: str | None = None,
    tegenpartij_naam: str = "Testpartij B.V.",
    omschrijving: str = "test",
    payment_account_id: uuid.UUID | None = None,
    rlz_voorstel_item_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Directe insert van een cache-rij (schema-owner) — de sync-tests dekken het vullen zelf."""
    mutatie_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.bank_mutatie "
                "(id, administratie_id, payment_account_id, boekdatum, bedrag, open_bedrag, "
                " tegenpartij_naam, omschrijving, rlz_voorstel_item_id, brondata) "
                "VALUES (:id, :aid, :account, CURRENT_DATE, :bedrag, :open_bedrag, :naam, :oms, :voorstel, '{}')"
            ),
            {
                "id": mutatie_id,
                "aid": administratie_id,
                "account": payment_account_id,
                "bedrag": bedrag,
                "open_bedrag": open_bedrag if open_bedrag is not None else bedrag,
                "naam": tegenpartij_naam,
                "oms": omschrijving,
                "voorstel": rlz_voorstel_item_id,
            },
        )
    return mutatie_id


def maak_payment_item(
    admin_engine: Engine,
    *,
    administratie_id: uuid.UUID,  # noqa: F811 — zelfde overweging als maak_bank_mutatie
    bedrag: str = "121.00",
    referentie: str | None = "F-2026-0642",
    rlz_document_id: uuid.UUID | None = None,
    entity_guid: uuid.UUID | None = None,
    entity_naam: str | None = None,
) -> uuid.UUID:
    item_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.payment_item_cache "
                "(id, administratie_id, bedrag, referentie, rlz_document_id, entity_guid, entity_naam, brondata) "
                "VALUES (:id, :aid, :bedrag, :ref, :doc, :entity, :entity_naam, '{}')"
            ),
            {
                "id": item_id,
                "aid": administratie_id,
                "bedrag": bedrag,
                "ref": referentie,
                "doc": rlz_document_id or uuid.uuid4(),
                "entity": entity_guid,
                "entity_naam": entity_naam,
            },
        )
    return item_id


def maak_intercompany_tegenpartij(
    admin_engine: Engine,
    *,
    administratie_id: uuid.UUID,  # noqa: F811
    entity_guid: uuid.UUID,
    naam: str = "Veldhoven Recreatie B.V.",
    actief: bool = True,
) -> uuid.UUID:
    """IC-rij zoals de doorbelasting-service die onderhoudt (migratie 0045, blok 2)."""
    rij_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.intercompany_tegenpartij "
                "(id, administratie_id, entity_guid, naam, actief) "
                "VALUES (:id, :aid, :entity, :naam, :actief)"
            ),
            {"id": rij_id, "aid": administratie_id, "entity": entity_guid, "naam": naam, "actief": actief},
        )
    return rij_id


@pytest.fixture
def boeken_aan(admin_engine: Engine, administratie_id: uuid.UUID) -> None:  # noqa: F811
    """Zet de schrijf-failsafe open voor deze administratie (de globale kill switch staat in de
    testdatabase al aan via conftest-herstel)."""
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.administratie SET boeken_ingeschakeld = true WHERE id = :aid"),
            {"aid": administratie_id},
        )
