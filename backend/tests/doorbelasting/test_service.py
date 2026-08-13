"""Servicelaag-tests doorbelasting (app/doorbelasting/service.py): Kempen-seed,
verdeling opslaan (grootste-rest + whitelist + bevriezing), run-poorten, review-previews
en het IC-vlagbeheer bij mapping-wijzigingen."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select

from app.db.session import scoped_session
from app.documenten import service as documenten_service
from app.documenten.models import DocumentSoort
from app.documenten.storage import LokaleBestandsopslag
from app.doorbelasting import service as doorbelasting_service
from app.doorbelasting.models import DoorbelastingMapping, IntercompanyTegenpartij
from app.doorbelasting.service import (
    KEMPEN_SEED,
    DoorbelastingFout,
    VerdeelRegelInvoerData,
    VerdelingBevroren,
    seed_kempen_mappings,
)
from tests.doorbelasting.conftest import (
    DOEL_KOSTEN_LEDGER_ID,
    DoorbelastingOpzet,
    FakeDoorbelastingClient,
    maak_administratie,
    maak_geboekt_inkoopfactuur,
    maak_mapping,
    start_run_met_verdeling,
)

D = Decimal


class TestSeedKempenMappings:
    def test_idempotent_met_ic_rijen_en_onboarded_koppeling(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        rubicon_id = maak_administratie(admin_engine, "Rubicon Investments B.V.")

        assert seed_kempen_mappings(administratie_id=administratie_id, actor_id=beheerder_id) == 8
        # tweede keer draaien voegt niets toe (idempotent)
        assert seed_kempen_mappings(administratie_id=administratie_id, actor_id=beheerder_id) == 0

        mappings = doorbelasting_service.lijst_mappings(administratie_id=administratie_id)
        assert len(mappings) == 8
        assert {m.doelentiteit_naam for m in mappings} == {naam for naam, _ in KEMPEN_SEED}
        per_naam = {m.doelentiteit_naam: m for m in mappings}
        # naam-match: Rubicon is al onboarded, de rest (nog) niet
        assert per_naam["Rubicon Investments B.V."].doel_administratie_id == rubicon_id
        assert all(
            m.doel_administratie_id is None for naam, m in per_naam.items() if naam != "Rubicon Investments B.V."
        )
        # bron-kant IC-rijen: elke doelentiteit-als-debiteur is intercompany
        with scoped_session(administratie_id) as session:
            ic_rijen = list(
                session.scalars(
                    select(IntercompanyTegenpartij).where(
                        IntercompanyTegenpartij.administratie_id == administratie_id
                    )
                )
            )
            assert {str(r.entity_guid) for r in ic_rijen} == {guid for _, guid in KEMPEN_SEED}
            assert all(r.actief for r in ic_rijen)


class TestSlaVerdelingOp:
    @pytest.fixture
    def run_met_drie_mappings(
        self,
        doorbelasting_aan: None,
        instelling_compleet: None,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
    ) -> tuple[uuid.UUID, uuid.UUID, list[DoorbelastingMapping]]:
        """(run_id, bron_regel_id, drie mappings) voor een bron-regel van € 411,10."""
        document_id, regel_ids = maak_geboekt_inkoopfactuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            nettos=[D("411.10")],
        )
        mappings = [
            maak_mapping(administratie_id=administratie_id, actor_id=beheerder_id, naam=f"Doel {i} B.V.")
            for i in range(3)
        ]
        run = doorbelasting_service.start_of_haal_run(
            administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id
        )
        return run.id, regel_ids[0], mappings

    def test_grootste_rest_er_raakt_nooit_een_cent_kwijt(
        self,
        run_met_drie_mappings: tuple[uuid.UUID, uuid.UUID, list[DoorbelastingMapping]],
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
    ) -> None:
        run_id, bron_regel_id, mappings = run_met_drie_mappings
        regels = doorbelasting_service.sla_verdeling_op(
            administratie_id=administratie_id,
            run_id=run_id,
            actor_id=beheerder_id,
            regels=[
                VerdeelRegelInvoerData(
                    bron_regel_id=bron_regel_id, mapping_id=m.id, percentage=pct, doel_kosten_ledger_id=None
                )
                for m, pct in zip(mappings, [D("50"), D("30"), D("20")], strict=True)
            ],
        )
        per_mapping = {r.mapping_id: r.netto_deel for r in regels}
        assert per_mapping[mappings[0].id] == D("205.55")
        assert per_mapping[mappings[1].id] == D("123.33")
        assert per_mapping[mappings[2].id] == D("82.22")
        assert sum(per_mapping.values()) == D("411.10")

    def test_whitelist_weigert_onbekende_mapping(
        self,
        run_met_drie_mappings: tuple[uuid.UUID, uuid.UUID, list[DoorbelastingMapping]],
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
    ) -> None:
        run_id, bron_regel_id, _mappings = run_met_drie_mappings
        with pytest.raises(DoorbelastingFout, match="whitelist"):
            doorbelasting_service.sla_verdeling_op(
                administratie_id=administratie_id,
                run_id=run_id,
                actor_id=beheerder_id,
                regels=[
                    VerdeelRegelInvoerData(
                        bron_regel_id=bron_regel_id,
                        mapping_id=uuid.uuid4(),  # bestaat niet — doelentiteit buiten de lijst
                        percentage=D("100"),
                        doel_kosten_ledger_id=None,
                    )
                ],
            )

    def test_verdeling_bevroren_na_boeking(
        self, spiegel_open_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID
    ) -> None:
        opzet = spiegel_open_opzet
        from app.doorbelasting.boeken import boek_doorbelasting_run

        boek_doorbelasting_run(
            administratie_id=opzet.administratie_id,
            run_id=opzet.run.id,
            actor_id=beheerder_id,
            bron_client=FakeDoorbelastingClient(),
            doel_client_factory=lambda _aid: pytest.fail("geen doel-client voor spiegel_open"),
        )
        with pytest.raises(VerdelingBevroren):
            doorbelasting_service.sla_verdeling_op(
                administratie_id=opzet.administratie_id,
                run_id=opzet.run.id,
                actor_id=beheerder_id,
                regels=[
                    VerdeelRegelInvoerData(
                        bron_regel_id=opzet.regel_ids[0],
                        mapping_id=opzet.mapping.id,
                        percentage=D("100"),
                        doel_kosten_ledger_id=None,
                    )
                ],
            )


class TestStartOfHaalRun:
    def test_weigert_niet_geboekt_document(
        self,
        doorbelasting_aan: None,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
    ) -> None:
        resultaat = documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="nog-niet-geboekt.pdf",
            inhoud=b"%PDF-1.4 concept",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        with pytest.raises(DoorbelastingFout, match="geboekt document"):
            doorbelasting_service.start_of_haal_run(
                administratie_id=administratie_id, document_id=resultaat.document_id, actor_id=beheerder_id
            )

    def test_weigert_verkeerde_soort(
        self,
        doorbelasting_aan: None,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
    ) -> None:
        document_id, _ = maak_geboekt_inkoopfactuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            nettos=[D("100.00")],
            soort=DocumentSoort.KASSARAPPORT,
            bestandsnaam="margerapport.pdf",
        )
        with pytest.raises(DoorbelastingFout, match="inkoopfactuur"):
            doorbelasting_service.start_of_haal_run(
                administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id
            )

    def test_tweede_aanroep_geeft_dezelfde_run(
        self,
        doorbelasting_aan: None,
        geboekt_document: tuple[uuid.UUID, list[uuid.UUID]],
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
    ) -> None:
        document_id, _ = geboekt_document
        eerste = doorbelasting_service.start_of_haal_run(
            administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id
        )
        tweede = doorbelasting_service.start_of_haal_run(
            administratie_id=administratie_id, document_id=document_id, actor_id=beheerder_id
        )
        assert eerste.id == tweede.id


class TestReviewData:
    def test_previews_met_provisie_en_btw_uit_het_cache_tarief(
        self, onboarded_opzet: DoorbelastingOpzet
    ) -> None:
        opzet = onboarded_opzet
        data = doorbelasting_service.review_data(
            administratie_id=opzet.administratie_id, run_id=opzet.run.id
        )
        assert data.run.id == opzet.run.id
        assert len(data.regels) == 1
        assert len(data.previews) == 1
        preview = data.previews[0]
        assert preview.mapping_id == opzet.mapping.id
        assert preview.doelentiteit_naam == opzet.mapping.doelentiteit_naam
        assert preview.onboarded is True
        assert preview.netto_totaal == D("100.00")
        assert preview.provisie_bedrag == D("5.00")  # 5% over het netto doorbelaste totaal
        assert preview.btw_bedrag == D("22.05")  # 21% over 100,00 + 21% over 5,00, per regel
        assert preview.boeking_status is None  # nog niets geboekt
        # het checks-rapport is aanwezig én groen voor deze volledig geconfigureerde run
        assert len(data.rapport.resultaten) == 4
        assert not data.rapport.geblokkeerd


class TestWijzigMapping:
    def test_intercompany_uit_deactiveert_de_ic_rij_zonder_verwijderen(
        self, administratie_id: uuid.UUID, beheerder_id: uuid.UUID
    ) -> None:
        seed_kempen_mappings(administratie_id=administratie_id, actor_id=beheerder_id)
        mappings = doorbelasting_service.lijst_mappings(administratie_id=administratie_id)
        doelwit = next(m for m in mappings if m.doelentiteit_naam == "Rubicon Investments B.V.")

        doorbelasting_service.wijzig_mapping(
            administratie_id=administratie_id,
            mapping_id=doelwit.id,
            actor_id=beheerder_id,
            intercompany=False,
        )
        with scoped_session(administratie_id) as session:
            ic_rijen = list(
                session.scalars(
                    select(IntercompanyTegenpartij).where(
                        IntercompanyTegenpartij.administratie_id == administratie_id
                    )
                )
            )
            assert len(ic_rijen) == 8  # nooit verwijderd, alleen gedeactiveerd
            per_guid = {r.entity_guid: r for r in ic_rijen}
            assert per_guid[doelwit.doel_customer_guid].actief is False
            assert sum(1 for r in ic_rijen if r.actief) == 7
