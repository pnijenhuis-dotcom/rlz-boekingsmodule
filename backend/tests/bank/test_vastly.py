"""Vastly-terugkoppeling "factuur afgeletterd": detectie op documentstatus 3, alleen
vastgoed-administraties, idempotent via de outbox-rij zelf."""

from __future__ import annotations

import uuid

from sqlalchemy import Engine, text

from app.bank import vastly
from app.documenten.rlz_ids import rlz_purchase_invoice_id
from tests.bank.conftest import FakeBankClient


def _maak_geboekt_document(
    admin_engine: Engine, *, administratie_id: uuid.UUID, referentie: str = "F-2026-0642"
) -> uuid.UUID:
    document_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.document (id, administratie_id, bron, bestandsnaam, sha256_hash, "
                "status, opslag_pad) VALUES (:id, :aid, 'upload', 'f.pdf', :hash, 'geboekt', 'pad')"
            ),
            {"id": document_id, "aid": administratie_id, "hash": str(uuid.uuid4())},
        )
        conn.execute(
            text(
                "INSERT INTO boekhouding.boekvoorstel (document_id, referentie, rlz_boekstuknummer) "
                "VALUES (:id, :ref, 'RLZ-04-00002012')"
            ),
            {"id": document_id, "ref": referentie},
        )
    return document_id


def _zet_vastgoed(admin_engine: Engine, administratie_id: uuid.UUID) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.administratie SET is_vastgoed = true WHERE id = :aid"),
            {"aid": administratie_id},
        )


def _outbox(admin_engine: Engine) -> list[tuple]:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT document_id, event, payload, status FROM boekhouding.webhook_uitgaand")
        ).all()


def test_geen_event_voor_niet_vastgoed_administratie(
    administratie_id: uuid.UUID, admin_engine: Engine
) -> None:
    document_id = _maak_geboekt_document(admin_engine, administratie_id=administratie_id)
    rlz_id = rlz_purchase_invoice_id(document_id)
    client = FakeBankClient(invoices={str(rlz_id): {"Status": 3}})
    assert vastly.detecteer_en_meld_afgeletterd(administratie_id=administratie_id, client=client) == 0
    assert _outbox(admin_engine) == []


def test_event_bij_status_3_en_idempotent(
    administratie_id: uuid.UUID, admin_engine: Engine
) -> None:
    _zet_vastgoed(admin_engine, administratie_id)
    document_id = _maak_geboekt_document(admin_engine, administratie_id=administratie_id)
    rlz_id = rlz_purchase_invoice_id(document_id)
    client = FakeBankClient(invoices={str(rlz_id): {"Status": 3}})

    assert vastly.detecteer_en_meld_afgeletterd(administratie_id=administratie_id, client=client) == 1
    rijen = _outbox(admin_engine)
    assert len(rijen) == 1
    doc_id, event, payload, status = rijen[0]
    assert doc_id == document_id
    assert event == "factuur_afgeletterd"
    assert status == "openstaand"
    # Ongetekende envelope (de afleveraar tekent per verzendpoging) mét het juiste document.
    assert payload["schema_version"] == "1.0"
    assert payload["data"]["rlz_document_id"] == str(rlz_id)
    assert payload["data"]["rlz_boekstuknummer"] == "RLZ-04-00002012"
    assert "handtekening" not in payload

    # Tweede run: geen tweede rij (outbox-rij is de idempotentie-marker).
    assert vastly.detecteer_en_meld_afgeletterd(administratie_id=administratie_id, client=client) == 0
    assert len(_outbox(admin_engine)) == 1


def test_geen_event_zolang_status_open_is(
    administratie_id: uuid.UUID, admin_engine: Engine
) -> None:
    _zet_vastgoed(admin_engine, administratie_id)
    document_id = _maak_geboekt_document(admin_engine, administratie_id=administratie_id)
    rlz_id = rlz_purchase_invoice_id(document_id)
    client = FakeBankClient(invoices={str(rlz_id): {"Status": 2}})  # geboekt, nog niet afgeletterd
    assert vastly.detecteer_en_meld_afgeletterd(administratie_id=administratie_id, client=client) == 0
    assert _outbox(admin_engine) == []


def test_onleesbare_factuur_stopt_de_rest_niet(
    administratie_id: uuid.UUID, admin_engine: Engine
) -> None:
    _zet_vastgoed(admin_engine, administratie_id)
    # "Kapot" document: ontbreekt in de fake → 404 bij de status-GET.
    _maak_geboekt_document(admin_engine, administratie_id=administratie_id, referentie="F-1")
    goed = _maak_geboekt_document(admin_engine, administratie_id=administratie_id, referentie="F-2")
    client = FakeBankClient(invoices={str(rlz_purchase_invoice_id(goed)): {"Status": 3}})
    # `kapot` ontbreekt in de fake → 404, wordt gelogd en overgeslagen.
    assert vastly.detecteer_en_meld_afgeletterd(administratie_id=administratie_id, client=client) == 1
    assert len(_outbox(admin_engine)) == 1
