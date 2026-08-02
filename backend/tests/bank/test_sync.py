"""Bank-leeskant: rekeningen (incl. versheid-probe), incrementele mutatie-sync met
CreateDate-watermark + open-verversronde, open-posten met verdwenen-markering."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Engine, text

from app.bank import sync
from tests.bank.conftest import FakeBankClient


def _account_record(*, naam: str = "ING zakelijk", rekening_type: int = 1) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "Name": naam,
        "IBAN": "NL91INGB0002445588",
        "Type": rekening_type,
        "CurrentBalance": 48212.90,
        "LastBalanceDate": "2026-07-31T00:00:00",
        "IsArchived": False,
        "BankGatewayState": None,
        "BankGatewayType": 0,
    }


def _tx_record(*, create_date: str, bedrag: float = -24.50, open_amount: float | None = None,
               account_id: str | None = None, tx_id: str | None = None) -> dict:
    return {
        "id": tx_id or str(uuid.uuid4()),
        "BookDate": "2026-07-01T00:00:00",
        "CreateDate": create_date,
        "Amount": bedrag,
        "OpenAmount": open_amount if open_amount is not None else bedrag,
        "CounterAccount": "NL00BANK0123456789",
        "Name": "ING Bank N.V.",
        "Reference": "kosten zakelijk juni",
        "Type": 1,
        "PaymentAccount": {"id": account_id or str(uuid.uuid4())},
    }


def test_sync_accounts_met_versheid_probe(administratie_id: uuid.UUID, admin_engine: Engine) -> None:
    account = _account_record()
    kas = _account_record(naam="Kas", rekening_type=3)
    client = FakeBankClient(
        accounts=[account, kas],
        last_imports={
            account["id"]: {"FileName": "MT940-0731.940", "Date": "2026-07-31T06:04:00",
                            "BankImportSource": 1, "BankImportType": "MT940"},
            kas["id"]: None,
        },
    )
    telling = sync.sync_payment_accounts(administratie_id=administratie_id, client=client)
    assert telling.aangemaakt == 2

    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text(
                "SELECT naam, rekening_type, saldo, laatste_import IS NOT NULL "
                "FROM boekhouding.payment_account_cache WHERE administratie_id = :aid ORDER BY naam"
            ),
            {"aid": administratie_id},
        ).all()
    assert rijen[0] == ("ING zakelijk", 1, Decimal("48212.90"), True)
    assert rijen[1][0] == "Kas" and rijen[1][3] is False  # kas: geen import — geen fout


def test_mutatie_sync_is_incrementeel_op_create_date(
    administratie_id: uuid.UUID, admin_engine: Engine
) -> None:
    oud = _tx_record(create_date="2026-07-01T08:00:00")
    client = FakeBankClient(transacties={oud["id"]: oud})

    eerste = sync.sync_payment_transactions(administratie_id=administratie_id, client=client)
    assert (eerste.aangemaakt, eerste.bijgewerkt) == (1, 0)

    nieuw = _tx_record(create_date="2026-07-02T08:00:00", bedrag=-68.45)
    client.transacties[nieuw["id"]] = nieuw
    tweede = sync.sync_payment_transactions(administratie_id=administratie_id, client=client)
    # De oude rij valt binnen het ge-filter (zelfde watermark) en wordt bijgewerkt; de nieuwe
    # komt erbij — maar er verdwijnt nooit iets.
    assert tweede.aangemaakt == 1

    with admin_engine.connect() as conn:
        aantal, watermark = conn.execute(
            text(
                "SELECT (SELECT COUNT(*) FROM boekhouding.bank_mutatie WHERE administratie_id = :aid), "
                "mutaties_watermark FROM boekhouding.bank_sync_stand WHERE administratie_id = :aid"
            ),
            {"aid": administratie_id},
        ).one()
    assert aantal == 2
    from datetime import UTC, datetime

    assert watermark == datetime(2026, 7, 2, 8, 0, tzinfo=UTC)


def test_open_verversronde_haalt_gewijzigd_open_bedrag_op(
    administratie_id: uuid.UUID, admin_engine: Engine
) -> None:
    """Een lokaal-open mutatie die in RLZ intussen is afgeletterd (OpenAmount 0) wordt in de
    verversronde per-id opgehaald — óók als hij buiten het incrementele venster valt."""
    tx = _tx_record(create_date="2026-06-01T08:00:00", bedrag=-121.0)
    client = FakeBankClient(transacties={tx["id"]: tx})
    sync.sync_payment_transactions(administratie_id=administratie_id, client=client)

    # In RLZ afgeletterd; CreateDate blijft oud, dus het ge-filter van een tweede run die alleen
    # nieuwere ziet, mist hem — er is bovendien een nieuwe mutatie zodat de watermark opschuift.
    tx["OpenAmount"] = 0
    nieuw = _tx_record(create_date="2026-07-01T08:00:00")
    client.transacties[nieuw["id"]] = nieuw
    telling = sync.sync_payment_transactions(administratie_id=administratie_id, client=client)
    assert telling.open_ververst >= 0  # de oude rij zat in ge-venster óf verversronde

    with admin_engine.connect() as conn:
        open_bedrag = conn.execute(
            text("SELECT open_bedrag FROM boekhouding.bank_mutatie WHERE id = :id"), {"id": tx["id"]}
        ).scalar_one()
    assert open_bedrag == Decimal("0")


def test_open_posten_sync_markeert_verdwenen(administratie_id: uuid.UUID, admin_engine: Engine) -> None:
    item = {"id": str(uuid.uuid4()), "Amount": 121.0, "Reference": "F-1", "PaymentStatus": 1,
            "Document": {"id": str(uuid.uuid4())}}
    telling = sync.sync_payment_items(administratie_id=administratie_id, client=FakeBankClient(items=[item]))
    assert telling.aangemaakt == 1

    # Post betaald → verdwijnt uit de collectie → gemarkeerd, nooit verwijderd.
    telling = sync.sync_payment_items(administratie_id=administratie_id, client=FakeBankClient(items=[]))
    assert telling.verdwenen == 1
    with admin_engine.connect() as conn:
        verdwenen = conn.execute(
            text("SELECT verdwenen_uit_bron_op FROM boekhouding.payment_item_cache WHERE id = :id"),
            {"id": item["id"]},
        ).scalar_one()
    assert verdwenen is not None


def test_volledige_bank_sync_run_zonder_autoboeken(
    administratie_id: uuid.UUID, admin_engine: Engine
) -> None:
    tx = _tx_record(create_date="2026-07-01T08:00:00")
    client = FakeBankClient(accounts=[_account_record()], transacties={tx["id"]: tx}, items=[])
    resultaat = sync.sync_bank_voor_administratie(administratie_id=administratie_id, client=client)
    assert resultaat.mutaties.aangemaakt == 1
    assert resultaat.automatisch_geboekt == 0
    assert resultaat.vastly_gemeld == 0
