"""RLZ-UI-storno-detectie → factuur_gestorneerd (koppelcontract §3 v1.14, kostenflow-randvraag
c): een lokaal GEBOEKT inkoopdocument van een vastgoed-administratie dat in RLZ op Status 1
staat (actie 19 in de RLZ-UI) krijgt één gestorneerd-event in de boekstand-reeks — idempotent,
en alleen als er ooit een factuur_geboekt-event was (anders valt er bij vastgoed niets te
corrigeren)."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import Engine, text

from app.documenten import storno_detectie
from app.documenten.rlz_ids import rlz_purchase_invoice_id
from tests.bank.conftest import FakeBankClient


def _maak_geboekt_document(admin_engine: Engine, *, administratie_id: uuid.UUID) -> uuid.UUID:
    document_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.document (id, administratie_id, bron, bestandsnaam, sha256_hash, "
                "status, opslag_pad, soort) "
                "VALUES (:id, :aid, 'upload', 'f.pdf', :hash, 'geboekt', 'pad', 'inkoopfactuur')"
            ),
            {"id": document_id, "aid": administratie_id, "hash": str(uuid.uuid4())},
        )
    return document_id


def _zet_vastgoed(admin_engine: Engine, administratie_id: uuid.UUID) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.administratie SET is_vastgoed = true WHERE id = :aid"),
            {"aid": administratie_id},
        )


def _voeg_geboekt_event_toe(
    admin_engine: Engine, *, document_id: uuid.UUID, volgnummer: int | None = 1, schema: str = "1.1"
) -> None:
    """Outbox-rij zoals _sla_webhook_op die maakt; volgnummer=None simuleert het 1.0-formaat."""
    data = {
        "rlz_document_id": str(rlz_purchase_invoice_id(document_id)),
        "rlz_admin_id": "rlz-test",
        "rlz_boekstuknummer": "RLZ-04-00002001",
        "referentie": "F-2026-001",
    }
    if volgnummer is not None:
        data["volgnummer"] = volgnummer
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.webhook_uitgaand (id, document_id, event, payload) "
                "VALUES (:id, :doc, 'factuur_geboekt', :payload)"
            ),
            {
                "id": uuid.uuid4(),
                "doc": document_id,
                "payload": json.dumps({"schema_version": schema, "event": "factuur_geboekt", "data": data}),
            },
        )


def _outbox(admin_engine: Engine) -> list[tuple]:
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT document_id, event, payload FROM boekhouding.webhook_uitgaand "
                "ORDER BY aangemaakt_op"
            )
        ).all()


def _client_met_status(document_id: uuid.UUID, status: int) -> FakeBankClient:
    return FakeBankClient(invoices={str(rlz_purchase_invoice_id(document_id)): {"Status": status}})


class TestDetectie:
    def test_status_1_na_geboekt_event_geeft_gestorneerd_met_volgend_volgnummer(
        self, administratie_id: uuid.UUID, admin_engine: Engine  # noqa: F811
    ) -> None:
        _zet_vastgoed(admin_engine, administratie_id)
        document_id = _maak_geboekt_document(admin_engine, administratie_id=administratie_id)
        _voeg_geboekt_event_toe(admin_engine, document_id=document_id, volgnummer=1)
        client = _client_met_status(document_id, 1)

        assert storno_detectie.detecteer_en_meld_gestorneerd(
            administratie_id=administratie_id, client=client
        ) == 1
        rijen = _outbox(admin_engine)
        assert [r.event for r in rijen] == ["factuur_geboekt", "factuur_gestorneerd"]
        data = rijen[-1].payload["data"]
        assert rijen[-1].payload["schema_version"] == "1.0"
        assert data["volgnummer"] == 2  # zelfde reeks als factuur_geboekt
        assert data["bron"] == "rlz_ui_detectie"
        assert data["reden"] is None
        # kop-velden uit de laatst gemelde geboekt-stand — exact wat de ontvanger kent
        assert data["rlz_boekstuknummer"] == "RLZ-04-00002001"
        assert data["referentie"] == "F-2026-001"

        # Idempotent: de storno is al gemeld — een tweede run doet niets.
        assert storno_detectie.detecteer_en_meld_gestorneerd(
            administratie_id=administratie_id, client=client
        ) == 0
        assert len(_outbox(admin_engine)) == 2

    def test_geboekt_document_op_status_2_of_3_geeft_niets(
        self, administratie_id: uuid.UUID, admin_engine: Engine  # noqa: F811
    ) -> None:
        _zet_vastgoed(admin_engine, administratie_id)
        for status in (2, 3):
            document_id = _maak_geboekt_document(admin_engine, administratie_id=administratie_id)
            _voeg_geboekt_event_toe(admin_engine, document_id=document_id)
            client = _client_met_status(document_id, status)
            assert storno_detectie.detecteer_en_meld_gestorneerd(
                administratie_id=administratie_id, client=client
            ) == 0

    def test_zonder_geboekt_event_geen_storno_event(
        self, administratie_id: uuid.UUID, admin_engine: Engine  # noqa: F811
    ) -> None:
        """Vastgoed kreeg nooit een geboekt-melding (bv. geboekt vóórdat de administratie
        is_vastgoed werd) — dan valt er dáár ook niets te corrigeren."""
        _zet_vastgoed(admin_engine, administratie_id)
        document_id = _maak_geboekt_document(admin_engine, administratie_id=administratie_id)
        client = _client_met_status(document_id, 1)
        assert storno_detectie.detecteer_en_meld_gestorneerd(
            administratie_id=administratie_id, client=client
        ) == 0
        assert _outbox(admin_engine) == []

    def test_niet_vastgoed_administratie_geeft_niets(
        self, administratie_id: uuid.UUID, admin_engine: Engine  # noqa: F811
    ) -> None:
        document_id = _maak_geboekt_document(admin_engine, administratie_id=administratie_id)
        _voeg_geboekt_event_toe(admin_engine, document_id=document_id)
        client = _client_met_status(document_id, 1)
        assert storno_detectie.detecteer_en_meld_gestorneerd(
            administratie_id=administratie_id, client=client
        ) == 0

    def test_geboekt_event_in_1_0_formaat_telt_als_stand_0(
        self, administratie_id: uuid.UUID, admin_engine: Engine  # noqa: F811
    ) -> None:
        """Een vóór de 1.1-bump geboekt document (geboekt-event zonder volgnummer) krijgt bij
        een RLZ-UI-storno gewoon een gestorneerd-event met volgnummer 1 — de ontvanger telt
        1.0-events als stand 0, dus de storno wint."""
        _zet_vastgoed(admin_engine, administratie_id)
        document_id = _maak_geboekt_document(admin_engine, administratie_id=administratie_id)
        _voeg_geboekt_event_toe(admin_engine, document_id=document_id, volgnummer=None, schema="1.0")
        client = _client_met_status(document_id, 1)
        assert storno_detectie.detecteer_en_meld_gestorneerd(
            administratie_id=administratie_id, client=client
        ) == 1
        data = _outbox(admin_engine)[-1].payload["data"]
        assert data["volgnummer"] == 1

    def test_onleesbare_factuur_stopt_de_rest_niet(
        self, administratie_id: uuid.UUID, admin_engine: Engine  # noqa: F811
    ) -> None:
        """Een 404/fout op één document (geen storno-bewijs: actie 19 laat het document als
        concept bestaan) wordt overgeslagen; het volgende document wordt gewoon verwerkt."""
        _zet_vastgoed(admin_engine, administratie_id)
        kapot = _maak_geboekt_document(admin_engine, administratie_id=administratie_id)
        _voeg_geboekt_event_toe(admin_engine, document_id=kapot)
        goed = _maak_geboekt_document(admin_engine, administratie_id=administratie_id)
        _voeg_geboekt_event_toe(admin_engine, document_id=goed)
        client = _client_met_status(goed, 1)  # `kapot` ontbreekt in de fake → 404
        assert storno_detectie.detecteer_en_meld_gestorneerd(
            administratie_id=administratie_id, client=client
        ) == 1
        gestorneerd = [r for r in _outbox(admin_engine) if r.event == "factuur_gestorneerd"]
        assert [r.document_id for r in gestorneerd] == [goed]


class TestBoekstandReeks:
    def test_herboeking_na_storno_krijgt_volgnummer_3(
        self, administratie_id: uuid.UUID, admin_engine: Engine  # noqa: F811
    ) -> None:
        """Randvraag (b), het reconciliatie-scenario: geboekt (1) → RLZ-UI-storno (2) → als een
        herboeking hetzelfde rlz_document_id opnieuw meldt, telt de reeks door — de ontvanger
        pakt de hoogste stand, ongeacht afleveringsvolgorde."""
        from app.db.session import scoped_session
        from app.documenten.boekstand import laatste_boekstand, volgend_volgnummer

        _zet_vastgoed(admin_engine, administratie_id)
        document_id = _maak_geboekt_document(admin_engine, administratie_id=administratie_id)
        rlz_id = rlz_purchase_invoice_id(document_id)
        _voeg_geboekt_event_toe(admin_engine, document_id=document_id, volgnummer=1)
        client = _client_met_status(document_id, 1)
        assert storno_detectie.detecteer_en_meld_gestorneerd(
            administratie_id=administratie_id, client=client
        ) == 1

        with scoped_session(administratie_id) as session:
            stand, event = laatste_boekstand(session, document_id=document_id, rlz_document_id=rlz_id)
            assert (stand, event) == (2, "factuur_gestorneerd")
            assert volgend_volgnummer(session, document_id=document_id, rlz_document_id=rlz_id) == 3

    def test_reeks_is_per_rlz_document_niet_per_bron_document(
        self, administratie_id: uuid.UUID, admin_engine: Engine  # noqa: F811
    ) -> None:
        """Doorbelasting-spiegels delen het bron-document als document_id maar hebben elk hun
        eigen rlz_document_id — de reeksen mogen elkaar niet beïnvloeden."""
        from app.db.session import scoped_session
        from app.documenten.boekstand import volgend_volgnummer

        document_id = _maak_geboekt_document(admin_engine, administratie_id=administratie_id)
        _voeg_geboekt_event_toe(admin_engine, document_id=document_id, volgnummer=4)
        ander_rlz_id = uuid.uuid4()
        with scoped_session(administratie_id) as session:
            assert volgend_volgnummer(session, document_id=document_id, rlz_document_id=ander_rlz_id) == 1
