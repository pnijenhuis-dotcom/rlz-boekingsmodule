"""RC-consequentie doorbelasting (BLOK 2, verkenning/16 §2b): open posten van
intercompany-tegenpartijen lopen via de rekening-courant en mogen in géén enkel
afletter-voorstel of match verschijnen — plus de fail-closed poort voor de handmatige route."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine

from app.bank import afletteren, voorstellen
from app.bank.matchmotor import VoorstelSoort
from app.bank.sync import _item_waarden
from tests.auth.conftest import actieve_gebruiker, administratie_id, beheerder_id  # noqa: F401
from tests.bank.conftest import (  # noqa: F401
    FakeBankClient,
    maak_bank_mutatie,
    maak_intercompany_tegenpartij,
    maak_payment_item,
)

IC_ENTITY = uuid.UUID("c997e324-bfda-4a84-afc7-a416d367db3a")  # Veldhoven Recreatie (§1)


def test_matchcontext_filtert_ic_posten(administratie_id: uuid.UUID, admin_engine: Engine) -> None:
    ic_item = maak_payment_item(
        admin_engine, administratie_id=administratie_id, entity_guid=IC_ENTITY, entity_naam="Veldhoven Recreatie B.V."
    )
    gewoon_item = maak_payment_item(admin_engine, administratie_id=administratie_id, referentie="F-2026-9999")
    maak_intercompany_tegenpartij(admin_engine, administratie_id=administratie_id, entity_guid=IC_ENTITY)

    context = voorstellen.laad_matchcontext(administratie_id=administratie_id)
    post_ids = {post.id for post in context.open_posten}
    assert gewoon_item in post_ids
    assert ic_item not in post_ids


def test_inactieve_ic_rij_filtert_niet(administratie_id: uuid.UUID, admin_engine: Engine) -> None:
    # intrekbaar: mapping op intercompany=False → rij inactief → post doet gewoon weer mee
    item = maak_payment_item(admin_engine, administratie_id=administratie_id, entity_guid=IC_ENTITY)
    maak_intercompany_tegenpartij(
        admin_engine, administratie_id=administratie_id, entity_guid=IC_ENTITY, actief=False
    )
    context = voorstellen.laad_matchcontext(administratie_id=administratie_id)
    assert item in {post.id for post in context.open_posten}


def test_exacte_match_kandidaat_wordt_nooit_ic_voorstel(
    administratie_id: uuid.UUID, admin_engine: Engine
) -> None:
    """Een IC-post die qua referentie+bedrag exact zou matchen (stap 1, auto-afletteren) mag
    nooit als voorstel verschijnen — de mutatie valt terug op handmatig."""
    maak_bank_mutatie(
        admin_engine,
        administratie_id=administratie_id,
        bedrag="-121.00",
        omschrijving="betaling F-2026-0642",
    )
    maak_payment_item(
        admin_engine,
        administratie_id=administratie_id,
        bedrag="121.00",
        referentie="F-2026-0642",
        entity_guid=IC_ENTITY,
    )
    maak_intercompany_tegenpartij(admin_engine, administratie_id=administratie_id, entity_guid=IC_ENTITY)

    met_voorstel = voorstellen.open_mutaties_met_voorstellen(administratie_id=administratie_id)
    assert len(met_voorstel) == 1
    assert met_voorstel[0].voorstel.soort == VoorstelSoort.HANDMATIG
    assert met_voorstel[0].voorstel.payment_item_id is None


def test_zet_klaar_voor_afletteren_weigert_ic_post_fail_closed(
    administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID
) -> None:
    """De handmatige API-route (rechtstreeks een payment_item_id aanwijzen) botst op de
    fail-closed poort — óók al staat de post gewoon in de cache."""
    mutatie_id = maak_bank_mutatie(admin_engine, administratie_id=administratie_id)
    item_id = maak_payment_item(
        admin_engine,
        administratie_id=administratie_id,
        entity_guid=IC_ENTITY,
        entity_naam="Veldhoven Recreatie B.V.",
    )
    maak_intercompany_tegenpartij(admin_engine, administratie_id=administratie_id, entity_guid=IC_ENTITY)

    with pytest.raises(afletteren.IntercompanyPostUitgesloten, match="rekening-courant"):
        afletteren.zet_klaar_voor_afletteren(
            administratie_id=administratie_id,
            payment_transaction_id=mutatie_id,
            payment_item_id=item_id,
            actor_id=beheerder_id,
            client=FakeBankClient(),
        )


def test_item_waarden_neemt_entity_mee_uit_geneste_expand() -> None:
    """STAP-0-geverifieerd (2026-08-13): Document($expand=Entity) draagt de tegenpartij."""
    record = {
        "id": str(uuid.uuid4()),
        "Amount": 121.0,
        "Reference": "F-2026-0642",
        "Document": {"id": str(uuid.uuid4()), "Entity": {"id": str(IC_ENTITY), "Name": "Veldhoven Recreatie B.V."}},
    }
    waarden = _item_waarden(record)
    assert waarden["entity_guid"] == IC_ENTITY
    assert waarden["entity_naam"] == "Veldhoven Recreatie B.V."

    zonder = _item_waarden({"id": str(uuid.uuid4()), "Amount": 1.0, "Document": {"id": str(uuid.uuid4())}})
    assert zonder["entity_guid"] is None
    assert zonder["entity_naam"] is None
