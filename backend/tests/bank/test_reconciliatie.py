"""Bank-reconciliatie: rapporteert (nooit stil corrigeert) wanneer RLZ afwijkt van de eigen
werkstaat — de vangnet-failsafe voor storno's die rechtstreeks in de RLZ-UI zijn gedaan."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Engine

from app.bank import boeken
from app.bank.boeken import BankBoekRegelInput
from app.bank.reconciliatie import reconcilieer_bank
from tests.bank.conftest import FakeBankClient, maak_bank_mutatie, maak_payment_item


def _boek(administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, client: FakeBankClient):
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id)
    client.transacties[str(mutatie_id)] = {
        "id": str(mutatie_id), "Amount": -121.0, "OpenAmount": -121.0, "PaymentReferenceList": [],
    }
    return boeken.boek_mutatie_direct(
        administratie_id=administratie_id,
        payment_transaction_id=mutatie_id,
        regels=[BankBoekRegelInput(ledger_id=uuid.uuid4(), netto_bedrag=Decimal("-121.00"))],
        actor_id=beheerder_id,
        client=client,
    )


def test_geen_afwijkingen_bij_consistente_staat(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
) -> None:
    client = FakeBankClient()
    _boek(administratie_id, admin_engine, beheerder_id, client)
    rapport = reconcilieer_bank(administratie_id=administratie_id, client=client)
    assert rapport.boekingen_gecontroleerd == 1
    assert rapport.afwijkingen == ()


def test_in_rlz_ui_gestorneerde_boeking_wordt_gerapporteerd(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
) -> None:
    client = FakeBankClient()
    resultaat = _boek(administratie_id, admin_engine, beheerder_id, client)
    # Storno buiten de app om (rechtstreeks in de RLZ-UI): document terug naar Status 1.
    client.direct_bookings[str(resultaat.rlz_document_id)]["Status"] = 1

    rapport = reconcilieer_bank(administratie_id=administratie_id, client=client)
    assert len(rapport.afwijkingen) == 1
    assert rapport.afwijkingen[0].soort == "boeking_teruggedraaid_in_rlz"


def test_teruggedraaide_aflettering_wordt_gerapporteerd(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID
) -> None:
    from app.bank import afletteren

    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id)
    item_id = maak_payment_item(admin_engine, administratie_id=administratie_id)
    afletteren.zet_klaar_voor_afletteren(
        administratie_id=administratie_id, payment_transaction_id=mutatie_id,
        payment_item_id=item_id, actor_id=beheerder_id,
        client=FakeBankClient(faal_op="link"),
    )
    client = FakeBankClient(
        transacties={str(mutatie_id): {"id": str(mutatie_id), "OpenAmount": 0, "PaymentReferenceList": []}}
    )
    afletteren.verifieer_openstaande_opdrachten(administratie_id=administratie_id, client=client)

    # Aflettering in RLZ teruggedraaid: mutatie weer open.
    client.transacties[str(mutatie_id)]["OpenAmount"] = -121.0
    rapport = reconcilieer_bank(administratie_id=administratie_id, client=client)
    assert rapport.afletteringen_gecontroleerd == 1
    assert len(rapport.afwijkingen) == 1
    assert rapport.afwijkingen[0].soort == "aflettering_teruggedraaid_in_rlz"
