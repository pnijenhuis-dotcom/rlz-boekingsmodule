"""Gedeelde push-anders-mail-verzending voor accordeurberichten.

Eén kanaalkeuze voor alle accordeurmeldingen (dagelijkse 09:00-herinnering, handmatige
herinnering per document, nieuwe-facturen-bundel): push naar álle actieve subscripties van
niet-ingetrokken apparaten (kill-switch bijt dubbel), lukt geen enkele push dan e-mail met
hetzelfde bericht; geen kanaal = overgeslagen mét reden (zichtbaar, geen stille no-op).

HARD PRINCIPE (BESLISSINGEN "Accordeur-notificaties"): elk bericht linkt uitsluitend als
deep-link naar de PWA — goedkeuren-zonder-inloggen bestaat bewust niet; push-url's beginnen
altijd met /accordeur (de service worker weigert anders)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from app.berichten import mail, push
from app.berichten.models import HerinneringKanaal, HerinneringStatus, PushSubscriptie
from app.db.models import Gebruiker, WebauthnCredential
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID


def actieve_subscripties(gebruiker_id: uuid.UUID) -> list[PushSubscriptie]:
    """Actieve subscripties van niet-ingetrokken apparaten — de kill-switch bijt dus óók hier,
    zelfs als het intrekken van de subscriptie-rij ooit zou ontbreken (dubbele borging)."""
    with scoped_session(None) as session:
        rijen = session.scalars(
            select(PushSubscriptie)
            .join(WebauthnCredential, WebauthnCredential.id == PushSubscriptie.apparaat_id)
            .where(
                PushSubscriptie.gebruiker_id == gebruiker_id,
                PushSubscriptie.ingetrokken_op.is_(None),
                WebauthnCredential.ingetrokken_op.is_(None),
            )
        ).all()
        session.expunge_all()
        return list(rijen)


def markeer_subscriptie_vervallen(subscriptie_id: uuid.UUID) -> None:
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        rij = session.get(PushSubscriptie, subscriptie_id)
        if rij is not None and rij.ingetrokken_op is None:
            rij.ingetrokken_op = datetime.now(UTC)
            rij.ingetrokken_reden = "vervallen"


@dataclass(frozen=True)
class VerzendUitkomst:
    status: HerinneringStatus
    kanaal: HerinneringKanaal | None
    detail: dict | None
    subscripties_vervallen: int


def verstuur_push_anders_mail(
    gebruiker: Gebruiker,
    *,
    onderwerp: str,
    pushtekst: str,
    mailtekst: str,
    url: str,
    extra_payload: dict | None = None,
) -> VerzendUitkomst:
    """Push eerst (alle actieve subscripties), anders e-mail. Vervallen subscripties (404/410)
    worden gemarkeerd en geteld; falen is nooit stil — de uitkomst draagt status + detail."""
    subscripties = actieve_subscripties(gebruiker.id)
    push_gelukt = 0
    vervallen = 0
    push_fouten: list[str] = []
    if subscripties:
        payload = {"titel": "RLZ Goedkeuren", "tekst": pushtekst, "url": url}
        if extra_payload:
            payload.update(extra_payload)
        for subscriptie in subscripties:
            # Per soort geconfigureerd? (fase 3: webpush | apns | fcm) — een niet-
            # geconfigureerde soort telt niet als fout, zelfde stille-terugval-semantiek als
            # de oude VAPID-poort; de adapterlaag kiest zelf het juiste kanaal.
            if not push.is_geconfigureerd(subscriptie.soort):
                continue
            try:
                push.verzend_push(subscriptie, payload=payload)
                push_gelukt += 1
            except push.PushSubscriptieVervallen:
                markeer_subscriptie_vervallen(subscriptie.id)
                vervallen += 1
            except push.PushFout as exc:
                push_fouten.append(str(exc))
    if push_gelukt:
        return VerzendUitkomst(
            HerinneringStatus.VERZONDEN, HerinneringKanaal.PUSH, {"subscripties": push_gelukt}, vervallen
        )
    # Terugval: e-mail met hetzelfde bericht (ook wanneer álle subscripties vervallen bleken).
    if not gebruiker.e_mail:
        return VerzendUitkomst(
            HerinneringStatus.OVERGESLAGEN, None, {"reden": "geen mailadres en geen subscriptie"}, vervallen
        )
    try:
        mail.verzend_mail(naar=gebruiker.e_mail, onderwerp=onderwerp, tekst=mailtekst)
    except mail.MailFout as exc:
        detail: dict = {"fout": str(exc)}
        if push_fouten:
            detail["push_fouten"] = push_fouten
        return VerzendUitkomst(HerinneringStatus.MISLUKT, None, detail, vervallen)
    detail_ok = {"na_push_fouten": push_fouten} if push_fouten else None
    return VerzendUitkomst(HerinneringStatus.VERZONDEN, HerinneringKanaal.E_MAIL, detail_ok, vervallen)
