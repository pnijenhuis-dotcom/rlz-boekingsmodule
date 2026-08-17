"""Push-subscriptie-beheer (berichten-bouwsteen, migratie 0050).

Een subscriptie hoort bij precies één GEBRUIKER+APPARAAT (de apparaat-claim van de
passkey-sessie) — zo trekt de bestaande kill-switch (trek_apparaat_in) het pushkanaal mee in.
Registreren/intrekken wordt geauditeerd (append-only, zelfde patroon als apparaat-registratie)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from app.berichten.models import PushSoort, PushSubscriptie
from app.db.audit import record_audit_event
from app.db.models import WebauthnCredential
from app.db.session import scoped_session


class BerichtenFout(Exception):
    pass


class ApparaatVereist(BerichtenFout):
    """De sessie draagt geen apparaat-claim (geen passkey-sessie) — een subscriptie zonder
    apparaatbinding zou buiten de kill-switch vallen en is daarom niet toegestaan."""


class OnbekendeSubscriptie(BerichtenFout):
    pass


class OngeldigeSubscriptie(BerichtenFout):
    """Soort/sleutel-combinatie klopt niet (webpush vereist p256dh+auth, native juist niet) —
    zelfde regel als de DB-check van migratie 0055, maar dan als nette 400."""


@dataclass(frozen=True)
class SubscriptieData:
    id: uuid.UUID
    endpoint: str
    aangemaakt_op: datetime


def registreer_subscriptie(
    *,
    gebruiker_id: uuid.UUID,
    apparaat_id: uuid.UUID | None,
    endpoint: str,
    p256dh: str | None,
    auth: str | None,
    soort: str = PushSoort.WEBPUSH.value,
) -> SubscriptieData:
    """Idempotent op endpoint (webpush: de push-URL van de browser; native: het device-token):
    hetzelfde apparaat dat opnieuw registreert krijgt zijn bestaande rij terug (sleutels +
    binding ververst, intrekking opgeheven — de aanroep zelf bewijst dat het kanaal weer/nog
    leeft). Soorten (fase 3): webpush vereist de RFC 8291-sleutels, apns/fcm juist niet."""
    if apparaat_id is None:
        raise ApparaatVereist("Meldingen kunnen alleen aangezet worden vanuit een apparaat-gebonden sessie.")
    if soort not in (PushSoort.WEBPUSH.value, PushSoort.APNS.value, PushSoort.FCM.value):
        raise OngeldigeSubscriptie(f"Onbekende subscriptie-soort: {soort}")
    if soort == PushSoort.WEBPUSH.value and (not p256dh or not auth):
        raise OngeldigeSubscriptie("Web-Push-subscriptie zonder p256dh/auth-sleutels.")
    if soort != PushSoort.WEBPUSH.value and (p256dh or auth):
        raise OngeldigeSubscriptie("Native subscriptie (apns/fcm) draagt geen p256dh/auth-sleutels.")
    with scoped_session(None, actor_id=gebruiker_id) as session:
        credential = session.get(WebauthnCredential, apparaat_id)
        if credential is None or credential.ingetrokken_op is not None or credential.gebruiker_id != gebruiker_id:
            raise ApparaatVereist("Onbekend of ingetrokken apparaat.")
        rij = session.scalars(select(PushSubscriptie).where(PushSubscriptie.endpoint == endpoint)).first()
        actie = "push_subscriptie_bijgewerkt"
        if rij is None:
            rij = PushSubscriptie(
                gebruiker_id=gebruiker_id,
                apparaat_id=apparaat_id,
                soort=soort,
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
            )
            session.add(rij)
            session.flush()
            actie = "push_subscriptie_geregistreerd"
        else:
            rij.gebruiker_id = gebruiker_id
            rij.apparaat_id = apparaat_id
            rij.soort = soort
            rij.p256dh = p256dh
            rij.auth = auth
            rij.ingetrokken_op = None
            rij.ingetrokken_reden = None
        record_audit_event(
            session,
            actor_id=gebruiker_id,
            module="platform",
            tabel="push_subscriptie",
            record_id=rij.id,
            actie=actie,
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"apparaat_id": str(apparaat_id), "soort": soort, "endpoint": endpoint[:120]},
        )
        return SubscriptieData(id=rij.id, endpoint=rij.endpoint, aangemaakt_op=rij.aangemaakt_op)


def trek_subscriptie_in(*, gebruiker_id: uuid.UUID, endpoint: str) -> None:
    """Alleen de eigen subscriptie (zelfde geen-bestaans-lek-lijn als apparaten: niet-eigen =
    onbekend). Idempotent op al-ingetrokken."""
    with scoped_session(None, actor_id=gebruiker_id) as session:
        rij = session.scalars(select(PushSubscriptie).where(PushSubscriptie.endpoint == endpoint)).first()
        if rij is None or rij.gebruiker_id != gebruiker_id:
            raise OnbekendeSubscriptie("Onbekende subscriptie")
        if rij.ingetrokken_op is not None:
            return
        rij.ingetrokken_op = datetime.now(UTC)
        rij.ingetrokken_reden = "gebruiker"
        record_audit_event(
            session,
            actor_id=gebruiker_id,
            module="platform",
            tabel="push_subscriptie",
            record_id=rij.id,
            actie="push_subscriptie_ingetrokken",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"reden": "gebruiker"},
        )


def heeft_actieve_subscriptie(*, gebruiker_id: uuid.UUID, apparaat_id: uuid.UUID | None) -> bool:
    if apparaat_id is None:
        return False
    with scoped_session(None) as session:
        rij = session.scalars(
            select(PushSubscriptie.id).where(
                PushSubscriptie.gebruiker_id == gebruiker_id,
                PushSubscriptie.apparaat_id == apparaat_id,
                PushSubscriptie.ingetrokken_op.is_(None),
            )
        ).first()
        return rij is not None
