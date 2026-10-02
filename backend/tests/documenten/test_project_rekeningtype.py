# ruff: noqa: F811 — pytest-fixtures als parameters
"""Punt 6 "Boeken prettig 1" (Peter 02-10: "soms hebben we gewoon spullen die als voorraad worden gekocht, die moeten
helemaal geen project krijgen"): projecteis en projectverdeling gelden uitsluitend voor KOSTENrekeningen
(`grootboekrekening.soort == 2`). Voorraad (3xxx), activa (0xxx), passiva/tussenrekeningen: geen projectveld, geen
verdeling, geen check. Deterministisch op het rekeningtype uit de sync; een onbekende rekening telt als kosten
(fail-closed). De RLZ-adapter splitst een balansregel nooit over de verdeling."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.backends.rlz_inkoop import regels_naar_rlz_lines
from app.beheer import service as beheer_service
from app.db.models import Grootboekrekening
from app.db.session import scoped_session
from app.documenten import boeken, boekvoorstel, rekeningtype
from app.documenten.checks import CheckRegel, check_verplichte_velden
from app.documenten.models import DocumentStatus
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.projectverdeling.conftest import (  # noqa: F401 — fixtures her-exporteren
    _opslag_naar_tmp,
    actieve_gebruiker,
    administratie_id,
    beheerder_id,
    document_zonder_project,
    gescoopte_gebruiker,
    opslag,
    projecten,
    regel,
    vendor_id,
)

GB_VOORRAAD = uuid.UUID("44444444-0000-0000-0000-000000003000")  # 3000 Voorraad — balans (soort 3)
GB_ACTIVA = uuid.UUID("44444444-0000-0000-0000-000000000107")  # 0107 Inventaris — activa (soort 3)
GB_TUSSEN = uuid.UUID("44444444-0000-0000-0000-000000002100")  # 2100 Tussenrekening — passiva (soort 4)
GB_KOSTEN = uuid.UUID("44444444-0000-0000-0000-000000004501")  # 4501 kosten (soort 2)
GB_ONBEKEND = uuid.UUID("44444444-0000-0000-0000-000000009999")  # niet in de cache


class TestPuur:
    def test_project_van_toepassing_is_kosten_of_onbekend(self) -> None:
        balans = frozenset({GB_VOORRAAD, GB_ACTIVA, GB_TUSSEN})
        assert rekeningtype.project_van_toepassing(GB_KOSTEN, balans) is True
        assert rekeningtype.project_van_toepassing(GB_ONBEKEND, balans) is True  # fail-closed: onbekend = kosten
        assert rekeningtype.project_van_toepassing(None, balans) is True
        assert all(rekeningtype.project_van_toepassing(b, balans) is False for b in balans)

    def test_check_verplichte_velden_eist_geen_project_op_een_balansregel(self) -> None:
        kosten = CheckRegel(GB_KOSTEN, uuid.uuid4(), Decimal("100"), Decimal("21"), project_id=None)
        voorraad = CheckRegel(
            GB_VOORRAAD, uuid.uuid4(), Decimal("500"), Decimal("105"), project_id=None, project_van_toepassing=False
        )
        gemeenschappelijk = dict(
            vendor_id=uuid.uuid4(), referentie="F-1", factuurdatum=date(2026, 7, 31), totaalbedrag=Decimal("726")
        )
        alleen_voorraad = check_verplichte_velden(regels=[voorraad], project_verplicht=True, **gemeenschappelijk)
        assert alleen_voorraad.ok, alleen_voorraad.melding
        beide = check_verplichte_velden(regels=[voorraad, kosten], project_verplicht=True, **gemeenschappelijk)
        assert not beide.ok and "project (regel 2)" in beide.melding and "regel 1" not in beide.melding


def _rekeningen(administratie_id: uuid.UUID) -> None:
    with scoped_session(administratie_id) as session:
        for ledger_id, code, naam, soort in (
            (GB_VOORRAAD, "3000", "Voorraad steigermateriaal", 3),
            (GB_ACTIVA, "0107", "Inventaris", 3),
            (GB_TUSSEN, "2100", "Tussenrekening", 4),
            (GB_KOSTEN, "4501", "Brandstof", 2),
        ):
            session.add(
                Grootboekrekening(
                    ledger_id=ledger_id,
                    administratie_id=administratie_id,
                    code=code,
                    naam=naam,
                    soort=soort,
                    is_totaalrekening=False,
                )
            )


def _sla_op(administratie_id, document_id, actor_id, vendor_id, regels) -> None:
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        vendor_id=vendor_id,
        referentie="FB-2026-0731",
        factuurdatum=date(2026, 7, 31),
        totaalbedrag=Decimal("2420.00"),
        regels=regels,
    )


def _checks(administratie_id: uuid.UUID, document_id: uuid.UUID) -> dict:
    rapport = boekvoorstel.voer_checks_uit(
        administratie_id=administratie_id, document_id=document_id, client=FakeBoekClient()
    )
    return {r.naam: r for r in rapport.resultaten}


class TestKeten:
    @pytest.fixture(autouse=True)
    def _omgeving(self, administratie_id, beheerder_id, admin_engine: Engine) -> None:
        beheer_service.zet_project_verplicht(actor_id=beheerder_id, administratie_id=administratie_id, verplicht=True)
        _rekeningen(administratie_id)

    @pytest.mark.parametrize("balans_ledger", [GB_VOORRAAD, GB_ACTIVA, GB_TUSSEN], ids=["voorraad", "activa", "tussen"])
    def test_balansregel_zonder_project_geen_eis_geen_verdeling_geen_check(
        self, administratie_id, gescoopte_gebruiker, vendor_id, document_zonder_project, projecten, balans_ledger
    ) -> None:
        _sla_op(
            administratie_id,
            document_zonder_project,
            gescoopte_gebruiker,
            vendor_id,
            [regel(ledger_id=balans_ledger, netto_bedrag=Decimal("2000.00"), btw_bedrag=Decimal("420.00"))],
        )
        voorstel = boekvoorstel.haal_boekvoorstel_op(
            administratie_id=administratie_id, document_id=document_zonder_project
        )
        assert voorstel.regels[0].project_van_toepassing is False
        assert voorstel.projectverdeling is None  # geen kostenregel zonder project → niets te verdelen
        per_naam = _checks(administratie_id, document_zonder_project)
        assert per_naam["Verplichte velden"].ok, per_naam["Verplichte velden"].melding
        assert per_naam["Projectverdeling"].ok and not per_naam["Projectverdeling"].signaal
        assert per_naam["Projectverdeling"].melding == "Geen projectverdeling van toepassing"

    def test_mengvorm_alleen_de_kostenregel_telt_en_wordt_verdeeld_en_gesplitst(
        self,
        administratie_id,
        gescoopte_gebruiker,
        beheerder_id,
        vendor_id,
        document_zonder_project,
        projecten,
        admin_engine,
        monkeypatch,
    ) -> None:
        _sla_op(
            administratie_id,
            document_zonder_project,
            gescoopte_gebruiker,
            vendor_id,
            [
                regel(ledger_id=GB_VOORRAAD, netto_bedrag=Decimal("1500.00"), btw_bedrag=Decimal("315.00")),
                regel(ledger_id=GB_KOSTEN, netto_bedrag=Decimal("500.00"), btw_bedrag=Decimal("105.00")),
            ],
        )
        voorstel = boekvoorstel.haal_boekvoorstel_op(
            administratie_id=administratie_id, document_id=document_zonder_project
        )
        assert [r.project_van_toepassing for r in voorstel.regels] == [False, True]
        data = voorstel.projectverdeling
        assert data is not None and data.prefill and data.compleet
        assert data.basisbedrag == Decimal("500.00") and data.regels_zonder_project == 1 and data.regels_totaal == 1
        per_naam = _checks(administratie_id, document_zonder_project)
        assert per_naam["Verplichte velden"].ok, per_naam["Verplichte velden"].melding
        assert per_naam["Projectverdeling"].melding == "Verdeeld: € 500,00 over 3 projecten, pro rato omzet juli 2026"
        # Adapter: de voorraadregel blijft één regel zonder Project, de kostenregel wordt per project gesplitst.
        lines = regels_naar_rlz_lines(voorstel)
        voorraad = [line for line in lines if line["Account"]["id"] == str(GB_VOORRAAD)]
        kosten = [line for line in lines if line["Account"]["id"] == str(GB_KOSTEN)]
        assert len(voorraad) == 1 and "Project" not in voorraad[0] and voorraad[0]["NetAmount"] == 1500.0
        assert len(kosten) == 3 and all("Project" in line for line in kosten)
        assert sum(Decimal(str(line["NetAmount"])) for line in kosten) == Decimal("500.00")
        # Boeken kan direct.
        beheer_service.zet_boeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        fake = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
        boeken.boek_document(
            administratie_id=administratie_id, document_id=document_zonder_project, actor_id=gescoopte_gebruiker
        )
        with admin_engine.connect() as conn:
            status = conn.execute(
                text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_zonder_project}
            ).scalar_one()
        assert status == DocumentStatus.GEBOEKT.value and len(fake.puts[0]["lines"]) == 4

    def test_onbekende_rekening_telt_als_kosten(
        self, administratie_id, gescoopte_gebruiker, vendor_id, document_zonder_project, admin_engine
    ) -> None:
        # Geen projecten/omzet in deze test: de kostenregel zonder project moet dan blokkeren — en een rekening die
        # niet in de cache staat gedraagt zich exact zo (fail-closed richting de projectplicht).
        _sla_op(
            administratie_id,
            document_zonder_project,
            gescoopte_gebruiker,
            vendor_id,
            [regel(ledger_id=GB_ONBEKEND, netto_bedrag=Decimal("2000.00"), btw_bedrag=Decimal("420.00"))],
        )
        voorstel = boekvoorstel.haal_boekvoorstel_op(
            administratie_id=administratie_id, document_id=document_zonder_project
        )
        assert voorstel.regels[0].project_van_toepassing is True
        per_naam = _checks(administratie_id, document_zonder_project)
        assert not per_naam["Verplichte velden"].ok and "project (regel 1)" in per_naam["Verplichte velden"].melding

    def test_prefill_zet_nooit_een_project_op_een_balansregel(
        self, administratie_id, gescoopte_gebruiker, vendor_id, document_zonder_project, projecten, admin_engine
    ) -> None:
        """Ook een factuur die een projectcode noemt vult op een voorraadregel geen project (regel_prefill)."""
        from app.documenten import regel_prefill

        with scoped_session(administratie_id) as session:
            regels, _ = regel_prefill.verrijk_prefill(
                session,
                administratie_id=administratie_id,
                document_id=document_zonder_project,
                vendor_id=vendor_id,
                regels=[
                    regel(ledger_id=GB_VOORRAAD, omschrijving="Steigerdelen voorraad 26127"),
                    regel(ledger_id=GB_KOSTEN, omschrijving="Brandstof werk 26127"),
                ],
                samengevoegde_regel=None,
                project_verplicht=True,
            )
        assert regels[0].project_id is None and regels[0].project_bron is None
        assert regels[1].project_id == projecten["tilburg"] and regels[1].project_bron == "factuur"
