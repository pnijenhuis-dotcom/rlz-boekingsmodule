"""Mock-ontvangertest voor het factuur_afgeletterd-event v2.0 (koppelcontract §3 v1.11) —
zelfde patroon als de factuur_geboekt-afleveringstests: échte HMAC-verificatie + replay-venster
+ nonce-dedup aan ontvangstzijde, via de bestaande (event-agnostische) afleveraar."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Engine

from app.db.session import scoped_session
from app.documenten import service, webhook_afleveraar
from app.documenten.models import WebhookUitgaand
from app.documenten.storage import LokaleBestandsopslag
from app.documenten.webhook import bouw_factuur_afgeletterd_payload

# Fixture-herbruik uit de geboekt-afleveringstests (MockOntvanger verifieert écht).
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401
from tests.documenten.test_webhook_afleveraar import (  # noqa: F401
    MockOntvanger,
    aflevering_aan,
    vastgoed_administratie,
)


def _maak_afgeletterd_rij(
    *, administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag  # noqa: F811
) -> uuid.UUID:
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="factuur.pdf",
        inhoud=b"%PDF-1.4 afgeletterd-webhooktest",
        actor_id=actor_id,
        opslag=opslag,
    )
    payload = bouw_factuur_afgeletterd_payload(
        administratie_id=administratie_id,
        rlz_admin_id="rlz-admin-test",
        rlz_document_id=uuid.uuid4(),
        rlz_boekstuknummer="RLZ-04-00002012",
        referentie="F-2026-0642",
        volgnummer=2,
        betaald_bedrag=Decimal("100.00"),
        open_bedrag=Decimal("21.00"),
        scenario="deel_afgeletterd",
        afgeletterd_op=datetime.now(UTC),
    )
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij = WebhookUitgaand(document_id=resultaat.document_id, event=payload["event"], payload=payload)
        session.add(rij)
        session.flush()
        return rij.id


def test_afgeletterd_v2_wordt_geleverd_en_hmac_geverifieerd(
    vastgoed_administratie: uuid.UUID,  # noqa: F811
    gescoopte_gebruiker: uuid.UUID,  # noqa: F811
    opslag: LokaleBestandsopslag,  # noqa: F811
    aflevering_aan: None,  # noqa: F811
    admin_engine: Engine,
) -> None:
    _maak_afgeletterd_rij(
        administratie_id=vastgoed_administratie, actor_id=gescoopte_gebruiker, opslag=opslag
    )
    ontvanger = MockOntvanger()
    rapport = webhook_afleveraar.verwerk_openstaande_webhooks(transport=ontvanger.transport)
    assert rapport.afgeleverd == 1
    [envelope] = ontvanger.ontvangen
    # Eigen schemaversie + de definitieve v1.11-velden, mét geldige HMAC (MockOntvanger
    # verifieert het viertal timestamp/nonce/data/handtekening zelf).
    assert envelope["schema_version"] == "2.0"
    assert envelope["event"] == "factuur_afgeletterd"
    data = envelope["data"]
    assert data["volgnummer"] == 2
    assert data["betaald_bedrag"] == "100.00"
    assert data["open_bedrag"] == "21.00"
    assert data["scenario"] == "deel_afgeletterd"
    assert data["referentie"] == "F-2026-0642"
    assert data["afgeletterd_op"]
