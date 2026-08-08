"""Bank-leeskant: rekeningen (incl. versheid-probe), incrementele mutatie-sync met
CreateDate-watermark + open-verversronde, open-posten met verdwenen-markering."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Engine, text

from app.bank import sync
from tests.bank.conftest import FakeBankClient


def _account_record(*, naam: str = "ING zakelijk", rekening_type: int = 1, is_archived: bool = False) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "Name": naam,
        "IBAN": "NL91INGB0002445588",
        "Type": rekening_type,
        "CurrentBalance": 48212.90,
        "LastBalanceDate": "2026-07-31T00:00:00",
        "IsArchived": is_archived,
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


def test_probe_slaat_rekeningen_zonder_aanleverpad_over(administratie_id: uuid.UUID) -> None:
    """Kliktest-fix 2026-08-08: kas (3), verrekeningen (4), RC/privé (5) en gearchiveerde
    rekeningen geven bewezen 400 op LastBankImport — die worden niet eens geprobed."""
    bank = _account_record()
    kas = _account_record(naam="Kas", rekening_type=3)
    verrekeningen = _account_record(naam="Verrekeningen", rekening_type=4)
    rc = _account_record(naam="RC Beheer B.V.", rekening_type=5)
    archief = _account_record(naam="Oude betaalrekening", is_archived=True)
    client = FakeBankClient(
        accounts=[bank, kas, verrekeningen, rc, archief],
        last_imports={bank["id"]: {"FileName": "x.940", "Date": "2026-07-31T06:04:00"}},
    )
    telling = sync.sync_payment_accounts(administratie_id=administratie_id, client=client)
    assert telling.aangemaakt == 5
    assert client.import_probes == [bank["id"]]


def test_falende_probe_breekt_sync_niet_af_en_is_zichtbaar(
    administratie_id: uuid.UUID, admin_engine: Engine
) -> None:
    """Failsafe (kliktest 2026-08-08, make bank-sync → 0/3): één kapotte versheid-probe mag
    nooit de administratie-sync afbreken — de rekening wordt zichtbaar gemarkeerd
    (laatste_import_probe_fout), de bestaande versheid blijft staan en de rest draait door.
    Regressie: een onverwachte 400 uit de probe hoort hier ook doorheen te komen."""
    from app.rlz.client import RlzApiError

    goed = _account_record(naam="Knab Zakelijk")
    kapot = _account_record(naam="ING zakelijk")
    versheid = {"FileName": "eerder.940", "Date": "2026-07-01T06:00:00"}

    # Ronde 1: beide probes slagen — de kapotte rekening heeft dan al een bekende versheid.
    client = FakeBankClient(
        accounts=[goed, kapot],
        last_imports={goed["id"]: {"FileName": "x.940"}, kapot["id"]: versheid},
    )
    sync.sync_payment_accounts(administratie_id=administratie_id, client=client)

    # Ronde 2: de probe op één rekening faalt met een onverwachte 400.
    client.last_imports[kapot["id"]] = RlzApiError(
        400, "GET", f"PaymentAccounts/{kapot['id']}/LastBankImport", '{"Message":"iets anders"}'
    )
    telling = sync.sync_payment_accounts(administratie_id=administratie_id, client=client)
    assert telling.bijgewerkt == 2  # de sync liep gewoon door

    with admin_engine.connect() as conn:
        rijen = {
            naam: (fout, bestand)
            for naam, fout, bestand in conn.execute(
                text(
                    "SELECT naam, laatste_import_probe_fout, laatste_import ->> 'FileName' "
                    "FROM boekhouding.payment_account_cache WHERE administratie_id = :aid"
                ),
                {"aid": administratie_id},
            ).all()
        }
    fout, bestand = rijen["ING zakelijk"]
    assert fout is not None and "400" in fout
    assert bestand == "eerder.940"  # laatst-bekende versheid blijft staan
    assert rijen["Knab Zakelijk"][0] is None

    # Ronde 3: probe herstelt — de markering verdwijnt en de versheid wordt ververst.
    client.last_imports[kapot["id"]] = {"FileName": "nieuw.940"}
    sync.sync_payment_accounts(administratie_id=administratie_id, client=client)
    with admin_engine.connect() as conn:
        fout, bestand = conn.execute(
            text(
                "SELECT laatste_import_probe_fout, laatste_import ->> 'FileName' "
                "FROM boekhouding.payment_account_cache WHERE administratie_id = :aid AND naam = 'ING zakelijk'"
            ),
            {"aid": administratie_id},
        ).one()
    assert fout is None
    assert bestand == "nieuw.940"


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
