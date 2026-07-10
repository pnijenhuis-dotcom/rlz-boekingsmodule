from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.documenten.rlz_ids import rlz_vendor_id
from app.sync import service
from app.sync.service import CrediteurAanmakenUitgeschakeld, CrediteurBestaatAl, SyncFout
from tests.sync.conftest import FakeRlzClient

# Fix 2 (2026-07-10, Peters controle van een echte factuur): de AI las de leverancier correct
# maar die stond niet in de crediteuren-cache — het controlescherm biedt dan "nieuwe crediteur
# aanmaken in RLZ". Deze tests dekken de servicelaag: idempotent GUID, duplicaatcheck,
# failsafe-poort (zelfde toggle als boeken + globale kill switch), cache-upsert en audit_event.


@pytest.fixture
def boeken_aan(beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)


def _cache_rijen(admin_engine: Engine, administratie_id: uuid.UUID) -> list[tuple]:
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT id, naam, verdwenen_uit_bron_op FROM boekhouding.vendor_cache "
                "WHERE administratie_id = :aid ORDER BY naam"
            ),
            {"aid": administratie_id},
        ).all()


def test_maakt_crediteur_aan_in_rlz_en_cache_met_audit(
    boeken_aan: None,
    administratie_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
    admin_engine: Engine,
) -> None:
    client = FakeRlzClient({})
    crediteur = service.maak_crediteur_aan(
        administratie_id=administratie_id, actor_id=gescoopte_gebruiker, naam="Confide BV", client=client
    )

    assert crediteur.naam == "Confide BV"
    assert crediteur.id == rlz_vendor_id(administratie_id, "Confide BV")
    assert client.aangemaakte_vendors == [(crediteur.id, "Confide BV")]

    rijen = _cache_rijen(admin_engine, administratie_id)
    assert len(rijen) == 1
    assert rijen[0][0] == crediteur.id
    assert rijen[0][1] == "Confide BV"
    assert rijen[0][2] is None  # niet verdwenen — direct kiesbaar in de combobox

    with admin_engine.connect() as conn:
        audit = conn.execute(
            text(
                "SELECT actie, nieuwe_waarde->>'naam' FROM platform.audit_event "
                "WHERE record_id = :rid AND actie = 'crediteur_aangemaakt_in_rlz'"
            ),
            {"rid": crediteur.id},
        ).all()
    assert audit == [("crediteur_aangemaakt_in_rlz", "Confide BV")]


def test_guid_is_deterministisch_op_administratie_en_genormaliseerde_naam(administratie_id: uuid.UUID) -> None:
    # Idempotentie-fundament: dubbele klik/retry op dezelfde naam raakt dezelfde RLZ-vendor.
    assert rlz_vendor_id(administratie_id, "Confide BV") == rlz_vendor_id(administratie_id, "  confide   bv ")
    assert rlz_vendor_id(administratie_id, "Confide BV") != rlz_vendor_id(uuid.uuid4(), "Confide BV")


def test_bestaande_naam_in_cache_geeft_conflict_zonder_rlz_schrijfactie(
    boeken_aan: None,
    administratie_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
) -> None:
    bestaande_id = uuid.uuid4()
    service.sync_vendors(
        administratie_id=administratie_id,
        client=FakeRlzClient({"Vendors": [{"id": str(bestaande_id), "Name": "Confide BV", "IsArchived": False}]}),
    )

    client = FakeRlzClient({})
    with pytest.raises(CrediteurBestaatAl) as excinfo:
        service.maak_crediteur_aan(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, naam="confide bv", client=client
        )
    assert excinfo.value.vendor_id == bestaande_id
    assert client.aangemaakte_vendors == []


def test_failsafe_poort_blokkeert_zonder_boeken_toggle(
    administratie_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
) -> None:
    # Default staat boeken_ingeschakeld uit — dan gaat er ook via deze route geen schrijfactie
    # de klantboekhouding in ("failsafe-denken bij geld", WERKWIJZE.md).
    client = FakeRlzClient({})
    with pytest.raises(CrediteurAanmakenUitgeschakeld):
        service.maak_crediteur_aan(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, naam="Confide BV", client=client
        )
    assert client.aangemaakte_vendors == []


def test_lege_naam_is_fout(boeken_aan: None, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID) -> None:
    with pytest.raises(SyncFout):
        service.maak_crediteur_aan(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, naam="   ", client=FakeRlzClient({})
        )


def test_router_409_bevat_de_bestaande_vendor_id(
    boeken_aan: None,
    administratie_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
) -> None:
    """Fix 2, API-niveau: bij "bestaat al" stuurt de router de bestaande vendor_id mee zodat de
    frontend die crediteur direct kan selecteren — geen kale foutmelding."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.security.tokens import create_access_token

    bestaande_id = uuid.uuid4()
    service.sync_vendors(
        administratie_id=administratie_id,
        client=FakeRlzClient({"Vendors": [{"id": str(bestaande_id), "Name": "Confide BV", "IsArchived": False}]}),
    )

    client = TestClient(app)
    resp = client.post(
        f"/administraties/{administratie_id}/crediteuren",
        json={"naam": "confide bv"},
        headers={"Authorization": f"Bearer {create_access_token(gescoopte_gebruiker, rol='boekhouding')}"},
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["vendor_id"] == str(bestaande_id)
    assert "bestaat al" in detail["message"]
