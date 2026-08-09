"""Afletteren via de betaal-kant (seam-swap 2026-08-09): API-koppeling + directe verificatie,
assist-fallback bij een API-fout (de bestaande verificatie-/leesspoor-tests dekken die route),
intrekken, tekens/deelbetaling en de automatische stap-1-verwerking."""

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
        client=FakeBankClient(faal_op="link"),
    )
    # API-fout → assist-fallback: opdracht blijft zichtbaar klaargezet mét de fout (nooit stil).
    assert uitvoering.uitkomst == "wacht_op_mens_in_rlz"
    assert uitvoering.fout is not None

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
        client=FakeBankClient(faal_op="link"),
    )
    with pytest.raises(afletteren.OpdrachtBestaatAl):
        afletteren.zet_klaar_voor_afletteren(
            administratie_id=administratie_id, payment_transaction_id=mutatie_id,
            payment_item_id=item_id, actor_id=beheerder_id,
            client=FakeBankClient(faal_op="link"),
        )

    dichte_mutatie = maak_bank_mutatie(admin_engine, administratie_id=administratie_id, open_bedrag="0")
    with pytest.raises(afletteren.MutatieNietOpen):
        afletteren.zet_klaar_voor_afletteren(
            administratie_id=administratie_id, payment_transaction_id=dichte_mutatie,
            payment_item_id=item_id, actor_id=beheerder_id,
            client=FakeBankClient(faal_op="link"),
        )


def test_verificatie_wacht_zolang_mutatie_open_is_en_stempelt_de_poging(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID
) -> None:
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id)
    item_id = maak_payment_item(admin_engine, administratie_id=administratie_id)
    afletteren.zet_klaar_voor_afletteren(
        administratie_id=administratie_id, payment_transaction_id=mutatie_id,
        payment_item_id=item_id, actor_id=beheerder_id,
        client=FakeBankClient(faal_op="link"),
    )
    client = FakeBankClient(
        transacties={str(mutatie_id): {"id": str(mutatie_id), "OpenAmount": -121.0, "PaymentReferenceList": []}}
    )
    assert afletteren.verifieer_openstaande_opdrachten(administratie_id=administratie_id, client=client) == 0
    assert _opdrachten(admin_engine, administratie_id)[0][0] == "klaargezet"
    # Kliktest 2026-08-08: de poging is zichtbaar gestempeld — de UI kan "wacht op verificatie
    # (laatst gecontroleerd …, nog open in RLZ)" tonen i.p.v. een status die niets lijkt te doen.
    with admin_engine.connect() as conn:
        poging = conn.execute(
            text(
                "SELECT laatste_verificatie_poging_op FROM boekhouding.bank_afletter_opdracht "
                "WHERE administratie_id = :aid"
            ),
            {"aid": administratie_id},
        ).scalar_one()
    assert poging is not None


def test_verificatie_per_rekening_raakt_alleen_die_rekening(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID
) -> None:
    """De "nu verifiëren"-knop verifieert per rekening — een klaargezette opdracht op een andere
    rekening blijft onaangeroerd (en de fake zou er ook op stukgelopen zijn: geen transactie)."""
    rekening_a, rekening_b = uuid.uuid4(), uuid.uuid4()
    mutatie_a = maak_bank_mutatie(admin_engine, administratie_id=administratie_id, payment_account_id=rekening_a)
    mutatie_b = maak_bank_mutatie(admin_engine, administratie_id=administratie_id, payment_account_id=rekening_b)
    item_id = maak_payment_item(admin_engine, administratie_id=administratie_id)
    for mutatie_id in (mutatie_a, mutatie_b):
        afletteren.zet_klaar_voor_afletteren(
            administratie_id=administratie_id, payment_transaction_id=mutatie_id,
            payment_item_id=item_id, actor_id=beheerder_id,
            client=FakeBankClient(faal_op="link"),
        )
    client = FakeBankClient(
        transacties={str(mutatie_a): {"id": str(mutatie_a), "OpenAmount": 0, "PaymentReferenceList": []}}
    )
    geverifieerd = afletteren.verifieer_openstaande_opdrachten(
        administratie_id=administratie_id, client=client, payment_account_id=rekening_a
    )
    assert geverifieerd == 1
    statussen = {rij[0] for rij in _opdrachten(admin_engine, administratie_id)}
    assert statussen == {"geverifieerd", "klaargezet"}


def test_opdrachten_voor_rekening_levert_levenscyclus_lijst(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID
) -> None:
    """Geverifieerde opdrachten verdwenen stil uit de open-mutatielijst (kliktest 2026-08-08) —
    deze lijst houdt ze zichtbaar, mét mutatie-context."""
    rekening = uuid.uuid4()
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id, payment_account_id=rekening)
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

    lijst = afletteren.afletter_opdrachten_voor_rekening(
        administratie_id=administratie_id, payment_account_id=rekening
    )
    assert len(lijst) == 1
    assert lijst[0].opdracht.status == "geverifieerd"
    assert lijst[0].opdracht.geverifieerd_op is not None
    assert lijst[0].tegenpartij_naam == "Testpartij B.V."
    # Andere rekening: leeg.
    assert (
        afletteren.afletter_opdrachten_voor_rekening(
            administratie_id=administratie_id, payment_account_id=uuid.uuid4()
        )
        == []
    )


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
        client=FakeBankClient(faal_op="link"),
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
        client=FakeBankClient(faal_op="link"),
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
        client=FakeBankClient(faal_op="link"),
    )
    afletteren.trek_afletter_opdracht_in(
        administratie_id=administratie_id, opdracht_id=uitvoering.opdracht_id, actor_id=beheerder_id
    )
    assert _opdrachten(admin_engine, administratie_id)[0][0] == "ingetrokken"
    # En daarna mag er een nieuwe opdracht klaargezet worden.
    afletteren.zet_klaar_voor_afletteren(
        administratie_id=administratie_id, payment_transaction_id=mutatie_id,
        payment_item_id=item_id, actor_id=beheerder_id,
        client=FakeBankClient(faal_op="link"),
    )


# --------------------------------------------------------------------- API-pad (seam-swap 2026-08-09)


def test_bereken_linked_amount_tekens_en_deelbetaling() -> None:
    """LinkedAmount draagt het teken van de mutatie; grootte = min(|mutatie|, |post|)."""
    from decimal import Decimal

    # Afschrijving (negatief), post exact even groot → volledig, negatief.
    assert afletteren.bereken_linked_amount(Decimal("-121.00"), Decimal("121.00")) == Decimal("-121.00")
    # Ontvangst (positief, huurbetaling) → positief.
    assert afletteren.bereken_linked_amount(Decimal("850.00"), Decimal("850.00")) == Decimal("850.00")
    # G-rekening-deelbetaling: mutatie kleiner dan de post → mutatiebedrag.
    assert afletteren.bereken_linked_amount(Decimal("-50.00"), Decimal("-105.42")) == Decimal("-50.00")
    # Verzamelbetaling: mutatie groter dan de post → postbedrag (mét mutatie-teken).
    assert afletteren.bereken_linked_amount(Decimal("-500.00"), Decimal("121.00")) == Decimal("-121.00")
    # Geen postbedrag bekend → het open mutatiebedrag.
    assert afletteren.bereken_linked_amount(Decimal("-121.00"), None) == Decimal("-121.00")


def _werkende_fake(mutatie_id: uuid.UUID, item_id: uuid.UUID, rlz_document_id: uuid.UUID) -> FakeBankClient:
    return FakeBankClient(
        transacties={
            str(mutatie_id): {"id": str(mutatie_id), "OpenAmount": -121.0, "PaymentReferenceList": []}
        },
        item_documenten={str(item_id): str(rlz_document_id)},
    )


def test_afletteren_via_api_koppelt_en_verifieert_direct(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID
) -> None:
    rlz_document_id = uuid.uuid4()
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id)
    item_id = maak_payment_item(
        admin_engine, administratie_id=administratie_id, rlz_document_id=rlz_document_id
    )
    fake = _werkende_fake(mutatie_id, item_id, rlz_document_id)
    uitvoering = afletteren.zet_klaar_voor_afletteren(
        administratie_id=administratie_id, payment_transaction_id=mutatie_id,
        payment_item_id=item_id, actor_id=beheerder_id, client=fake,
    )
    assert uitvoering.uitkomst == "afgeletterd_via_api"
    assert uitvoering.fout is None
    # De echte body-vorm ging eruit (capture-replay): teken van de mutatie, pin op methode 1.
    [link] = fake.links
    assert link["linked_amount"] == -121.0
    assert link["is_completely_paid"] is False
    assert link["payment_correction_method"] == 1
    status, detail = _opdrachten(admin_engine, administratie_id)[0]
    assert status == "geverifieerd"
    assert detail["uitvoering"] == "api"
    assert detail["voorstel_gevolgd"] is True
    assert detail["koppelingen"][0]["rlz_document_id"] == str(rlz_document_id)
    with admin_engine.connect() as conn:
        open_bedrag = conn.execute(
            text("SELECT open_bedrag FROM boekhouding.bank_mutatie WHERE id = :id"), {"id": mutatie_id}
        ).scalar_one()
        audits = conn.execute(
            text("SELECT COUNT(*) FROM platform.audit_event WHERE actie = 'afgeletterd_via_api'")
        ).scalar_one()
    assert open_bedrag == 0
    assert audits == 1


def test_api_fout_valt_zichtbaar_terug_op_assist(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID
) -> None:
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id)
    item_id = maak_payment_item(admin_engine, administratie_id=administratie_id)
    uitvoering = afletteren.zet_klaar_voor_afletteren(
        administratie_id=administratie_id, payment_transaction_id=mutatie_id,
        payment_item_id=item_id, actor_id=beheerder_id,
        client=FakeBankClient(faal_op="link_stale_item"),  # 404 = verouderd item-id (replay-les)
    )
    assert uitvoering.uitkomst == "wacht_op_mens_in_rlz"
    assert "mislukt" in (uitvoering.fout or "")
    assert _opdrachten(admin_engine, administratie_id)[0][0] == "klaargezet"
    with admin_engine.connect() as conn:
        audits = conn.execute(
            text("SELECT COUNT(*) FROM platform.audit_event WHERE actie = 'afletteren_api_fout'")
        ).scalar_one()
    assert audits == 1


def test_204_zonder_effect_is_zichtbare_fout(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID
) -> None:
    """Bekend RLZ-gedrag: 204 zonder waarneembaar effect — nooit stil als succes behandelen."""
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id)
    item_id = maak_payment_item(admin_engine, administratie_id=administratie_id)
    fake = FakeBankClient(
        transacties={
            str(mutatie_id): {"id": str(mutatie_id), "OpenAmount": -121.0, "PaymentReferenceList": []}
        },
        faal_op="link_zonder_effect",
    )
    uitvoering = afletteren.zet_klaar_voor_afletteren(
        administratie_id=administratie_id, payment_transaction_id=mutatie_id,
        payment_item_id=item_id, actor_id=beheerder_id, client=fake,
    )
    assert uitvoering.uitkomst == "wacht_op_mens_in_rlz"
    assert "niet zichtbaar" in (uitvoering.fout or "")
    assert _opdrachten(admin_engine, administratie_id)[0][0] == "klaargezet"


def test_voer_bestaande_opdracht_uit_na_eerdere_fout(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID
) -> None:
    """'Nu afletteren' op een opdracht uit het assist-tijdperk (of na een API-fout)."""
    rlz_document_id = uuid.uuid4()
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id)
    item_id = maak_payment_item(
        admin_engine, administratie_id=administratie_id, rlz_document_id=rlz_document_id
    )
    eerste = afletteren.zet_klaar_voor_afletteren(
        administratie_id=administratie_id, payment_transaction_id=mutatie_id,
        payment_item_id=item_id, actor_id=beheerder_id,
        client=FakeBankClient(faal_op="link"),
    )
    assert eerste.uitkomst == "wacht_op_mens_in_rlz"
    fake = _werkende_fake(mutatie_id, item_id, rlz_document_id)
    tweede = afletteren.voer_bestaande_opdracht_uit(
        administratie_id=administratie_id, opdracht_id=eerste.opdracht_id,
        actor_id=beheerder_id, client=fake,
    )
    assert tweede.uitkomst == "afgeletterd_via_api"
    assert _opdrachten(admin_engine, administratie_id)[0][0] == "geverifieerd"


def test_exacte_matches_automatisch_achter_optin_en_volumerem(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Voorstel-volgorde stap 1 automatisch tijdens de sync: exacte match (referentie + bedrag)
    lettert af met de systeem-actor; een deelmatch blijft liggen (één-klik, nooit auto)."""
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID

    rlz_document_id = uuid.uuid4()
    # Exacte match: omschrijving draagt de referentie, bedrag gelijk.
    exact = maak_bank_mutatie(
        admin_engine, administratie_id=administratie_id,
        omschrijving="betaling F-2026-0642", bedrag="-121.00",
    )
    item_id = maak_payment_item(
        admin_engine, administratie_id=administratie_id,
        referentie="F-2026-0642", rlz_document_id=rlz_document_id,
    )
    # Deelmatch (zelfde referentie, ander bedrag): mág niet automatisch.
    deel = maak_bank_mutatie(
        admin_engine, administratie_id=administratie_id,
        omschrijving="deelbetaling F-2026-0642", bedrag="-50.00",
    )
    fake = FakeBankClient(
        transacties={
            str(exact): {"id": str(exact), "OpenAmount": -121.0, "PaymentReferenceList": []},
            str(deel): {"id": str(deel), "OpenAmount": -50.0, "PaymentReferenceList": []},
        },
        item_documenten={str(item_id): str(rlz_document_id)},
    )
    gedaan, fouten = afletteren.verwerk_exacte_matches_automatisch(
        administratie_id=administratie_id, client=fake
    )
    assert gedaan == 1 and fouten == []
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text(
                "SELECT payment_transaction_id, status, klaargezet_door "
                "FROM boekhouding.bank_afletter_opdracht WHERE administratie_id = :aid"
            ),
            {"aid": administratie_id},
        ).all()
    assert len(rijen) == 1
    assert rijen[0][0] == exact  # alleen de exacte match, nooit de deelmatch
    assert rijen[0][1] == "geverifieerd"
    assert str(rijen[0][2]) == str(SYSTEEM_ACTOR_ID)

    # Volumerem: limiet 0 → niets meer, zichtbare reden.
    from app.config import settings

    monkeypatch.setattr(settings, "max_boekingen_per_dag_per_administratie", 0)
    nogmaals = maak_bank_mutatie(
        admin_engine, administratie_id=administratie_id,
        omschrijving="betaling F-2026-0643", bedrag="-99.00",
    )
    maak_payment_item(
        admin_engine, administratie_id=administratie_id, referentie="F-2026-0643", bedrag="99.00",
    )
    fake.transacties[str(nogmaals)] = {"id": str(nogmaals), "OpenAmount": -99.0, "PaymentReferenceList": []}
    gedaan2, fouten2 = afletteren.verwerk_exacte_matches_automatisch(
        administratie_id=administratie_id, client=fake
    )
    assert gedaan2 == 0
    assert any("volumerem" in f for f in fouten2)
