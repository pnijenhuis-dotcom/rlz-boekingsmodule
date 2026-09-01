"""Berichten-bouwsteen (accordeur-notificaties, migratie 0050): push-subscripties per
apparaat + het idempotentie-log van de dagelijkse 09:00-herinnering.

Platform-breed (gebruiker-gebonden, niet administratie-gebonden) — zelfde categorie als
webauthn_credential/refresh_token, dus geen RLS (conform migratie 0003/0040)."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class PushSoort(enum.StrEnum):
    """WEBPUSH = browser/PWA (pywebpush, endpoint = push-URL van de browser); APNS/FCM =
    native store-apps (fase 3, endpoint = device-token). Adapterkeuze in app/berichten/push.py."""

    WEBPUSH = "webpush"
    APNS = "apns"
    FCM = "fcm"


class PushSubscriptie(Base):
    """Push-subscriptie per GEBRUIKER+APPARAAT (naast de apparaten-administratie van
    migratie 0040): de kill-switch die een apparaat intrekt, trekt óók deze subscripties in
    (app/auth/webauthn_service.py::trek_apparaat_in) — voor álle soorten. Web Push: `endpoint`
    is de unieke push-URL van de browser, p256dh/auth de encryptiesleutels van de subscription
    (RFC 8291) — géén geheimen van ons, wel per subscriptie uniek. Native (apns/fcm, migratie
    0055): `endpoint` draagt het device-token, sleutels bestaan daar niet (NULL — de
    DB-check dwingt de combinatie af)."""

    __tablename__ = "push_subscriptie"
    __table_args__ = (
        Index("ix_push_subscriptie_gebruiker_id", "gebruiker_id"),
        Index("ix_push_subscriptie_apparaat_id", "apparaat_id"),
        {"schema": "platform"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gebruiker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    apparaat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.webauthn_credential.id")
    )
    soort: Mapped[str] = mapped_column(default=PushSoort.WEBPUSH.value, server_default="webpush")
    endpoint: Mapped[str] = mapped_column(unique=True)
    p256dh: Mapped[str | None] = mapped_column(default=None)
    auth: Mapped[str | None] = mapped_column(default=None)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    laatst_gebruikt_op: Mapped[datetime | None] = mapped_column(default=None)
    ingetrokken_op: Mapped[datetime | None] = mapped_column(default=None)
    # 'gebruiker' (zelf uitgezet), 'kill_switch' (apparaat ingetrokken), 'vervallen'
    # (push-dienst antwoordde 404/410 — subscription bestaat niet meer).
    ingetrokken_reden: Mapped[str | None] = mapped_column(default=None)


class HerinneringStatus(enum.StrEnum):
    """BEZIG = rij geclaimd, verzending loopt (blijft dit hangen dan is de run gecrasht — telt
    als fout in het rapport en wordt NOOIT automatisch opnieuw verstuurd: "een herhaalde run mag
    nooit dubbel sturen"); MISLUKT = verzending aantoonbaar niet gelukt (herhaalde run probeert
    opnieuw); OVERGESLAGEN = geen kanaal (geen subscriptie én geen mailadres) — zichtbaar in de
    joblog-teller, geen fout."""

    BEZIG = "bezig"
    VERZONDEN = "verzonden"
    MISLUKT = "mislukt"
    OVERGESLAGEN = "overgeslagen"


class HerinneringKanaal(enum.StrEnum):
    PUSH = "push"
    E_MAIL = "e-mail"


class AccordeurHerinnering(Base):
    """Idempotentie-log van de dagelijkse herinnering: hooguit één rij per accordeur per
    kalenderdag (Europe/Amsterdam) — een herhaalde job-run stuurt nooit dubbel. Alleen
    accordeurs mét openstaand werk krijgen een rij (>0-drempel; geen werk = níéts, ook geen
    rij)."""

    __tablename__ = "accordeur_herinnering"
    __table_args__ = (
        UniqueConstraint("gebruiker_id", "datum", name="uq_accordeur_herinnering_dag"),
        {"schema": "platform"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gebruiker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    datum: Mapped[date]
    aantal_open: Mapped[int]
    status: Mapped[str] = mapped_column(default=HerinneringStatus.BEZIG.value)
    kanaal: Mapped[str | None] = mapped_column(default=None)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    verzonden_op: Mapped[datetime | None] = mapped_column(default=None)
    detail: Mapped[dict | None] = mapped_column(JSONB, default=None)


class AccordeurNieuwGemeld(Base):
    """Idempotentie-log van de nieuwe-facturen-bundelmelding (migratie 0054, besluit Peter
    2026-08-16: géén melding per factuur — bundelen): één rij per (accordeur, document), uniek.
    Een document wordt nooit tweemaal aan dezelfde accordeur gemeld — ook niet als het later
    opnieuw ter accordering komt (afwijzen + opnieuw aanbieden). Claim-vóór-verzenden zoals
    accordeur_herinnering."""

    __tablename__ = "accordeur_nieuw_gemeld"
    __table_args__ = (
        UniqueConstraint("gebruiker_id", "document_id", name="uq_accordeur_nieuw_gemeld"),
        Index("ix_accordeur_nieuw_gemeld_gebruiker_id", "gebruiker_id"),
        {"schema": "platform"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gebruiker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("boekhouding.document.id"))
    status: Mapped[str] = mapped_column(default=HerinneringStatus.BEZIG.value)
    kanaal: Mapped[str | None] = mapped_column(default=None)
    detail: Mapped[dict | None] = mapped_column(JSONB, default=None)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    verzonden_op: Mapped[datetime | None] = mapped_column(default=None)


class KantoorDigest(Base):
    """Maandagochtend-digest kantoor (D2, 01-09; migratie 0097): één rij per (kantoormedewerker, ISO-week)
    — claim-vóór-verzenden (status bezig → verzonden/mislukt), unique zodat een herhaalde run nooit dubbel
    mailt. Alleen aangemaakt als er iets te melden was."""

    __tablename__ = "kantoor_digest"
    __table_args__ = (
        UniqueConstraint("gebruiker_id", "iso_week", name="uq_kantoor_digest_week"),
        {"schema": "platform"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gebruiker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.gebruiker.id"))
    iso_week: Mapped[str]
    status: Mapped[str] = mapped_column(default=HerinneringStatus.BEZIG.value)
    aangemaakt_op: Mapped[datetime] = mapped_column(server_default=func.now())
    verzonden_op: Mapped[datetime | None] = mapped_column(default=None)
    detail: Mapped[dict | None] = mapped_column(JSONB, default=None)
