"""Tegenboek-pad (mockup tegenboek-mockup.html, akkoord Peter 22-08; STAP-0 "Tegenboek-pad"
in api-verkenning): de leesroute (geblokkeerde storno → knop, voorbeeld, betaalstatus), de
twee smaken (volledig = chip TEGENGEBOEKT zonder statuswijziging; vervang = terug naar
te_controleren + boek_cyclus +1 met eigen herboeking-GUID en duplicaat-keten-uitzondering),
de poorten (alleen bij geblokkeerde storno, verplichte reden, nooit dubbel, harde checks
onverkort), idempotente RLZ-retry en het webhook-gedrag (factuur_geboekt met negatieve
regels — creditnota-norm §3a; bewust géén factuur_gestorneerd)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.documenten import boeken, boekvoorstel, service, tegenboeken
from app.documenten.models import DocumentStatus
from app.documenten.rlz_ids import rlz_herboeking_id, rlz_tegenboeking_id
from app.documenten.storage import LokaleBestandsopslag
from app.zoeken import service as zoeken_service
from tests.documenten.fake_rlz_client import FakeBoekClient

# Ingediende btw-aangifte (Status 2) die de factuurdatum van het testdocument (2026-07-01)
# dekt — precies het scenario waarin storno geblokkeerd is en tegenboeken de route wordt.
AANGIFTE_Q3_INGEDIEND = {"Status": 2, "StartDate": "2026-07-01T00:00:00", "Date": "2026-09-30T00:00:00"}
REDEN = "factuur dubbel geboekt — origineel zat al in periode april"


def _regel(**overrides) -> boekvoorstel.BoekvoorstelRegelData:
    basis = dict(
        ledger_id=uuid.uuid4(),
        taxrate_id=uuid.uuid4(),
        project_id=None,
        netto_bedrag=Decimal("100.00"),
        btw_bedrag=Decimal("21.00"),
        omschrijving="Testregel",
    )
    basis.update(overrides)
    return boekvoorstel.BoekvoorstelRegelData(**basis)


@pytest.fixture
def geboekt_document(
    gescoopte_gebruiker: uuid.UUID,
    administratie_id: uuid.UUID,
    beheerder_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[uuid.UUID, FakeBoekClient]:
    """Een via de gewone motor GEBOEKT document + de fake-client (mét ingediende aangifte)
    die daarna ook het tegenboek-pad bedient."""
    beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="factuur.pdf",
        inhoud=b"%PDF-1.4 testfactuur",
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    )
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=gescoopte_gebruiker,
        vendor_id=uuid.uuid4(),
        referentie="F-2026-0841",
        factuurdatum=date(2026, 7, 1),
        totaalbedrag=Decimal("121.00"),
        regels=[_regel()],
    )
    fake_client = FakeBoekClient(aangiften=[AANGIFTE_Q3_INGEDIEND])
    monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)
    monkeypatch.setattr(tegenboeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)
    boeken.boek_document(
        administratie_id=administratie_id, document_id=resultaat.document_id, actor_id=gescoopte_gebruiker
    )
    return resultaat.document_id, fake_client


def _document_status(admin_engine: Engine, document_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}
        ).scalar_one()


class TestToets:
    def test_geblokkeerde_storno_met_voorbeeld_en_zonder_bestaande_tegenboeking(
        self, geboekt_document, administratie_id: uuid.UUID
    ) -> None:
        document_id, _ = geboekt_document
        toets = tegenboeken.toets(administratie_id=administratie_id, document_id=document_id)
        assert toets.storno_geblokkeerd is True
        assert toets.tegenboeking is None
        assert toets.tegenboek_referentie == "TB F-2026-0841"
        [regel] = toets.voorbeeld
        assert (regel.netto_bedrag, regel.btw_bedrag) == (Decimal("-100.00"), Decimal("-21.00"))
        assert toets.totaal_netto == Decimal("-100.00")
        assert "TEGENBOEKING F-2026-0841" in regel.omschrijving

    def test_vrije_storno_betekent_geen_tegenboek_knop(
        self, geboekt_document, administratie_id: uuid.UUID
    ) -> None:
        document_id, fake_client = geboekt_document
        fake_client.aangiften = []  # geen ingediende aangifte → storno vrij
        toets = tegenboeken.toets(administratie_id=administratie_id, document_id=document_id)
        assert toets.storno_geblokkeerd is False

    def test_betaalstatus_uit_rlz(self, geboekt_document, administratie_id: uuid.UUID) -> None:
        document_id, fake_client = geboekt_document
        origineel = fake_client._invoices[str(rlz_herboeking_id(document_id, 0))]
        origineel.update({"BasePaidAmount": 60.5, "BaseRemainingAmount": 60.5})
        toets = tegenboeken.toets(administratie_id=administratie_id, document_id=document_id)
        assert toets.betaalstatus is not None
        assert toets.betaalstatus.betaald_bedrag == Decimal("60.5")
        assert toets.betaalstatus.open_bedrag == Decimal("60.5")
        assert toets.betaalstatus.volledig_afgeletterd is False


class TestVolledigTegenboeken:
    def test_boekt_negatieve_spiegel_en_markeert_tegengeboekt(
        self, geboekt_document, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        document_id, fake_client = geboekt_document
        resultaat = tegenboeken.voer_tegenboeking_uit(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            soort="volledig",
            reden=REDEN,
        )
        # RLZ: een NIEUWE PurchaseInvoice (eigen GUID) met gespiegelde negatieve regels op
        # dezelfde Entity, geboekt (actie 17), mét bijlage.
        assert resultaat.rlz_tegenboeking_id == rlz_tegenboeking_id(document_id, 0)
        assert resultaat.rlz_tegenboeking_id != rlz_herboeking_id(document_id, 0)
        tegen_put = fake_client.puts[-1]
        assert tegen_put["id"] == resultaat.rlz_tegenboeking_id
        [line] = tegen_put["lines"]
        assert (line["NetAmount"], line["TaxAmount"]) == (-100.0, -21.0)
        assert tegen_put["reference"] == "TB F-2026-0841"
        assert resultaat.rlz_tegenboeking_id in fake_client.geboekte_acties
        assert any(u["entity_id"] == resultaat.rlz_tegenboeking_id for u in fake_client.uploads)
        # Lokaal: status blijft geboekt, chip TEGENGEBOEKT via de tegenboeking-rij +
        # tijdlijn-regel zónder statusovergang, audit.
        assert resultaat.status == DocumentStatus.GEBOEKT
        assert _document_status(admin_engine, document_id) == "geboekt"
        with admin_engine.connect() as conn:
            rij = conn.execute(
                text("SELECT soort, reden, rlz_boekstuknummer FROM boekhouding.tegenboeking WHERE document_id = :id"),
                {"id": document_id},
            ).one()
            assert (rij.soort, rij.reden) == ("volledig", REDEN)
            assert rij.rlz_boekstuknummer is not None
            tijdlijn = conn.execute(
                text(
                    "SELECT van_status, naar_status, detail FROM boekhouding.document_gebeurtenis "
                    "WHERE document_id = :id AND detail ? 'tegenboeking'"
                ),
                {"id": document_id},
            ).one()
            assert tijdlijn.van_status == tijdlijn.naar_status == "geboekt"
            assert tijdlijn.detail["tegenboeking"]["reden"] == REDEN
            audit = conn.execute(
                text(
                    "SELECT count(*) FROM platform.audit_event "
                    "WHERE tabel = 'tegenboeking' AND actie = 'tegengeboekt_in_rlz'"
                )
            ).scalar_one()
            assert audit == 1
        # Archief: de rij draagt de tegengeboekt-vlag (chip TEGENGEBOEKT).
        [archief_rij] = [
            d for d in zoeken_service.archief(administratie_id=administratie_id) if d.document_id == document_id
        ]
        assert archief_rij.tegengeboekt is True
        # De toets toont nu de kruisverwijzing.
        toets = tegenboeken.toets(administratie_id=administratie_id, document_id=document_id)
        assert toets.tegenboeking is not None
        assert toets.tegenboeking.rlz_boekstuknummer == rij.rlz_boekstuknummer

    def test_dubbele_tegenboeking_weigert(
        self, geboekt_document, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        document_id, _ = geboekt_document
        tegenboeken.voer_tegenboeking_uit(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker,
            soort="volledig", reden=REDEN,
        )
        with pytest.raises(tegenboeken.TegenboekingBestaatAl):
            tegenboeken.voer_tegenboeking_uit(
                administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker,
                soort="volledig", reden=REDEN,
            )


class TestVervang:
    def test_terug_naar_werkvoorraad_en_herboeking_met_eigen_guid(
        self, geboekt_document, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        document_id, fake_client = geboekt_document
        resultaat = tegenboeken.voer_tegenboeking_uit(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker,
            soort="vervang", reden=REDEN,
        )
        assert resultaat.status == DocumentStatus.TE_CONTROLEREN
        assert _document_status(admin_engine, document_id) == "te_controleren"
        with admin_engine.connect() as conn:
            cyclus = conn.execute(
                text("SELECT boek_cyclus FROM boekhouding.boekvoorstel WHERE document_id = :id"),
                {"id": document_id},
            ).scalar_one()
        assert cyclus == 1
        # De herboeking: zelfde Entity+Referentie+bedrag als het origineel — het origineel én
        # de tegenboeking zijn uitgezonderd van het duplicaatsignaal (keten), de herboeking
        # krijgt een EIGEN RLZ-GUID (nooit her-PUT op het origineel).
        fake_client.duplicaten = [
            {"id": str(rlz_herboeking_id(document_id, 0))},
            {"id": str(rlz_tegenboeking_id(document_id, 0))},
        ]
        herboeking = boeken.boek_document(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
        )
        assert herboeking.rlz_document_id == rlz_herboeking_id(document_id, 1)
        assert herboeking.rlz_document_id != rlz_herboeking_id(document_id, 0)
        assert _document_status(admin_engine, document_id) == "geboekt"

    def test_vreemd_duplicaat_blokkeert_de_herboeking_nog_steeds(
        self, geboekt_document, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        document_id, fake_client = geboekt_document
        tegenboeken.voer_tegenboeking_uit(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker,
            soort="vervang", reden=REDEN,
        )
        fake_client.duplicaten = [{"id": str(uuid.uuid4())}]  # écht ander RLZ-document
        with pytest.raises(boeken.BoekenGeblokkeerdDoorChecks):
            boeken.boek_document(
                administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
            )


class TestPoorten:
    def test_alleen_bij_geblokkeerde_storno(
        self, geboekt_document, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        document_id, fake_client = geboekt_document
        fake_client.aangiften = []  # storno vrij → tegenboeken is niet de route
        with pytest.raises(tegenboeken.TegenboekenNietToegestaan):
            tegenboeken.voer_tegenboeking_uit(
                administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker,
                soort="volledig", reden=REDEN,
            )

    def test_reden_verplicht(
        self, geboekt_document, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        document_id, _ = geboekt_document
        with pytest.raises(tegenboeken.OngeldigeTegenboeking, match="Reden"):
            tegenboeken.voer_tegenboeking_uit(
                administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker,
                soort="volledig", reden="  x ",
            )

    def test_origineel_al_gestorneerd_in_rlz_weigert(
        self, geboekt_document, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        document_id, fake_client = geboekt_document
        fake_client._invoices[str(rlz_herboeking_id(document_id, 0))]["Status"] = 1
        with pytest.raises(tegenboeken.OngeldigeTegenboeking, match="concept"):
            tegenboeken.voer_tegenboeking_uit(
                administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker,
                soort="volledig", reden=REDEN,
            )

    def test_duplicaatcheck_op_de_tegenboeking_blokkeert_vreemd_document(
        self, geboekt_document, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID
    ) -> None:
        document_id, fake_client = geboekt_document
        fake_client.duplicaten = [{"id": str(uuid.uuid4())}]
        with pytest.raises(tegenboeken.TegenboekenGeblokkeerdDoorChecks):
            tegenboeken.voer_tegenboeking_uit(
                administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker,
                soort="volledig", reden=REDEN,
            )

    def test_niet_geboekt_document_weigert(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="nieuw.pdf",
            inhoud=b"%PDF-1.4 nieuw",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        with pytest.raises(tegenboeken.OngeldigeTegenboeking, match="status"):
            tegenboeken.voer_tegenboeking_uit(
                administratie_id=administratie_id, document_id=resultaat.document_id,
                actor_id=gescoopte_gebruiker, soort="volledig", reden=REDEN,
            )


class TestIdempotentie:
    def test_retry_na_halve_mislukking_boekt_niet_dubbel(
        self, geboekt_document, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        """De tegenboeking staat al geboekt in RLZ (eerdere poging strandde ná de RLZ-writes)
        — de retry doet géén tweede PUT/boekactie en maakt alleen de lokale registratie af."""
        document_id, fake_client = geboekt_document
        tegen_guid = rlz_tegenboeking_id(document_id, 0)
        fake_client._invoices[str(tegen_guid)] = {"Status": 2, "ReceiptNumber": "RLZ-TEST-EERDER", "Date": None}
        puts_voor = len(fake_client.puts)
        resultaat = tegenboeken.voer_tegenboeking_uit(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker,
            soort="volledig", reden=REDEN,
        )
        assert len(fake_client.puts) == puts_voor  # geen tweede PUT
        assert tegen_guid not in fake_client.geboekte_acties  # geen tweede actie 17
        assert resultaat.rlz_boekstuknummer == "RLZ-TEST-EERDER"
        with admin_engine.connect() as conn:
            aantal = conn.execute(
                text("SELECT count(*) FROM boekhouding.tegenboeking WHERE document_id = :id"), {"id": document_id}
            ).scalar_one()
        assert aantal == 1


class TestWebhook:
    def test_vastgoed_krijgt_factuur_geboekt_met_negatieve_regels_geen_gestorneerd(
        self, geboekt_document, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        document_id, _ = geboekt_document
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET is_vastgoed = true WHERE id = :id"),
                {"id": administratie_id},
            )
        tegenboeken.voer_tegenboeking_uit(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker,
            soort="volledig", reden=REDEN,
        )
        with admin_engine.connect() as conn:
            rijen = conn.execute(
                text("SELECT event, payload FROM boekhouding.webhook_uitgaand WHERE document_id = :id"),
                {"id": document_id},
            ).all()
        events = [r.event for r in rijen]
        # Creditnota-norm §3a: één factuur_geboekt met negatieve regels en een EIGEN
        # rlz_document_id (eigen volgnummer-reeks start op 1); nooit factuur_gestorneerd —
        # het origineel blijft in RLZ geboekt staan.
        assert "factuur_gestorneerd" not in events
        tegen_guid = str(rlz_tegenboeking_id(document_id, 0))
        [tegen_event] = [r for r in rijen if r.payload["data"]["rlz_document_id"] == tegen_guid]
        assert tegen_event.event == "factuur_geboekt"
        data = tegen_event.payload["data"]
        assert data["volgnummer"] == 1
        assert data["referentie"] == "TB F-2026-0841"
        assert Decimal(data["regels"][0]["netto_bedrag"]) == Decimal("-100.00")
        # Schema 1.2 (v1.17, akkoord Vastly 23-08): het tegenboeking-event draagt de
        # kruisverwijzing naar het origineel — deterministisch uit (document_id, boek_cyclus).
        assert data["corrigeert_document_id"] == str(rlz_herboeking_id(document_id, 0))
        assert tegen_event.payload["schema_version"] == "1.2"

    def test_herboeking_draagt_geen_corrigeert_document_id(
        self, geboekt_document, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        """§3a v1.17: de herboeking bij "tegenboeken én opnieuw boeken" is een gewoon nieuw
        document — haar factuur_geboekt-event draagt het veld níét (sleutel afwezig)."""
        document_id, fake_client = geboekt_document
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET is_vastgoed = true WHERE id = :id"),
                {"id": administratie_id},
            )
        tegenboeken.voer_tegenboeking_uit(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker,
            soort="vervang", reden=REDEN,
        )
        fake_client.duplicaten = [
            {"id": str(rlz_herboeking_id(document_id, 0))},
            {"id": str(rlz_tegenboeking_id(document_id, 0))},
        ]
        boeken.boek_document(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
        )
        with admin_engine.connect() as conn:
            rijen = conn.execute(
                text("SELECT payload FROM boekhouding.webhook_uitgaand WHERE document_id = :id"),
                {"id": document_id},
            ).all()
        herboek_guid = str(rlz_herboeking_id(document_id, 1))
        [herboek_event] = [r for r in rijen if r.payload["data"]["rlz_document_id"] == herboek_guid]
        assert "corrigeert_document_id" not in herboek_event.payload["data"]
        tegen_guid = str(rlz_tegenboeking_id(document_id, 0))
        [tegen_event] = [r for r in rijen if r.payload["data"]["rlz_document_id"] == tegen_guid]
        assert tegen_event.payload["data"]["corrigeert_document_id"] == str(rlz_herboeking_id(document_id, 0))

    def test_geen_webhook_zonder_vastgoed_vlag(
        self, geboekt_document, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
    ) -> None:
        document_id, _ = geboekt_document
        tegenboeken.voer_tegenboeking_uit(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker,
            soort="volledig", reden=REDEN,
        )
        with admin_engine.connect() as conn:
            aantal = conn.execute(
                text("SELECT count(*) FROM boekhouding.webhook_uitgaand WHERE document_id = :id"), {"id": document_id}
            ).scalar_one()
        assert aantal == 0
