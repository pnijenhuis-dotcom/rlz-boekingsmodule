"""Webhook-afleveraar (koppelcontract §3; Platform OPEN_ITEMS webhook-item, actiepunt 2).

Leest openstaande rijen uit boekhouding.webhook_uitgaand en POST ze naar de vastgoed-ontvanger.
De kern-fix t.o.v. de oude outbox-stub: timestamp + nonce + HMAC-handtekening worden PER
VERZENDPOGING berekend (onderteken_voor_verzending), niet bij het boeken — het ~5 min-
replay-venster van de ontvanger meet dan de werkelijke verzendtijd, en een outbox-retry uren
later is gewoon geldig. Het wire-formaat is ongewijzigd (zelfde envelope als de oude, bij
boeken getekende payload); timestamp/nonce/handtekening gaan daarnaast ook als headers mee.

Failsafes ("niets verdwijnt stil", maar ook: nooit per ongeluk pushen):
- Geen doel-URL of geen HMAC-secret → onvoldoende geconfigureerd: rijen blijven openstaand,
  GEEN fout — vastgoed's ontvanger bestaat nog niet, dit is de verwachte begintoestand.
- Expliciete toggle (platform.webhook_instelling, default UIT) parallel aan de boeken-failsafe.
- Alleen vastgoed-administratie-rijen (al gefilterd bij aanmaak: boeken.py::_sla_webhook_op,
  verkoop-variant, en het doorbelasting-spiegelpad doorbelasting/boeken.py — dat laatste zet
  webhook_uitgaand.administratie_id op de dóél-administratie, migratie 0046) — hier nogmaals
  ge-assert: een rij van een niet-vastgoed-administratie wordt nooit verzonden maar zichtbaar
  op 'mislukt' gezet, met audit_event.
- Fout bij verzenden = retry met exponentiële backoff; na max pogingen zichtbaar 'mislukt'
  (dead-letter). Elke poging (gelukt, mislukt, geweigerd) krijgt een audit_event met de
  systeem-actor. Dead-letter is géén eindstation: herstel_dead_letters() (CLI webhook-redrive)
  zet rijen als expliciete admin-actie terug naar openstaand — een legitiem mislukte levering
  (vastgoed-endpoint langere tijd down) mag nooit permanent verloren zijn.

Uitvoervormen (zelfde patroon als de extractie-worker/sync): in dev een in-process
achtergrondlus (InProcessWebhookAfleveraar, gestart in de app-lifespan); productie draait
dezelfde verwerk-functie als Cloud Scheduler → Cloud Run-job via `python -m app.cli
webhook-afleveren`. Dubbel draaien is veilig: elke rij wordt met FOR UPDATE SKIP LOCKED
geclaimd, dus twee gelijktijdige runs leveren nooit dezelfde rij dubbel af.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select

from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import Administratie, WebhookInstelling
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.models import Document, WebhookStatus, WebhookUitgaand
from app.documenten.webhook import onderteken_voor_verzending, webhook_secret

logger = logging.getLogger(__name__)

TIMESTAMP_HEADER = "X-Webhook-Timestamp"
NONCE_HEADER = "X-Webhook-Nonce"
SIGNATURE_HEADER = "X-Webhook-Signature"


@dataclass(frozen=True)
class AfleverConfig:
    doel_url: str
    secret: str


def haal_aflever_config_op() -> AfleverConfig | None:
    """None = onvoldoende geconfigureerd. Bewust géén exception: zonder doel-URL (vastgoed's
    ontvanger bestaat nog niet) blijven de rijen openstaand — de verwachte begintoestand, geen
    fout. Een ontbrekend secret buiten dev logt wél een waarschuwing: dan is er een URL maar
    kan er niet getekend worden, dat is een configuratiefout die iemand moet zien."""
    doel_url = settings.webhook_doel_url
    if not doel_url:
        return None
    try:
        secret = webhook_secret()
    except RuntimeError as exc:
        logger.warning("Webhook-doel-URL is gezet maar het HMAC-secret ontbreekt: %s", exc)
        return None
    return AfleverConfig(doel_url=doel_url, secret=secret)


def _aflevering_ingeschakeld() -> bool:
    with scoped_session(None) as session:
        instelling = session.get(WebhookInstelling, True)
        return instelling is not None and instelling.aflevering_ingeschakeld


@dataclass
class AfleverRapport:
    """Zichtbare uitkomst van één verwerk-run (CLI print 'm, tests asserten erop)."""

    overgeslagen_reden: str | None = None
    afgeleverd: int = 0
    poging_mislukt: int = 0
    dead_letter: int = 0
    geweigerd_geen_vastgoed: int = 0
    fouten: list[str] = field(default_factory=list)


def _backoff_seconds(pogingen: int) -> float:
    return min(
        settings.webhook_backoff_basis_seconds * (2 ** (pogingen - 1)),
        settings.webhook_backoff_max_seconds,
    )


def _verstuur(*, client: httpx.Client, config: AfleverConfig, envelope: dict) -> str | None:
    """POST één getekende envelope. Retourneert None bij succes (2xx), anders de foutomschrijving
    — exceptions worden hier al platgeslagen zodat de aanroeper altijd één pad heeft."""
    headers = {
        TIMESTAMP_HEADER: envelope["timestamp"],
        NONCE_HEADER: envelope["nonce"],
        SIGNATURE_HEADER: envelope["handtekening"],
    }
    try:
        response = client.post(config.doel_url, json=envelope, headers=headers)
    except httpx.HTTPError as exc:
        return f"verbindingsfout: {exc}"
    if response.is_success:
        return None
    return f"HTTP {response.status_code}: {response.text[:200]}"


def _lever_rij_af(
    *,
    rij_id: uuid.UUID,
    administratie_id: uuid.UUID,
    is_vastgoed: bool,
    config: AfleverConfig,
    client: httpx.Client,
    nu: datetime,
    rapport: AfleverRapport,
) -> None:
    """Eén verzendpoging voor één rij, in een eigen transactie: de rij wordt met FOR UPDATE
    SKIP LOCKED geclaimd (geen dubbele aflevering bij een parallelle run), status opnieuw
    gecontroleerd (kan intussen gewijzigd zijn), en het resultaat — afgeleverd, retry-met-
    backoff of dead-letter — atomair mét zijn audit_event vastgelegd. De HTTP-call gebeurt
    binnen de claim; bij deze volumes (enkele boekingen per dag) is een kort vastgehouden
    connectie een prima prijs voor gegarandeerd niet-dubbel afleveren."""
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        rij = session.scalars(
            select(WebhookUitgaand)
            .where(WebhookUitgaand.id == rij_id, WebhookUitgaand.status == WebhookStatus.OPENSTAAND.value)
            .with_for_update(skip_locked=True)
        ).one_or_none()
        if rij is None:
            return

        correlatie_id = uuid.uuid4()

        if not is_vastgoed:
            # Assert op de aanmaak-scope-filter (migratie 0018): deze rij had niet mogen bestaan
            # of de vlag is later uitgezet — nooit alsnog verzenden, wel zichtbaar maken.
            rij.status = WebhookStatus.MISLUKT.value
            rij.laatste_fout = "administratie is geen vastgoed-administratie — aflevering geweigerd"
            rij.laatste_poging_op = nu
            record_audit_event(
                session,
                actor_id=SYSTEEM_ACTOR_ID,
                module="boekhouding",
                tabel="webhook_uitgaand",
                record_id=rij.id,
                actie="webhook_geweigerd_geen_vastgoed",
                correlatie_id=correlatie_id,
                nieuwe_waarde={"document_id": str(rij.document_id), "fout": rij.laatste_fout},
                administratie_id=administratie_id,
            )
            rapport.geweigerd_geen_vastgoed += 1
            logger.error(
                "Webhook-rij %s geweigerd: administratie %s is geen vastgoed-administratie", rij.id, administratie_id
            )
            return

        envelope = onderteken_voor_verzending(payload=rij.payload, secret=config.secret, nu=nu)
        fout = _verstuur(client=client, config=config, envelope=envelope)

        rij.pogingen += 1
        rij.laatste_poging_op = nu
        poging_detail = {
            "document_id": str(rij.document_id),
            "poging": rij.pogingen,
            "timestamp": envelope["timestamp"],
            "nonce": envelope["nonce"],
        }

        if fout is None:
            rij.status = WebhookStatus.AFGELEVERD.value
            rij.afgeleverd_op = nu
            rij.laatste_fout = None
            rij.volgende_poging_op = None
            actie = "webhook_afgeleverd"
            rapport.afgeleverd += 1
        elif rij.pogingen >= settings.webhook_max_pogingen:
            rij.status = WebhookStatus.MISLUKT.value
            rij.laatste_fout = fout
            rij.volgende_poging_op = None
            actie = "webhook_dead_letter"
            poging_detail["fout"] = fout
            rapport.dead_letter += 1
            rapport.fouten.append(f"{rij.id}: dead-letter na {rij.pogingen} pogingen — {fout}")
            logger.error("Webhook-rij %s definitief mislukt na %s pogingen: %s", rij.id, rij.pogingen, fout)
        else:
            rij.laatste_fout = fout
            rij.volgende_poging_op = nu + timedelta(seconds=_backoff_seconds(rij.pogingen))
            actie = "webhook_poging_mislukt"
            poging_detail["fout"] = fout
            poging_detail["volgende_poging_op"] = rij.volgende_poging_op.isoformat()
            rapport.poging_mislukt += 1
            rapport.fouten.append(f"{rij.id}: poging {rij.pogingen} mislukt — {fout}")
            logger.warning("Webhook-rij %s poging %s mislukt: %s", rij.id, rij.pogingen, fout)

        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="boekhouding",
            tabel="webhook_uitgaand",
            record_id=rij.id,
            actie=actie,
            correlatie_id=correlatie_id,
            nieuwe_waarde=poging_detail,
            administratie_id=administratie_id,
        )


def verwerk_openstaande_webhooks(
    *, nu: datetime | None = None, transport: httpx.BaseTransport | None = None
) -> AfleverRapport:
    """Eén verwerk-run: alle openstaande, aan-de-beurt-zijnde outbox-rijen (volgende_poging_op
    leeg of verstreken) één verzendpoging geven. Idempotent en veilig om vaker te draaien —
    de in-process lus, de CLI en een toekomstige Cloud Scheduler-job gebruiken exact deze
    functie. `transport` is er voor tests (httpx.MockTransport als mock-ontvanger)."""
    nu = nu or datetime.now(UTC)
    rapport = AfleverRapport()

    if not _aflevering_ingeschakeld():
        rapport.overgeslagen_reden = "aflevering staat uit (platform.webhook_instelling, default UIT)"
        return rapport
    config = haal_aflever_config_op()
    if config is None:
        rapport.overgeslagen_reden = (
            "onvoldoende geconfigureerd (webhook_doel_url en/of WEBHOOK_HMAC_SECRET ontbreekt) — "
            "rijen blijven openstaand"
        )
        return rapport

    with scoped_session(None) as session:
        administraties = [(a.id, a.is_vastgoed) for a in session.scalars(select(Administratie))]

    with httpx.Client(transport=transport, timeout=settings.webhook_timeout_seconds) as client:
        for administratie_id, is_vastgoed in administraties:
            with scoped_session(administratie_id) as session:
                # Outer join + coalesce (migratie 0046): een rij met eigen administratie_id
                # (doorbelasting-spiegel) hoort bij DIE administratie — het bron-document is
                # onder deze scope niet eens zichtbaar (RLS), vandaar outer i.p.v. inner join.
                # De coalesce sluit 'm tegelijk uit onder de bron-administratie: nooit dubbel.
                rij_ids = list(
                    session.scalars(
                        select(WebhookUitgaand.id)
                        .outerjoin(Document, WebhookUitgaand.document_id == Document.id)
                        .where(
                            func.coalesce(WebhookUitgaand.administratie_id, Document.administratie_id)
                            == administratie_id,
                            WebhookUitgaand.status == WebhookStatus.OPENSTAAND.value,
                            (WebhookUitgaand.volgende_poging_op.is_(None))
                            | (WebhookUitgaand.volgende_poging_op <= nu),
                        )
                        .order_by(WebhookUitgaand.aangemaakt_op)
                    )
                )
            for rij_id in rij_ids:
                _lever_rij_af(
                    rij_id=rij_id,
                    administratie_id=administratie_id,
                    is_vastgoed=is_vastgoed,
                    config=config,
                    client=client,
                    nu=nu,
                    rapport=rapport,
                )

    return rapport


def herstel_dead_letters(*, actor_id: uuid.UUID, outbox_id: uuid.UUID | None = None) -> int:
    """Re-drive (expliciete admin-actie): zet dead-letter-rijen (`mislukt`) terug naar
    `openstaand` zodat de afleveraar ze weer oppakt — hét normale herstel wanneer de
    vastgoed-ontvanger langere tijd down was en rijen door hun retry-budget heen zijn. Zonder
    dit pad zou een legitiem mislukte levering permanent verloren zijn ("niets verdwijnt stil"
    geldt óók voor de dead-letter). `pogingen` gaat terug naar 0 (vol retry-budget — de reden
    van het mislukken is verholpen, anders had de re-drive geen zin); `laatste_fout` blijft
    staan tot de eerstvolgende poging hem overschrijft, zodat de historie zichtbaar blijft.
    Met `outbox_id` één specifieke rij, zonder alle dead-letters. Audit_event per rij, met de
    aanroepende Beheerder als actor (dit is een menselijke beslissing, geen systeemactie).
    Retourneert het aantal teruggezette rijen."""
    with scoped_session(None) as session:
        administratie_ids = [a.id for a in session.scalars(select(Administratie))]

    hersteld = 0
    for administratie_id in administratie_ids:
        with scoped_session(administratie_id, actor_id=actor_id) as session:
            query = (
                select(WebhookUitgaand)
                .outerjoin(Document, WebhookUitgaand.document_id == Document.id)
                .where(
                    func.coalesce(WebhookUitgaand.administratie_id, Document.administratie_id)
                    == administratie_id,
                    WebhookUitgaand.status == WebhookStatus.MISLUKT.value,
                )
                .with_for_update(of=WebhookUitgaand, skip_locked=True)
            )
            if outbox_id is not None:
                query = query.where(WebhookUitgaand.id == outbox_id)
            for rij in session.scalars(query):
                oude_pogingen = rij.pogingen
                rij.status = WebhookStatus.OPENSTAAND.value
                rij.pogingen = 0
                rij.volgende_poging_op = None
                record_audit_event(
                    session,
                    actor_id=actor_id,
                    module="boekhouding",
                    tabel="webhook_uitgaand",
                    record_id=rij.id,
                    actie="webhook_redrive",
                    correlatie_id=uuid.uuid4(),
                    oude_waarde={
                        "status": WebhookStatus.MISLUKT.value,
                        "pogingen": oude_pogingen,
                        "laatste_fout": rij.laatste_fout,
                    },
                    nieuwe_waarde={"status": WebhookStatus.OPENSTAAND.value, "pogingen": 0},
                    administratie_id=administratie_id,
                )
                hersteld += 1
                logger.info(
                    "Webhook-rij %s teruggezet naar openstaand (re-drive, was %s pogingen)", rij.id, oude_pogingen
                )
    return hersteld


class InProcessWebhookAfleveraar:
    """Dev-achtergrondlus (zelfde in-process-patroon als de extractie-wachtrij): roept
    verwerk_openstaande_webhooks() elke `interval_seconds` aan tot stop(). Elke iteratie is
    volledig afgeschermd — een onverwachte fout wordt gelogd en de lus draait door, nooit een
    kale crash. Productie gebruikt deze lus niet: daar draait dezelfde verwerk-functie als
    Cloud Scheduler → Cloud Run-job (`python -m app.cli webhook-afleveren`)."""

    def __init__(self, *, interval_seconds: float | None = None) -> None:
        self._interval = interval_seconds or settings.webhook_afleveraar_interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._lus, name="webhook-afleveraar", daemon=True)
        self._thread.start()

    def _lus(self) -> None:
        while not self._stop_event.is_set():
            try:
                rapport = verwerk_openstaande_webhooks()
                if rapport.afgeleverd or rapport.poging_mislukt or rapport.dead_letter:
                    logger.info(
                        "Webhook-afleveraar: %s afgeleverd, %s poging(en) mislukt, %s dead-letter",
                        rapport.afgeleverd,
                        rapport.poging_mislukt,
                        rapport.dead_letter,
                    )
            except Exception:  # noqa: BLE001 — vangnet: de lus mag nooit stil sterven
                logger.exception("Webhook-afleveraar-iteratie faalde onverwacht")
            self._stop_event.wait(self._interval)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None


_afleveraar: InProcessWebhookAfleveraar | None = None


def start_in_process_afleveraar() -> None:
    """Gestart vanuit de app-lifespan (app/main.py), alleen als er een doel-URL geconfigureerd
    is — zonder URL valt er niets af te leveren en is een pollende thread alleen maar ruis
    (de config-failsafe laat rijen dan sowieso openstaand)."""
    global _afleveraar
    if not settings.webhook_doel_url or _afleveraar is not None:
        return
    _afleveraar = InProcessWebhookAfleveraar()
    _afleveraar.start()
    logger.info("In-process webhook-afleveraar gestart (interval %ss)", settings.webhook_afleveraar_interval_seconds)


def stop_in_process_afleveraar() -> None:
    global _afleveraar
    if _afleveraar is not None:
        _afleveraar.stop()
        _afleveraar = None
