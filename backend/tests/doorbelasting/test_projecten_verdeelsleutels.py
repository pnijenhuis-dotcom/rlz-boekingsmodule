"""Doorbelasting × projecten + verdeelsleutels (besluit Peter 25-08 "optie 2", deel 2 punt 2):
project per verdeelregel uit de doel-administratie (verplicht bij project_verplicht van het
doel), multi-project-verdeling (m² óf gelijk, centen server-side), spiegel-regels mét Project,
herbruikbare verdeelsleutels met versie + herleidbaarheid op de run."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.doorbelasting import boeken, verdeelhulp
from app.doorbelasting import service as doorbelasting_service
from app.doorbelasting.checks import MappingInvoer, VerdeelRegelInvoer, check_project_verplicht_doel
from app.documenten.rlz_ids import rlz_doorbelasting_spiegel_id
from app.doorbelasting.service import DoorbelastingFout, VerdeelRegelInvoerData
from tests.doorbelasting.conftest import (
    DOEL_KOSTEN_LEDGER_ID,
    DoorbelastingOpzet,
    FakeDoorbelastingClient,
    haal_run,
)

D = Decimal


# --- verdeelhulp (pure, herbruikbare bouwsteen — parkeerpost 2d) ------------------------------


class TestVerdeelhulp:
    def test_m2_grootste_rest_sluit_exact(self) -> None:
        doelen = [verdeelhulp.VerdeelDoel("a", D("100")), verdeelhulp.VerdeelDoel("b", D("300")), verdeelhulp.VerdeelDoel("c", D("50"))]
        delen = verdeelhulp.verdeel_over_doelen(D("100.00"), doelen, "m2")
        assert [d.bedrag for d in delen] == [D("22.22"), D("66.67"), D("11.11")]
        assert sum(d.bedrag for d in delen) == D("100.00")
        assert [str(d.aandeel) for d in delen] == ["0.222222", "0.666667", "0.111111"]

    def test_gelijk_per_object_ook_bij_negatief_bedrag(self) -> None:
        doelen = [verdeelhulp.VerdeelDoel(str(i)) for i in range(3)]
        delen = verdeelhulp.verdeel_over_doelen(D("-100.00"), doelen, "gelijk")
        assert sum(d.bedrag for d in delen) == D("-100.00")
        assert sorted(abs(d.bedrag) for d in delen) == [D("33.33"), D("33.33"), D("33.34")]

    def test_ontbrekende_m2_benoemt_de_projecten_nooit_gokken(self) -> None:
        doelen = [verdeelhulp.VerdeelDoel("a", D("100"), naam="Pand A"), verdeelhulp.VerdeelDoel("b", None, naam="Pand B")]
        with pytest.raises(verdeelhulp.VerdeelFout, match="Pand B"):
            verdeelhulp.verdeel_over_doelen(D("100.00"), doelen, "m2")
        with pytest.raises(verdeelhulp.VerdeelFout):
            verdeelhulp.verdeel_over_doelen(D("100.00"), doelen, "procent")  # type: ignore[arg-type]

    def test_veertig_panden_geen_cent_kwijt(self) -> None:
        doelen = [verdeelhulp.VerdeelDoel(f"p{i}", D(str(37 + (i * 13) % 90))) for i in range(40)]
        delen = verdeelhulp.verdeel_over_doelen(D("1234.57"), doelen, "m2")
        assert len(delen) == 40 and sum(d.bedrag for d in delen) == D("1234.57")


def test_check_project_verplicht_doel() -> None:
    bron, mapping = uuid.uuid4(), uuid.uuid4()
    regel = VerdeelRegelInvoer(bron_regel_id=bron, bron_netto=D(100), mapping_id=mapping, percentage=D(100), netto_deel=D(100), doel_kosten_ledger_id=None)
    verplicht = {mapping: MappingInvoer(mapping_id=mapping, actief=True, doel_administratie_id=uuid.uuid4(), provisie_kosten_ledger_id=None, doel_project_verplicht=True, doelentiteit_naam="Molenhof Beheer B.V.")}
    rood = check_project_verplicht_doel([regel], verplicht)
    assert not rood.ok and "Molenhof Beheer B.V." in rood.melding
    groen = check_project_verplicht_doel([VerdeelRegelInvoer(**{**regel.__dict__, "project_id": uuid.uuid4()})], verplicht)
    assert groen.ok
    vrij = {mapping: MappingInvoer(**{**verplicht[mapping].__dict__, "doel_project_verplicht": False})}
    assert check_project_verplicht_doel([regel], vrij).ok


# --- service + motor (DB) -------------------------------------------------------------------


def _project(admin_engine: Engine, door: uuid.UUID, administratie_id: uuid.UUID, naam: str, *, m2: str | None, actief: bool = True) -> uuid.UUID:
    pid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.project_cache (id, administratie_id, naam, is_actief, brondata) "
                "VALUES (:id, :aid, :naam, :actief, '{}')"
            ),
            {"id": pid, "aid": administratie_id, "naam": naam, "actief": actief},
        )
        if m2 is not None:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.project_specificatie (project_id, administratie_id, contract_m2, bijgewerkt_door) "
                    "VALUES (:id, :aid, :m2, :door)"
                ),
                {"id": pid, "aid": administratie_id, "m2": m2, "door": door},
            )
    return pid


def _zet_project_verplicht(admin_engine: Engine, administratie_id: uuid.UUID, aan: bool) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.administratie SET project_verplicht = :aan WHERE id = :id"),
            {"aan": aan, "id": administratie_id},
        )


def _invoer(opzet: DoorbelastingOpzet, **extra) -> VerdeelRegelInvoerData:
    return VerdeelRegelInvoerData(
        bron_regel_id=opzet.regel_ids[0],
        mapping_id=opzet.mapping.id,
        percentage=D("100"),
        doel_kosten_ledger_id=DOEL_KOSTEN_LEDGER_ID,
        **extra,
    )


class TestProjectPerVerdeelregel:
    def test_multi_project_naar_rato_m2_en_gelijk(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        opzet = onboarded_opzet
        doel = opzet.doel_administratie_id
        assert doel is not None
        a = _project(admin_engine, beheerder_id, doel, "Pand A", m2="100")
        b = _project(admin_engine, beheerder_id, doel, "Pand B", m2="300")
        regels = doorbelasting_service.sla_verdeling_op(
            administratie_id=opzet.administratie_id,
            run_id=opzet.run.id,
            regels=[_invoer(opzet, project_ids=(a, b), verdeelbasis="m2")],
            actor_id=beheerder_id,
        )
        # bron-regel netto 100,00 → 25/75 naar m²; percentage blijft het doelentiteit-aandeel (100)
        per_project = {r.project_id: r for r in regels}
        assert per_project[a].netto_deel == D("25.00") and per_project[b].netto_deel == D("75.00")
        assert all(r.percentage == D("100") and r.verdeelbasis == "m2" for r in regels)
        assert per_project[a].m2 == D("100.00") and str(per_project[b].project_aandeel) == "0.750000"

        review = doorbelasting_service.review_data(administratie_id=opzet.administratie_id, run_id=opzet.run.id)
        assert not review.rapport.geblokkeerd  # 100% per regel, bedragen sluiten, project-check vrij
        [preview] = review.previews
        assert preview.netto_totaal == D("100.00")
        assert [(p.naam, p.netto_totaal) for p in preview.projecten] == [("Pand A", D("25.00")), ("Pand B", D("75.00"))]
        assert review.project_namen == {a: "Pand A", b: "Pand B"}

        regels = doorbelasting_service.sla_verdeling_op(
            administratie_id=opzet.administratie_id,
            run_id=opzet.run.id,
            regels=[_invoer(opzet, project_ids=(a, b), verdeelbasis="gelijk")],
            actor_id=beheerder_id,
        )
        assert sorted(r.netto_deel for r in regels) == [D("50.00"), D("50.00")]

    def test_ontbrekende_m2_blokkeert_met_projectnaam_en_onbekend_project_geweigerd(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        opzet = onboarded_opzet
        a = _project(admin_engine, beheerder_id, opzet.doel_administratie_id, "Pand A", m2="100")
        zonder = _project(admin_engine, beheerder_id, opzet.doel_administratie_id, "Pand Zonder m²", m2=None)
        with pytest.raises(DoorbelastingFout, match="Pand Zonder m²"):
            doorbelasting_service.sla_verdeling_op(
                administratie_id=opzet.administratie_id,
                run_id=opzet.run.id,
                regels=[_invoer(opzet, project_ids=(a, zonder), verdeelbasis="m2")],
                actor_id=beheerder_id,
            )
        with pytest.raises(DoorbelastingFout, match="verdeelbasis"):
            doorbelasting_service.sla_verdeling_op(
                administratie_id=opzet.administratie_id,
                run_id=opzet.run.id,
                regels=[_invoer(opzet, project_ids=(a, zonder))],
                actor_id=beheerder_id,
            )
        with pytest.raises(DoorbelastingFout, match="Onbekend project"):
            doorbelasting_service.sla_verdeling_op(
                administratie_id=opzet.administratie_id,
                run_id=opzet.run.id,
                regels=[_invoer(opzet, project_ids=(uuid.uuid4(),))],
                actor_id=beheerder_id,
            )
        # De mislukte opslag liet de bestaande verdeling intact (transactie teruggedraaid).
        assert len(haal_run(opzet.administratie_id, opzet.run.id).id.hex) == 32
        review = doorbelasting_service.review_data(administratie_id=opzet.administratie_id, run_id=opzet.run.id)
        assert len(review.regels) == 1 and review.regels[0].project_id is None

    def test_project_verplicht_in_doel_blokkeert_zonder_project(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        opzet = onboarded_opzet
        _zet_project_verplicht(admin_engine, opzet.doel_administratie_id, True)
        review = doorbelasting_service.review_data(administratie_id=opzet.administratie_id, run_id=opzet.run.id)
        rood = next(r for r in review.rapport.resultaten if r.naam == "Project verplicht in doel-administratie")
        assert not rood.ok and review.rapport.geblokkeerd
        # Met project → groen
        a = _project(admin_engine, beheerder_id, opzet.doel_administratie_id, "Pand A", m2=None)
        doorbelasting_service.sla_verdeling_op(
            administratie_id=opzet.administratie_id,
            run_id=opzet.run.id,
            regels=[_invoer(opzet, project_ids=(a,))],
            actor_id=beheerder_id,
        )
        review = doorbelasting_service.review_data(administratie_id=opzet.administratie_id, run_id=opzet.run.id)
        assert not review.rapport.geblokkeerd
        assert review.regels[0].project_id == a and review.regels[0].project_aandeel == D("1")

    def test_spiegel_regels_dragen_het_project(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        opzet = onboarded_opzet
        a = _project(admin_engine, beheerder_id, opzet.doel_administratie_id, "Pand A", m2="100")
        b = _project(admin_engine, beheerder_id, opzet.doel_administratie_id, "Pand B", m2="100")
        doorbelasting_service.sla_verdeling_op(
            administratie_id=opzet.administratie_id,
            run_id=opzet.run.id,
            regels=[_invoer(opzet, project_ids=(a, b), verdeelbasis="gelijk")],
            actor_id=beheerder_id,
        )
        bron, doel = FakeDoorbelastingClient(), FakeDoorbelastingClient()
        resultaat = boeken.boek_doorbelasting_run(
            administratie_id=opzet.administratie_id,
            run_id=opzet.run.id,
            actor_id=beheerder_id,
            bron_client=bron,
            doel_client_factory=lambda _aid: doel,
        )
        assert resultaat == {str(opzet.mapping.id): "geboekt"}
        spiegel = doel.purchase_invoices[str(rlz_doorbelasting_spiegel_id(opzet.document_id, opzet.mapping.doel_customer_guid))]
        lines = spiegel["DocumentLineList"]
        # één regel per project + de provisieregel zónder project
        assert len(lines) == 3
        assert {line["Project"]["id"] for line in lines[:2]} == {str(a), str(b)}
        assert [line["NetAmount"] for line in lines[:2]] == [50.0, 50.0]
        assert "Project" not in lines[2]
        # verkoop in de bron: één regel per verdeelregel (2) + provisie
        [verkoop] = bron.sales_invoices.values()
        assert len(verkoop["DocumentLineList"]) == 3


class TestVerdeelsleutels:
    def test_opslaan_versioneert_en_toepassen_is_herleidbaar(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        opzet = onboarded_opzet
        doel = opzet.doel_administratie_id
        a = _project(admin_engine, beheerder_id, doel, "Pand A", m2="100")
        b = _project(admin_engine, beheerder_id, doel, "Pand B", m2="300")
        _project(admin_engine, beheerder_id, doel, "Oud pand", m2="500", actief=False)
        definitie = {
            "doelen": [
                {"mapping_id": str(opzet.mapping.id), "percentage": "100", "doel_kosten_ledger_id": str(DOEL_KOSTEN_LEDGER_ID), "projecten": "alle_actief", "verdeelbasis": "m2"}
            ]
        }
        v1 = doorbelasting_service.sla_verdeelsleutel_op(
            administratie_id=opzet.administratie_id, naam="Alle panden naar m²", definitie=definitie, actor_id=beheerder_id
        )
        assert v1.versie == 1 and v1.actief
        v2 = doorbelasting_service.sla_verdeelsleutel_op(
            administratie_id=opzet.administratie_id, naam="Alle panden naar m²", definitie={**definitie, "doelen": [{**definitie["doelen"][0], "verdeelbasis": "gelijk"}]}, actor_id=beheerder_id
        )
        assert v2.versie == 2
        actief = doorbelasting_service.lijst_verdeelsleutels(administratie_id=opzet.administratie_id)
        assert [(s.naam, s.versie) for s in actief] == [("Alle panden naar m²", 2)]
        alle = doorbelasting_service.lijst_verdeelsleutels(administratie_id=opzet.administratie_id, alleen_actief=False)
        assert len(alle) == 2  # v1 blijft bestaan (append-only)

        # Toepassen van v1 (m²): 'alle_actief' → alleen de actieve panden A+B, 25/75
        regels = doorbelasting_service.pas_verdeelsleutel_toe(
            administratie_id=opzet.administratie_id, run_id=opzet.run.id, sleutel_id=v1.id, actor_id=beheerder_id
        )
        assert {r.project_id: r.netto_deel for r in regels} == {a: D("25.00"), b: D("75.00")}
        run = haal_run(opzet.administratie_id, opzet.run.id)
        assert run.verdeelsleutel_id == v1.id and run.verdeelsleutel_toegepast_op is not None
        review = doorbelasting_service.review_data(administratie_id=opzet.administratie_id, run_id=opzet.run.id)
        assert review.verdeelsleutel is not None and (review.verdeelsleutel.naam, review.verdeelsleutel.versie) == ("Alle panden naar m²", 1)
        with admin_engine.connect() as conn:
            acties = conn.execute(
                text("SELECT actie, nieuwe_waarde FROM platform.audit_event WHERE record_id = :id ORDER BY tijdstip"),
                {"id": opzet.run.id},
            ).all()
        toegepast = [n for a_, n in acties if a_ == "doorbelasting_verdeelsleutel_toegepast"]
        assert toegepast and toegepast[-1]["versie"] == 1 and toegepast[-1]["naam"] == "Alle panden naar m²"
        opgeslagen = [n for a_, n in acties if a_ == "doorbelasting_verdeling_opgeslagen"]
        assert opgeslagen[-1]["verdeelsleutel_id"] == str(v1.id) and len(opgeslagen[-1]["projecten"]) == 2

    def test_sleutel_valideert_whitelist_en_100_procent(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID
    ) -> None:
        opzet = onboarded_opzet
        with pytest.raises(DoorbelastingFout, match="whitelist"):
            doorbelasting_service.sla_verdeelsleutel_op(
                administratie_id=opzet.administratie_id, naam="x", definitie={"doelen": [{"mapping_id": str(uuid.uuid4()), "percentage": "100"}]}, actor_id=beheerder_id
            )
        with pytest.raises(DoorbelastingFout, match="100%"):
            doorbelasting_service.sla_verdeelsleutel_op(
                administratie_id=opzet.administratie_id, naam="x", definitie={"doelen": [{"mapping_id": str(opzet.mapping.id), "percentage": "60"}]}, actor_id=beheerder_id
            )
        with pytest.raises(DoorbelastingFout, match="verdeelbasis"):
            doorbelasting_service.sla_verdeelsleutel_op(
                administratie_id=opzet.administratie_id, naam="x", definitie={"doelen": [{"mapping_id": str(opzet.mapping.id), "percentage": "100", "projecten": "alle_actief"}]}, actor_id=beheerder_id
            )


class TestProjectenVoorMapping:
    def test_leest_doelprojecten_alleen_met_scope(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID, admin_engine: Engine, actieve_gebruiker
    ) -> None:
        opzet = onboarded_opzet
        a = _project(admin_engine, beheerder_id, opzet.doel_administratie_id, "Pand A", m2="12.5")
        projecten = doorbelasting_service.projecten_voor_mapping(
            administratie_id=opzet.administratie_id, mapping_id=opzet.mapping.id, actor_id=beheerder_id
        )
        assert [(p.id, p.naam, p.is_actief, p.contract_m2) for p in projecten] == [(a, "Pand A", True, D("12.50"))]
        # medewerker zónder scope op het doel → geen lees (fail-closed)
        with pytest.raises(doorbelasting_service.GeenScopeOpDoel):
            doorbelasting_service.projecten_voor_mapping(
                administratie_id=opzet.administratie_id, mapping_id=opzet.mapping.id, actor_id=actieve_gebruiker.id
            )
