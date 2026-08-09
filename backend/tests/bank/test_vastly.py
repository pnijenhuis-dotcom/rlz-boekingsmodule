"""Vastly-terugkoppeling "factuur afgeletterd" — velddefinitie v1.11 (koppelcontract §3):
cumulatief betaald/open uit BaseRemainingAmount, volgnummer per standwijziging, scenario-enum
mét ont_afgeletterd, tier-vlag per administratie, eigen schema_version 2.0."""

from __future__ import annotations

import uuid

from sqlalchemy import Engine, text

from app.bank import vastly
from app.documenten.rlz_ids import rlz_purchase_invoice_id
from tests.bank.conftest import FakeBankClient


def _maak_geboekt_document(
    admin_engine: Engine, *, administratie_id: uuid.UUID, referentie: str = "F-2026-0642"
) -> uuid.UUID:
    document_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.document (id, administratie_id, bron, bestandsnaam, sha256_hash, "
                "status, opslag_pad) VALUES (:id, :aid, 'upload', 'f.pdf', :hash, 'geboekt', 'pad')"
            ),
            {"id": document_id, "aid": administratie_id, "hash": str(uuid.uuid4())},
        )
        conn.execute(
            text(
                "INSERT INTO boekhouding.boekvoorstel (document_id, referentie, rlz_boekstuknummer) "
                "VALUES (:id, :ref, 'RLZ-04-00002012')"
            ),
            {"id": document_id, "ref": referentie},
        )
    return document_id


def _zet_tier(admin_engine: Engine, administratie_id: uuid.UUID) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE platform.administratie SET is_vastgoed = true, "
                "afgeletterd_event_ingeschakeld = true WHERE id = :aid"
            ),
            {"aid": administratie_id},
        )


def _outbox(admin_engine: Engine) -> list[tuple]:
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT document_id, event, payload, status FROM boekhouding.webhook_uitgaand "
                "ORDER BY aangemaakt_op"
            )
        ).all()


def _factuur(*, totaal: float = 121.0, open_bedrag: float) -> dict:
    # ⚠️ IsComplete bewust aanwezig én misleidend: de detectie mag er nooit op varen.
    return {
        "Status": 3 if open_bedrag == 0 else 2,
        "BaseInvoiceAmount": totaal,
        "BaseRemainingAmount": open_bedrag,
        "IsComplete": True,
    }


class TestTierVlag:
    def test_geen_event_zonder_tier_vlag_ook_niet_bij_vastgoed(
        self, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET is_vastgoed = true WHERE id = :aid"),
                {"aid": administratie_id},
            )
        document_id = _maak_geboekt_document(admin_engine, administratie_id=administratie_id)
        client = FakeBankClient(
            invoices={str(rlz_purchase_invoice_id(document_id)): _factuur(open_bedrag=0.0)}
        )
        assert vastly.detecteer_en_meld_afgeletterd(administratie_id=administratie_id, client=client) == 0
        assert _outbox(admin_engine) == []

    def test_geen_event_zonder_vastgoed_vlag(self, administratie_id: uuid.UUID, admin_engine: Engine) -> None:
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET afgeletterd_event_ingeschakeld = true WHERE id = :aid"),
                {"aid": administratie_id},
            )
        document_id = _maak_geboekt_document(admin_engine, administratie_id=administratie_id)
        client = FakeBankClient(
            invoices={str(rlz_purchase_invoice_id(document_id)): _factuur(open_bedrag=0.0)}
        )
        assert vastly.detecteer_en_meld_afgeletterd(administratie_id=administratie_id, client=client) == 0


class TestScenarios:
    def test_volledig_afgeletterd_payload_v2(self, administratie_id: uuid.UUID, admin_engine: Engine) -> None:
        _zet_tier(admin_engine, administratie_id)
        document_id = _maak_geboekt_document(admin_engine, administratie_id=administratie_id)
        rlz_id = rlz_purchase_invoice_id(document_id)
        client = FakeBankClient(invoices={str(rlz_id): _factuur(open_bedrag=0.0)})

        assert vastly.detecteer_en_meld_afgeletterd(administratie_id=administratie_id, client=client) == 1
        [(doc_id, event, payload, status)] = _outbox(admin_engine)
        assert doc_id == document_id
        assert event == "factuur_afgeletterd"
        assert status == "openstaand"
        assert payload["schema_version"] == "2.0"  # eigen bump (registers/schema-versions.md)
        data = payload["data"]
        assert data["rlz_document_id"] == str(rlz_id)
        assert data["volgnummer"] == 1
        assert data["betaald_bedrag"] == "121.00"
        assert data["open_bedrag"] == "0.00"
        assert data["scenario"] == "afgeletterd"
        assert data["afgeletterd_op"]
        assert "handtekening" not in payload

        # Geen standwijziging → geen tweede rij (idempotent per (document, volgnummer)).
        assert vastly.detecteer_en_meld_afgeletterd(administratie_id=administratie_id, client=client) == 0
        assert len(_outbox(admin_engine)) == 1

    def test_deelbetaling_dan_volledig_dan_ont_afgeletterd(
        self, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        """G-rekening-split (standaardcase): deelbetaling → deel_afgeletterd; restant →
        afgeletterd; terugdraaien in de RLZ-UI → ont_afgeletterd. Cumulatieve bedragen,
        monotoon volgnummer."""
        _zet_tier(admin_engine, administratie_id)
        document_id = _maak_geboekt_document(admin_engine, administratie_id=administratie_id)
        rlz_id = rlz_purchase_invoice_id(document_id)

        client = FakeBankClient(invoices={str(rlz_id): _factuur(open_bedrag=21.0)})
        assert vastly.detecteer_en_meld_afgeletterd(administratie_id=administratie_id, client=client) == 1

        client.invoices[str(rlz_id)] = _factuur(open_bedrag=0.0)
        assert vastly.detecteer_en_meld_afgeletterd(administratie_id=administratie_id, client=client) == 1

        client.invoices[str(rlz_id)] = _factuur(open_bedrag=121.0)  # storno/ont-aflettering
        assert vastly.detecteer_en_meld_afgeletterd(administratie_id=administratie_id, client=client) == 1

        rijen = _outbox(admin_engine)
        standen = [
            (r.payload["data"]["volgnummer"], r.payload["data"]["scenario"],
             r.payload["data"]["betaald_bedrag"], r.payload["data"]["open_bedrag"])
            for r in rijen
        ]
        assert standen == [
            (1, "deel_afgeletterd", "100.00", "21.00"),
            (2, "afgeletterd", "121.00", "0.00"),
            (3, "ont_afgeletterd", "0.00", "121.00"),
        ]

    def test_onbetaald_document_genereert_niets(
        self, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        _zet_tier(admin_engine, administratie_id)
        document_id = _maak_geboekt_document(admin_engine, administratie_id=administratie_id)
        client = FakeBankClient(
            invoices={str(rlz_purchase_invoice_id(document_id)): _factuur(open_bedrag=121.0)}
        )
        assert vastly.detecteer_en_meld_afgeletterd(administratie_id=administratie_id, client=client) == 0
        assert _outbox(admin_engine) == []

    def test_oude_v1_rij_telt_niet_als_gemelde_stand(
        self, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        """Een outbox-rij in het vervallen v1.10-formaat (zonder volgnummer/bedragen) blokkeert
        de definitieve melding niet: het document krijgt alsnog één v2.0-rij."""
        _zet_tier(admin_engine, administratie_id)
        document_id = _maak_geboekt_document(admin_engine, administratie_id=administratie_id)
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.webhook_uitgaand (id, document_id, event, payload) "
                    "VALUES (:id, :doc, 'factuur_afgeletterd', :payload)"
                ),
                {
                    "id": uuid.uuid4(),
                    "doc": document_id,
                    "payload": '{"schema_version": "1.0", "event": "factuur_afgeletterd", "data": {}}',
                },
            )
        client = FakeBankClient(
            invoices={str(rlz_purchase_invoice_id(document_id)): _factuur(open_bedrag=0.0)}
        )
        assert vastly.detecteer_en_meld_afgeletterd(administratie_id=administratie_id, client=client) == 1
        nieuwe = [r for r in _outbox(admin_engine) if r.payload.get("schema_version") == "2.0"]
        assert len(nieuwe) == 1
        assert nieuwe[0].payload["data"]["volgnummer"] == 1

    def test_onleesbare_factuur_stopt_de_rest_niet(
        self, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        _zet_tier(admin_engine, administratie_id)
        _maak_geboekt_document(admin_engine, administratie_id=administratie_id, referentie="F-1")
        goed = _maak_geboekt_document(admin_engine, administratie_id=administratie_id, referentie="F-2")
        client = FakeBankClient(invoices={str(rlz_purchase_invoice_id(goed)): _factuur(open_bedrag=0.0)})
        assert vastly.detecteer_en_meld_afgeletterd(administratie_id=administratie_id, client=client) == 1
        assert len(_outbox(admin_engine)) == 1
