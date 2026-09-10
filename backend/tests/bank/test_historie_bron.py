"""Historie-cache (blok B bundel 10-09): module-boekingen + RLZ-lezing via PaymentReferenceList/BMDB,
markeringsrijen, max-per-run, geen dubbele lezing, en de matchcontext leest 'm terug."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import Engine, text

from app.bank import historie_bron, voorstellen
from tests.bank.conftest import FakeBankClient, maak_bank_mutatie


def _cache(admin_engine: Engine, administratie_id: uuid.UUID) -> list[tuple]:
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT payment_transaction_id, ledger_id, bron FROM boekhouding.bank_historie_boeking "
                "WHERE administratie_id = :aid ORDER BY bron, payment_transaction_id"
            ),
            {"aid": administratie_id},
        ).all()


def _afgeletterde_mutatie(admin_engine, administratie_id, *, dagen_terug: int = 100) -> uuid.UUID:
    return maak_bank_mutatie(
        admin_engine,
        administratie_id=administratie_id,
        bedrag="-100.00",
        open_bedrag="0",
        tegenpartij_naam="KPN B.V.",
        omschrijving="KPN abonnement",
        tegenrekening_iban="NL20INGB0001234567",
        boekdatum=(date.today() - timedelta(days=dagen_terug)).isoformat(),
    )


def _bmdb(client: FakeBankClient, mutatie_id: uuid.UUID, *, lines: list[dict]) -> None:
    doc_id = str(uuid.uuid4())
    client.direct_bookings[doc_id] = {"id": doc_id, "Status": 3, "DocumentType": 19, "DocumentLineList": lines}
    client.transacties[str(mutatie_id)] = {
        "id": str(mutatie_id),
        "OpenAmount": 0.0,
        "PaymentReferenceList": [{"Amount": -100.0, "Document": {"id": doc_id, "DocumentType": 19, "Status": 3}}],
    }


def test_rlz_lezing_vult_cache_en_markeert_zonder_grootboek(administratie_id: uuid.UUID, admin_engine: Engine) -> None:
    ledger = uuid.uuid4()
    m_gb = _afgeletterde_mutatie(admin_engine, administratie_id, dagen_terug=100)
    m_factuur = _afgeletterde_mutatie(admin_engine, administratie_id, dagen_terug=90)
    m_split = _afgeletterde_mutatie(admin_engine, administratie_id, dagen_terug=80)
    m_oud = _afgeletterde_mutatie(admin_engine, administratie_id, dagen_terug=500)  # buiten het venster
    client = FakeBankClient()
    _bmdb(client, m_gb, lines=[{"Account": {"id": str(ledger)}, "TaxRate": None, "NetAmount": -100.0}])
    client.transacties[str(m_factuur)] = {
        "id": str(m_factuur),
        "OpenAmount": 0.0,
        "PaymentReferenceList": [{"Document": {"id": str(uuid.uuid4()), "DocumentType": 1, "Status": 3}}],
    }
    _bmdb(client, m_split, lines=[{"Account": {"id": str(uuid.uuid4())}}, {"Account": {"id": str(uuid.uuid4())}}])

    vulling = historie_bron.vul_historie_cache(administratie_id=administratie_id, client=client)

    assert (vulling.module_toegevoegd, vulling.rlz_toegevoegd, vulling.rlz_gemarkeerd, vulling.rlz_resterend) == (
        0,
        1,
        2,
        0,
    )
    assert vulling.fouten == []
    rijen = {r[0]: (r[1], r[2]) for r in _cache(admin_engine, administratie_id)}
    assert rijen[m_gb] == (ledger, "rlz")
    assert rijen[m_factuur] == (None, "rlz_geen_grootboek")
    assert rijen[m_split] == (None, "rlz_gesplitst")
    assert m_oud not in rijen

    # Tweede run: niets opnieuw gelezen (markeringen voorkomen een GET-storm).
    aantal_voor = len(client.lijst_params)
    vulling2 = historie_bron.vul_historie_cache(administratie_id=administratie_id, client=client)
    assert (vulling2.rlz_toegevoegd, vulling2.rlz_gemarkeerd) == (0, 0) and len(client.lijst_params) == aantal_voor

    ctx = voorstellen.laad_matchcontext(administratie_id=administratie_id)
    assert [h.ledger_id for h in ctx.historie] == [ledger]


def test_max_per_run_laat_rest_voor_volgende_nacht(administratie_id: uuid.UUID, admin_engine: Engine) -> None:
    client = FakeBankClient()
    for i in range(3):
        m = _afgeletterde_mutatie(admin_engine, administratie_id, dagen_terug=10 + i)
        _bmdb(client, m, lines=[{"Account": {"id": str(uuid.uuid4())}}])
    vulling = historie_bron.vul_historie_cache(administratie_id=administratie_id, client=client, max_rlz_lezingen=2)
    assert (vulling.rlz_toegevoegd, vulling.rlz_resterend) == (2, 1)
    vulling2 = historie_bron.vul_historie_cache(administratie_id=administratie_id, client=client, max_rlz_lezingen=2)
    assert (vulling2.rlz_toegevoegd, vulling2.rlz_resterend) == (1, 0)


def test_module_boekingen_komen_in_de_cache_zonder_rlz_lezing(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID
) -> None:
    mutatie_id = _afgeletterde_mutatie(admin_engine, administratie_id)
    boeking_id, ledger = uuid.uuid4(), uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.bank_boeking "
                "(id, administratie_id, payment_transaction_id, rlz_document_id, bron, "
                "status, geboekt_door) VALUES (:id, :aid, :tx, :doc, 'handmatig', 'geboekt', :door)"
            ),
            {"id": boeking_id, "aid": administratie_id, "tx": mutatie_id, "doc": uuid.uuid4(), "door": beheerder_id},
        )
        conn.execute(
            text(
                "INSERT INTO boekhouding.bank_boeking_regel (id, bank_boeking_id, volgnummer, ledger_id, netto_bedrag) "
                "VALUES (:id, :b, 1, :ledger, -100.00)"
            ),
            {"id": uuid.uuid4(), "b": boeking_id, "ledger": ledger},
        )
    client = FakeBankClient()  # kent de mutatie niet: een RLZ-lezing zou 404 geven
    vulling = historie_bron.vul_historie_cache(administratie_id=administratie_id, client=client)
    assert (vulling.module_toegevoegd, vulling.rlz_toegevoegd, vulling.fouten) == (1, 0, [])
    assert _cache(admin_engine, administratie_id) == [(mutatie_id, ledger, "module")]


def test_zonder_client_alleen_module_en_telling_resterend(administratie_id: uuid.UUID, admin_engine: Engine) -> None:
    _afgeletterde_mutatie(admin_engine, administratie_id)
    vulling = historie_bron.vul_historie_cache(administratie_id=administratie_id, client=None)
    assert (vulling.rlz_toegevoegd, vulling.rlz_resterend) == (0, 1)
