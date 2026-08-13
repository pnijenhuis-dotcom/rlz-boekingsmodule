from __future__ import annotations

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
    ) -> None:
        self.accounts = accounts or []
        self.last_imports = last_imports or {}
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
        return self.items

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        entiteit_id = path.rsplit("/", 1)[-1]
        if path.startswith("PurchaseInvoices/"):
            if entiteit_id not in self.invoices:
                raise RlzApiError(404, "GET", path, "Niet gevonden (simulatie)")
            return self.invoices[entiteit_id]
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
        }
        self.direct_bookings[str(booking_id)] = document
        tx = self.transacties[str(payment_transaction_id)]
        tx["OpenAmount"] = 0
        tx["PaymentReferenceList"] = [
            {"id": str(uuid.uuid4()), "Sequence": 1, "Amount": tx.get("Amount"), "Document": document}
        ]

    def get_bank_mutation_direct_booking(self, booking_id: Any) -> dict[str, Any]:
        return self.direct_bookings[str(booking_id)]

    def correct_bank_mutation_direct_booking(self, booking_id: Any) -> None:
        if self.faal_op == "correct":
            raise RlzApiError(500, "POST", "Actions", "Storno mislukt (simulatie)")
        self.correcties.append(str(booking_id))
        document = self.direct_bookings[str(booking_id)]
        document["Status"] = 1
        for tx in self.transacties.values():
            refs = tx.get("PaymentReferenceList") or []
            if any((ref.get("Document") or {}).get("id") == str(booking_id) for ref in refs):
                # Schrijf-PoC §6: OpenAmount hersteld, maar de referentie blijft naar het (nu
                # concept-)document wijzen — het gestorneerde document wordt zelf de huls.
                tx["OpenAmount"] = tx.get("Amount")


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
