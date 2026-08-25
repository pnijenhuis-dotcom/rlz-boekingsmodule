"""Klaargezette doorbelasting door de klant-accorderingsflow (besluit Peter 25-08, punt A3):
aanbieden vereist groene doorbelasting-checks, de accordeur ziet de verdeling alleen-lezen in
de wachtrij, en ná het laatste akkoord boekt alles in één gang (inkoop → verkoop → spiegel)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine

from app.accordering import service
from app.documenten import boeken
from app.doorbelasting import boeken as doorbelasting_boeken
from app.doorbelasting import service as doorbelasting_service
from app.doorbelasting.service import VerdeelRegelInvoerData
from tests.accordering.conftest import document_status, zet_schema
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.doorbelasting.conftest import (  # noqa: F401 — fixtures via import geregistreerd
    DOEL_KOSTEN_LEDGER_ID,
    PROVISIE_KOSTEN_LEDGER_ID,
    FakeDoorbelastingClient,
    doel_administratie_id,
    doorbelasting_aan,
    haal_run,
    instelling_compleet,
    maak_mapping,
)


def _laag(volgnummer: int, accordeur_id: uuid.UUID) -> service.LaagInput:
    return service.LaagInput(volgnummer=volgnummer, accordeur_gebruiker_id=accordeur_id, bedrag_drempel=None)


@pytest.fixture
def klaargezet_op_klaar_document(
    doorbelasting_aan: None,  # noqa: F811
    instelling_compleet: None,  # noqa: F811
    doel_administratie_id: uuid.UUID,  # noqa: F811
    klaar_document: uuid.UUID,
    administratie_id: uuid.UUID,
    beheerder_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
) -> dict:
    from app.documenten import boekvoorstel

    voorstel = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=klaar_document)
    mapping = maak_mapping(
        administratie_id=administratie_id,
        actor_id=beheerder_id,
        naam="Oirschot Recreatie B.V.",
        doel_administratie_id=doel_administratie_id,
        provisie_kosten_ledger_id=PROVISIE_KOSTEN_LEDGER_ID,
    )
    run = doorbelasting_service.start_of_haal_run(
        administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker
    )
    doorbelasting_service.sla_verdeling_op(
        administratie_id=administratie_id,
        run_id=run.id,
        actor_id=gescoopte_gebruiker,
        regels=[
            VerdeelRegelInvoerData(
                bron_regel_id=voorstel.regels[0].id,
                mapping_id=mapping.id,
                percentage=Decimal("100"),
                doel_kosten_ledger_id=DOEL_KOSTEN_LEDGER_ID,
            )
        ],
    )
    return {"run": run, "mapping": mapping, "regel_id": voorstel.regels[0].id}


def test_aanbieden_weigert_rode_doorbelasting_checks(
    klaargezet_op_klaar_document: dict,
    klaar_document: uuid.UUID,
    administratie_id: uuid.UUID,
    beheerder_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
    accordeur_1: uuid.UUID,
    admin_engine: Engine,
) -> None:
    zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
    doorbelasting_service.sla_verdeling_op(
        administratie_id=administratie_id,
        run_id=klaargezet_op_klaar_document["run"].id,
        actor_id=gescoopte_gebruiker,
        regels=[
            VerdeelRegelInvoerData(
                bron_regel_id=klaargezet_op_klaar_document["regel_id"],
                mapping_id=klaargezet_op_klaar_document["mapping"].id,
                percentage=Decimal("40"),
                doel_kosten_ledger_id=DOEL_KOSTEN_LEDGER_ID,
            )
        ],
    )
    with pytest.raises(service.ChecksNietGroen):
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
    assert document_status(admin_engine, klaar_document) == "klaar_om_te_boeken"


def test_accordeur_ziet_verdeling_alleen_lezen_en_laatste_akkoord_boekt_alles(
    klaargezet_op_klaar_document: dict,
    klaar_document: uuid.UUID,
    administratie_id: uuid.UUID,
    beheerder_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
    accordeur_1: uuid.UUID,
    boeken_aan: None,
    admin_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inkoop = FakeBoekClient()
    monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: inkoop)
    bron, doel = FakeDoorbelastingClient(), FakeDoorbelastingClient()
    # De accorderingsflow kent geen client-seams: de motor-clientfabriek wordt hier gepatcht
    # (bron-administratie → bron, elke andere → doel).
    monkeypatch.setattr(doorbelasting_boeken, "_rlz_client_voor", lambda aid: bron if aid == administratie_id else doel)
    zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])

    # Aanbieden toetst óók de doel-scope (A2): een medewerker met alleen bron-scope wordt vooraf
    # geweigerd — niets geschreven; de Beheerder (scope op alles) mag door.
    with pytest.raises(service.ChecksNietGroen):
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
    service.bied_ter_accordering_aan(
        administratie_id=administratie_id,
        document_id=klaar_document,
        actor_id=beheerder_id,
        actor_rol="beheerder",
    )
    assert document_status(admin_engine, klaar_document) == "ter_accordering"

    # Wachtrij: alleen-lezen samenvatting per doelentiteit (naam, %, bedrag excl., provisie)
    [item] = service.wachtrij_voor_accordeur(actor_id=accordeur_1, administratie_ids=[administratie_id])
    assert item.doorbelasting is not None and len(item.doorbelasting) == 1
    regel = item.doorbelasting[0]
    assert regel.doelentiteit_naam == "Oirschot Recreatie B.V."
    assert regel.percentage == Decimal("100.00")
    assert regel.netto_totaal == Decimal("100.00")
    assert regel.provisie_bedrag == Decimal("5.00")

    # Verdeling is bevroren zolang het bij de klant ligt
    with pytest.raises(doorbelasting_service.VerdelingBevroren):
        doorbelasting_service.sla_verdeling_op(
            administratie_id=administratie_id,
            run_id=klaargezet_op_klaar_document["run"].id,
            actor_id=gescoopte_gebruiker,
            regels=[],
        )

    resultaat = service.geef_akkoord(
        administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1
    )
    assert resultaat.alles_akkoord is True
    assert resultaat.geboekt is True
    assert resultaat.boek_fout is None
    assert document_status(admin_engine, klaar_document) == "geboekt"
    assert len(inkoop.puts) == 1
    assert len(bron.sales_invoices) == 1 and len(doel.purchase_invoices) == 1
    assert haal_run(administratie_id, klaargezet_op_klaar_document["run"].id).status == "geboekt"


def test_afwijzen_door_accordeur_geeft_verdeling_weer_vrij(
    klaargezet_op_klaar_document: dict,
    klaar_document: uuid.UUID,
    administratie_id: uuid.UUID,
    beheerder_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
    accordeur_1: uuid.UUID,
    admin_engine: Engine,
) -> None:
    """Fout in de verdeling = de bestaande afwijsknop met verplichte reden (geen aparte
    doorbelasting-afwijzing); daarna kan kantoor de klaargezette verdeling weer aanpassen."""
    zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
    service.bied_ter_accordering_aan(
        administratie_id=administratie_id,
        document_id=klaar_document,
        actor_id=beheerder_id,
        actor_rol="beheerder",
    )
    service.wijs_af(
        administratie_id=administratie_id,
        document_id=klaar_document,
        actor_id=accordeur_1,
        reden="Verdeling klopt niet: Oirschot hoort 50% te dragen",
    )
    assert document_status(admin_engine, klaar_document) != "ter_accordering"
    assert haal_run(administratie_id, klaargezet_op_klaar_document["run"].id).status == "klaargezet"
    doorbelasting_service.sla_verdeling_op(
        administratie_id=administratie_id,
        run_id=klaargezet_op_klaar_document["run"].id,
        actor_id=gescoopte_gebruiker,
        regels=[
            VerdeelRegelInvoerData(
                bron_regel_id=klaargezet_op_klaar_document["regel_id"],
                mapping_id=klaargezet_op_klaar_document["mapping"].id,
                percentage=Decimal("100"),
                doel_kosten_ledger_id=DOEL_KOSTEN_LEDGER_ID,
            )
        ],
    )
