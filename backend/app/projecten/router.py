"""Synchroon aanvraag-koppelvlak voor vastgoed (route A, koppelcontract §5 v1.15):
`POST /koppelvlak/vastgoed/projectaanvragen`. Machine-naar-machine — géén JWT/gebruikersauth,
maar het bestaande webhookpatroon in de inkomende richting: HMAC-SHA256 over
(timestamp, nonce, canonieke data-JSON) met een EIGEN secret voor dit kanaal
(settings.projectaanvraag_hmac_secret — nooit het uitgaande webhook-secret hergebruiken),
timestamp-replay-venster ~5 min, nonce-uniciteit, en `bericht_id` als idempotentiesleutel
(patroon waarborg-route): een herlevering krijgt exact hetzelfde antwoord, zonder tweede
RLZ-call.

Verificatievolgorde is bewust: eerst handtekening (over de RUWE ontvangen data — nooit de
pydantic-genormaliseerde vorm, de bytes moeten exact matchen), dan venster/schema/velden, dan
idempotentie, dan scope (alleen is_vastgoed-administraties), dan pas de motor. Elke geslaagde
verwerking = rij in boekhouding.projectaanvraag + audit_event; elke weigering/fout is een
zichtbare, gecodeerde HTTP-fout — nooit stil."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.webhook import _canonical_json, verifieer_handtekening
from app.projecten import motor
from app.projecten.models import ProjectAanvraag
from app.projecten.naamconventie import OngeldigeProjectnaam
from app.projecten.schemas import (
    PROJECTAANVRAAG_EVENT,
    PROJECTAANVRAAG_SCHEMA_VERSION,
    ProjectAanvraagEnvelope,
    ProjectAanvraagResponse,
)
from app.rlz.credentials import GeenRlzCredentials
from app.security.inkomend_secret import DEV_ENVIRONMENTS, resolve_inkomend_kanaal_secret

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/koppelvlak/vastgoed", tags=["projecten-koppelvlak"])

_DEV_ENVIRONMENTS = DEV_ENVIRONMENTS


def _resolve_projectaanvraag_secret(env: Mapping[str, str]) -> str:
    """Zelfde bewaking als het webhook-/JWT-secret: geen stil fallback buiten dev (gedeelde
    resolutie met het registersync-kanaal — app/security/inkomend_secret.py)."""
    return resolve_inkomend_kanaal_secret(
        env,
        env_var="PROJECTAANVRAAG_HMAC_SECRET",
        dev_fallback="dev-only-insecure-projectaanvraag-hmac-secret",
    )


def projectaanvraag_secret() -> str:
    if settings.projectaanvraag_hmac_secret:
        return settings.projectaanvraag_hmac_secret
    return _resolve_projectaanvraag_secret({"ENVIRONMENT": settings.environment})


def _fout(status_code: int, code: str, melding: str) -> HTTPException:
    """Gecodeerde fout (contract §5: vaste foutcodes zodat vastgoed er machinaal op kan
    handelen); de melding is voor de mens in hun logboek."""
    return HTTPException(status_code=status_code, detail={"code": code, "melding": melding})


def _bestaande_rij_response(rij: ProjectAanvraag) -> ProjectAanvraagResponse:
    return ProjectAanvraagResponse(
        schema_version=PROJECTAANVRAAG_SCHEMA_VERSION,
        bericht_id=rij.bericht_id,
        status=rij.status,
        rlz_project_id=rij.rlz_project_id,
        projectnaam=rij.projectnaam,
    )


@router.post("/projectaanvragen", response_model=ProjectAanvraagResponse)
async def verwerk_projectaanvraag(request: Request) -> ProjectAanvraagResponse:
    try:
        secret = projectaanvraag_secret()
    except RuntimeError as exc:
        logger.error("Projectaanvraag-koppelvlak niet geconfigureerd: %s", exc)
        raise _fout(
            status.HTTP_503_SERVICE_UNAVAILABLE, "niet_geconfigureerd",
            "Het koppelvlak-secret is niet geconfigureerd",
        ) from exc

    try:
        raw = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise _fout(status.HTTP_400_BAD_REQUEST, "geen_json", "Body is geen geldige JSON") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("data"), dict):
        raise _fout(status.HTTP_400_BAD_REQUEST, "velden_ongeldig", "Envelope mist het data-object")

    # 1. Handtekening — over de RUWE data zoals ontvangen (canonieke serialisatie), vóór élke
    #    andere verwerking: een bericht dat hier niet doorkomt is niet van vastgoed.
    timestamp = str(raw.get("timestamp") or "")
    nonce = str(raw.get("nonce") or "")
    handtekening = str(raw.get("handtekening") or "")
    if not verifieer_handtekening(
        secret=secret,
        payload_json=_canonical_json(raw["data"]),
        timestamp=timestamp,
        nonce=nonce,
        handtekening=handtekening,
    ):
        logger.warning("Projectaanvraag geweigerd: ongeldige HMAC-handtekening")
        raise _fout(status.HTTP_401_UNAUTHORIZED, "handtekening_ongeldig", "HMAC-handtekening klopt niet")

    # 2. Replay-venster (~5 min, koppelcontract-patroon): timestamp te oud óf te ver in de
    #    toekomst = weigeren. De handtekening dekt de timestamp, dus hij is niet vervalsbaar.
    try:
        verzonden_op = datetime.fromisoformat(timestamp)
        if verzonden_op.tzinfo is None:
            raise ValueError("timestamp zonder tijdzone")
    except ValueError as exc:
        raise _fout(
            status.HTTP_400_BAD_REQUEST, "timestamp_ongeldig",
            "timestamp is geen ISO-8601-moment mét tijdzone",
        ) from exc
    if abs((datetime.now(UTC) - verzonden_op).total_seconds()) > settings.projectaanvraag_replay_venster_seconds:
        raise _fout(
            status.HTTP_400_BAD_REQUEST, "timestamp_buiten_venster",
            f"timestamp valt buiten het replay-venster van "
            f"{settings.projectaanvraag_replay_venster_seconds:.0f} s",
        )

    # 3. Schema + velden.
    try:
        envelope = ProjectAanvraagEnvelope.model_validate(raw)
    except ValidationError as exc:
        raise _fout(status.HTTP_400_BAD_REQUEST, "velden_ongeldig", str(exc)) from exc
    if envelope.schema_version != PROJECTAANVRAAG_SCHEMA_VERSION:
        raise _fout(
            status.HTTP_400_BAD_REQUEST, "schema_version_onbekend",
            f"schema_version {envelope.schema_version!r} wordt niet ondersteund "
            f"(verwacht {PROJECTAANVRAAG_SCHEMA_VERSION})",
        )
    if envelope.event != PROJECTAANVRAAG_EVENT:
        raise _fout(
            status.HTTP_400_BAD_REQUEST, "event_onbekend",
            f"event {envelope.event!r} hoort niet op dit endpoint (verwacht {PROJECTAANVRAAG_EVENT})",
        )
    data = envelope.data

    # 4. Scope: alleen bekende is_vastgoed-administraties (server-side, hard).
    with scoped_session(None) as session:
        administratie = session.get(Administratie, data.administratie_id)
        administratie_is_vastgoed = administratie.is_vastgoed if administratie is not None else None
    if administratie_is_vastgoed is None:
        raise _fout(
            status.HTTP_404_NOT_FOUND, "administratie_onbekend",
            f"administratie {data.administratie_id} is hier niet geregistreerd",
        )
    if not administratie_is_vastgoed:
        raise _fout(
            status.HTTP_403_FORBIDDEN, "geen_vastgoed_administratie",
            f"administratie {data.administratie_id} is geen vastgoed-administratie — "
            "projectaanvragen zijn hard beperkt tot is_vastgoed-administraties",
        )

    # 5. Idempotentie op bericht_id (patroon waarborg-route): herlevering = zelfde antwoord,
    #    geen tweede RLZ-call. Zelfde bericht_id met ándere inhoud is een contract-schending.
    with scoped_session(data.administratie_id) as session:
        rij = session.get(ProjectAanvraag, data.bericht_id)
        if rij is not None:
            if rij.pand_referentie != data.pand_referentie or rij.naam_invoer != data.naam_invoer:
                raise _fout(
                    status.HTTP_409_CONFLICT, "bericht_conflict",
                    "bericht_id is al verwerkt met een andere inhoud",
                )
            return _bestaande_rij_response(rij)
        # Nonce-replay vóór de motor (niet pas bij de insert): een hergebruikte nonce mag
        # nooit eerst nog een RLZ-write veroorzaken. De DB-uniciteit blijft als sluitstuk
        # staan (dekt ook de race en cross-administratie-hergebruik).
        nonce_bezet = session.scalars(
            select(ProjectAanvraag).where(ProjectAanvraag.nonce == nonce)
        ).one_or_none()
        if nonce_bezet is not None:
            raise _fout(
                status.HTTP_409_CONFLICT, "nonce_hergebruikt",
                "deze nonce is al gebruikt voor een ander bericht",
            )

    # 6. De motor: idempotente aanmaak tegen de actuele RLZ-staat.
    try:
        resultaat = motor.maak_pand_project_aan(
            administratie_id=data.administratie_id,
            actor_id=SYSTEEM_ACTOR_ID,
            pand_referentie=data.pand_referentie,
            naam_invoer=data.naam_invoer,
        )
    except OngeldigeProjectnaam as exc:
        raise _fout(status.HTTP_400_BAD_REQUEST, "naam_ongeldig", str(exc)) from exc
    except motor.ProjectNaamConflict as exc:
        raise _fout(status.HTTP_409_CONFLICT, "naam_conflict", str(exc)) from exc
    except (motor.ProjectAanmakenMislukt, GeenRlzCredentials) as exc:
        # Zichtbare foutstatus ("niets verdwijnt stil"): audit + 502; vastgoed herhaalt met
        # hetzelfde bericht_id zodra de oorzaak weg is.
        with scoped_session(data.administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            record_audit_event(
                session,
                actor_id=SYSTEEM_ACTOR_ID,
                module="boekhouding",
                tabel="projectaanvraag",
                record_id=data.bericht_id,
                actie="projectaanvraag_mislukt",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde={
                    "bericht_id": str(data.bericht_id),
                    "pand_referentie": data.pand_referentie,
                    "fout": str(exc),
                },
                administratie_id=data.administratie_id,
            )
        logger.error("Projectaanvraag %s mislukt: %s", data.bericht_id, exc)
        raise _fout(status.HTTP_502_BAD_GATEWAY, "rlz_fout", str(exc)) from exc

    # 7. Registreren (append-only) + audit, daarna het synchrone antwoord.
    try:
        with scoped_session(data.administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            session.add(
                ProjectAanvraag(
                    bericht_id=data.bericht_id,
                    administratie_id=data.administratie_id,
                    nonce=nonce,
                    pand_referentie=data.pand_referentie,
                    naam_invoer=data.naam_invoer,
                    projectnaam=resultaat.projectnaam,
                    rlz_project_id=resultaat.rlz_project_id,
                    status=resultaat.status.value,
                )
            )
            record_audit_event(
                session,
                actor_id=SYSTEEM_ACTOR_ID,
                module="boekhouding",
                tabel="projectaanvraag",
                record_id=data.bericht_id,
                actie="projectaanvraag_verwerkt",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde={
                    "bericht_id": str(data.bericht_id),
                    "pand_referentie": data.pand_referentie,
                    "naam_invoer": data.naam_invoer,
                    "projectnaam": resultaat.projectnaam,
                    "rlz_project_id": str(resultaat.rlz_project_id),
                    "status": resultaat.status.value,
                },
                administratie_id=data.administratie_id,
            )
    except IntegrityError as exc:
        # Twee gevallen, beide via de DB-uniciteit: (a) race op hetzelfde bericht_id — de
        # motor was idempotent, dus de eerder gecommitte rij is het juiste antwoord; (b) een
        # hergebruikte nonce onder een ánder bericht — replay-verdediging, weigeren.
        if "projectaanvraag_nonce" in str(exc.orig):
            raise _fout(
                status.HTTP_409_CONFLICT, "nonce_hergebruikt",
                "deze nonce is al gebruikt voor een ander bericht",
            ) from exc
        with scoped_session(data.administratie_id) as session:
            rij = session.get(ProjectAanvraag, data.bericht_id)
        if rij is not None:
            return _bestaande_rij_response(rij)
        raise

    return ProjectAanvraagResponse(
        schema_version=PROJECTAANVRAAG_SCHEMA_VERSION,
        bericht_id=data.bericht_id,
        status=resultaat.status.value,
        rlz_project_id=resultaat.rlz_project_id,
        projectnaam=resultaat.projectnaam,
    )
