"""Deel 4 punt 4 — splitsen: geldlogica (Σ = mutatie), geordende compositie, half-verwerkt + hervatten,
storno per deel (STAP-0 25-08 §2)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.bank import splitsen
from app.bank.splitsen import DeelInvoer
from tests.bank.conftest import FakeBankClient, maak_bank_mutatie, maak_payment_item, maak_relatie_referentiedata


def _tx(mutatie_id: uuid.UUID, bedrag: str = "-300.00") -> dict:
    return {"id": str(mutatie_id), "Amount": float(bedrag), "OpenAmount": float(bedrag), "PaymentReferenceList": [],
            "Date": "2026-08-25T00:00:00"}


def _grootboek(bedrag: str, *, netto: str | None = None, btw: str | None = None) -> DeelInvoer:
    return DeelInvoer(soort="grootboek", bedrag=Decimal(bedrag), spec={"regels": [
        {"ledger_id": str(uuid.uuid4()), "netto_bedrag": netto or bedrag, "btw_bedrag": btw}]})


def test_valideer_delen_som_teken_en_bestemming() -> None:
    m = Decimal("-300.00")
    splitsen.valideer_delen([_grootboek("-100.00"), _grootboek("-200.00")], mutatie_bedrag=m)
    with pytest.raises(splitsen.SplitsingOngeldig, match="rest"):
        splitsen.valideer_delen([_grootboek("-100.00"), _grootboek("-150.00")], mutatie_bedrag=m)
    with pytest.raises(splitsen.SplitsingOngeldig, match="teken"):
        splitsen.valideer_delen([_grootboek("-400.00"), _grootboek("100.00")], mutatie_bedrag=m)
    with pytest.raises(splitsen.SplitsingOngeldig, match="minstens twee"):
        splitsen.valideer_delen([_grootboek("-300.00")], mutatie_bedrag=m)
    with pytest.raises(splitsen.SplitsingOngeldig, match="regels"):
        splitsen.valideer_delen([_grootboek("-100.00", netto="-90.00"), _grootboek("-200.00")], mutatie_bedrag=m)
    with pytest.raises(splitsen.SplitsingOngeldig, match="payment_item_id"):
        splitsen.valideer_delen([DeelInvoer(soort="open_post", bedrag=Decimal("-100.00")), _grootboek("-200.00")], mutatie_bedrag=m)
    with pytest.raises(splitsen.SplitsingOngeldig, match="relatie_soort"):
        splitsen.valideer_delen([DeelInvoer(soort="relatie", bedrag=Decimal("-100.00"), spec={"entity_id": "x"}), _grootboek("-200.00")], mutatie_bedrag=m)


def test_mengvorm_open_post_relatie_grootboek_sluit_de_mutatie(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
) -> None:
    ref = maak_relatie_referentiedata(admin_engine, administratie_id=administratie_id)
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id, bedrag="-300.00")
    factuur_doc = uuid.uuid4()
    item_id = maak_payment_item(admin_engine, administratie_id=administratie_id, bedrag="100.00", rlz_document_id=factuur_doc)
    client = FakeBankClient(
        transacties={str(mutatie_id): _tx(mutatie_id)},
        items=[{"id": str(item_id), "OpenAmount": 100.0, "Document": {"id": str(factuur_doc)}}],
        item_documenten={str(item_id): str(factuur_doc)},
    )
    resultaat = splitsen.start_splitsing(
        administratie_id=administratie_id, payment_transaction_id=mutatie_id, actor_id=beheerder_id, client=client,
        delen=[
            _grootboek("-150.00", netto="-123.97", btw="-26.03"),  # kruispost/kosten — gewoon grootboek
            DeelInvoer(soort="relatie", bedrag=Decimal("-50.00"), spec={"relatie_soort": "crediteur", "entity_id": str(ref["vendor_id"])}),
            DeelInvoer(soort="open_post", bedrag=Decimal("-100.00"), spec={"payment_item_id": str(item_id)}),
        ],
    )
    assert resultaat.status == "verwerkt"
    # Volgorde: open post → relatie → grootboek (posten eerst).
    assert [d.soort for d in resultaat.delen] == ["open_post", "relatie", "grootboek"]
    assert all(d.status == "verwerkt" for d in resultaat.delen)
    assert client.links[0]["linked_amount"] == -100.0  # expliciet deelbedrag, niet min(open, post)
    assert client.links[1]["linked_amount"] == -50.0  # aanbetalingsdocument-koppeling
    assert client.transacties[str(mutatie_id)]["OpenAmount"] == 0.0
    with admin_engine.connect() as conn:
        open_bedrag = conn.execute(text("SELECT open_bedrag FROM boekhouding.bank_mutatie WHERE id = :id"), {"id": mutatie_id}).scalar_one()
        audits = conn.execute(text("SELECT actie, COUNT(*) FROM platform.audit_event WHERE actie LIKE 'bank_splitsing%' GROUP BY actie ORDER BY actie")).all()
    assert open_bedrag == Decimal("0")
    assert dict(audits) == {"bank_splitsing_aangemaakt": 1, "bank_splitsing_deel_verwerkt": 3, "bank_splitsing_status_gewijzigd": 1}
    # Leeslijst per rekening (mutatie zonder rekening → administratie-breed).
    assert [s.splitsing_id for s in splitsen.splitsingen_voor_rekening(administratie_id=administratie_id)] == [resultaat.splitsing_id]
    # Tweede actieve splitsing op dezelfde mutatie weigert.
    with pytest.raises(splitsen.SplitsingOngeldig):
        splitsen.start_splitsing(administratie_id=administratie_id, payment_transaction_id=mutatie_id, actor_id=beheerder_id,
                                 client=client, delen=[_grootboek("-100.00"), _grootboek("-200.00")])


def test_half_verwerkt_zichtbaar_en_hervatten_verwerkt_de_rest(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
) -> None:
    ref = maak_relatie_referentiedata(admin_engine, administratie_id=administratie_id)
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id, bedrag="-300.00")
    client = FakeBankClient(transacties={str(mutatie_id): _tx(mutatie_id)}, faal_op="put_aanbetaling")
    resultaat = splitsen.start_splitsing(
        administratie_id=administratie_id, payment_transaction_id=mutatie_id, actor_id=beheerder_id, client=client,
        delen=[
            DeelInvoer(soort="relatie", bedrag=Decimal("-50.00"), spec={"relatie_soort": "crediteur", "entity_id": str(ref["vendor_id"])}),
            _grootboek("-250.00"),
        ],
    )
    assert resultaat.status == "half_verwerkt"
    relatie_deel, gb_deel = resultaat.delen
    assert relatie_deel.status == "fout" and "mislukt" in (relatie_deel.fout or "")
    assert gb_deel.status == "wacht"  # stopt bij de eerste fout, rest blijft wachten — nooit stil doorgaan
    assert client.transacties[str(mutatie_id)]["OpenAmount"] == -300.0

    client.faal_op = None
    hervat = splitsen.hervat_splitsing(administratie_id=administratie_id, splitsing_id=resultaat.splitsing_id,
                                       actor_id=beheerder_id, client=client)
    assert hervat.status == "verwerkt" and all(d.status == "verwerkt" for d in hervat.delen)
    assert client.transacties[str(mutatie_id)]["OpenAmount"] == 0.0
    with admin_engine.connect() as conn:
        mislukt = conn.execute(text("SELECT COUNT(*) FROM platform.audit_event WHERE actie = 'bank_splitsing_deel_mislukt'")).scalar_one()
    assert mislukt == 1


def test_storno_per_deel_grootboek_terug_afletterdeel_niet_via_api(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID, boeken_aan: None
) -> None:
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id, bedrag="-300.00")
    factuur_doc = uuid.uuid4()
    item_id = maak_payment_item(admin_engine, administratie_id=administratie_id, bedrag="100.00", rlz_document_id=factuur_doc)
    client = FakeBankClient(
        transacties={str(mutatie_id): _tx(mutatie_id)},
        items=[{"id": str(item_id), "OpenAmount": 100.0, "Document": {"id": str(factuur_doc)}}],
        item_documenten={str(item_id): str(factuur_doc)},
    )
    resultaat = splitsen.start_splitsing(
        administratie_id=administratie_id, payment_transaction_id=mutatie_id, actor_id=beheerder_id, client=client,
        delen=[DeelInvoer(soort="open_post", bedrag=Decimal("-100.00"), spec={"payment_item_id": str(item_id)}), _grootboek("-200.00")],
    )
    open_post_deel, gb_deel = resultaat.delen
    with pytest.raises(splitsen.SplitsenFout, match="Type 16"):
        splitsen.storno_deel(administratie_id=administratie_id, deel_id=open_post_deel.deel_id, actor_id=beheerder_id,
                             reden="fout", client=client)
    na = splitsen.storno_deel(administratie_id=administratie_id, deel_id=gb_deel.deel_id, actor_id=beheerder_id,
                              reden="verkeerde kostenrekening", client=client)
    assert na.status == "half_verwerkt"
    gestorneerd = next(d for d in na.delen if d.deel_id == gb_deel.deel_id)
    assert gestorneerd.status == "gestorneerd"
    assert client.transacties[str(mutatie_id)]["OpenAmount"] == -200.0  # het deel komt terug (§2.4)
    # Hervatten boekt het gestorneerde deel opnieuw — mét cyclus 1, dus een nieuw GUID.
    opnieuw = splitsen.hervat_splitsing(administratie_id=administratie_id, splitsing_id=resultaat.splitsing_id,
                                        actor_id=beheerder_id, client=client)
    assert opnieuw.status == "half_verwerkt"  # gestorneerd deel blijft als historie; herverwerking is een expliciete keuze
    with admin_engine.connect() as conn:
        rij = conn.execute(text("SELECT status, cyclus FROM boekhouding.bank_splitsing_deel WHERE id = :id"), {"id": gb_deel.deel_id}).one()
    assert rij == ("gestorneerd", 1)
