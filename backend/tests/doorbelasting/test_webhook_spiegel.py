"""Spiegel-webhook (besluit Peter 2026-08-14, sluit Platform/OPEN_ITEMS-gat (b) van de
doorbelasting-gaten-scan): een spiegel-inkoopfactuur in een vastgoed-doel-administratie krijgt
óók het `factuur_geboekt`-event — zelfde outbox/idempotentie-patroon als de document-pipeline,
leverancier = de bron-administratie (Kempen Facilities). Motor-kant (outbox-rij in dezelfde
transactie als de boeking, alleen bij is_vastgoed) én aflevering end-to-end tegen de
mock-ontvanger van vastgoed (HMAC + replay-venster + nonce-dedup), inclusief het bewijs dat
de rij onder de dóél-administratie afgeleverd wordt en nooit dubbel onder de bron."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select, text

from app.beheer import service as beheer_service
from app.config import settings
from app.db.models import Grootboekrekening
from app.db.session import scoped_session
from app.documenten.models import WebhookStatus, WebhookUitgaand
from app.documenten.rlz_ids import rlz_doorbelasting_spiegel_id
from app.documenten.webhook_afleveraar import verwerk_openstaande_webhooks
from app.doorbelasting import service as doorbelasting_service
from app.doorbelasting.boeken import boek_doorbelasting_run, boek_spiegel_alsnog, storno_doorbelasting_boeking
from app.doorbelasting.models import DoorbelastingRegel
from tests.documenten.test_webhook_afleveraar import DOEL_URL, GEDEELD_SECRET, MockOntvanger
from tests.doorbelasting.conftest import (
    DOEL_KOSTEN_LEDGER_ID,
    PROVISIE_KOSTEN_LEDGER_ID,
    DoorbelastingOpzet,
    FakeDoorbelastingClient,
    haal_boekingen,
    maak_administratie,
)

D = Decimal


def _zet_vastgoed(admin_engine: Engine, administratie_id: uuid.UUID) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.administratie SET is_vastgoed = true WHERE id = :id"),
            {"id": administratie_id},
        )


def _vul_doel_ledger_cache(doel_administratie_id: uuid.UUID) -> None:
    """GB-codes in de cache van de dóél-administratie — de payload-regels lezen dáár (RLS)."""
    with scoped_session(doel_administratie_id) as session:
        session.add(
            Grootboekrekening(
                ledger_id=DOEL_KOSTEN_LEDGER_ID,
                administratie_id=doel_administratie_id,
                code="4110",
                naam="Huisvestingskosten",
                soort=2,
                is_totaalrekening=False,
            )
        )
        session.add(
            Grootboekrekening(
                ledger_id=PROVISIE_KOSTEN_LEDGER_ID,
                administratie_id=doel_administratie_id,
                code="4808",
                naam="Provisie doorbelasting",
                soort=2,
                is_totaalrekening=False,
            )
        )


def _outbox_rijen(scope_administratie_id: uuid.UUID) -> list[WebhookUitgaand]:
    with scoped_session(scope_administratie_id) as session:
        rijen = list(session.scalars(select(WebhookUitgaand).order_by(WebhookUitgaand.aangemaakt_op)))
        session.expunge_all()
        return rijen


def _boek(opzet: DoorbelastingOpzet, actor_id: uuid.UUID, *, doel: FakeDoorbelastingClient | None) -> None:
    boek_doorbelasting_run(
        administratie_id=opzet.administratie_id,
        run_id=opzet.run.id,
        actor_id=actor_id,
        bron_client=FakeDoorbelastingClient(),
        doel_client_factory=lambda _aid: doel,
    )


class TestSpiegelWebhookOutbox:
    def test_vastgoed_doel_krijgt_factuur_geboekt_rij_met_doel_administratie(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        opzet = onboarded_opzet
        _zet_vastgoed(admin_engine, opzet.doel_administratie_id)
        _vul_doel_ledger_cache(opzet.doel_administratie_id)
        _boek(opzet, beheerder_id, doel=FakeDoorbelastingClient())

        rijen = _outbox_rijen(opzet.doel_administratie_id)
        assert len(rijen) == 1
        rij = rijen[0]
        assert rij.event == "factuur_geboekt"
        assert rij.administratie_id == opzet.doel_administratie_id
        assert rij.document_id == opzet.document_id  # bron-document blijft de FK/traceerbaarheid
        assert rij.status == WebhookStatus.OPENSTAAND.value

        boeking = haal_boekingen(opzet.administratie_id, opzet.run.id)[0]
        data = rij.payload["data"]
        assert rij.payload["event"] == "factuur_geboekt"
        assert data["administratie_id"] == str(opzet.doel_administratie_id)
        assert data["rlz_admin_id"] == f"rlz-{opzet.doel_administratie_id}"
        spiegel_id = rlz_doorbelasting_spiegel_id(opzet.document_id, opzet.mapping.doel_customer_guid)
        assert data["rlz_document_id"] == str(spiegel_id)
        assert data["rlz_boekstuknummer"] == "RLZ-30-00000012"  # uit de fake, gevangen bij het boeken
        # leverancier = de bron-administratie; referentie = de spiegel-Reference (verkoopnummer)
        assert data["leverancier"]["naam"] == "Scope-test"
        assert data["referentie"] == boeking.verkoop_referentie
        # regels: kostenregel + provisieregel, GB-codes uit de dóél-cache, exacte decimalen
        assert [(r["grootboek_code"], r["netto_bedrag"], r["btw_bedrag"]) for r in data["regels"]] == [
            ("4110", "100.00", "21.00"),
            ("4808", "5.00", "1.05"),
        ]

    def test_niet_vastgoed_doel_krijgt_geen_rij(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID
    ) -> None:
        opzet = onboarded_opzet
        _boek(opzet, beheerder_id, doel=FakeDoorbelastingClient())
        assert _outbox_rijen(opzet.doel_administratie_id) == []
        assert _outbox_rijen(opzet.administratie_id) == []

    def test_spiegel_open_geen_rij_pas_bij_alsnog_boeken(
        self, spiegel_open_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        opzet = spiegel_open_opzet
        _boek(opzet, beheerder_id, doel=None)
        assert _outbox_rijen(opzet.administratie_id) == []
        boeking_id = haal_boekingen(opzet.administratie_id, opzet.run.id)[0].id

        doel_administratie = maak_administratie(admin_engine, "Veldhoven Recreatie B.V.")
        _zet_vastgoed(admin_engine, doel_administratie)
        _vul_doel_ledger_cache(doel_administratie)
        doorbelasting_service.wijzig_mapping(
            administratie_id=opzet.administratie_id,
            mapping_id=opzet.mapping.id,
            actor_id=beheerder_id,
            doel_administratie_id=doel_administratie,
            provisie_kosten_ledger_id=PROVISIE_KOSTEN_LEDGER_ID,
        )
        with scoped_session(opzet.administratie_id, actor_id=beheerder_id) as session:
            for regel in session.scalars(
                select(DoorbelastingRegel).where(DoorbelastingRegel.run_id == opzet.run.id)
            ):
                regel.doel_kosten_ledger_id = DOEL_KOSTEN_LEDGER_ID

        boek_spiegel_alsnog(
            administratie_id=opzet.administratie_id,
            boeking_id=boeking_id,
            actor_id=beheerder_id,
            doel_client=FakeDoorbelastingClient(),
        )
        rijen = _outbox_rijen(doel_administratie)
        assert len(rijen) == 1
        assert rijen[0].administratie_id == doel_administratie
        assert rijen[0].payload["data"]["regels"][0]["grootboek_code"] == "4110"

    def test_half_geboekt_geen_rij(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        opzet = onboarded_opzet
        _zet_vastgoed(admin_engine, opzet.doel_administratie_id)
        _boek(opzet, beheerder_id, doel=FakeDoorbelastingClient(faal_op={"spiegel_boek", "storno_verkoop"}))
        assert _outbox_rijen(opzet.doel_administratie_id) == []


class TestSpiegelStornoEvent:
    """Module-storno = direct `factuur_gestorneerd`-event (koppelcontract §3 v1.14, randvraag
    c): de spiegel-kant meldde eerder geboekt bij vastgoed, dus de storno meldt zich óók —
    zelfde boekstand-reeks, bron `module_storno`, reden verplicht meegeleverd."""

    def _storneer(self, opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID) -> None:
        boeking = haal_boekingen(opzet.administratie_id, opzet.run.id)[0]
        storno_doorbelasting_boeking(
            administratie_id=opzet.administratie_id,
            boeking_id=boeking.id,
            actor_id=beheerder_id,
            reden="Verkeerde verdeelsleutel gebruikt",
            bron_client=FakeDoorbelastingClient(),
            doel_client=FakeDoorbelastingClient(),
        )

    def test_storno_van_vastgoed_spiegel_vuurt_gestorneerd_in_zelfde_reeks(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        opzet = onboarded_opzet
        _zet_vastgoed(admin_engine, opzet.doel_administratie_id)
        _vul_doel_ledger_cache(opzet.doel_administratie_id)
        _boek(opzet, beheerder_id, doel=FakeDoorbelastingClient())
        self._storneer(opzet, beheerder_id)

        rijen = _outbox_rijen(opzet.doel_administratie_id)
        assert [r.event for r in rijen] == ["factuur_geboekt", "factuur_gestorneerd"]
        geboekt, gestorneerd = rijen[0].payload["data"], rijen[1].payload["data"]
        assert rijen[1].administratie_id == opzet.doel_administratie_id
        assert rijen[1].document_id == opzet.document_id
        assert gestorneerd["rlz_document_id"] == geboekt["rlz_document_id"]
        assert (geboekt["volgnummer"], gestorneerd["volgnummer"]) == (1, 2)
        assert gestorneerd["bron"] == "module_storno"
        assert gestorneerd["reden"] == "Verkeerde verdeelsleutel gebruikt"
        # kop-velden identiek aan wat de ontvanger bij geboekt kreeg
        assert gestorneerd["rlz_boekstuknummer"] == geboekt["rlz_boekstuknummer"]
        assert gestorneerd["referentie"] == geboekt["referentie"]
        assert gestorneerd["rlz_admin_id"] == geboekt["rlz_admin_id"]

    def test_storno_zonder_vastgoed_doel_vuurt_niets(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID
    ) -> None:
        opzet = onboarded_opzet
        _boek(opzet, beheerder_id, doel=FakeDoorbelastingClient())
        self._storneer(opzet, beheerder_id)
        assert _outbox_rijen(opzet.doel_administratie_id) == []
        assert _outbox_rijen(opzet.administratie_id) == []

    def test_herboeking_na_storno_krijgt_volgnummer_3(
        self, onboarded_opzet: DoorbelastingOpzet, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        """Randvraag (b) bewezen op het bestaande pad: een nieuwe run op hetzelfde bron-document
        hergebruikt het deterministische spiegel-GUID — hetzelfde rlz_document_id komt opnieuw
        langs, mét hoger volgnummer, zodat de ontvanger de herboeking niet als duplicaat wegdedupt."""
        opzet = onboarded_opzet
        _zet_vastgoed(admin_engine, opzet.doel_administratie_id)
        _vul_doel_ledger_cache(opzet.doel_administratie_id)
        _boek(opzet, beheerder_id, doel=FakeDoorbelastingClient())
        self._storneer(opzet, beheerder_id)

        from app.doorbelasting.service import VerdeelRegelInvoerData
        from tests.doorbelasting.conftest import DOEL_KOSTEN_LEDGER_ID, start_run_met_verdeling

        nieuwe_run = start_run_met_verdeling(
            administratie_id=opzet.administratie_id,
            document_id=opzet.document_id,
            actor_id=beheerder_id,
            regels=[
                VerdeelRegelInvoerData(
                    bron_regel_id=opzet.regel_ids[0],
                    mapping_id=opzet.mapping.id,
                    percentage=Decimal("100"),
                    doel_kosten_ledger_id=DOEL_KOSTEN_LEDGER_ID,
                )
            ],
        )
        boek_doorbelasting_run(
            administratie_id=opzet.administratie_id,
            run_id=nieuwe_run.id,
            actor_id=beheerder_id,
            bron_client=FakeDoorbelastingClient(),
            doel_client_factory=lambda _aid: FakeDoorbelastingClient(),
        )
        rijen = _outbox_rijen(opzet.doel_administratie_id)
        assert [(r.event, r.payload["data"]["volgnummer"]) for r in rijen] == [
            ("factuur_geboekt", 1),
            ("factuur_gestorneerd", 2),
            ("factuur_geboekt", 3),
        ]
        # zelfde rlz_document_id door de hele reeks (deterministisch spiegel-GUID)
        assert len({r.payload["data"]["rlz_document_id"] for r in rijen}) == 1


class TestSpiegelWebhookAflevering:
    @pytest.fixture
    def aflevering_aan(self, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> None:
        beheer_service.zet_webhook_aflevering_ingeschakeld(actor_id=beheerder_id, ingeschakeld=True)
        monkeypatch.setattr(settings, "webhook_doel_url", DOEL_URL)
        monkeypatch.setattr(settings, "webhook_hmac_secret", GEDEELD_SECRET)
        yield
        beheer_service.zet_webhook_aflevering_ingeschakeld(actor_id=beheerder_id, ingeschakeld=False)

    def test_aflevering_onder_de_doel_administratie_en_nooit_dubbel(
        self,
        onboarded_opzet: DoorbelastingOpzet,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        aflevering_aan: None,
    ) -> None:
        opzet = onboarded_opzet
        _zet_vastgoed(admin_engine, opzet.doel_administratie_id)
        _vul_doel_ledger_cache(opzet.doel_administratie_id)
        _boek(opzet, beheerder_id, doel=FakeDoorbelastingClient())

        ontvanger = MockOntvanger()
        rapport = verwerk_openstaande_webhooks(transport=ontvanger.transport)
        # precies één aflevering: onder de doel-administratie (de bron — geen vastgoed — mag
        # 'm niet oppakken, en de coalesce sluit dubbele oppak uit)
        assert rapport.afgeleverd == 1
        assert rapport.geweigerd_geen_vastgoed == 0
        assert rapport.fouten == []
        envelope = ontvanger.ontvangen[0]
        assert envelope["event"] == "factuur_geboekt"
        assert envelope["data"]["administratie_id"] == str(opzet.doel_administratie_id)
        assert envelope["data"]["leverancier"]["naam"] == "Scope-test"

        rij = _outbox_rijen(opzet.doel_administratie_id)[0]
        assert rij.status == WebhookStatus.AFGELEVERD.value

        # tweede run: niets meer openstaand — geen herlevering
        rapport2 = verwerk_openstaande_webhooks(transport=ontvanger.transport)
        assert rapport2.afgeleverd == 0
        assert ontvanger.aantal_requests == 1
