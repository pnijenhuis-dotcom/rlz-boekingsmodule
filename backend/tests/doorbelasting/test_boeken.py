"""Motor-tests doorbelasting (app/doorbelasting/boeken.py): tweezijdige boeking per
doelentiteit, spiegel_open-pad, half-geboekt-patroon, poorten (checks, toggles, volumerem,
rechten-probe), storno beide kanten en de spiegel-alsnog-taak — alles via de test-seams
(`bron_client`/`doel_client_factory`/`doel_client`), nooit echte HTTP."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select, text

from app.config import settings
from app.db.session import scoped_session
from app.documenten.boeken import BoekenUitgeschakeld, VolumeremBereikt
from app.documenten.models import DocumentGebeurtenis
from app.documenten.rlz_ids import (
    rlz_doorbelasting_spiegel_id,
    rlz_doorbelasting_verkoop_id,
    rlz_vendor_id,
)
from app.doorbelasting import service as doorbelasting_service
from app.doorbelasting.boeken import (
    AdministratieNietBereikbaar,
    BoekenGeblokkeerdDoorChecks,
    boek_doorbelasting_run,
    boek_spiegel_alsnog,
    storno_doorbelasting_boeking,
    storno_toets_voor_document,
)
from app.doorbelasting.models import (
    DoorbelastingBoekingStatus,
    DoorbelastingRegel,
    DoorbelastingRunStatus,
    IntercompanyTegenpartij,
)
from app.doorbelasting.service import DoorbelastingFout, VerdeelRegelInvoerData
from app.rlz.aangifte import StornoGeblokkeerdDoorAangifte
from tests.doorbelasting.conftest import (
    DOEL_KOSTEN_LEDGER_ID,
    PROVISIE_KOSTEN_LEDGER_ID,
    DoorbelastingOpzet,
    FakeDoorbelastingClient,
    geef_scope,
    haal_boekingen,
    haal_run,
    maak_administratie,
    maak_mapping,
    start_run_met_verdeling,
)

D = Decimal


def _boek(
    opzet: DoorbelastingOpzet,
    actor_id: uuid.UUID,
    *,
    bron: FakeDoorbelastingClient,
    doel: FakeDoorbelastingClient | None = None,
) -> dict[str, str]:
    def factory(_administratie_id: uuid.UUID) -> FakeDoorbelastingClient:
        assert doel is not None, "doel_client_factory mag hier niet aangeroepen worden"
        return doel

    return boek_doorbelasting_run(
        administratie_id=opzet.administratie_id,
        run_id=opzet.run.id,
        actor_id=actor_id,
        bron_client=bron,
        doel_client_factory=factory,
    )


class TestHappyPathOnboarded:
    def test_boekt_beide_kanten_met_provisieregel_en_gedeelde_referentie(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        opzet = onboarded_opzet
        bron, doel = FakeDoorbelastingClient(), FakeDoorbelastingClient()
        resultaat = _boek(opzet, beheerder_id, bron=bron, doel=doel)
        assert resultaat == {str(opzet.mapping.id): DoorbelastingBoekingStatus.GEBOEKT.value}

        verkoop_id = rlz_doorbelasting_verkoop_id(opzet.document_id, opzet.mapping.doel_customer_guid)
        spiegel_id = rlz_doorbelasting_spiegel_id(opzet.document_id, opzet.mapping.doel_customer_guid)

        # verkoop in de bron: kostenregel + losse provisieregel als laatste (Kempen-patroon)
        verkoop = bron.sales_invoices[str(verkoop_id)]
        assert verkoop["Status"] == 2
        assert verkoop["Entity"] == {"id": str(opzet.mapping.doel_customer_guid)}
        lines = verkoop["DocumentLineList"]
        assert len(lines) == 2
        assert lines[0]["NetAmount"] == 100.0
        assert lines[0]["TaxAmount"] == 21.0
        assert lines[-1]["Description"] == "Provisie 5% over nettobedrag"
        assert lines[-1]["NetAmount"] == 5.0  # 5% over € 100,00 netto
        assert lines[-1]["TaxAmount"] == 1.05

        # spiegel in het doel: Reference == het verkoopnummer van kant 1 (STAP-0 2026-08-13)
        spiegel = doel.purchase_invoices[str(spiegel_id)]
        assert spiegel["Status"] == 2
        assert spiegel["Reference"] == verkoop["Reference"]
        # Punt 15 (28-08): beide kanten op de FACTUURDATUM van het bron-document (Date + BookDate),
        # niet op de dag van de run — STAP 0 boekdatum: de journaalpost volgt BookDate.
        with admin_engine.connect() as conn:
            factuurdatum = conn.execute(
                text("SELECT factuurdatum FROM boekhouding.boekvoorstel WHERE document_id = :d"),
                {"d": opzet.document_id},
            ).scalar_one()
        verwacht = f"{factuurdatum.isoformat()}T00:00:00"
        assert verkoop["Date"] == verkoop["BookDate"] == verwacht
        assert spiegel["Date"] == spiegel["BookDate"] == verwacht
        assert spiegel["DocumentLineList"][0]["Account"] == {"id": str(DOEL_KOSTEN_LEDGER_ID)}
        assert spiegel["DocumentLineList"][-1]["Account"] == {"id": str(PROVISIE_KOSTEN_LEDGER_ID)}
        # bijlage aan beide kanten
        assert {u["pad"] for u in bron.uploads} == {"SalesInvoices"}
        assert {u["pad"] for u in doel.uploads} == {"PurchaseInvoices"}

        # boeking-rij + bedragen
        boekingen = haal_boekingen(opzet.administratie_id, opzet.run.id)
        assert len(boekingen) == 1
        boeking = boekingen[0]
        assert boeking.status == DoorbelastingBoekingStatus.GEBOEKT.value
        assert boeking.netto_totaal == D("100.00")
        assert boeking.provisie_bedrag == D("5.00")
        assert boeking.btw_bedrag == D("22.05")  # 21,00 + 1,05, per regel afgerond
        assert boeking.verkoop_referentie == verkoop["Reference"]
        assert boeking.doel_administratie_id == opzet.doel_administratie_id
        assert haal_run(opzet.administratie_id, opzet.run.id).status == DoorbelastingRunStatus.GEBOEKT.value

        # tijdlijn-gebeurtenis op het bron-document
        with scoped_session(opzet.administratie_id) as session:
            details = [
                g.detail
                for g in session.scalars(
                    select(DocumentGebeurtenis).where(DocumentGebeurtenis.document_id == opzet.document_id)
                )
                if g.detail
            ]
        assert any(d.get("gebeurtenis") == "doorbelast" for d in details)

        # audit_event
        with admin_engine.connect() as conn:
            audit = conn.execute(
                text(
                    "SELECT count(*) FROM platform.audit_event "
                    "WHERE tabel = 'doorbelasting_boeking' AND actie = 'doorbelasting_geboekt'"
                )
            ).scalar_one()
        assert audit == 1

        # IC-rij in de DOEL-scope: de bron-administratie is daar intercompany-tegenpartij
        vendor_id = rlz_vendor_id(opzet.doel_administratie_id, "Scope-test")
        with scoped_session(opzet.doel_administratie_id) as session:
            ic = session.scalars(
                select(IntercompanyTegenpartij).where(
                    IntercompanyTegenpartij.administratie_id == opzet.doel_administratie_id
                )
            ).one()
            assert ic.entity_guid == vendor_id
            assert ic.naam == "Scope-test"
            assert ic.actief is True

    def test_medewerker_met_scope_op_doel_boekt_de_losse_actie(
        self,
        onboarded_opzet: DoorbelastingOpzet,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
    ) -> None:
        """Losse "Doorbelasten…" op een geboekt document — zelfde scope-poort als de boekflow
        (bugfix 2026-08-25: echte niet-Beheerder MÉT doel-scope moet door)."""
        opzet = onboarded_opzet
        assert opzet.doel_administratie_id is not None
        geef_scope(
            beheerder_id=beheerder_id, gebruiker_id=gescoopte_gebruiker, administratie_id=opzet.doel_administratie_id
        )
        bron, doel = FakeDoorbelastingClient(), FakeDoorbelastingClient()
        resultaat = _boek(opzet, gescoopte_gebruiker, bron=bron, doel=doel)
        assert resultaat == {str(opzet.mapping.id): DoorbelastingBoekingStatus.GEBOEKT.value}
        assert len(bron.sales_invoices) == 1 and len(doel.purchase_invoices) == 1

    def test_medewerker_zonder_scope_op_doel_wordt_geweigerd_zonder_writes(
        self, onboarded_opzet: DoorbelastingOpzet, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        opzet = onboarded_opzet
        bron, doel = FakeDoorbelastingClient(), FakeDoorbelastingClient()
        with pytest.raises(DoorbelastingFout, match="Geen scope op doel-administratie van Veldhoven Recreatie B.V."):
            _boek(opzet, gescoopte_gebruiker, bron=bron, doel=doel)
        assert bron.sales_invoices == {} and doel.purchase_invoices == {}

    def test_tweede_keer_boeken_van_geboekte_run_weigert(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID
    ) -> None:
        opzet = onboarded_opzet
        _boek(opzet, beheerder_id, bron=FakeDoorbelastingClient(), doel=FakeDoorbelastingClient())
        with pytest.raises(DoorbelastingFout, match="al geboekt"):
            _boek(opzet, beheerder_id, bron=FakeDoorbelastingClient(), doel=FakeDoorbelastingClient())


class TestSpiegelOpen:
    def test_niet_onboarded_doel_boekt_alleen_bron_en_zet_open_taak(
        self, spiegel_open_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID
    ) -> None:
        opzet = spiegel_open_opzet
        bron = FakeDoorbelastingClient()
        # doel=None: de factory hoort nooit aangeroepen te worden voor een niet-onboarded doel
        resultaat = _boek(opzet, beheerder_id, bron=bron, doel=None)
        assert resultaat == {str(opzet.mapping.id): DoorbelastingBoekingStatus.SPIEGEL_OPEN.value}

        verkoop_id = rlz_doorbelasting_verkoop_id(opzet.document_id, opzet.mapping.doel_customer_guid)
        assert bron.sales_invoices[str(verkoop_id)]["Status"] == 2

        boekingen = haal_boekingen(opzet.administratie_id, opzet.run.id)
        assert len(boekingen) == 1
        assert boekingen[0].status == DoorbelastingBoekingStatus.SPIEGEL_OPEN.value
        assert boekingen[0].spiegel_geboekt_op is None
        # zichtbaar als open taak — nooit stil half
        taken = doorbelasting_service.open_spiegel_taken(administratie_id=opzet.administratie_id)
        assert [t.id for t in taken] == [boekingen[0].id]


class TestSpiegelFaalt:
    def test_storno_bron_slaagt_geen_boeking_rij_en_fout_op_de_run(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID
    ) -> None:
        opzet = onboarded_opzet
        bron = FakeDoorbelastingClient()
        doel = FakeDoorbelastingClient(faal_op="spiegel_boek")
        resultaat = _boek(opzet, beheerder_id, bron=bron, doel=doel)
        assert resultaat == {str(opzet.mapping.id): "mislukt"}

        verkoop_id = rlz_doorbelasting_verkoop_id(opzet.document_id, opzet.mapping.doel_customer_guid)
        assert bron.verkoop_correcties == [str(verkoop_id)]  # actie 19 op de bron-verkoop
        assert haal_boekingen(opzet.administratie_id, opzet.run.id) == []

        run = haal_run(opzet.administratie_id, opzet.run.id)
        assert run.status == DoorbelastingRunStatus.CONCEPT.value
        assert run.laatste_fout is not None
        fout = run.laatste_fout[str(opzet.mapping.id)]["fout"]
        assert "gestorneerd" in fout

    def test_storno_bron_faalt_ook_half_geboekt_met_detail(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID
    ) -> None:
        opzet = onboarded_opzet
        bron = FakeDoorbelastingClient(faal_op="storno_verkoop")
        doel = FakeDoorbelastingClient(faal_op="spiegel_boek")
        resultaat = _boek(opzet, beheerder_id, bron=bron, doel=doel)
        assert resultaat == {str(opzet.mapping.id): DoorbelastingBoekingStatus.HALF_GEBOEKT.value}

        boekingen = haal_boekingen(opzet.administratie_id, opzet.run.id)
        assert len(boekingen) == 1
        boeking = boekingen[0]
        assert boeking.status == DoorbelastingBoekingStatus.HALF_GEBOEKT.value
        assert boeking.half_geboekt_detail is not None
        assert "spiegel_fout" in boeking.half_geboekt_detail
        assert "storno_verkoop_fout" in boeking.half_geboekt_detail
        assert "herstel" in boeking.half_geboekt_detail
        # de run blijft 'concept' (fix 2026-08-13 n.a.v. testbevinding): half_geboekt is open
        # menselijk herstelwerk — 'geboekt' als run-status zou dat maskeren. De halve
        # boeking-rij zelf blokkeert intussen elke nieuwe boekpoging (duplicaatbewaking).
        assert haal_run(opzet.administratie_id, opzet.run.id).status == DoorbelastingRunStatus.CONCEPT.value


class TestPoorten:
    def test_verdeling_niet_100_blokkeert_zonder_rlz_calls(
        self,
        doorbelasting_aan: None,
        instelling_compleet: None,
        geboekt_document: tuple[uuid.UUID, list[uuid.UUID]],
        doel_administratie_id: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
    ) -> None:
        document_id, regel_ids = geboekt_document
        mapping = maak_mapping(
            administratie_id=administratie_id,
            actor_id=beheerder_id,
            doel_administratie_id=doel_administratie_id,
            provisie_kosten_ledger_id=PROVISIE_KOSTEN_LEDGER_ID,
        )
        run = start_run_met_verdeling(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=beheerder_id,
            regels=[
                VerdeelRegelInvoerData(
                    bron_regel_id=regel_ids[0],
                    mapping_id=mapping.id,
                    percentage=D("60"),
                    doel_kosten_ledger_id=DOEL_KOSTEN_LEDGER_ID,
                )
            ],
        )
        bron = FakeDoorbelastingClient()
        with pytest.raises(BoekenGeblokkeerdDoorChecks) as excinfo:
            boek_doorbelasting_run(
                administratie_id=administratie_id,
                run_id=run.id,
                actor_id=beheerder_id,
                bron_client=bron,
                doel_client_factory=lambda _aid: pytest.fail("doel-factory aangeroepen ondanks blokkade"),
            )
        assert excinfo.value.rapport.geblokkeerd
        assert bron.sales_invoices == {}
        assert bron.probes == 0  # geblokkeerd vóór de eerste RLZ-call

    def test_doorbelasting_uitgeschakeld_weigert(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        opzet = onboarded_opzet
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET doorbelasting_ingeschakeld = false WHERE id = :id"),
                {"id": opzet.administratie_id},
            )
        with pytest.raises(DoorbelastingFout, match="staat uit"):
            _boek(opzet, beheerder_id, bron=FakeDoorbelastingClient(), doel=FakeDoorbelastingClient())

    def test_boeken_toggle_doel_administratie_blokkeert(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        opzet = onboarded_opzet
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET boeken_ingeschakeld = false WHERE id = :id"),
                {"id": opzet.doel_administratie_id},
            )
        bron = FakeDoorbelastingClient()
        with pytest.raises(BoekenUitgeschakeld, match="doel-administratie"):
            _boek(opzet, beheerder_id, bron=bron, doel=FakeDoorbelastingClient())
        assert bron.sales_invoices == {}

    def test_volumerem(
        self,
        onboarded_opzet: DoorbelastingOpzet,
        beheerder_id: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "max_boekingen_per_dag_per_administratie", 0)
        bron = FakeDoorbelastingClient()
        with pytest.raises(VolumeremBereikt):
            _boek(onboarded_opzet, beheerder_id, bron=bron, doel=FakeDoorbelastingClient())
        assert bron.sales_invoices == {}

    def test_rechten_probe_doel_faalt_voor_de_eerste_write(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID
    ) -> None:
        opzet = onboarded_opzet
        bron = FakeDoorbelastingClient()
        doel = FakeDoorbelastingClient(faal_op="rechten_probe")
        with pytest.raises(AdministratieNietBereikbaar, match="niets geboekt"):
            _boek(opzet, beheerder_id, bron=bron, doel=doel)
        assert bron.sales_invoices == {}
        assert doel.purchase_invoices == {}
        assert doel.vendors == {}
        assert haal_boekingen(opzet.administratie_id, opzet.run.id) == []


class TestMeerdereDoelen:
    def test_een_falend_doel_stopt_het_andere_niet(
        self,
        doorbelasting_aan: None,
        instelling_compleet: None,
        geboekt_document: tuple[uuid.UUID, list[uuid.UUID]],
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        document_id, regel_ids = geboekt_document
        doel_a = maak_administratie(admin_engine, "Oirschot Recreatie B.V.")
        doel_b = maak_administratie(admin_engine, "Molenhof Beheer B.V.")
        mapping_a = maak_mapping(
            administratie_id=administratie_id,
            actor_id=beheerder_id,
            naam="Oirschot Recreatie B.V.",
            doel_administratie_id=doel_a,
            provisie_kosten_ledger_id=PROVISIE_KOSTEN_LEDGER_ID,
        )
        mapping_b = maak_mapping(
            administratie_id=administratie_id,
            actor_id=beheerder_id,
            naam="Molenhof Beheer B.V.",
            doel_administratie_id=doel_b,
            provisie_kosten_ledger_id=PROVISIE_KOSTEN_LEDGER_ID,
        )
        run = start_run_met_verdeling(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=beheerder_id,
            regels=[
                VerdeelRegelInvoerData(
                    bron_regel_id=regel_ids[0],
                    mapping_id=mapping_a.id,
                    percentage=D("50"),
                    doel_kosten_ledger_id=DOEL_KOSTEN_LEDGER_ID,
                ),
                VerdeelRegelInvoerData(
                    bron_regel_id=regel_ids[0],
                    mapping_id=mapping_b.id,
                    percentage=D("50"),
                    doel_kosten_ledger_id=DOEL_KOSTEN_LEDGER_ID,
                ),
            ],
        )
        bron = FakeDoorbelastingClient()
        fakes = {doel_a: FakeDoorbelastingClient(), doel_b: FakeDoorbelastingClient(faal_op="spiegel_boek")}
        resultaat = boek_doorbelasting_run(
            administratie_id=administratie_id,
            run_id=run.id,
            actor_id=beheerder_id,
            bron_client=bron,
            doel_client_factory=lambda aid: fakes[aid],
        )
        assert resultaat == {
            str(mapping_a.id): DoorbelastingBoekingStatus.GEBOEKT.value,
            str(mapping_b.id): "mislukt",
        }
        boekingen = haal_boekingen(administratie_id, run.id)
        assert [b.mapping_id for b in boekingen] == [mapping_a.id]
        assert boekingen[0].netto_totaal == D("50.00")
        assert boekingen[0].provisie_bedrag == D("2.50")
        # de mislukte kant is netjes gestorneerd in de bron én als fout op de run zichtbaar
        verkoop_b = rlz_doorbelasting_verkoop_id(document_id, mapping_b.doel_customer_guid)
        assert bron.verkoop_correcties == [str(verkoop_b)]
        run_na = haal_run(administratie_id, run.id)
        assert run_na.status == DoorbelastingRunStatus.CONCEPT.value
        assert str(mapping_b.id) in (run_na.laatste_fout or {})
        assert str(mapping_a.id) not in (run_na.laatste_fout or {})


class TestStorno:
    def test_storno_beide_kanten_spiegel_eerst(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID
    ) -> None:
        opzet = onboarded_opzet
        logboek: list[tuple[str, str]] = []
        bron = FakeDoorbelastingClient(logboek=logboek)
        doel = FakeDoorbelastingClient(logboek=logboek)
        _boek(opzet, beheerder_id, bron=bron, doel=doel)
        boeking = haal_boekingen(opzet.administratie_id, opzet.run.id)[0]

        gestorneerd = storno_doorbelasting_boeking(
            administratie_id=opzet.administratie_id,
            boeking_id=boeking.id,
            actor_id=beheerder_id,
            reden="Verkeerde verdeelsleutel gebruikt",
            bron_client=bron,
            doel_client=doel,
        )
        assert gestorneerd.status == DoorbelastingBoekingStatus.GESTORNEERD.value
        assert gestorneerd.storno_reden == "Verkeerde verdeelsleutel gebruikt"
        # vaste volgorde: eerst de spiegel in het doel, dan de bron-verkoop (actie 19)
        verkoop_id = rlz_doorbelasting_verkoop_id(opzet.document_id, opzet.mapping.doel_customer_guid)
        spiegel_id = rlz_doorbelasting_spiegel_id(opzet.document_id, opzet.mapping.doel_customer_guid)
        assert logboek == [("spiegel_storno", str(spiegel_id)), ("verkoop_storno", str(verkoop_id))]
        # laatste actieve boeking weg → run gestorneerd
        assert haal_run(opzet.administratie_id, opzet.run.id).status == DoorbelastingRunStatus.GESTORNEERD.value

    def test_storno_vereist_reden_van_minimaal_5_tekens(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID
    ) -> None:
        opzet = onboarded_opzet
        bron, doel = FakeDoorbelastingClient(), FakeDoorbelastingClient()
        _boek(opzet, beheerder_id, bron=bron, doel=doel)
        boeking = haal_boekingen(opzet.administratie_id, opzet.run.id)[0]
        with pytest.raises(DoorbelastingFout, match="reden"):
            storno_doorbelasting_boeking(
                administratie_id=opzet.administratie_id,
                boeking_id=boeking.id,
                actor_id=beheerder_id,
                reden="kort",
                bron_client=bron,
                doel_client=doel,
            )
        # niets teruggedraaid
        assert bron.verkoop_correcties == []
        assert doel.spiegel_correcties == []


class TestHerstartNaStornoEnUiVerwijdering:
    """Regressie kliktest 2 TEST-ONB-KLIKTEST-01 (2026-08-16): storno beide kanten → Peter
    verwijdert de bron-verkoop-concepten handmatig in de RLZ-UI (spiegel-concepten blijven
    staan mét hun bijlage) → nieuwe run op hetzelfde document. De bug: de her-upload op het
    deterministische (in cyclus 1 verbruikte) upload-GUID gaf 404 _NotFound, waardoor élke
    doelentiteit op "mislukt" strandde en de bron-verkopen als concept zónder PDF
    achterbleven. De fix (app/rlz/bijlage.py): aanwezigheids-check via de Uploads-leesroute
    + deterministisch cyclus-GUID bij een verbruikt basis-GUID."""

    def test_herstart_boekt_beide_kanten_met_bijlage_en_zonder_duplicaat(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID
    ) -> None:
        from app.documenten.rlz_ids import rlz_doorbelasting_upload_id
        from app.rlz.bijlage import cyclus_upload_id

        opzet = onboarded_opzet
        bron, doel = FakeDoorbelastingClient(), FakeDoorbelastingClient()
        verkoop_id = rlz_doorbelasting_verkoop_id(opzet.document_id, opzet.mapping.doel_customer_guid)
        spiegel_id = rlz_doorbelasting_spiegel_id(opzet.document_id, opzet.mapping.doel_customer_guid)

        # cyclus 1: boeken + storno beide kanten (concepten blijven staan, bijlagen ook)
        _boek(opzet, beheerder_id, bron=bron, doel=doel)
        boeking = haal_boekingen(opzet.administratie_id, opzet.run.id)[0]
        storno_doorbelasting_boeking(
            administratie_id=opzet.administratie_id,
            boeking_id=boeking.id,
            actor_id=beheerder_id,
            reden="Kliktest: cyclus 1 terugdraaien",
            bron_client=bron,
            doel_client=doel,
        )
        # Peter verwijdert het bron-verkoop-concept in de RLZ-UI; de spiegel blijft concept
        bron.verwijder_document_in_rlz_ui("SalesInvoices", verkoop_id)
        assert bron.get(f"SalesInvoices/{verkoop_id}/Uploads")["value"] == []
        # spiegel: factuur-PDF (blok A) + originele bon = twee bijlagen
        assert len(doel.get(f"PurchaseInvoices/{spiegel_id}/Uploads")["value"]) == 2

        # cyclus 2: nieuwe run (de oude is gestorneerd), zelfde verdeling
        run2 = start_run_met_verdeling(
            administratie_id=opzet.administratie_id,
            document_id=opzet.document_id,
            actor_id=beheerder_id,
            regels=[
                VerdeelRegelInvoerData(
                    bron_regel_id=opzet.regel_ids[0],
                    mapping_id=opzet.mapping.id,
                    percentage=D("100"),
                    doel_kosten_ledger_id=DOEL_KOSTEN_LEDGER_ID,
                )
            ],
        )
        assert run2.id != opzet.run.id
        opzet2 = DoorbelastingOpzet(
            administratie_id=opzet.administratie_id,
            doel_administratie_id=opzet.doel_administratie_id,
            document_id=opzet.document_id,
            regel_ids=opzet.regel_ids,
            mapping=opzet.mapping,
            run=run2,
        )
        resultaat = _boek(opzet2, beheerder_id, bron=bron, doel=doel)
        assert resultaat == {str(opzet.mapping.id): DoorbelastingBoekingStatus.GEBOEKT.value}

        # bron-verkoop opnieuw aangemaakt, GEBOEKT en mét de bon als bijlage — op het
        # deterministische cyclus-1-GUID (het basis-GUID is verbruikt door de verwijdering);
        # daarnaast de factuur-PDF (blok A), óók op háár cyclus-1-GUID
        from app.documenten.rlz_ids import rlz_doorbelasting_factuur_upload_id

        assert bron.sales_invoices[str(verkoop_id)]["Status"] == 2
        verkoop_uploads = bron.get(f"SalesInvoices/{verkoop_id}/Uploads")["value"]
        basis = rlz_doorbelasting_upload_id(opzet.document_id, opzet.mapping.doel_customer_guid, kant="verkoop")
        factuur_basis = rlz_doorbelasting_factuur_upload_id(
            opzet.document_id, opzet.mapping.doel_customer_guid, kant="verkoop"
        )
        assert [u["upload_id"] for u in verkoop_uploads] == [
            str(cyclus_upload_id(basis, 1)),
            str(cyclus_upload_id(factuur_basis, 1)),
        ]

        # spiegel her-geboekt zonder dubbele bon (aanwezigheids-check op bestandsnaam); de
        # herboekte verkoop heeft een NIEUW nummer (RLZ-2) → nieuwe factuur-PDF erbij; de
        # cyclus-1-factuur (RLZ-1, gestorneerd) blijft staan — de app verwijdert nooit in RLZ
        assert doel.purchase_invoices[str(spiegel_id)]["Status"] == 2
        spiegel_namen = [u["FileName"] for u in doel.get(f"PurchaseInvoices/{spiegel_id}/Uploads")["value"]]
        assert spiegel_namen[1] == "factuur-doorbelasting.pdf"
        assert spiegel_namen[0].startswith("Factuur RLZ-1 ") and spiegel_namen[2].startswith("Factuur RLZ-2 ")

        # run 2 GEBOEKT zonder achtergebleven fout; geen halve staat
        run_na = haal_run(opzet.administratie_id, run2.id)
        assert run_na.status == DoorbelastingRunStatus.GEBOEKT.value
        assert run_na.laatste_fout is None
        statussen = sorted(b.status for b in haal_boekingen(opzet.administratie_id, run2.id))
        assert statussen == [DoorbelastingBoekingStatus.GEBOEKT.value]


# Dekt élke datum — de motor boekt op de systeemdatum, dus dit simuleert "de boekperiode valt
# in een ingediende btw-aangifte" zonder aan de motor-datum te hoeven draaien.
_AANGIFTE_ALLES_INGEDIEND = {"Status": 2, "StartDate": "2000-01-01T00:00:00", "Date": "2099-12-31T00:00:00"}
_AANGIFTE_CONCEPT = {"Status": 1, "StartDate": "2000-01-01T00:00:00", "Date": "2099-12-31T00:00:00"}


class TestStornoAangiftePoort:
    """Storno-blokkade ná ingediende btw-aangifte (besluit Peter 2026-08-15): alles-of-niets
    vóór de eerste RLZ-write, fail-closed, en de leesroute voor de UI-knop."""

    def _geboekte_boeking(
        self,
        opzet: DoorbelastingOpzet,
        beheerder_id: uuid.UUID,
        *,
        bron: FakeDoorbelastingClient,
        doel: FakeDoorbelastingClient,
    ):
        _boek(opzet, beheerder_id, bron=bron, doel=doel)
        return haal_boekingen(opzet.administratie_id, opzet.run.id)[0]

    def test_bron_kant_in_ingediende_periode_blokkeert_zonder_writes(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID
    ) -> None:
        opzet = onboarded_opzet
        bron = FakeDoorbelastingClient(aangiften=[_AANGIFTE_ALLES_INGEDIEND])
        doel = FakeDoorbelastingClient()
        boeking = self._geboekte_boeking(opzet, beheerder_id, bron=bron, doel=doel)

        with pytest.raises(StornoGeblokkeerdDoorAangifte) as excinfo:
            storno_doorbelasting_boeking(
                administratie_id=opzet.administratie_id,
                boeking_id=boeking.id,
                actor_id=beheerder_id,
                reden="Verkeerde verdeelsleutel gebruikt",
                bron_client=bron,
                doel_client=doel,
            )
        # alles-of-niets: aan géén van beide kanten is iets teruggedraaid, boeking blijft staan
        assert bron.verkoop_correcties == []
        assert doel.spiegel_correcties == []
        boeking_na = haal_boekingen(opzet.administratie_id, opzet.run.id)[0]
        assert boeking_na.status == DoorbelastingBoekingStatus.GEBOEKT.value
        assert any(not t.toegestaan and "verkoopfactuur" in t.kant for t in excinfo.value.kanten)

    def test_doel_kant_in_ingediende_periode_blokkeert_ook_de_bron(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID
    ) -> None:
        opzet = onboarded_opzet
        bron = FakeDoorbelastingClient(aangiften=[_AANGIFTE_CONCEPT])
        doel = FakeDoorbelastingClient(aangiften=[_AANGIFTE_ALLES_INGEDIEND])
        boeking = self._geboekte_boeking(opzet, beheerder_id, bron=bron, doel=doel)

        with pytest.raises(StornoGeblokkeerdDoorAangifte) as excinfo:
            storno_doorbelasting_boeking(
                administratie_id=opzet.administratie_id,
                boeking_id=boeking.id,
                actor_id=beheerder_id,
                reden="Verkeerde verdeelsleutel gebruikt",
                bron_client=bron,
                doel_client=doel,
            )
        assert bron.verkoop_correcties == []
        assert doel.spiegel_correcties == []
        geblokkeerd = [t for t in excinfo.value.kanten if not t.toegestaan]
        assert len(geblokkeerd) == 1
        assert "spiegel-inkoopfactuur" in geblokkeerd[0].kant

    def test_onleesbare_aangifte_status_is_fail_closed(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID
    ) -> None:
        opzet = onboarded_opzet
        bron = FakeDoorbelastingClient(faal_op="aangiften")
        doel = FakeDoorbelastingClient()
        boeking = self._geboekte_boeking(opzet, beheerder_id, bron=bron, doel=doel)
        with pytest.raises(StornoGeblokkeerdDoorAangifte):
            storno_doorbelasting_boeking(
                administratie_id=opzet.administratie_id,
                boeking_id=boeking.id,
                actor_id=beheerder_id,
                reden="Verkeerde verdeelsleutel gebruikt",
                bron_client=bron,
                doel_client=doel,
            )
        assert bron.verkoop_correcties == []
        assert doel.spiegel_correcties == []

    def test_concept_aangifte_blokkeert_niet(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID
    ) -> None:
        opzet = onboarded_opzet
        bron = FakeDoorbelastingClient(aangiften=[_AANGIFTE_CONCEPT])
        doel = FakeDoorbelastingClient(aangiften=[_AANGIFTE_CONCEPT])
        boeking = self._geboekte_boeking(opzet, beheerder_id, bron=bron, doel=doel)
        gestorneerd = storno_doorbelasting_boeking(
            administratie_id=opzet.administratie_id,
            boeking_id=boeking.id,
            actor_id=beheerder_id,
            reden="Verkeerde verdeelsleutel gebruikt",
            bron_client=bron,
            doel_client=doel,
        )
        assert gestorneerd.status == DoorbelastingBoekingStatus.GESTORNEERD.value

    def test_storno_toets_voor_document_rapporteert_per_boeking_en_kant(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID
    ) -> None:
        opzet = onboarded_opzet
        bron = FakeDoorbelastingClient(aangiften=[_AANGIFTE_CONCEPT])
        doel = FakeDoorbelastingClient(aangiften=[_AANGIFTE_ALLES_INGEDIEND])
        boeking = self._geboekte_boeking(opzet, beheerder_id, bron=bron, doel=doel)

        per_boeking = storno_toets_voor_document(
            administratie_id=opzet.administratie_id,
            document_id=opzet.document_id,
            bron_client=bron,
            doel_client_factory=lambda _aid: doel,
        )
        assert set(per_boeking) == {boeking.id}
        toetsen = per_boeking[boeking.id]
        assert [t.toegestaan for t in toetsen] == [True, False]
        assert "spiegel-inkoopfactuur" in toetsen[1].kant
        assert "ingediende btw-aangifte" in (toetsen[1].reden or "")

    def test_storno_toets_zonder_boekingen_is_leeg_en_raakt_rlz_niet(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID
    ) -> None:
        opzet = onboarded_opzet
        bron = FakeDoorbelastingClient()
        per_boeking = storno_toets_voor_document(
            administratie_id=opzet.administratie_id,
            document_id=opzet.document_id,
            bron_client=bron,
            doel_client_factory=lambda _aid: FakeDoorbelastingClient(),
        )
        assert per_boeking == {}
        assert bron.probes == 0


class TestSpiegelAlsnog:
    def _maak_spiegel_open_boeking(
        self, opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID
    ) -> tuple[uuid.UUID, str | None]:
        bron = FakeDoorbelastingClient()
        _boek(opzet, beheerder_id, bron=bron, doel=None)
        boeking = haal_boekingen(opzet.administratie_id, opzet.run.id)[0]
        return boeking.id, boeking.verkoop_referentie

    def test_na_onboarding_boekt_de_spiegel_alsnog(
        self,
        spiegel_open_opzet: DoorbelastingOpzet,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        opzet = spiegel_open_opzet
        boeking_id, verkoop_referentie = self._maak_spiegel_open_boeking(opzet, beheerder_id)

        doel_administratie = maak_administratie(admin_engine, "Veldhoven Recreatie B.V.")
        doorbelasting_service.wijzig_mapping(
            administratie_id=opzet.administratie_id,
            mapping_id=opzet.mapping.id,
            actor_id=beheerder_id,
            doel_administratie_id=doel_administratie,
            provisie_kosten_ledger_id=PROVISIE_KOSTEN_LEDGER_ID,
        )
        # de verdeling is bevroren (run geboekt) — de doel-GB wordt dus rechtstreeks gezet,
        # precies wat de spiegel-alsnog-UI via haar eigen pad zou doen
        with scoped_session(opzet.administratie_id, actor_id=beheerder_id) as session:
            for regel in session.scalars(select(DoorbelastingRegel).where(DoorbelastingRegel.run_id == opzet.run.id)):
                regel.doel_kosten_ledger_id = DOEL_KOSTEN_LEDGER_ID

        doel = FakeDoorbelastingClient()
        boeking = boek_spiegel_alsnog(
            administratie_id=opzet.administratie_id,
            boeking_id=boeking_id,
            actor_id=beheerder_id,
            doel_client=doel,
        )
        assert boeking.status == DoorbelastingBoekingStatus.GEBOEKT.value
        assert boeking.doel_administratie_id == doel_administratie
        assert boeking.spiegel_geboekt_op is not None

        spiegel_id = rlz_doorbelasting_spiegel_id(opzet.document_id, opzet.mapping.doel_customer_guid)
        spiegel = doel.purchase_invoices[str(spiegel_id)]
        assert spiegel["Status"] == 2
        assert spiegel["Reference"] == verkoop_referentie
        # geen open taak meer
        assert doorbelasting_service.open_spiegel_taken(administratie_id=opzet.administratie_id) == []

    def test_zonder_provisie_gb_weigert(
        self,
        spiegel_open_opzet: DoorbelastingOpzet,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        opzet = spiegel_open_opzet
        boeking_id, _ = self._maak_spiegel_open_boeking(opzet, beheerder_id)
        doel_administratie = maak_administratie(admin_engine, "Veldhoven Recreatie B.V.")
        # wél gekoppeld, maar zonder provisie-GB op de mapping
        doorbelasting_service.wijzig_mapping(
            administratie_id=opzet.administratie_id,
            mapping_id=opzet.mapping.id,
            actor_id=beheerder_id,
            doel_administratie_id=doel_administratie,
        )
        with scoped_session(opzet.administratie_id, actor_id=beheerder_id) as session:
            for regel in session.scalars(select(DoorbelastingRegel).where(DoorbelastingRegel.run_id == opzet.run.id)):
                regel.doel_kosten_ledger_id = DOEL_KOSTEN_LEDGER_ID

        doel = FakeDoorbelastingClient()
        with pytest.raises(DoorbelastingFout, match="provisie-GB"):
            boek_spiegel_alsnog(
                administratie_id=opzet.administratie_id,
                boeking_id=boeking_id,
                actor_id=beheerder_id,
                doel_client=doel,
            )
        assert doel.purchase_invoices == {}
