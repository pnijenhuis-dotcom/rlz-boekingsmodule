from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.config import settings

WEBHOOK_SCHEMA_VERSION = "1.0"
FACTUUR_GEBOEKT_EVENT = "factuur_geboekt"
# Tier-model-terugkoppeling naar Vastly (bankmodule, 2026-08-02): zelfde kanaal, zelfde
# envelope/HMAC, alleen een extra event-type — géén nieuw koppelvlak. De ontvanger routeert op
# het `event`-veld; koppelcontract §3 moet dit event nog formeel opnemen (open punt richting
# vastgoed, zie docs/BESLISSINGEN.md "Bankmodule").
FACTUUR_AFGELETTERD_EVENT = "factuur_afgeletterd"
_DEV_ENVIRONMENTS = ("dev", "local")


def _resolve_webhook_secret(env: Mapping[str, str]) -> str:
    """Analoog aan app/security/tokens.py::_resolve_jwt_secret — geen stil fallback buiten dev."""
    secret = env.get("WEBHOOK_HMAC_SECRET")
    if secret:
        return secret
    environment = env.get("ENVIRONMENT", "dev")
    if environment not in _DEV_ENVIRONMENTS:
        raise RuntimeError(
            f"WEBHOOK_HMAC_SECRET ontbreekt en ENVIRONMENT={environment!r} is geen dev-omgeving "
            f"({', '.join(_DEV_ENVIRONMENTS)}). Zet WEBHOOK_HMAC_SECRET (Cloud Run: via Secret "
            "Manager) — zonder gedeeld secret kan de afleveraar niet tekenen."
        )
    return "dev-only-insecure-webhook-hmac-secret"


def webhook_secret() -> str:
    if settings.webhook_hmac_secret:
        return settings.webhook_hmac_secret
    return _resolve_webhook_secret({"ENVIRONMENT": settings.environment})


@dataclass(frozen=True)
class WebhookRegel:
    ledger_id: uuid.UUID
    grootboek_code: str
    project_id: uuid.UUID | None
    netto_bedrag: Decimal
    btw_bedrag: Decimal
    omschrijving: str | None


def _canonical_json(data: dict) -> str:
    """Vaste sleutelvolgorde + compacte separators: de handtekening moet altijd over exact
    dezelfde bytes berekend worden, ongeacht dict-insertievolgorde."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def bereken_handtekening(*, secret: str, payload_json: str, timestamp: str, nonce: str) -> str:
    """HMAC-SHA256 over timestamp+nonce+payload (koppelcontract v1.3: HMAC + timestamp + nonce,
    replay-venster ~5 min) — timestamp/nonce zitten IN het ondertekende bericht, zodat een
    afgevangen (payload, timestamp, nonce, handtekening)-viertal niet met een andere timestamp
    hergebruikt kan worden: de ontvanger verifieert het hele viertal, niet losse velden."""
    bericht = f"{timestamp}.{nonce}.{payload_json}".encode()
    return hmac.new(secret.encode(), bericht, hashlib.sha256).hexdigest()


def verifieer_handtekening(*, secret: str, payload_json: str, timestamp: str, nonce: str, handtekening: str) -> bool:
    verwacht = bereken_handtekening(secret=secret, payload_json=payload_json, timestamp=timestamp, nonce=nonce)
    return hmac.compare_digest(verwacht, handtekening)


def bouw_factuur_geboekt_payload(
    *,
    administratie_id: uuid.UUID,
    rlz_admin_id: str,
    rlz_document_id: uuid.UUID,
    rlz_boekstuknummer: str | None,
    factuurdatum: date,
    vendor_id: uuid.UUID,
    vendor_naam: str | None,
    referentie: str,
    regels: list[WebhookRegel],
) -> dict:
    """ONGETEKENDE payload voor het "factuur geboekt"-event (koppelcontract §3 + CLAUDE.md-
    koppelvlak: RLZ-GUID, project-GUID, datum, bedragen per regel, GB, leverancier, omschrijving,
    adminId). De aanroeper (app/documenten/boeken.py) legt dit vast in
    boekhouding.webhook_uitgaand; timestamp/nonce/handtekening horen hier bewust NIET in — die
    berekent de afleveraar pas per verzendpoging (onderteken_voor_verzending), anders wijst het
    ~5 min-replay-venster van de ontvanger elke aflevering later dan ~5 min na het boeken
    (outbox-retry!) per definitie af."""
    data = {
        "administratie_id": str(administratie_id),
        "rlz_admin_id": rlz_admin_id,
        "rlz_document_id": str(rlz_document_id),
        "rlz_boekstuknummer": rlz_boekstuknummer,
        "datum": factuurdatum.isoformat(),
        "leverancier": {"vendor_id": str(vendor_id), "naam": vendor_naam},
        "referentie": referentie,
        "regels": [
            {
                "ledger_id": str(regel.ledger_id),
                "grootboek_code": regel.grootboek_code,
                "project_id": str(regel.project_id) if regel.project_id else None,
                "netto_bedrag": str(regel.netto_bedrag),
                "btw_bedrag": str(regel.btw_bedrag),
                "omschrijving": regel.omschrijving,
            }
            for regel in regels
        ],
    }
    return {
        "schema_version": WEBHOOK_SCHEMA_VERSION,
        "event": FACTUUR_GEBOEKT_EVENT,
        "data": data,
    }


def bouw_factuur_afgeletterd_payload(
    *,
    administratie_id: uuid.UUID,
    rlz_admin_id: str,
    rlz_document_id: uuid.UUID,
    rlz_boekstuknummer: str | None,
    referentie: str | None,
    geconstateerd_op: datetime,
) -> dict:
    """ONGETEKENDE payload voor het "factuur afgeletterd"-event (tier-model naar Vastly): een
    eerder via de webhook gemelde, geboekte inkoopfactuur van een vastgoed-administratie heeft
    RLZ-documentstatus 3 (Gesloten — volledig betaald/afgeletterd) bereikt. Detectie loopt via
    de documentstatus zelf en dekt dus zowel afletteren in de RLZ-UI (assist-model) als elke
    toekomstige API-route. `geconstateerd_op` is het detectiemoment (onze sync), niet het
    exacte betaalmoment — dat kent RLZ's status-veld niet."""
    data = {
        "administratie_id": str(administratie_id),
        "rlz_admin_id": rlz_admin_id,
        "rlz_document_id": str(rlz_document_id),
        "rlz_boekstuknummer": rlz_boekstuknummer,
        "referentie": referentie,
        "geconstateerd_op": geconstateerd_op.isoformat(),
    }
    return {
        "schema_version": WEBHOOK_SCHEMA_VERSION,
        "event": FACTUUR_AFGELETTERD_EVENT,
        "data": data,
    }


def onderteken_voor_verzending(*, payload: dict, secret: str, nu: datetime) -> dict:
    """Teken een opgeslagen outbox-payload voor precies één verzendpoging: verse timestamp +
    verse nonce + HMAC over (timestamp, nonce, canonieke data). Het resultaat is exact de
    envelope die vóór de HMAC-timing-fix als geheel in de outbox stond — het wire-formaat naar
    vastgoed is dus ongewijzigd, alleen het moment van tekenen is verschoven naar de verzending.
    Elke poging krijgt een eigen nonce: een eerdere (mogelijk afgevangen of half-afgeleverde)
    poging kan nooit als replay van de nieuwe gelden, en de ontvanger kan per nonce dedupliceren."""
    timestamp = nu.isoformat()
    nonce = secrets.token_hex(16)
    payload_json = _canonical_json(payload["data"])
    handtekening = bereken_handtekening(secret=secret, payload_json=payload_json, timestamp=timestamp, nonce=nonce)
    return {
        "schema_version": payload["schema_version"],
        "event": payload["event"],
        "timestamp": timestamp,
        "nonce": nonce,
        "data": payload["data"],
        "handtekening": handtekening,
    }
