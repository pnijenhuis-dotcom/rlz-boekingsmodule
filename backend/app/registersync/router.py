"""Registersync-koppelvlak voor Vastly (koppelcontract §8 v1.18): `GET
/koppelvlak/vastgoed/register` levert in één response het VOLLEDIGE register (alle administraties
+ alle actuele grootboekrekeningen) — snapshot, geen delta's, geen paginering, geen filtering
(behalve de actuele-rijen-semantiek, zie service.py). Read-only en deterministisch.

Beveiliging = het route-A-patroon (HMAC-SHA256 + timestamp + nonce, replay-venster ~5 min) mét een
EIGEN inkomend secret (`REGISTERSYNC_HMAC_SECRET`) — nooit het webhook- of projectaanvraag-secret
(compartimentering per koppelvlak). Een GET heeft geen body: timestamp, nonce en handtekening
reizen als headers, en de ondertekende "data" is de vaste canonieke JSON van
`{"event": "registersync"}` — zo blijft de bericht-vorm `"{timestamp}.{nonce}.{data}"` identiek aan
het §3-/§5-kanaal en heeft Vastly één HMAC-implementatie voor alle kanalen.

Volgorde: secret-configuratie → handtekening → replay-venster → nonce-uniciteit (vóór het werk)
→ snapshot → leveringslog-rij (nonce DB-uniek als sluitstuk tegen de race). Elke weigering is een
gecodeerde HTTP-fout, elke levering een rij in boekhouding.registersync_levering — nooit stil."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db.session import scoped_session
from app.documenten.webhook import _canonical_json, verifieer_handtekening
from app.registersync.models import RegistersyncLevering
from app.registersync.schemas import (
    NONCE_HEADER,
    REGISTERSYNC_EVENT,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    RegisterSnapshot,
)
from app.registersync.service import bouw_snapshot
from app.security.inkomend_secret import resolve_inkomend_kanaal_secret

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/koppelvlak/vastgoed", tags=["registersync-koppelvlak"])

DEV_SECRET = "dev-only-insecure-registersync-hmac-secret"
# De vaste, ondertekende "data" van het GET-verzoek (canoniek: sort_keys + compacte separators).
ONDERTEKENDE_DATA = _canonical_json({"event": REGISTERSYNC_EVENT})


def registersync_secret() -> str:
    if settings.registersync_hmac_secret:
        return settings.registersync_hmac_secret
    return resolve_inkomend_kanaal_secret(
        {"ENVIRONMENT": settings.environment},
        env_var="REGISTERSYNC_HMAC_SECRET",
        dev_fallback=DEV_SECRET,
    )


def _fout(status_code: int, code: str, melding: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "melding": melding})


@router.get("/register", response_model=RegisterSnapshot)
def lever_register(request: Request) -> RegisterSnapshot:
    try:
        secret = registersync_secret()
    except RuntimeError as exc:
        logger.error("Registersync-koppelvlak niet geconfigureerd: %s", exc)
        raise _fout(
            status.HTTP_503_SERVICE_UNAVAILABLE, "niet_geconfigureerd",
            "Het koppelvlak-secret is niet geconfigureerd",
        ) from exc

    # 1. Handtekening — over timestamp + nonce + de vaste data; vóór élke andere verwerking.
    timestamp = request.headers.get(TIMESTAMP_HEADER, "")
    nonce = request.headers.get(NONCE_HEADER, "")
    handtekening = request.headers.get(SIGNATURE_HEADER, "")
    if not (timestamp and nonce and handtekening) or not verifieer_handtekening(
        secret=secret,
        payload_json=ONDERTEKENDE_DATA,
        timestamp=timestamp,
        nonce=nonce,
        handtekening=handtekening,
    ):
        logger.warning("Registersync geweigerd: ontbrekende of ongeldige HMAC-handtekening")
        raise _fout(status.HTTP_401_UNAUTHORIZED, "handtekening_ongeldig", "HMAC-handtekening klopt niet")

    # 2. Replay-venster (~5 min): de handtekening dekt de timestamp, dus die is niet vervalsbaar.
    try:
        verzonden_op = datetime.fromisoformat(timestamp)
        if verzonden_op.tzinfo is None:
            raise ValueError("timestamp zonder tijdzone")
    except ValueError as exc:
        raise _fout(
            status.HTTP_400_BAD_REQUEST, "timestamp_ongeldig",
            "timestamp is geen ISO-8601-moment mét tijdzone",
        ) from exc
    if abs((datetime.now(UTC) - verzonden_op).total_seconds()) > settings.registersync_replay_venster_seconds:
        raise _fout(
            status.HTTP_400_BAD_REQUEST, "timestamp_buiten_venster",
            f"timestamp valt buiten het replay-venster van "
            f"{settings.registersync_replay_venster_seconds:.0f} s",
        )

    # 3. Nonce-uniciteit vóór het werk (een replay mag geen snapshot-opbouw kosten); de
    #    DB-uniciteit bij de insert hieronder blijft het sluitstuk (dekt de race).
    with scoped_session(None) as session:
        bezet = session.scalars(
            select(RegistersyncLevering.id).where(RegistersyncLevering.nonce == nonce)
        ).first()
    if bezet is not None:
        raise _fout(status.HTTP_409_CONFLICT, "nonce_hergebruikt", "deze nonce is al gebruikt")

    # 4. Snapshot (read-only transactie, zie service.py).
    snapshot, duur_ms = bouw_snapshot()

    # 5. Leveringslog + nonce-registratie (append-only).
    try:
        with scoped_session(None) as session:
            session.add(
                RegistersyncLevering(
                    nonce=nonce,
                    generated_at=snapshot.generated_at,
                    aantal_administraties=snapshot.administraties.aantal,
                    aantal_grootboekrekeningen=snapshot.grootboekrekeningen.aantal,
                    duur_ms=duur_ms,
                )
            )
    except IntegrityError as exc:
        raise _fout(
            status.HTTP_409_CONFLICT, "nonce_hergebruikt", "deze nonce is al gebruikt"
        ) from exc

    logger.info(
        "Registersync geleverd: %d administraties, %d grootboekrekeningen, %d ms",
        snapshot.administraties.aantal, snapshot.grootboekrekeningen.aantal, duur_ms,
    )
    return snapshot
