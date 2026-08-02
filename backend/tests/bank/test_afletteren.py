"""Assist-model afletteren: klaarzetten (seam), verificatie op OpenAmount + leesspoor met
huls-filter, intrekken."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.bank import afletteren
from tests.bank.conftest import FakeBankClient, maak_bank_mutatie, maak_payment_item


def _opdrachten(admin_engine: Engine, administratie_id: uuid.UUID) -> list[tuple]:
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT status, verificatie_detail FROM boekhouding.bank_afletter_opdracht "
                "WHERE administratie_id = :aid"
            ),
            {"aid": administratie_id},
        ).all()


def test_klaarzetten_maakt_opdracht_en_audit(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID
) -> None:
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id)
    item_id = maak_payment_item(admin_engine, administratie_id=administratie_id)

    uitvoering = afletteren.zet_klaar_voor_afletteren(
        administratie_id=administratie_id,
        payment_transaction_id=mutatie_id,
        payment_item_id=item_id,
        actor_id=beheerder_id,
    )
    # De seam levert vandaag altijd het assist-resultaat — bij een latere 15/16-upgrade
    # verandert deze uitkomst, niet de aanroepers.
    assert uitvoering.uitkomst == "wacht_op_mens_in_rlz"

    rijen = _opdrachten(admin_engine, administratie_id)
    assert len(rijen) == 1 and rijen[0][0] == "klaargezet"
    with admin_engine.connect() as conn:
        audit = conn.execute(
            text("SELECT COUNT(*) FROM platform.audit_event WHERE actie = 'afletteren_klaargezet'")
        ).scalar_one()
    assert audit == 1


def test_klaarzetten_weigert_tweede_opdracht_en_gesloten_mutatie(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID
) -> None:
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id)
    item_id = maak_payment_item(admin_engine, administratie_id=administratie_id)
    afletteren.zet_klaar_voor_afletteren(
        administratie_id=administratie_id, payment_transaction_id=mutatie_id,
        payment_item_id=item_id, actor_id=beheerder_id,
    )
    with pytest.raises(afletteren.OpdrachtBestaatAl):
        afletteren.zet_klaar_voor_afletteren(
            administratie_id=administratie_id, payment_transaction_id=mutatie_id,
            payment_item_id=item_id, actor_id=beheerder_id,
        )

    dichte_mutatie = maak_bank_mutatie(admin_engine, administratie_id=administratie_id, open_bedrag="0")
    with pytest.raises(afletteren.MutatieNietOpen):
        afletteren.zet_klaar_voor_afletteren(
            administratie_id=administratie_id, payment_transaction_id=dichte_mutatie,
            payment_item_id=item_id, actor_id=beheerder_id,
        )


def test_verificatie_wacht_zolang_mutatie_open_is(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID
) -> None:
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id)
    item_id = maak_payment_item(admin_engine, administratie_id=administratie_id)
    afletteren.zet_klaar_voor_afletteren(
        administratie_id=administratie_id, payment_transaction_id=mutatie_id,
        payment_item_id=item_id, actor_id=beheerder_id,
    )
    client = FakeBankClient(
        transacties={str(mutatie_id): {"id": str(mutatie_id), "OpenAmount": -121.0, "PaymentReferenceList": []}}
    )
    assert afletteren.verifieer_openstaande_opdrachten(administratie_id=administratie_id, client=client) == 0
    assert _opdrachten(admin_engine, administratie_id)[0][0] == "klaargezet"


def test_verificatie_legt_leesspoor_vast_en_filtert_hulzen(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID
) -> None:
    rlz_document_id = uuid.uuid4()
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id)
    item_id = maak_payment_item(
        admin_engine, administratie_id=administratie_id, rlz_document_id=rlz_document_id
    )
    afletteren.zet_klaar_voor_afletteren(
        administratie_id=administratie_id, payment_transaction_id=mutatie_id,
        payment_item_id=item_id, actor_id=beheerder_id,
    )
    client = FakeBankClient(
        transacties={
            str(mutatie_id): {
                "id": str(mutatie_id),
                "OpenAmount": 0,
                "PaymentReferenceList": [
                    # De echte koppeling (onze factuur) …
                    {
                        "Sequence": 1,
                        "Amount": 121.0,
                        "PaymentReconciliationSource": 2,
                        "Document": {"id": str(rlz_document_id), "Status": 3, "DocumentType": 4,
                                     "ReceiptNumber": "RLZ-04-00002012"},
                    },
                    # … en een systeemhuls / gestorneerd concept (DocumentType 19 + Status 1):
                    # PoC-leesregel — uitsluiten, nooit op IsSystemGenerated alleen varen.
                    {
                        "Sequence": 2,
                        "Amount": 121.0,
                        "Document": {"id": str(uuid.uuid4()), "Status": 1, "DocumentType": 19,
                                     "IsSystemGenerated": False},
                    },
                ],
            }
        }
    )

    assert afletteren.verifieer_openstaande_opdrachten(administratie_id=administratie_id, client=client) == 1

    rijen = _opdrachten(admin_engine, administratie_id)
    status, detail = rijen[0]
    assert status == "geverifieerd"
    assert detail["voorstel_gevolgd"] is True
    assert len(detail["koppelingen"]) == 1
    assert detail["koppelingen"][0]["rlz_document_id"] == str(rlz_document_id)

    with admin_engine.connect() as conn:
        open_bedrag = conn.execute(
            text("SELECT open_bedrag FROM boekhouding.bank_mutatie WHERE id = :id"), {"id": mutatie_id}
        ).scalar_one()
    assert open_bedrag == 0


def test_verificatie_markeert_afwijkend_gevolgd_voorstel(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID
) -> None:
    """De mens koos in RLZ een ánder document dan het voorstel — zichtbaar, nooit stil."""
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id)
    item_id = maak_payment_item(
        admin_engine, administratie_id=administratie_id, rlz_document_id=uuid.uuid4()
    )
    afletteren.zet_klaar_voor_afletteren(
        administratie_id=administratie_id, payment_transaction_id=mutatie_id,
        payment_item_id=item_id, actor_id=beheerder_id,
    )
    client = FakeBankClient(
        transacties={
            str(mutatie_id): {
                "id": str(mutatie_id),
                "OpenAmount": 0,
                "PaymentReferenceList": [
                    {"Sequence": 1, "Amount": 121.0,
                     "Document": {"id": str(uuid.uuid4()), "Status": 3, "DocumentType": 4}},
                ],
            }
        }
    )
    afletteren.verifieer_openstaande_opdrachten(administratie_id=administratie_id, client=client)
    _, detail = _opdrachten(admin_engine, administratie_id)[0]
    assert detail["voorstel_gevolgd"] is False


def test_intrekken(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID
) -> None:
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id)
    item_id = maak_payment_item(admin_engine, administratie_id=administratie_id)
    uitvoering = afletteren.zet_klaar_voor_afletteren(
        administratie_id=administratie_id, payment_transaction_id=mutatie_id,
        payment_item_id=item_id, actor_id=beheerder_id,
    )
    afletteren.trek_afletter_opdracht_in(
        administratie_id=administratie_id, opdracht_id=uitvoering.opdracht_id, actor_id=beheerder_id
    )
    assert _opdrachten(admin_engine, administratie_id)[0][0] == "ingetrokken"
    # En daarna mag er een nieuwe opdracht klaargezet worden.
    afletteren.zet_klaar_voor_afletteren(
        administratie_id=administratie_id, payment_transaction_id=mutatie_id,
        payment_item_id=item_id, actor_id=beheerder_id,
    )
