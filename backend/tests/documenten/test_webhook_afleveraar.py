"""Webhook-afleveraar (app/documenten/webhook_afleveraar.py) tegen een mock-ontvanger die zich
exact als vastgoed's endpoint gedraagt (koppelcontract §3): HMAC-verificatie met het gedeelde
secret, ~5 min-replay-venster op de timestamp, nonce-deduplicatie. De kern-test is de
HMAC-timing-fix: een aflevering (veel) later dan 5 min ná het aanmaken van de outbox-rij krijgt
een VERSE timestamp en wordt dus niet als replay afgewezen — precies de bug van de oude
teken-bij-boeken-outbox (Platform OPEN_ITEMS webhook-item, actiepunt 2)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.config import settings
from app.db.session import scoped_session
from app.documenten import service
from app.documenten.models import WebhookStatus, WebhookUitgaand
from app.documenten.storage import LokaleBestandsopslag
from app.documenten.webhook import WebhookRegel, bouw_factuur_geboekt_payload, verifieer_handtekening
from app.documenten.webhook_afleveraar import (
    NONCE_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    herstel_dead_letters,
    verwerk_openstaande_webhooks,
)

GEDEELD_SECRET = "gedeeld-vastgoed-secret"
DOEL_URL = "https://vastgoed.test/webhooks/rlz"
REPLAY_VENSTER_SECONDEN = 300  # koppelcontract §3: ~5 minuten


class MockOntvanger:
    """Vastgoed's ontvangst-endpoint volgens koppelcontract §3: weigert een ongeldige HMAC, een
    timestamp buiten het ~5 min-venster en een eerder geziene nonce. `forceer_status` laat de
    eerste N requests met een opgelegde statuscode falen (retry-/dead-letter-tests)."""

    def __init__(self, secret: str = GEDEELD_SECRET, *, forceer_status: list[int] | None = None) -> None:
        self.secret = secret
        self.geziene_nonces: set[str] = set()
        self.ontvangen: list[dict] = []
        self.headers_ontvangen: list[dict] = []
        self.aantal_requests = 0
        self._forceer_status = list(forceer_status or [])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.aantal_requests += 1
        self.headers_ontvangen.append(dict(request.headers))
        if self._forceer_status:
            return httpx.Response(self._forceer_status.pop(0), text="opgelegde fout (test)")
        return self.verwerk(json.loads(request.content))

    def verwerk(self, envelope: dict) -> httpx.Response:
        payload_json = json.dumps(envelope["data"], sort_keys=True, separators=(",", ":"), default=str)
        if not verifieer_handtekening(
            secret=self.secret,
            payload_json=payload_json,
            timestamp=envelope["timestamp"],
            nonce=envelope["nonce"],
            handtekening=envelope["handtekening"],
        ):
            return httpx.Response(401, text="handtekening ongeldig")
        leeftijd = abs((datetime.now(UTC) - datetime.fromisoformat(envelope["timestamp"])).total_seconds())
        if leeftijd > REPLAY_VENSTER_SECONDEN:
            return httpx.Response(401, text="timestamp buiten replay-venster")
        if envelope["nonce"] in self.geziene_nonces:
            return httpx.Response(409, text="nonce al gezien (replay)")
        self.geziene_nonces.add(envelope["nonce"])
        self.ontvangen.append(envelope)
        return httpx.Response(200)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


@pytest.fixture
def vastgoed_administratie(administratie_id: uuid.UUID, admin_engine: Engine) -> uuid.UUID:
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.administratie SET is_vastgoed = true WHERE id = :id"),
            {"id": administratie_id},
        )
    return administratie_id


@pytest.fixture
def aflevering_aan(beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> None:
    """Toggle aan + doel-URL + gedeeld secret — de volledige configuratie. De toggle gaat na de
    test terug naar UIT (de DB overleeft de test, settings-monkeypatches niet)."""
    beheer_service.zet_webhook_aflevering_ingeschakeld(actor_id=beheerder_id, ingeschakeld=True)
    monkeypatch.setattr(settings, "webhook_doel_url", DOEL_URL)
    monkeypatch.setattr(settings, "webhook_hmac_secret", GEDEELD_SECRET)
    yield
    beheer_service.zet_webhook_aflevering_ingeschakeld(actor_id=beheerder_id, ingeschakeld=False)


def _maak_outbox_rij(
    *, administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag
) -> uuid.UUID:
    """Outbox-rij zoals boeken.py::_sla_webhook_op die aanmaakt: echt document (FK + RLS) met
    een ongetekende payload."""
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="factuur.pdf",
        inhoud=b"%PDF-1.4 webhooktest",
        actor_id=actor_id,
        opslag=opslag,
    )
    payload = bouw_factuur_geboekt_payload(
        administratie_id=administratie_id,
        rlz_admin_id="rlz-admin-test",
        rlz_document_id=uuid.uuid4(),
        rlz_boekstuknummer="RLZ-04-00002001",
        factuurdatum=datetime(2026, 7, 1).date(),
        vendor_id=uuid.uuid4(),
        vendor_naam="Test Leverancier",
        referentie=f"F-{resultaat.document_id}",
        regels=[
            WebhookRegel(
                ledger_id=uuid.uuid4(),
                grootboek_code="4699",
                project_id=None,
                netto_bedrag=Decimal("100.00"),
                btw_bedrag=Decimal("21.00"),
                omschrijving="Test",
            )
        ],
    )
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij = WebhookUitgaand(document_id=resultaat.document_id, event=payload["event"], payload=payload)
        session.add(rij)
        session.flush()
        return rij.id


def _rij(admin_engine: Engine, rij_id: uuid.UUID) -> dict:
    with admin_engine.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT status, pogingen, laatste_fout, afgeleverd_op, volgende_poging_op, laatste_poging_op "
                    "FROM boekhouding.webhook_uitgaand WHERE id = :id"
                ),
                {"id": rij_id},
            )
            .mappings()
            .one()
        )


def _audit_acties(admin_engine: Engine, rij_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        return list(
            conn.execute(
                text(
                    "SELECT actie FROM platform.audit_event "
                    "WHERE tabel = 'webhook_uitgaand' AND record_id = :id ORDER BY tijdstip"
                ),
                {"id": rij_id},
            ).scalars()
        )


class TestHmacTimingFix:
    def test_aflevering_lang_na_aanmaak_wordt_niet_als_replay_afgewezen(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
    ) -> None:
        """DE bug die we fixen: de rij is ruim buiten het ~5 min-replay-venster aangemaakt, maar
        de aflevering krijgt een VERSE timestamp (getekend per verzendpoging) en de ontvanger —
        die het venster strikt handhaaft — accepteert 'm gewoon. Met de oude teken-bij-boeken-
        payload was dit per definitie een 401."""
        rij_id = _maak_outbox_rij(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE boekhouding.webhook_uitgaand "
                    "SET aangemaakt_op = now() - interval '30 minutes' WHERE id = :id"
                ),
                {"id": rij_id},
            )
        ontvanger = MockOntvanger()

        rapport = verwerk_openstaande_webhooks(transport=ontvanger.transport)

        assert rapport.overgeslagen_reden is None
        assert rapport.afgeleverd == 1
        rij = _rij(admin_engine, rij_id)
        assert rij["status"] == WebhookStatus.AFGELEVERD.value
        assert rij["afgeleverd_op"] is not None
        assert len(ontvanger.ontvangen) == 1
        # De verstuurde timestamp is de verzendtijd, niet de (30 min oude) aanmaaktijd.
        verzonden = datetime.fromisoformat(ontvanger.ontvangen[0]["timestamp"])
        assert abs((datetime.now(UTC) - verzonden).total_seconds()) < REPLAY_VENSTER_SECONDEN

    def test_headers_dragen_timestamp_nonce_en_handtekening(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
    ) -> None:
        rij_id = _maak_outbox_rij(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        ontvanger = MockOntvanger()

        verwerk_openstaande_webhooks(transport=ontvanger.transport)

        assert _rij(admin_engine, rij_id)["status"] == WebhookStatus.AFGELEVERD.value
        headers = ontvanger.headers_ontvangen[0]
        envelope = ontvanger.ontvangen[0]
        assert headers[TIMESTAMP_HEADER.lower()] == envelope["timestamp"]
        assert headers[NONCE_HEADER.lower()] == envelope["nonce"]
        assert headers[SIGNATURE_HEADER.lower()] == envelope["handtekening"]


class TestHmacVerificatieDoorOntvanger:
    def test_verkeerd_secret_wordt_door_de_ontvanger_geweigerd(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """De mock-ontvanger verifieert écht met het gedeelde secret: tekenen wij met een ander
        secret, dan is het een 401 en blijft de rij (met retry) openstaand."""
        monkeypatch.setattr(settings, "webhook_hmac_secret", "een-ander-secret")
        rij_id = _maak_outbox_rij(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        ontvanger = MockOntvanger()  # verwacht GEDEELD_SECRET

        rapport = verwerk_openstaande_webhooks(transport=ontvanger.transport)

        assert rapport.afgeleverd == 0
        assert rapport.poging_mislukt == 1
        rij = _rij(admin_engine, rij_id)
        assert rij["status"] == WebhookStatus.OPENSTAAND.value
        assert "401" in rij["laatste_fout"]
        assert ontvanger.ontvangen == []

    def test_replay_van_afgevangen_envelope_wordt_geweigerd(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
    ) -> None:
        """Idempotentie/replay-bescherming via de nonce: dezelfde (afgevangen) envelope nogmaals
        aanbieden weigert de ontvanger; een échte volgende aflevering draagt een verse nonce en
        gaat gewoon door."""
        rij_a = _maak_outbox_rij(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        ontvanger = MockOntvanger()
        verwerk_openstaande_webhooks(transport=ontvanger.transport)
        assert _rij(admin_engine, rij_a)["status"] == WebhookStatus.AFGELEVERD.value
        afgevangen = ontvanger.ontvangen[0]

        replay_antwoord = ontvanger.verwerk(afgevangen)
        assert replay_antwoord.status_code == 409

        rij_b = _maak_outbox_rij(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        verwerk_openstaande_webhooks(transport=ontvanger.transport)
        assert _rij(admin_engine, rij_b)["status"] == WebhookStatus.AFGELEVERD.value
        assert len({e["nonce"] for e in ontvanger.ontvangen}) == 2


class TestRetryEnDeadLetter:
    def test_mislukte_poging_krijgt_backoff_en_wordt_pas_daarna_opnieuw_geprobeerd(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
    ) -> None:
        rij_id = _maak_outbox_rij(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        ontvanger = MockOntvanger(forceer_status=[500])
        nu = datetime.now(UTC)

        verwerk_openstaande_webhooks(nu=nu, transport=ontvanger.transport)
        rij = _rij(admin_engine, rij_id)
        assert rij["status"] == WebhookStatus.OPENSTAAND.value
        assert rij["pogingen"] == 1
        assert "500" in rij["laatste_fout"]
        verwacht_volgende = nu + timedelta(seconds=settings.webhook_backoff_basis_seconds)
        assert abs((rij["volgende_poging_op"] - verwacht_volgende).total_seconds()) < 1

        # Vóór het backoff-moment: geen nieuwe poging.
        verwerk_openstaande_webhooks(nu=nu + timedelta(seconds=10), transport=ontvanger.transport)
        assert _rij(admin_engine, rij_id)["pogingen"] == 1
        assert ontvanger.aantal_requests == 1

        # Ná het backoff-moment: poging 2, nu geslaagd (verse timestamp/nonce).
        verwerk_openstaande_webhooks(
            nu=nu + timedelta(seconds=settings.webhook_backoff_basis_seconds + 1),
            transport=ontvanger.transport,
        )
        rij = _rij(admin_engine, rij_id)
        assert rij["status"] == WebhookStatus.AFGELEVERD.value
        assert rij["pogingen"] == 2

    def test_dead_letter_na_max_pogingen_zichtbaar_mislukt(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "webhook_max_pogingen", 2)
        rij_id = _maak_outbox_rij(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        ontvanger = MockOntvanger(forceer_status=[500, 500])
        nu = datetime.now(UTC)

        verwerk_openstaande_webhooks(nu=nu, transport=ontvanger.transport)
        rapport = verwerk_openstaande_webhooks(
            nu=nu + timedelta(seconds=settings.webhook_backoff_basis_seconds + 1),
            transport=ontvanger.transport,
        )

        assert rapport.dead_letter == 1
        rij = _rij(admin_engine, rij_id)
        assert rij["status"] == WebhookStatus.MISLUKT.value
        assert rij["pogingen"] == 2
        assert rij["volgende_poging_op"] is None
        assert "500" in rij["laatste_fout"]

        # Een dead-letter-rij wordt daarna nooit meer stil opnieuw geprobeerd.
        verwerk_openstaande_webhooks(
            nu=nu + timedelta(seconds=7200), transport=ontvanger.transport
        )
        assert ontvanger.aantal_requests == 2

    def test_audit_event_per_poging(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
    ) -> None:
        rij_id = _maak_outbox_rij(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        ontvanger = MockOntvanger(forceer_status=[500])
        nu = datetime.now(UTC)

        verwerk_openstaande_webhooks(nu=nu, transport=ontvanger.transport)
        verwerk_openstaande_webhooks(
            nu=nu + timedelta(seconds=settings.webhook_backoff_basis_seconds + 1),
            transport=ontvanger.transport,
        )

        acties = _audit_acties(admin_engine, rij_id)
        assert acties == ["webhook_poging_mislukt", "webhook_afgeleverd"]


class TestRedrive:
    def _maak_dead_letter(
        self,
        *,
        administratie_id: uuid.UUID,
        actor_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        monkeypatch: pytest.MonkeyPatch,
    ) -> uuid.UUID:
        """Rij die door zijn retry-budget heen is: max_pogingen=1 + één opgelegde 500."""
        monkeypatch.setattr(settings, "webhook_max_pogingen", 1)
        rij_id = _maak_outbox_rij(administratie_id=administratie_id, actor_id=actor_id, opslag=opslag)
        verwerk_openstaande_webhooks(transport=MockOntvanger(forceer_status=[500]).transport)
        monkeypatch.setattr(settings, "webhook_max_pogingen", 8)
        return rij_id

    def test_redrive_zet_dead_letter_terug_en_aflevering_slaagt_daarna(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Het normale herstel-scenario: vastgoed-endpoint was langere tijd down → rij
        dead-letter → admin-re-drive → openstaand met vol retry-budget → volgende run levert
        gewoon af. Zonder dit pad zou de levering permanent verloren zijn."""
        rij_id = self._maak_dead_letter(
            administratie_id=vastgoed_administratie,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            monkeypatch=monkeypatch,
        )
        assert _rij(admin_engine, rij_id)["status"] == WebhookStatus.MISLUKT.value

        hersteld = herstel_dead_letters(actor_id=beheerder_id)

        assert hersteld == 1
        rij = _rij(admin_engine, rij_id)
        assert rij["status"] == WebhookStatus.OPENSTAAND.value
        assert rij["pogingen"] == 0
        assert rij["volgende_poging_op"] is None
        # De fout-historie blijft zichtbaar tot de eerstvolgende poging.
        assert "500" in rij["laatste_fout"]

        ontvanger = MockOntvanger()
        verwerk_openstaande_webhooks(transport=ontvanger.transport)
        assert _rij(admin_engine, rij_id)["status"] == WebhookStatus.AFGELEVERD.value
        assert len(ontvanger.ontvangen) == 1

    def test_redrive_schrijft_audit_event_met_beheerder_als_actor(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        rij_id = self._maak_dead_letter(
            administratie_id=vastgoed_administratie,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            monkeypatch=monkeypatch,
        )

        herstel_dead_letters(actor_id=beheerder_id)

        with admin_engine.connect() as conn:
            actor, oude_waarde, nieuwe_waarde = conn.execute(
                text(
                    "SELECT actor_id, oude_waarde, nieuwe_waarde FROM platform.audit_event "
                    "WHERE tabel = 'webhook_uitgaand' AND record_id = :id AND actie = 'webhook_redrive'"
                ),
                {"id": rij_id},
            ).one()
        # Re-drive is een menselijke beslissing — de Beheerder is de actor, niet de systeem-actor.
        assert actor == beheerder_id
        assert oude_waarde["status"] == WebhookStatus.MISLUKT.value
        assert oude_waarde["pogingen"] == 1
        assert nieuwe_waarde == {"status": WebhookStatus.OPENSTAAND.value, "pogingen": 0}

    def test_redrive_met_outbox_id_raakt_alleen_die_rij(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "webhook_max_pogingen", 1)
        rij_a = _maak_outbox_rij(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        rij_b = _maak_outbox_rij(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        verwerk_openstaande_webhooks(transport=MockOntvanger(forceer_status=[500, 500]).transport)
        assert _rij(admin_engine, rij_a)["status"] == WebhookStatus.MISLUKT.value
        assert _rij(admin_engine, rij_b)["status"] == WebhookStatus.MISLUKT.value

        hersteld = herstel_dead_letters(actor_id=beheerder_id, outbox_id=rij_a)

        assert hersteld == 1
        assert _rij(admin_engine, rij_a)["status"] == WebhookStatus.OPENSTAAND.value
        assert _rij(admin_engine, rij_b)["status"] == WebhookStatus.MISLUKT.value

    def test_redrive_raakt_openstaande_en_afgeleverde_rijen_niet(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
    ) -> None:
        rij_afgeleverd = _maak_outbox_rij(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        verwerk_openstaande_webhooks(transport=MockOntvanger().transport)
        rij_openstaand = _maak_outbox_rij(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag
        )

        assert herstel_dead_letters(actor_id=beheerder_id) == 0
        assert _rij(admin_engine, rij_afgeleverd)["status"] == WebhookStatus.AFGELEVERD.value
        rij = _rij(admin_engine, rij_openstaand)
        assert rij["status"] == WebhookStatus.OPENSTAAND.value
        assert rij["pogingen"] == 0


class TestFailsafes:
    def test_onvoldoende_config_laat_rijen_openstaand_zonder_fout(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Vastgoed's ontvanger bestaat nog niet: toggle aan maar geen doel-URL = rijen blijven
        openstaand, géén exception, géén poging — de verwachte begintoestand."""
        beheer_service.zet_webhook_aflevering_ingeschakeld(actor_id=beheerder_id, ingeschakeld=True)
        monkeypatch.setattr(settings, "webhook_doel_url", None)
        rij_id = _maak_outbox_rij(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        try:
            rapport = verwerk_openstaande_webhooks()
        finally:
            beheer_service.zet_webhook_aflevering_ingeschakeld(actor_id=beheerder_id, ingeschakeld=False)

        assert rapport.overgeslagen_reden is not None
        assert "onvoldoende geconfigureerd" in rapport.overgeslagen_reden
        rij = _rij(admin_engine, rij_id)
        assert rij["status"] == WebhookStatus.OPENSTAAND.value
        assert rij["pogingen"] == 0
        assert rij["laatste_poging_op"] is None

    def test_toggle_uit_levert_niet_af_ook_met_volledige_config(
        self,
        vastgoed_administratie: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Default UIT (migratie 0025): zonder expliciete Beheerder-actie wordt er nooit gepusht,
        ook al staan URL + secret klaar — parallel aan de boeken-failsafe."""
        monkeypatch.setattr(settings, "webhook_doel_url", DOEL_URL)
        monkeypatch.setattr(settings, "webhook_hmac_secret", GEDEELD_SECRET)
        rij_id = _maak_outbox_rij(
            administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        ontvanger = MockOntvanger()

        rapport = verwerk_openstaande_webhooks(transport=ontvanger.transport)

        assert rapport.overgeslagen_reden is not None
        assert "aflevering staat uit" in rapport.overgeslagen_reden
        assert _rij(admin_engine, rij_id)["status"] == WebhookStatus.OPENSTAAND.value
        assert ontvanger.aantal_requests == 0

    def test_niet_vastgoed_rij_wordt_geweigerd_niet_verzonden(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        aflevering_aan: None,
        admin_engine: Engine,
    ) -> None:
        """Assert op de aanmaak-scope-filter (migratie 0018): een outbox-rij van een
        niet-vastgoed-administratie (hier kunstmatig, via directe insert) wordt NOOIT verzonden
        maar zichtbaar op mislukt gezet, met audit_event — geen stille lek naar vastgoed."""
        rij_id = _maak_outbox_rij(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        ontvanger = MockOntvanger()

        rapport = verwerk_openstaande_webhooks(transport=ontvanger.transport)

        assert rapport.geweigerd_geen_vastgoed == 1
        rij = _rij(admin_engine, rij_id)
        assert rij["status"] == WebhookStatus.MISLUKT.value
        assert "vastgoed" in rij["laatste_fout"]
        assert ontvanger.aantal_requests == 0
        assert _audit_acties(admin_engine, rij_id) == ["webhook_geweigerd_geen_vastgoed"]
