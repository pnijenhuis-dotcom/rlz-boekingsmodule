# ruff: noqa: F811 — fixtures uit tests.auth.conftest worden via import geregistreerd en als parameter gebruikt
"""Instellingen › Doorbelasting voor een administratie ZONDER `doorbelasting_instelling`-rij (bug Peter 14-09).

Productie: `GET /doorbelasting/{aid}/instelling` liep in de centrale 500-handler op
`pydantic_core.ValidationError: 1 validation error for InstellingResponse` — `haal_instelling_op` gaf een kaal
`DoorbelastingInstelling(administratie_id=…)` terug en een SQLAlchemy kolom-`default=` geldt pas bij INSERT, dus
`provisie_percentage` was None terwijl het schema een Decimal eist. Dataconditie: een administratie die het scherm
opent zonder ooit instellingen te hebben opgeslagen. Fix: één bron `DoorbelastingInstelling.standaard()` voor de
niet-opgeslagen standaardstand, gebruikt door de route, de checks (`_check_invoer`) en de bulk-verdeling."""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.doorbelasting import service
from app.doorbelasting.models import STANDAARD_PROVISIE_PERCENTAGE, DoorbelastingInstelling
from app.main import app
from app.security.tokens import create_access_token
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401

from .conftest import (
    DOEL_KOSTEN_LEDGER_ID,
    DoorbelastingOpzet,
    VerdeelRegelInvoerData,
    maak_mapping,
    start_run_met_verdeling,
)

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str = "beheerder") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _aantal_rijen(admin_engine: Engine, aid: uuid.UUID) -> int:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM boekhouding.doorbelasting_instelling WHERE administratie_id = :aid"),
            {"aid": aid},
        ).scalar_one()


class TestValkuilKolomDefault:
    """Het mechanisme achter de bug, los van HTTP — de rode kant van vóór/na."""

    def test_kaal_orm_object_heeft_geen_provisie_percentage(self) -> None:
        # Dit is precies wat `haal_instelling_op` vóór de fix teruggaf: kolom-default geldt pas bij INSERT.
        assert DoorbelastingInstelling(administratie_id=uuid.uuid4()).provisie_percentage is None

    def test_standaard_draagt_het_default_percentage_en_lege_verwijzingen(self) -> None:
        aid = uuid.uuid4()
        instelling = DoorbelastingInstelling.standaard(aid)
        assert instelling.administratie_id == aid
        assert instelling.provisie_percentage == STANDAARD_PROVISIE_PERCENTAGE == Decimal("5.00")
        assert instelling.btw_taxrate_id is None
        assert instelling.omzet_ledger_id is None
        assert instelling.provisie_omzet_ledger_id is None


class TestInstellingRoute:
    def test_get_zonder_rij_geeft_200_met_standaardstand_en_schrijft_niets(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        assert _aantal_rijen(admin_engine, administratie_id) == 0

        resp = client.get(f"/doorbelasting/{administratie_id}/instelling", headers=_bearer(beheerder_id))

        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "administratie_id": str(administratie_id),
            "provisie_percentage": "5.00",
            "btw_taxrate_id": None,
            "omzet_ledger_id": None,
            "provisie_omzet_ledger_id": None,
        }
        # Lezen schrijft niets: de standaardstand blijft transient tot de eerste PUT.
        assert _aantal_rijen(admin_engine, administratie_id) == 0

    def test_get_zonder_rij_via_de_servicelaag(self, administratie_id: uuid.UUID) -> None:
        instelling = service.haal_instelling_op(administratie_id=administratie_id)
        assert instelling.provisie_percentage == Decimal("5.00")
        assert instelling.btw_taxrate_id is None

    def test_put_daarna_get_leest_de_opgeslagen_rij(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        taxrate = uuid.uuid4()
        put = client.put(
            f"/doorbelasting/{administratie_id}/instelling",
            json={"provisie_percentage": "7.50", "btw_taxrate_id": str(taxrate)},
            headers=_bearer(beheerder_id),
        )
        assert put.status_code == 200, put.text
        assert _aantal_rijen(admin_engine, administratie_id) == 1

        resp = client.get(f"/doorbelasting/{administratie_id}/instelling", headers=_bearer(beheerder_id))
        assert resp.status_code == 200
        assert resp.json()["provisie_percentage"] == "7.50"
        assert resp.json()["btw_taxrate_id"] == str(taxrate)


class TestZusterpadenZonderRij:
    """Dezelfde valkuil in de andere lezers van de instelling: checks/preview en de bulk-verdeling
    rekenen `provisie_over(netto, provisie_percentage)` — met None was dat een TypeError."""

    def _run_zonder_instelling(
        self,
        *,
        doorbelasting_aan: None,
        geboekt_document: tuple[uuid.UUID, list[uuid.UUID]],
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
    ) -> DoorbelastingOpzet:
        document_id, regel_ids = geboekt_document
        mapping = maak_mapping(administratie_id=administratie_id, actor_id=beheerder_id, doel_administratie_id=None)
        run = start_run_met_verdeling(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=beheerder_id,
            regels=[
                VerdeelRegelInvoerData(
                    bron_regel_id=regel_ids[0],
                    mapping_id=mapping.id,
                    percentage=Decimal("100"),
                    doel_kosten_ledger_id=DOEL_KOSTEN_LEDGER_ID,
                )
            ],
        )
        return DoorbelastingOpzet(
            administratie_id=administratie_id,
            doel_administratie_id=None,
            document_id=document_id,
            regel_ids=regel_ids,
            mapping=mapping,
            run=run,
        )

    def test_review_data_rekent_met_het_standaardpercentage_en_blokkeert_op_ontbrekende_config(
        self,
        doorbelasting_aan: None,
        geboekt_document: tuple[uuid.UUID, list[uuid.UUID]],
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        opzet = self._run_zonder_instelling(
            doorbelasting_aan=doorbelasting_aan,
            geboekt_document=geboekt_document,
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
        )
        assert _aantal_rijen(admin_engine, administratie_id) == 0

        data = service.review_data(administratie_id=administratie_id, run_id=opzet.run.id)

        assert [p.provisie_bedrag for p in data.previews] == [Decimal("5.00")]  # 5 % over € 100,00
        # Geen btw-tarief/omzet-GB → de harde checks houden boeken tegen (nooit stil).
        assert data.rapport.geblokkeerd is True

    def test_run_route_geeft_200_zonder_instellingen_rij(
        self,
        doorbelasting_aan: None,
        geboekt_document: tuple[uuid.UUID, list[uuid.UUID]],
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
    ) -> None:
        opzet = self._run_zonder_instelling(
            doorbelasting_aan=doorbelasting_aan,
            geboekt_document=geboekt_document,
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
        )
        resp = client.get(f"/doorbelasting/{administratie_id}/runs/{opzet.run.id}", headers=_bearer(beheerder_id))
        assert resp.status_code == 200, resp.text
        assert resp.json()["previews"][0]["provisie_bedrag"] == "5.00"

    def test_bulk_verdeling_rekent_met_het_standaardpercentage(
        self,
        doorbelasting_aan: None,
        geboekt_document: tuple[uuid.UUID, list[uuid.UUID]],
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
    ) -> None:
        from app.db.session import scoped_session

        opzet = self._run_zonder_instelling(
            doorbelasting_aan=doorbelasting_aan,
            geboekt_document=geboekt_document,
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
        )
        with scoped_session(administratie_id) as session:
            uit = service.verdeling_per_doelentiteit_bulk(
                session, administratie_id=administratie_id, run_ids=[opzet.run.id]
            )
        assert [v.provisie_bedrag for v in uit[opzet.run.id]] == [Decimal("5.00")]
