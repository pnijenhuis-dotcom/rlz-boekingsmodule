"""'+ Doelentiteit toevoegen' (mockup doorbelasting-doel-toevoegen.html, akkoord Peter 01-09):
kandidaat-doelen (onboarded, nog niet in de whitelist) + provisie-GB-voorstel, debiteur-lookup
op naam in de bron-RLZ (exact + deterministische bijna-match — de Mantelzorgwoning-les:
enkelvoud/meervoud nooit stil koppelen, de mens bevestigt) en de idempotente mapping-aanmaak
via de bestaande verkoopmotor-bouwsteen zorg_voor_debiteur (lookup-vóór-PUT + deterministisch
client-GUID). De seed-CLI blijft bestaan; de whitelist blijft server-side afgedwongen."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.documenten.rlz_ids import rlz_customer_id
from app.doorbelasting import service
from app.main import app
from app.security.tokens import create_access_token
from tests.doorbelasting.conftest import maak_administratie

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


class FakeBronClient:
    """Duck-typed bron-RLZ (patroon tests/verkoop): Customers-collectie + exact-lookup + PUT."""

    def __init__(self, customers: list[dict[str, Any]] | None = None) -> None:
        self.customers = customers or []
        self.puts: list[tuple[uuid.UUID, str]] = []

    def get(self, path: str, **_: Any) -> dict[str, Any]:
        assert path == "Customers"
        return {"value": list(self.customers)}

    def find_customers_by_name(self, *, name: str) -> list[dict[str, Any]]:
        return [c for c in self.customers if c.get("Name") == name]

    def put_customer(self, customer_id: uuid.UUID, *, name: str) -> None:
        self.puts.append((customer_id, name))
        self.customers.append({"id": str(customer_id), "Name": name})

    def close(self) -> None:  # pragma: no cover — seam-contract
        pass


MANTELZORG_GUID = "90dbadcb-5066-4822-a374-0b454a4a9180"


@pytest.fixture
def bron_client() -> FakeBronClient:
    return FakeBronClient(
        customers=[
            # De échte casus 01-09: RLZ-naam ENKELVOUD vs administratienaam MEERVOUD.
            {"id": MANTELZORG_GUID, "Name": "Mantelzorgwoning Midden Nederland B.V.", "City": "Amersfoort"},
            {"id": str(uuid.uuid4()), "Name": "Molenhof Beheer B.V."},
            {"id": str(uuid.uuid4()), "Name": "Oirschot Recreatie B.V.", "StatutoryName": "Oirschot Recreatie B.V."},
        ]
    )


class TestDebiteurLookup:
    def test_exacte_match_komt_eerst_met_kaartgegevens(
        self, administratie_id: uuid.UUID, bron_client: FakeBronClient
    ) -> None:
        matches = service.zoek_debiteur_in_bron(
            administratie_id=administratie_id,
            zoeknaam="Mantelzorgwoning Midden Nederland B.V.",
            client=bron_client,
        )
        assert matches[0].exact is True
        assert matches[0].customer_guid == uuid.UUID(MANTELZORG_GUID)
        assert matches[0].kaart == {"plaats": "Amersfoort"}

    def test_bijna_match_enkelvoud_meervoud_wordt_gevonden_maar_niet_als_exact(
        self, administratie_id: uuid.UUID, bron_client: FakeBronClient
    ) -> None:
        # De administratienaam (meervoud, zonder B.V.) vindt de enkelvoud-debiteur — als
        # bijna-match ter expliciete bevestiging, nooit stil gekoppeld.
        matches = service.zoek_debiteur_in_bron(
            administratie_id=administratie_id,
            zoeknaam="Mantelzorgwoningen Midden Nederland",
            client=bron_client,
        )
        assert [m.naam for m in matches] == ["Mantelzorgwoning Midden Nederland B.V."]
        assert matches[0].exact is False

    def test_verwante_namen_matchen_niet_op_de_gedeelde_kern_alleen(
        self, administratie_id: uuid.UUID, bron_client: FakeBronClient
    ) -> None:
        # 'Molenhof Verhuur' mag 'Molenhof Beheer' níét als match opleveren (en andersom).
        matches = service.zoek_debiteur_in_bron(
            administratie_id=administratie_id, zoeknaam="Molenhof Verhuur B.V.", client=bron_client
        )
        assert matches == []

    def test_het_projectanker_wordt_nooit_aangeboden(self, administratie_id: uuid.UUID) -> None:
        anker = FakeBronClient(customers=[{"id": str(uuid.uuid4()), "Name": "Pandprojecten (systeem)"}])
        assert (
            service.zoek_debiteur_in_bron(
                administratie_id=administratie_id, zoeknaam="Pandprojecten (systeem)", client=anker
            )
            == []
        )


class TestKandidaatDoelen:
    def test_filtert_bron_gekoppelde_en_gearchiveerde_en_stelt_provisie_voor(
        self,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        gekoppeld = maak_administratie(admin_engine, "Al Gekoppeld B.V.")
        maak_administratie(admin_engine, "Nog Vrij B.V.")
        archief = maak_administratie(admin_engine, "Archief B.V.")
        provisie_ledger = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(text("UPDATE platform.administratie SET actief = false WHERE id = :id"), {"id": archief})
            conn.execute(
                text(
                    "INSERT INTO platform.grootboekrekening "
                    "(ledger_id, administratie_id, code, naam, soort, is_totaalrekening) "
                    "VALUES (:lid, :aid, '4808', 'Provisie Kempen Facilities', 2, false)"
                ),
                {"lid": provisie_ledger, "aid": gekoppeld},
            )
        service.maak_mapping(
            administratie_id=administratie_id,
            actor_id=beheerder_id,
            doel_administratie_id=gekoppeld,
            doelentiteit_naam="Al Gekoppeld B.V.",
            doel_customer_guid=uuid.uuid4(),
            provisie_kosten_ledger_id=provisie_ledger,
            intercompany=True,
        )

        kandidaten, voorstel = service.kandidaat_doelen(administratie_id=administratie_id)
        namen = [k.naam for k in kandidaten]
        assert "Nog Vrij B.V." in namen
        assert "Al Gekoppeld B.V." not in namen
        assert "Archief B.V." not in namen
        assert all(k.id != administratie_id for k in kandidaten)
        # Provisie-voorstel = de rekeningCODE van de bestaande rijen (mockup ③).
        assert voorstel is not None
        assert (voorstel.code, voorstel.naam) == ("4808", "Provisie Kempen Facilities")


class TestMaakMapping:
    def test_bevestigde_match_koppelt_zonder_put_met_ic_rij_en_audit(
        self,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        bron_client: FakeBronClient,
    ) -> None:
        doel = maak_administratie(admin_engine, "Mantelzorgwoningen Midden Nederland")
        mapping = service.maak_mapping(
            administratie_id=administratie_id,
            actor_id=beheerder_id,
            doel_administratie_id=doel,
            doelentiteit_naam="Mantelzorgwoning Midden Nederland B.V.",
            doel_customer_guid=uuid.UUID(MANTELZORG_GUID),
            provisie_kosten_ledger_id=None,
            intercompany=True,
            client=bron_client,
        )
        assert bron_client.puts == []  # bevestigde match = koppelen, nooit een tweede debiteur
        assert mapping.doel_customer_guid == uuid.UUID(MANTELZORG_GUID)
        assert mapping.doelentiteit_naam == "Mantelzorgwoning Midden Nederland B.V."

        rijen = service.lijst_mappings(administratie_id=administratie_id)
        assert [m.id for m in rijen] == [mapping.id]  # direct bruikbaar in "Doorbelasten na boeken"
        with admin_engine.connect() as conn:
            audit = conn.execute(
                text("SELECT count(*) FROM platform.audit_event WHERE actie = 'doorbelasting_mapping_aangemaakt'")
            ).scalar_one()
            ic = conn.execute(
                text(
                    "SELECT actief FROM boekhouding.intercompany_tegenpartij "
                    "WHERE administratie_id = :aid AND entity_guid = :guid"
                ),
                {"aid": administratie_id, "guid": MANTELZORG_GUID},
            ).scalar_one()
        assert audit == 1
        assert ic is True

    def test_geen_match_maakt_debiteur_idempotent_aan_met_deterministisch_guid(
        self,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        bron_client: FakeBronClient,
    ) -> None:
        doel = maak_administratie(admin_engine, "Nieuw Doel B.V.")
        mapping = service.maak_mapping(
            administratie_id=administratie_id,
            actor_id=beheerder_id,
            doel_administratie_id=doel,
            doelentiteit_naam="Nieuw Doel B.V.",
            doel_customer_guid=None,
            provisie_kosten_ledger_id=None,
            intercompany=False,
            client=bron_client,
        )
        verwacht_guid = rlz_customer_id(administratie_id, "Nieuw Doel B.V.")
        assert bron_client.puts == [(verwacht_guid, "Nieuw Doel B.V.")]
        assert mapping.doel_customer_guid == verwacht_guid
        assert mapping.intercompany is False

    def test_poorten_dubbel_doel_gearchiveerd_en_bron_zelf(
        self,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        bron_client: FakeBronClient,
    ) -> None:
        doel = maak_administratie(admin_engine, "Dubbel B.V.")
        service.maak_mapping(
            administratie_id=administratie_id,
            actor_id=beheerder_id,
            doel_administratie_id=doel,
            doelentiteit_naam="Dubbel B.V.",
            doel_customer_guid=uuid.uuid4(),
            provisie_kosten_ledger_id=None,
            intercompany=True,
        )
        with pytest.raises(service.DoorbelastingFout, match="staat al in de whitelist"):
            service.maak_mapping(
                administratie_id=administratie_id,
                actor_id=beheerder_id,
                doel_administratie_id=doel,
                doelentiteit_naam="Dubbel B.V.",
                doel_customer_guid=None,
                provisie_kosten_ledger_id=None,
                intercompany=True,
                client=bron_client,
            )
        with pytest.raises(service.DoorbelastingFout, match="doelentiteit van zichzelf"):
            service.maak_mapping(
                administratie_id=administratie_id,
                actor_id=beheerder_id,
                doel_administratie_id=administratie_id,
                doelentiteit_naam="Bron Zelf",
                doel_customer_guid=None,
                provisie_kosten_ledger_id=None,
                intercompany=True,
                client=bron_client,
            )
        archief = maak_administratie(admin_engine, "Weg B.V.")
        with admin_engine.begin() as conn:
            conn.execute(text("UPDATE platform.administratie SET actief = false WHERE id = :id"), {"id": archief})
        with pytest.raises(service.DoorbelastingFout, match="gearchiveerd"):
            service.maak_mapping(
                administratie_id=administratie_id,
                actor_id=beheerder_id,
                doel_administratie_id=archief,
                doelentiteit_naam="Weg B.V.",
                doel_customer_guid=None,
                provisie_kosten_ledger_id=None,
                intercompany=True,
                client=bron_client,
            )


class TestEndpoints:
    def test_endpoints_zijn_beheerder_only(
        self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        assert (
            client.get(f"/doorbelasting/{administratie_id}/mappings/kandidaat-doelen", headers=headers).status_code
            == 403
        )
        assert (
            client.post(
                f"/doorbelasting/{administratie_id}/mappings/debiteur-lookup",
                json={"zoeknaam": "x"},
                headers=headers,
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/doorbelasting/{administratie_id}/mappings",
                json={"doel_administratie_id": str(uuid.uuid4()), "doelentiteit_naam": "x"},
                headers=headers,
            ).status_code
            == 403
        )

    def test_aanmaken_via_de_api_met_bevestigde_match(
        self,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        doel = maak_administratie(admin_engine, "API Doel B.V.")
        respons = client.post(
            f"/doorbelasting/{administratie_id}/mappings",
            json={
                "doel_administratie_id": str(doel),
                "doelentiteit_naam": "API Doel B.V.",
                "doel_customer_guid": str(uuid.uuid4()),
                "intercompany": True,
            },
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert respons.status_code == 201, respons.text
        assert respons.json()["doelentiteit_naam"] == "API Doel B.V."
        assert respons.json()["doel_administratie_id"] == str(doel)
