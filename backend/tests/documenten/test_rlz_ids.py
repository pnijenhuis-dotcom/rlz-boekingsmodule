from __future__ import annotations

import uuid

from app.documenten.rlz_ids import rlz_purchase_invoice_id, rlz_upload_id


def test_deterministisch_voor_hetzelfde_document() -> None:
    document_id = uuid.uuid4()
    assert rlz_purchase_invoice_id(document_id) == rlz_purchase_invoice_id(document_id)


def test_verschillend_per_document() -> None:
    assert rlz_purchase_invoice_id(uuid.uuid4()) != rlz_purchase_invoice_id(uuid.uuid4())


def test_upload_id_verschilt_van_het_document_id_zelf() -> None:
    document_id = uuid.uuid4()
    assert rlz_upload_id(document_id) != rlz_purchase_invoice_id(document_id)


def test_upload_id_is_ook_deterministisch() -> None:
    document_id = uuid.uuid4()
    assert rlz_upload_id(document_id) == rlz_upload_id(document_id)


def test_bekende_vaste_uitkomst_regressie() -> None:
    """Vastgelegde referentiewaarde — als deze test ooit faalt, is de namespace-constante in
    rlz_ids.py per ongeluk gewijzigd, wat de idempotentie van alle al geboekte documenten
    doorbreekt (een herhaalde boekpoging zou dan een NIEUW RLZ-document raken)."""
    document_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    assert str(rlz_purchase_invoice_id(document_id)) == "cc74074e-81b5-53d6-8679-1882367c5c43"
