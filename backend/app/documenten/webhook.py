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
            "Manager) vóórdat webhook-aflevering in productie gebouwd wordt."
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
    secret: str,
    administratie_id: uuid.UUID,
    rlz_admin_id: str,
    rlz_document_id: uuid.UUID,
    rlz_boekstuknummer: str | None,
    factuurdatum: date,
    vendor_id: uuid.UUID,
    vendor_naam: str | None,
    referentie: str,
    regels: list[WebhookRegel],
    nu: datetime,
) -> dict:
    """Payload voor het "factuur geboekt"-event (koppelcontract §3 + CLAUDE.md-koppelvlak:
    RLZ-GUID, project-GUID, datum, bedragen per regel, GB, leverancier, omschrijving, adminId).
    Aflevering (HTTP-push) is een fase-vervolg — deze functie bouwt en ondertekent alleen; de
    aanroeper (app/documenten/boeken.py) legt het resultaat vast in boekhouding.webhook_uitgaand."""
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
    timestamp = nu.isoformat()
    nonce = secrets.token_hex(16)
    payload_json = _canonical_json(data)
    handtekening = bereken_handtekening(secret=secret, payload_json=payload_json, timestamp=timestamp, nonce=nonce)
    return {
        "schema_version": WEBHOOK_SCHEMA_VERSION,
        "event": FACTUUR_GEBOEKT_EVENT,
        "timestamp": timestamp,
        "nonce": nonce,
        "data": data,
        "handtekening": handtekening,
    }
