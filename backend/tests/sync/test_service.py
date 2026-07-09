from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.sync import service
from tests.sync.conftest import FakeRlzClient


def _ledger_record(*, code: str = "4000", naam: str = "Testrekening", soort: int = 2) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "AccountNumber": code,
        "Description": naam,
        "AccountType": soort,
        "IsTotalAccount": False,
    }


def _grootboek_rijen(admin_engine: Engine, administratie_id: uuid.UUID) -> list[tuple]:
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT ledger_id, code, naam, soort, verdwenen_uit_bron_op "
                "FROM platform.grootboekrekening WHERE administratie_id = :aid ORDER BY code"
            ),
            {"aid": administratie_id},
        ).all()


def test_sync_ledgers_is_idempotent(administratie_id: uuid.UUID, admin_engine: Engine) -> None:
    record = _ledger_record()
    client = FakeRlzClient({"Ledgers": [record]})

    eerste = service.sync_ledgers(administratie_id=administratie_id, client=client)
    assert (eerste.aangemaakt, eerste.bijgewerkt, eerste.verdwenen) == (1, 0, 0)

    tweede = service.sync_ledgers(administratie_id=administratie_id, client=client)
    assert (tweede.aangemaakt, tweede.bijgewerkt, tweede.verdwenen) == (0, 1, 0)

    rijen = _grootboek_rijen(admin_engine, administratie_id)
    assert len(rijen) == 1
    assert rijen[0][1:4] == ("4000", "Testrekening", 2)


def test_sync_ledgers_markeert_verdwenen_en_herstelt_bij_terugkeer(
    administratie_id: uuid.UUID, admin_engine: Engine
) -> None:
    blijvend = _ledger_record(code="4000", naam="Blijft")
    verdwijnend = _ledger_record(code="4500", naam="Verdwijnt straks")

    service.sync_ledgers(administratie_id=administratie_id, client=FakeRlzClient({"Ledgers": [blijvend, verdwijnend]}))
    rijen = _grootboek_rijen(admin_engine, administratie_id)
    assert len(rijen) == 2
    assert all(verdwenen_op is None for *_, verdwenen_op in rijen)

    # Tweede sync: 4500 komt niet meer terug in de bron.
    telling = service.sync_ledgers(administratie_id=administratie_id, client=FakeRlzClient({"Ledgers": [blijvend]}))
    assert (telling.aangemaakt, telling.bijgewerkt, telling.verdwenen) == (0, 1, 1)
    rijen = _grootboek_rijen(admin_engine, administratie_id)
    verdwenen_rij = next(r for r in rijen if r[1] == "4500")
    assert verdwenen_rij[4] is not None  # verdwenen_uit_bron_op gezet

    # Derde sync: 4500 komt terug -> verdwenen_uit_bron_op weer NULL (nooit hard verwijderd).
    telling = service.sync_ledgers(
        administratie_id=administratie_id, client=FakeRlzClient({"Ledgers": [blijvend, verdwijnend]})
    )
    assert (telling.aangemaakt, telling.bijgewerkt, telling.verdwenen) == (0, 2, 0)
    rijen = _grootboek_rijen(admin_engine, administratie_id)
    teruggekeerde_rij = next(r for r in rijen if r[1] == "4500")
    assert teruggekeerde_rij[4] is None


def test_sync_vendors_slaat_naam_en_archief_vlag_op(administratie_id: uuid.UUID, admin_engine: Engine) -> None:
    vendor_id = uuid.uuid4()
    client = FakeRlzClient(
        {"Vendors": [{"id": str(vendor_id), "Name": "Bouwmaat Nederland B.V.", "IsArchived": False}]}
    )
    telling = service.sync_vendors(administratie_id=administratie_id, client=client)
    assert telling.aangemaakt == 1

    with admin_engine.connect() as conn:
        naam, is_gearchiveerd, brondata = conn.execute(
            text(
                "SELECT naam, is_gearchiveerd, brondata FROM boekhouding.vendor_cache "
                "WHERE administratie_id = :aid AND id = :id"
            ),
            {"aid": administratie_id, "id": vendor_id},
        ).one()
    assert naam == "Bouwmaat Nederland B.V."
    assert is_gearchiveerd is False
    assert brondata["Name"] == "Bouwmaat Nederland B.V."


def test_sync_projects_slaat_naam_en_actief_vlag_op(administratie_id: uuid.UUID, admin_engine: Engine) -> None:
    project_id = uuid.uuid4()
    project = {"id": str(project_id), "Name": "26001 Rotterdam (Kempen)", "IsActive": True}
    client = FakeRlzClient({"Projects": [project]})
    telling = service.sync_projects(administratie_id=administratie_id, client=client)
    assert telling.aangemaakt == 1

    with admin_engine.connect() as conn:
        naam, is_actief = conn.execute(
            text("SELECT naam, is_actief FROM boekhouding.project_cache WHERE administratie_id = :aid AND id = :id"),
            {"aid": administratie_id, "id": project_id},
        ).one()
    assert naam == "26001 Rotterdam (Kempen)"
    assert is_actief is True


def test_sync_taxrates_valt_terug_op_brondata(administratie_id: uuid.UUID, admin_engine: Engine) -> None:
    taxrate_id = uuid.uuid4()
    client = FakeRlzClient({"TaxRates": [{"id": str(taxrate_id), "Name": "NL Hoog 21%"}]})
    telling = service.sync_taxrates(administratie_id=administratie_id, client=client)
    assert telling.aangemaakt == 1

    with admin_engine.connect() as conn:
        naam, brondata = conn.execute(
            text("SELECT naam, brondata FROM boekhouding.taxrate_cache WHERE administratie_id = :aid AND id = :id"),
            {"aid": administratie_id, "id": taxrate_id},
        ).one()
    assert naam == "NL Hoog 21%"
    assert brondata["id"] == str(taxrate_id)


def test_sync_alles_voor_administratie_gebruikt_een_gedeelde_client(
    administratie_id: uuid.UUID,
) -> None:
    client = FakeRlzClient(
        {
            "Ledgers": [_ledger_record()],
            "TaxRates": [{"id": str(uuid.uuid4()), "Name": "NL Hoog 21%"}],
            "Vendors": [{"id": str(uuid.uuid4()), "Name": "Leverancier X", "IsArchived": False}],
            "Projects": [{"id": str(uuid.uuid4()), "Name": "Project Y", "IsActive": True}],
        }
    )
    resultaat = service.sync_alles_voor_administratie(administratie_id=administratie_id, client=client)

    assert resultaat.ledgers.aangemaakt == 1
    assert resultaat.taxrates.aangemaakt == 1
    assert resultaat.vendors.aangemaakt == 1
    assert resultaat.projects.aangemaakt == 1
    assert sorted(client.opgevraagde_paden) == ["Ledgers", "Projects", "TaxRates", "Vendors"]
    # Meegegeven client blijft van de aanroeper — de servicelaag sluit 'm niet zelf.
    assert client.closed is False


def test_sync_onbekende_administratie_geeft_syncfout() -> None:
    """Geen client meegeven -> de servicelaag moet zelf credentials proberen te resolven, wat
    faalt zodra de administratie niet bestaat (vóórdat er ooit een echte RlzClient wordt geopend)."""
    with pytest.raises(service.SyncFout, match="Onbekende administratie"):
        service.sync_ledgers(administratie_id=uuid.uuid4())


class TestLeeslijstenVoorControlescherm:
    """CLAUDE.md-taak 2.1: de GB-/btw-/crediteuren-/projectcomboboxen lezen uit deze
    sync-caches — totaalrekeningen en verdwenen rijen horen niet in de keuzelijst."""

    def test_grootboek_filtert_totaalrekening_en_verdwenen(
        self, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        zichtbaar = _ledger_record(code="4000", naam="Zichtbaar")
        totaal = _ledger_record(code="4999", naam="Totaalrekening")
        totaal["IsTotalAccount"] = True
        verdwenen = _ledger_record(code="4500", naam="Verdwenen")
        service.sync_ledgers(
            administratie_id=administratie_id, client=FakeRlzClient({"Ledgers": [zichtbaar, totaal, verdwenen]})
        )
        # Tweede sync zonder 'verdwenen' -> verdwenen_uit_bron_op wordt gezet.
        service.sync_ledgers(administratie_id=administratie_id, client=FakeRlzClient({"Ledgers": [zichtbaar, totaal]}))

        rekeningen = service.lijst_grootboek(administratie_id=administratie_id)
        assert [r.code for r in rekeningen] == ["4000"]

    def test_taxrates_filtert_verdwenen(self, administratie_id: uuid.UUID) -> None:
        blijvend_id, verdwijnend_id = uuid.uuid4(), uuid.uuid4()
        service.sync_taxrates(
            administratie_id=administratie_id,
            client=FakeRlzClient(
                {"TaxRates": [{"id": str(blijvend_id), "Name": "21%"}, {"id": str(verdwijnend_id), "Name": "9%"}]}
            ),
        )
        service.sync_taxrates(
            administratie_id=administratie_id,
            client=FakeRlzClient({"TaxRates": [{"id": str(blijvend_id), "Name": "21%"}]}),
        )

        codes = service.lijst_taxrates(administratie_id=administratie_id)
        assert [c.id for c in codes] == [blijvend_id]

    def test_vendors_en_projecten_geven_alleen_niet_verdwenen_terug(self, administratie_id: uuid.UUID) -> None:
        vendor_id = uuid.uuid4()
        service.sync_vendors(
            administratie_id=administratie_id,
            client=FakeRlzClient({"Vendors": [{"id": str(vendor_id), "Name": "Leverancier X", "IsArchived": False}]}),
        )
        project_id = uuid.uuid4()
        service.sync_projects(
            administratie_id=administratie_id,
            client=FakeRlzClient({"Projects": [{"id": str(project_id), "Name": "Project Y", "IsActive": True}]}),
        )

        assert [v.id for v in service.lijst_vendors(administratie_id=administratie_id)] == [vendor_id]
        assert [p.id for p in service.lijst_projects(administratie_id=administratie_id)] == [project_id]
