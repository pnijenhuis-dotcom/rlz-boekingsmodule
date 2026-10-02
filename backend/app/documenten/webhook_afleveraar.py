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
- Fout bij verzenden = storingscadans (zie onder, sinds 02-10 avond; was exponentiële backoff + dead-letter ná 8);
  daarna zichtbaar 'mislukt'. Elke poging (gelukt, mislukt, geweigerd) krijgt een audit_event met de systeem-actor. 'mislukt' is géén eindstation: herstel_dead_letters() (CLI webhook-redrive)
  zet rijen als expliciete admin-actie terug naar openstaand — een legitiem mislukte levering
  (vastgoed-endpoint langere tijd down) mag nooit permanent verloren zijn.
- 200 mét `{"resultaat": "genegeerd", "reden": …}` (Vastly's ontvanger, sinds 23-09 herkend) is GEEN aflevering: de
  rij gaat zichtbaar op 'mislukt' mét de reden uit de body, audit `webhook_genegeerd`, en wordt NIET herhaald (dezelfde
  payload geeft hetzelfde antwoord; herzenden is een mens-besluit via `herzend_afgeleverd`/`herstel_dead_letters`).
  Aanleiding: 11 kostenevents Rubicon/ARVUM (24-08…18-09) stonden bij ons "afgeleverd" terwijl Vastly ze als
  `onbekende_administratie` negeerde — Platform OPEN_ITEMS regel 13.
- `herzend_afgeleverd()` (CLI `webhook-herzenden`): zet AFGELEVERDE of MISLUKTE rijen op referentie(s) binnen één
  administratie terug naar openstaand (zelfde payload, dus zelfde rlz_document_id/volgnummer; de afleveraar tekent
  opnieuw mét verse timestamp + nonce), audit `webhook_herzonden` per rij mét reden; dry-run toont de rijen zonder te
  schrijven. `lever_rijen_direct_af()` (CLI `--afleveren`) geeft de teruggezette rijen direct één afleverronde en
  meldt per rij het antwoord van de ontvanger — een herzending bewijst zichzelf pas met een afleverronde erna (24-09).
- Samengesteld antwoord (24-09, herzending Rubicon): Vastly's ontvanger draait per `factuur_geboekt` twee
  verwerkers — de verkoopfactuur-badge (topniveau `resultaat`) en de kostenregel-verwerker (genest onder
  `kostenvoorstellen`). Voor een INKOOPfactuur zegt het topniveau per definitie `genegeerd`/`onbekend_document` (de
  badge matcht nooit) terwijl de echte uitkomst genest staat (`voorstellen`, `al_verwerkt`, `kostenintake_uit`, …).
  De afleveraar leest daarom het geneste resultaat als het topniveau `genegeerd` zegt; alleen als óók dat ontbreekt
  of `genegeerd` is, is het event genegeerd.
  `kostenintake_uit` (Vastly-tier-vlag `entiteit_config.rlz_kostenintake` staat uit) is een aflevering zónder
  verwerking: rij `afgeleverd`, maar zichtbaar in het rapport (LET-OP) en het audit — de klant zet de kostenintake
  aan Vastly-kant aan.
- 409 `niet_koppelbaar` (koppelcontract §3c, voorstel-3c-409; run A 02-10 punt 17, Peter 02-10; migratie 0175): de
  ontvanger zegt "nog niet koppelbaar" (onbekende_administratie / onbekend_document / referentie_conflict) — dat is
  geen fout van ons en nooit een dead-letter ná 8 pogingen. De rij gaat naar status `wacht_op_ontvanger` mét oplopende
  cadans vanaf de EERSTE 409 (`WACHT_CADANS`: 1 u → 6 u → 24 u, daarna dagelijks), zichtbaar in het reconciliatieblok
  `webhooks` (soort `webhook_wacht_op_ontvanger`, handeling "Nu opnieuw" = `nu_opnieuw()`), en pas ná `WACHT_MAX`
  (14 dagen) `mislukt` mét "ontvanger kon niet koppelen binnen 14 dagen: <reden>" (soort `webhook_niet_koppelbaar_
  verlopen`, zelfde handeling). Een 2xx ná het wachten = gewoon `afgeleverd`. De 409 van een nonce-replay
  (`{"fout": …}`, zonder `resultaat`) volgt de storingscadans hieronder. 409-pogingen tellen niet mee voor de
  storingsgrens.
- Élke ANDERE niet-2xx (besluit Peter 02-10 avond, "besluiten run A" punt 17a; herziet "8 pogingen, exponentiële
  backoff ≤ 3600 s, dead-letter ≈ 2 uur"): een storing bij de ontvanger — 5xx, 429, timeout/verbindingsfout, nonce-replay-409 — volgt
  DEZELFDE cadans als het wachten (`STORING_CADANS`: 1 u → 6 u → 24 u → dagelijks) maar hooguit **7 dagen**
  (`STORING_MAX`): de rij blijft `openstaand` mét `volgende_poging_op`; valt de volgende cadansstap voorbij de 7
  dagen, dan `mislukt` mét de laatste fout als reden ("aflevering mislukt binnen 7 dagen (N pogingen): HTTP 503 …",
  audit `webhook_aflevering_verlopen`) en een bevinding direct in `actie` (`webhook_aflevering_mislukt`, handeling "Nu
  opnieuw"). Een 4xx ≠ 409/429 (400/401/404/422 …) is een payload- of configuratiefout: herhalen is zinloos → DIRECT
  `mislukt` ("ontvanger weigerde het bericht (HTTP 400): … — payloadfout, herhalen zinloos", audit
  `webhook_geweigerd_4xx`, zelfde bevinding). Geen instelling. De cadans telt in pogingen (de volgende poging ligt
  nooit vóór de stap): 9 storingspogingen binnen 7 dagen (0 u, 1 u, 7 u, 31 u, 55 u, 79 u, 103 u, 127 u, 151 u), de
  tiende zou op 175 u vallen en komt er niet.

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
from app.documenten.models import WEBHOOK_ACTIEVE_STATUSSEN, Document, WebhookStatus, WebhookUitgaand
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
    #: 02-10 avond: storing bij de ontvanger (5xx/429/timeout) die ná de 7-dagen-cadans alsnog `mislukt` is (was:
    #: dead-letter ná 8).
    storing_verlopen: int = 0
    #: 02-10 avond: 4xx ≠ 409/429 = payload-/configuratiefout — direct `mislukt`, herhalen zinloos.
    geweigerd_4xx: int = 0
    geweigerd_geen_vastgoed: int = 0
    #: 200 mét resultaat "genegeerd" van de ontvanger — zichtbaar mislukt, niet herhaald (23-09).
    genegeerd: int = 0
    #: Afgeleverd, maar de ontvanger heeft bewust niets verwerkt (bv. `kostenintake_uit`) — zichtbaar, geen fout.
    zonder_verwerking: int = 0
    #: 02-10: 409 `niet_koppelbaar` → rij wacht op de ontvanger (cadans 1 u / 6 u / 24 u / dagelijks, max 14 dagen).
    wacht_op_ontvanger: int = 0
    #: 02-10: ná 14 dagen wachten alsnog `mislukt` mét de reden uit de body — zichtbaar, handeling "Nu opnieuw".
    wacht_verlopen: int = 0
    fouten: list[str] = field(default_factory=list)
    let_op: list[str] = field(default_factory=list)
    #: Uitkomst per rij (outbox_id → korte tekst) voor de directe afleverronde van `webhook-herzenden --afleveren`.
    per_rij: dict[uuid.UUID, str] = field(default_factory=dict)


#: Vastly's antwoordveld (rlz_webhook.py): "verwerkt" | "al_verwerkt" | "voorstellen" | "verouderde_stand" | … |
#: "genegeerd" (+ "reden"). Alleen "genegeerd" is een fout; alles anders is een aflevering.
RESULTAAT_GENEGEERD = "genegeerd"
#: Aflevering zónder verwerking aan de ontvangerkant (Vastly `_verwerk_factuur_geboekt_kostenregels`: tier-vlag
#: `entiteit_config.rlz_kostenintake` uit). Geen fout — wel zichtbaar (rapport LET-OP + audit), zodat "afgeleverd" nooit
#: stil "verwerkt" suggereert. Herzenden ná het aanzetten van de vlag is één `webhook-herzenden`-commando.
RESULTATEN_ZONDER_VERWERKING = frozenset({"kostenintake_uit"})
#: 409-body van Vastly als het bericht (nog) niet te koppelen is (koppelcontract §3c): `{"resultaat":
#: "niet_koppelbaar", "reden": onbekende_administratie | onbekend_document | referentie_conflict}`. De
#: nonce-replay-409 draagt `{"fout": …}` en blijft de gewone retry.
RESULTAAT_NIET_KOPPELBAAR = "niet_koppelbaar"
#: Cadans ná een 409 `niet_koppelbaar`, gerekend vanaf de EERSTE 409 (run A 02-10 punt 17): 1 u → 6 u → 24 u, daarna
#: dagelijks tot `WACHT_MAX`. Geen instelling (Peter 30-09 "hou het simpel").
WACHT_CADANS = (timedelta(hours=1), timedelta(hours=6), timedelta(hours=24))
WACHT_DAGELIJKS = timedelta(hours=24)
WACHT_MAX = timedelta(days=14)
WACHT_VERLOPEN_PREFIX = "ontvanger kon niet koppelen binnen 14 dagen"
WACHT_PREFIX = "ontvanger kan nog niet koppelen"
#: Storingscadans voor élke andere niet-2xx (besluit Peter 02-10 avond, punt 17a): dezelfde stappen als het wachten,
#: maar hooguit 7 dagen — daarna `mislukt` mét de laatste fout als reden. Telt in pogingen (`pogingen -
#: wacht_pogingen`): de volgende poging ligt nooit vóór de cadansstap, een stilstaande job schuift mee. Geen
#: instelling.
STORING_CADANS = WACHT_CADANS
STORING_DAGELIJKS = WACHT_DAGELIJKS
STORING_MAX = timedelta(days=7)
STORING_VERLOPEN_PREFIX = "aflevering mislukt binnen 7 dagen"
GEWEIGERD_PREFIX = "ontvanger weigerde het bericht"
#: 4xx die géén storing is: payload-/configuratiefout, herhalen zinloos (409 = wacht of nonce-replay, 429 = storing).
_STORING_4XX = frozenset({409, 429})


def storing_stap(storing_poging: int) -> timedelta:
    """Wachttijd ná de n-de mislukte storingspoging (1-gebaseerd): 1 u, 6 u, 24 u, daarna dagelijks."""
    if storing_poging <= 0:
        return STORING_CADANS[0]
    if storing_poging <= len(STORING_CADANS):
        return STORING_CADANS[storing_poging - 1]
    return STORING_DAGELIJKS


def storing_cumulatief(storing_pogingen: int) -> timedelta:
    """Som van de cadansstappen ná `storing_pogingen` mislukte pogingen = het moment (t.o.v. de eerste poging) van de
    volgende poging."""
    return sum((storing_stap(n) for n in range(1, storing_pogingen + 1)), timedelta(0))


def storing_verlopen(storing_pogingen: int) -> bool:
    """Waar zodra de volgende poging voorbij `STORING_MAX` zou vallen — die komt er dan niet: `mislukt` mét reden."""
    return storing_cumulatief(storing_pogingen) > STORING_MAX


def is_payloadfout(status_code: int | None) -> bool:
    return status_code is not None and 400 <= status_code < 500 and status_code not in _STORING_4XX


def is_verlopen_of_geweigerd(status: str, laatste_fout: str | None) -> bool:
    """Een `mislukt`-rij uit de storingscadans (ná 7 dagen) of een directe 4xx-weigering — de rijen van de bevinding
    `webhook_aflevering_mislukt` en van "Nu opnieuw" (naast de 409-rijen)."""
    return status == WebhookStatus.MISLUKT.value and bool(laatste_fout) and (
        laatste_fout.startswith(STORING_VERLOPEN_PREFIX) or laatste_fout.startswith(GEWEIGERD_PREFIX)
    )


def volgende_wacht_poging(*, sinds: datetime, nu: datetime) -> datetime:
    """Eerstvolgende poging ná `nu` volgens de cadans vanaf `sinds` (eerste 409): sinds + 1 u, + 7 u, + 31 u, daarna
    elke 24 u. Altijd strikt ná `nu`, zodat een late job-run nooit twee pogingen in één run doet."""
    moment = sinds
    for stap in WACHT_CADANS:
        moment = moment + stap
        if moment > nu:
            return moment
    while moment <= nu:
        moment = moment + WACHT_DAGELIJKS
    return moment


def wacht_verlopen(*, sinds: datetime, nu: datetime) -> bool:
    return nu - sinds >= WACHT_MAX


@dataclass(frozen=True)
class OntvangerAntwoord:
    fout: str | None
    resultaat: str | None = None
    reden: str | None = None
    body: str | None = None
    #: Topniveau-resultaat zoals de ontvanger het letterlijk gaf (diagnostiek; `resultaat` is de effectieve uitkomst).
    topniveau_resultaat: str | None = None
    #: HTTP-status van het antwoord (None bij een verbindingsfout).
    status_code: int | None = None
    #: 02-10: 409 mét `resultaat: niet_koppelbaar` — "nog niet koppelbaar", geen fout, geen dead-letter.
    niet_koppelbaar: bool = False


def _lees_antwoord(response: httpx.Response) -> tuple[str | None, str | None, str | None, str | None]:
    """(effectief resultaat, reden, body-tekst, topniveau-resultaat) uit een 2xx-antwoord; geen/ongeldige JSON =
    (None, None, tekst, None).

    Samengesteld antwoord (Vastly, 24-09): zegt het topniveau `genegeerd` maar draagt een geneste verwerker
    (`{"kostenvoorstellen": {"resultaat": …}}`) een ander resultaat, dan is DAT de uitkomst van het event — de
    verkoopfactuur-badge op het topniveau matcht bij een inkoopfactuur per definitie niet. Een genest `genegeerd`
    blijft genegeerd (mét de geneste reden als die er is)."""
    tekst = response.text[:500] if response.text else None
    try:
        data = response.json()
    except ValueError:
        return None, None, tekst, None
    if not isinstance(data, dict):
        return None, None, tekst, None
    top = data.get("resultaat")
    top_resultaat = str(top) if top is not None else None
    reden = data.get("reden")
    resultaat = top_resultaat
    if top_resultaat == RESULTAAT_GENEGEERD:
        for waarde in data.values():
            if isinstance(waarde, dict) and waarde.get("resultaat") is not None:
                resultaat = str(waarde["resultaat"])
                reden = waarde.get("reden") if resultaat == RESULTAAT_GENEGEERD else None
                break
    return (
        resultaat,
        str(reden) if reden is not None else None,
        tekst,
        top_resultaat,
    )


def _verstuur(*, client: httpx.Client, config: AfleverConfig, envelope: dict) -> OntvangerAntwoord:
    """POST één getekende envelope. `fout` None bij succes (2xx), anders de foutomschrijving — exceptions worden hier
    al platgeslagen zodat de aanroeper altijd één pad heeft. Bij 2xx reizen `resultaat`/`reden` uit de JSON-body mee
    (Vastly: "verwerkt" | "al_verwerkt" | "voorstellen" | … | "genegeerd" + reden) — de aanroeper beslist."""
    headers = {
        TIMESTAMP_HEADER: envelope["timestamp"],
        NONCE_HEADER: envelope["nonce"],
        SIGNATURE_HEADER: envelope["handtekening"],
    }
    try:
        response = client.post(config.doel_url, json=envelope, headers=headers)
    except httpx.HTTPError as exc:
        return OntvangerAntwoord(fout=f"verbindingsfout: {exc}")
    if response.is_success:
        resultaat, reden, body, topniveau = _lees_antwoord(response)
        return OntvangerAntwoord(
            fout=None,
            resultaat=resultaat,
            reden=reden,
            body=body,
            topniveau_resultaat=topniveau,
            status_code=response.status_code,
        )
    fout = f"HTTP {response.status_code}: {response.text[:200]}"
    if response.status_code == 409:
        # §3c: 409 `niet_koppelbaar` (+ reden) ≠ de nonce-replay-409 (`{"fout": …}`); alleen de eerste is "wacht".
        resultaat, reden, body, _ = _lees_antwoord(response)
        if resultaat == RESULTAAT_NIET_KOPPELBAAR:
            return OntvangerAntwoord(
                fout=fout, resultaat=resultaat, reden=reden, body=body, status_code=409, niet_koppelbaar=True
            )
    return OntvangerAntwoord(fout=fout, body=response.text[:500], status_code=response.status_code)


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
            .where(WebhookUitgaand.id == rij_id, WebhookUitgaand.status.in_(WEBHOOK_ACTIEVE_STATUSSEN))
            .with_for_update(skip_locked=True)
        ).one_or_none()
        if rij is None:
            return

        correlatie_id = uuid.uuid4()
        wachtte_al = rij.status == WebhookStatus.WACHT_OP_ONTVANGER.value

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
            rapport.per_rij[rij.id] = "geweigerd — administratie is geen vastgoed-administratie"
            logger.error(
                "Webhook-rij %s geweigerd: administratie %s is geen vastgoed-administratie", rij.id, administratie_id
            )
            return

        envelope = onderteken_voor_verzending(payload=rij.payload, secret=config.secret, nu=nu)
        antwoord = _verstuur(client=client, config=config, envelope=envelope)
        fout = antwoord.fout

        rij.pogingen += 1
        rij.laatste_poging_op = nu
        poging_detail = {
            "document_id": str(rij.document_id),
            "poging": rij.pogingen,
            "timestamp": envelope["timestamp"],
            "nonce": envelope["nonce"],
            "referentie": (rij.payload.get("data") or {}).get("referentie"),
            "resultaat": antwoord.resultaat,
            # 24-09: het letterlijke antwoord (≤ 500 tekens) reist mee zodat een samengesteld antwoord (topniveau
            # "genegeerd" + genest resultaat) achteraf te lezen is zonder de ontvanger te raadplegen.
            "ontvanger_antwoord": antwoord.body,
            "topniveau_resultaat": antwoord.topniveau_resultaat,
        }
        referentie_tekst = poging_detail["referentie"] or str(rij.id)

        if fout is None and antwoord.resultaat == RESULTAAT_GENEGEERD:
            # 23-09 (OPEN_ITEMS regel 13): de ontvanger antwoordt 200 maar heeft het event bewust NIET verwerkt — dat
            # is geen aflevering. Zichtbaar mislukt mét de reden uit de body; niet herhalen (zelfde payload = zelfde
            # antwoord); herzenden ná een fix aan de ontvangerkant is een mens-besluit (webhook-herzenden/-redrive).
            fout = f"ontvanger negeerde het event: {antwoord.reden or 'geen reden in het antwoord'}"
            rij.status = WebhookStatus.MISLUKT.value
            rij.laatste_fout = fout
            rij.volgende_poging_op = None
            actie = "webhook_genegeerd"
            poging_detail["fout"] = fout
            poging_detail["ontvanger_reden"] = antwoord.reden
            rapport.genegeerd += 1
            rapport.fouten.append(f"{rij.id}: genegeerd door de ontvanger — {antwoord.reden or '?'}")
            rapport.per_rij[rij.id] = f"genegeerd door de ontvanger — {antwoord.reden or '?'}"
            logger.error("Webhook-rij %s door de ontvanger genegeerd: %s", rij.id, antwoord.reden)
        elif fout is None:
            rij.status = WebhookStatus.AFGELEVERD.value
            rij.afgeleverd_op = nu
            rij.laatste_fout = None
            rij.volgende_poging_op = None
            actie = "webhook_afgeleverd"
            rapport.afgeleverd += 1
            rapport.per_rij[rij.id] = f"afgeleverd — resultaat {antwoord.resultaat or 'onbekend (geen JSON-body)'}"
            if wachtte_al:
                poging_detail["wachtte_sinds"] = (
                    rij.wacht_op_ontvanger_sinds.isoformat() if rij.wacht_op_ontvanger_sinds else None
                )
                poging_detail["wacht_pogingen"] = rij.wacht_pogingen
                rapport.per_rij[rij.id] += f" (ná {rij.wacht_pogingen} × wachten op de ontvanger)"
            if antwoord.resultaat in RESULTATEN_ZONDER_VERWERKING:
                # Afgeleverd, maar de ontvanger heeft bewust niets verwerkt: zichtbaar, geen fout, niet herhalen
                # (zelfde payload = zelfde antwoord tot de klant de vlag aan Vastly-kant omzet).
                rapport.zonder_verwerking += 1
                rapport.let_op.append(
                    f"{referentie_tekst}: afgeleverd maar niet verwerkt — ontvanger antwoordt {antwoord.resultaat}"
                )
                logger.warning(
                    "Webhook-rij %s afgeleverd zonder verwerking aan de ontvangerkant: %s", rij.id, antwoord.resultaat
                )
        elif antwoord.niet_koppelbaar:
            # 02-10 (run A punt 17): "nog niet koppelbaar" is geen fout van ons — wachten mét cadans vanaf de eerste
            # 409, zichtbaar als status + reconciliatiebevinding; pas ná 14 dagen `mislukt` mét de reden uit de body.
            sinds = rij.wacht_op_ontvanger_sinds or nu
            reden = antwoord.reden or "geen reden in het antwoord"
            rij.wacht_op_ontvanger_sinds = sinds
            rij.wacht_pogingen += 1
            poging_detail["ontvanger_reden"] = antwoord.reden
            poging_detail["wacht_sinds"] = sinds.isoformat()
            poging_detail["wacht_pogingen"] = rij.wacht_pogingen
            if wacht_verlopen(sinds=sinds, nu=nu):
                fout = f"{WACHT_VERLOPEN_PREFIX}: {reden}"
                rij.status = WebhookStatus.MISLUKT.value
                rij.laatste_fout = fout
                rij.volgende_poging_op = None
                actie = "webhook_niet_koppelbaar_verlopen"
                poging_detail["fout"] = fout
                rapport.wacht_verlopen += 1
                rapport.fouten.append(f"{referentie_tekst}: {fout} ({rij.wacht_pogingen} pogingen sinds {sinds:%d-%m})")
                rapport.per_rij[rij.id] = f"mislukt — {fout}"
                logger.error("Webhook-rij %s ná 14 dagen wachten alsnog mislukt: %s", rij.id, reden)
            else:
                fout = f"{WACHT_PREFIX} ({reden}) — wacht"
                rij.status = WebhookStatus.WACHT_OP_ONTVANGER.value
                rij.laatste_fout = fout
                rij.volgende_poging_op = volgende_wacht_poging(sinds=sinds, nu=nu)
                actie = "webhook_wacht_op_ontvanger"
                poging_detail["fout"] = fout
                poging_detail["volgende_poging_op"] = rij.volgende_poging_op.isoformat()
                rapport.wacht_op_ontvanger += 1
                rapport.let_op.append(
                    f"{referentie_tekst}: {fout} — volgende poging {rij.volgende_poging_op:%d-%m %H:%M} UTC "
                    f"(poging {rij.wacht_pogingen}, sinds {sinds:%d-%m})"
                )
                rapport.per_rij[rij.id] = (
                    f"wacht op de ontvanger ({reden}) — volgende poging {rij.volgende_poging_op:%d-%m %H:%M} UTC"
                )
                logger.warning(
                    "Webhook-rij %s wacht op de ontvanger (%s), poging %s", rij.id, reden, rij.wacht_pogingen
                )
        elif is_payloadfout(antwoord.status_code):
            # 02-10 avond (punt 17a): een 4xx ≠ 409/429 zegt iets over ÓNS bericht (schema, handtekening, GUID) —
            # herhalen geeft hetzelfde antwoord. Direct zichtbaar mislukt mét de body; herstel = fix +
            # webhook-herzenden/redrive.
            fout = (
                f"{GEWEIGERD_PREFIX} (HTTP {antwoord.status_code}): {(antwoord.body or '')[:200]} — payloadfout, "
                "herhalen zinloos"
            )
            rij.status = WebhookStatus.MISLUKT.value
            rij.laatste_fout = fout
            rij.volgende_poging_op = None
            actie = "webhook_geweigerd_4xx"
            poging_detail["fout"] = fout
            poging_detail["status_code"] = antwoord.status_code
            rapport.geweigerd_4xx += 1
            rapport.fouten.append(f"{referentie_tekst}: {fout}")
            rapport.per_rij[rij.id] = f"mislukt — {fout}"
            logger.error("Webhook-rij %s door de ontvanger geweigerd (HTTP %s): %s", rij.id, antwoord.status_code, fout)
        else:
            # Storing bij de ontvanger (5xx, 429, timeout/verbindingsfout, nonce-replay-409): storingscadans 1 u → 6 u
            # → 24 u → dagelijks, hooguit 7 dagen (besluit Peter 02-10 avond; was 8 pogingen/backoff ≤ 3600
            # s/dead-letter ≈ 2 u).
            storing_pogingen = rij.pogingen - rij.wacht_pogingen
            poging_detail["storing_pogingen"] = storing_pogingen
            poging_detail["status_code"] = antwoord.status_code
            if storing_verlopen(storing_pogingen):
                fout = f"{STORING_VERLOPEN_PREFIX} ({storing_pogingen} pogingen): {fout}"
                rij.status = WebhookStatus.MISLUKT.value
                rij.laatste_fout = fout
                rij.volgende_poging_op = None
                actie = "webhook_aflevering_verlopen"
                poging_detail["fout"] = fout
                rapport.storing_verlopen += 1
                rapport.fouten.append(f"{referentie_tekst}: {fout}")
                rapport.per_rij[rij.id] = f"mislukt — {fout}"
                logger.error(
                    "Webhook-rij %s ná %s storingspogingen (7 dagen) mislukt: %s", rij.id, storing_pogingen, fout
                )
            else:
                rij.laatste_fout = fout
                rij.volgende_poging_op = nu + storing_stap(storing_pogingen)
                actie = "webhook_poging_mislukt"
                poging_detail["fout"] = fout
                poging_detail["volgende_poging_op"] = rij.volgende_poging_op.isoformat()
                rapport.poging_mislukt += 1
                rapport.fouten.append(
                    f"{referentie_tekst}: poging {storing_pogingen} mislukt — {fout} — volgende poging "
                    f"{rij.volgende_poging_op:%d-%m %H:%M} UTC"
                )
                rapport.per_rij[rij.id] = f"poging {storing_pogingen} mislukt — {fout}"
                logger.warning("Webhook-rij %s storingspoging %s mislukt: %s", rij.id, storing_pogingen, fout)

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

    config = _config_of_overgeslagen(rapport)
    if config is None:
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
                            WebhookUitgaand.status.in_(WEBHOOK_ACTIEVE_STATUSSEN),
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


def _config_of_overgeslagen(rapport: AfleverRapport) -> AfleverConfig | None:
    """Beide failsafes in één plek (toggle + config); None = overgeslagen mét reden in het rapport."""
    if not _aflevering_ingeschakeld():
        rapport.overgeslagen_reden = "aflevering staat uit (platform.webhook_instelling, default UIT)"
        return None
    config = haal_aflever_config_op()
    if config is None:
        rapport.overgeslagen_reden = (
            "onvoldoende geconfigureerd (webhook_doel_url en/of WEBHOOK_HMAC_SECRET ontbreekt) — "
            "rijen blijven openstaand"
        )
    return config


def lever_rijen_direct_af(
    *,
    rij_ids: list[uuid.UUID],
    administratie_id: uuid.UUID,
    nu: datetime | None = None,
    transport: httpx.BaseTransport | None = None,
) -> AfleverRapport:
    """Eén afleverronde voor precies deze outbox-rijen van één administratie (CLI `webhook-herzenden --afleveren`,
    24-09): dezelfde `_lever_rij_af` als de gewone run (claim FOR UPDATE SKIP LOCKED, zelfde failsafes, zelfde audit),
    maar direct ná het terugzetten en mét de uitkomst per rij in `rapport.per_rij` — zodat de herzending zichzelf
    bewijst in dezelfde job-executie in plaats van pas in een scheduler-log vijf minuten later. Alleen rijen die op dit
    moment `openstaand` zijn worden geraakt (de claim controleert de status); een rij die de scheduler intussen al
    pakte, blijft ongemoeid en krijgt "niet geraakt (al geclaimd of niet openstaand)"."""
    nu = nu or datetime.now(UTC)
    rapport = AfleverRapport()
    config = _config_of_overgeslagen(rapport)
    if config is None:
        return rapport
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        is_vastgoed = bool(administratie is not None and administratie.is_vastgoed)
    with httpx.Client(transport=transport, timeout=settings.webhook_timeout_seconds) as client:
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
            rapport.per_rij.setdefault(rij_id, "niet geraakt (al geclaimd of niet openstaand)")
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
                rij.wacht_op_ontvanger_sinds = None
                rij.wacht_pogingen = 0
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


@dataclass(frozen=True)
class HerzendRij:
    """Eén outbox-rij in het herzend-overzicht (dry-run én uitvoering)."""

    outbox_id: uuid.UUID | None
    referentie: str
    event: str | None
    status_voor: str | None
    rlz_document_id: str | None
    volgnummer: int | None
    afgeleverd_op: datetime | None
    pogingen: int | None
    uitkomst: str  # "herzonden" | "zou herzenden (dry-run)" | "niet gevonden" | "al openstaand — niet herzonden"


def herzend_afgeleverd(
    *,
    actor_id: uuid.UUID,
    administratie_id: uuid.UUID,
    referenties: list[str],
    reden: str,
    event: str = "factuur_geboekt",
    dry_run: bool = True,
) -> list[HerzendRij]:
    """Herzend-actie (Platform OPEN_ITEMS regel 13, vastgoed-verzoek 21-09): AFGELEVERDE outbox-rijen van één
    administratie, gekozen op `payload.data.referentie`, terug naar `openstaand` zodat de gewone afleveraar ze opnieuw
    verstuurt — zelfde payload (dus zelfde `rlz_document_id`/`volgnummer`), verse timestamp/nonce/HMAC per poging.
    Nooit een payload wijzigen. Rijen mét status `afgeleverd` én `mislukt` (24-09: een door de ontvanger genegeerde rij
    staat `mislukt` — ná een fix aan de ontvangerkant is herzenden op referentie hét herstel, `webhook-redrive` blijft
    voor de kale dead-letter zonder referentie); een rij die al `openstaand` is wordt niet dubbel teruggezet; een
    referentie zonder rij komt zichtbaar terug als "niet gevonden".
    Audit `webhook_herzonden` per rij mét de aanroepende Beheerder als actor en de reden. `dry_run=True` schrijft niets.
    Herbruikbaar: geen eenmalige SQL — élke volgende herzending (nieuwe Vastly-fix, ander event) loopt hierlangs."""
    reden = (reden or "").strip()
    if not dry_run and len(reden) < 5:
        raise ValueError("reden is verplicht bij herzenden (minimaal 5 tekens)")
    gezocht = [r.strip() for r in referenties if r and r.strip()]
    uit: list[HerzendRij] = []
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        query = (
            select(WebhookUitgaand)
            .outerjoin(Document, WebhookUitgaand.document_id == Document.id)
            .where(
                func.coalesce(WebhookUitgaand.administratie_id, Document.administratie_id) == administratie_id,
                WebhookUitgaand.event == event,
                WebhookUitgaand.payload["data"]["referentie"].astext.in_(gezocht),
            )
            .order_by(WebhookUitgaand.aangemaakt_op)
        )
        if not dry_run:
            query = query.with_for_update(of=WebhookUitgaand, skip_locked=True)
        rijen = list(session.scalars(query))
        per_ref: dict[str, list[WebhookUitgaand]] = {r: [] for r in gezocht}
        for rij in rijen:
            per_ref.setdefault(str((rij.payload.get("data") or {}).get("referentie")), []).append(rij)
        for ref in gezocht:
            kandidaten = per_ref.get(ref) or []
            if not kandidaten:
                uit.append(
                    HerzendRij(
                        outbox_id=None, referentie=ref, event=event, status_voor=None, rlz_document_id=None,
                        volgnummer=None, afgeleverd_op=None, pogingen=None, uitkomst="niet gevonden",
                    )
                )
                continue
            for rij in kandidaten:
                data = rij.payload.get("data") or {}
                volg = data.get("volgnummer")
                basis = dict(
                    outbox_id=rij.id,
                    referentie=ref,
                    event=rij.event,
                    status_voor=rij.status,
                    rlz_document_id=str(data.get("rlz_document_id")) if data.get("rlz_document_id") else None,
                    volgnummer=int(volg) if volg is not None else None,
                    afgeleverd_op=rij.afgeleverd_op,
                    pogingen=rij.pogingen,
                )
                if rij.status in WEBHOOK_ACTIEVE_STATUSSEN:
                    # 02-10: ook een rij die op de ontvanger wacht is al onderweg — niet dubbel terugzetten.
                    uit.append(HerzendRij(**basis, uitkomst="al openstaand — niet herzonden"))
                    continue
                if dry_run:
                    uit.append(HerzendRij(**basis, uitkomst="zou herzenden (dry-run)"))
                    continue
                oud = {
                    "status": rij.status,
                    "pogingen": rij.pogingen,
                    "afgeleverd_op": rij.afgeleverd_op.isoformat() if rij.afgeleverd_op else None,
                    "laatste_poging_op": rij.laatste_poging_op.isoformat() if rij.laatste_poging_op else None,
                    "laatste_fout": rij.laatste_fout,
                }
                rij.status = WebhookStatus.OPENSTAAND.value
                rij.pogingen = 0
                rij.volgende_poging_op = None
                rij.afgeleverd_op = None
                rij.laatste_fout = None
                rij.wacht_op_ontvanger_sinds = None
                rij.wacht_pogingen = 0
                record_audit_event(
                    session,
                    actor_id=actor_id,
                    module="boekhouding",
                    tabel="webhook_uitgaand",
                    record_id=rij.id,
                    actie="webhook_herzonden",
                    correlatie_id=uuid.uuid4(),
                    oude_waarde=oud,
                    nieuwe_waarde={
                        "status": WebhookStatus.OPENSTAAND.value,
                        "pogingen": 0,
                        "referentie": ref,
                        "rlz_document_id": basis["rlz_document_id"],
                        "volgnummer": basis["volgnummer"],
                        "reden": reden,
                    },
                    administratie_id=administratie_id,
                )
                logger.info("Webhook-rij %s (referentie %s) herzonden → openstaand (%s)", rij.id, ref, reden)
                uit.append(HerzendRij(**basis, uitkomst="herzonden"))
    return uit


class NuOpnieuwNietMogelijk(Exception):
    """"Nu opnieuw" op een rij die niet (meer) wacht en niet door het wachten mislukt is — reden in de melding."""


@dataclass(frozen=True)
class NuOpnieuwResultaat:
    outbox_id: uuid.UUID
    status_voor: str
    status_na: str
    uitkomst: str


def nu_opnieuw(
    *,
    actor_id: uuid.UUID,
    administratie_id: uuid.UUID,
    outbox_id: uuid.UUID,
    nu: datetime | None = None,
    transport: httpx.BaseTransport | None = None,
) -> NuOpnieuwResultaat:
    """Handeling "Nu opnieuw" (run A 02-10 punt 17) op een rij die op de ontvanger wacht (`wacht_op_ontvanger`) of ná
    14 dagen wachten `mislukt` is: één directe afleverronde, buiten de cadans om — ná de melding van Vastly dat de
    koppeling hersteld is hoeft niemand op de volgende cadansstap te wachten. Een mens-besluit: audit
    `webhook_nu_opnieuw` mét de actor. Op een verlopen rij begint de 14-dagen-telling opnieuw (de rij gaat terug naar
    `openstaand`; antwoordt de ontvanger wéér 409, dan wacht ze opnieuw mét een verse `wacht_op_ontvanger_sinds`).
    Sinds 02-10 avond (punt 17a) geldt dezelfde handeling voor een rij die ná de 7-dagen-storingscadans of door een
    4xx-weigering `mislukt` is (`is_verlopen_of_geweigerd`): terug naar `openstaand` mét een vers storingsbudget.
    Een rij die al gewoon openstaand/afgeleverd is, of mislukt om een andere reden (genegeerd, geen vastgoed, oude
    dead-letter), hoort hier niet (409 in de router — daar is webhook-herzenden/-redrive de route)."""
    nu = nu or datetime.now(UTC)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij = session.scalars(
            select(WebhookUitgaand)
            .outerjoin(Document, WebhookUitgaand.document_id == Document.id)
            .where(
                WebhookUitgaand.id == outbox_id,
                func.coalesce(WebhookUitgaand.administratie_id, Document.administratie_id) == administratie_id,
            )
            .with_for_update(of=WebhookUitgaand)
        ).one_or_none()
        if rij is None:
            raise LookupError("outbox-rij niet gevonden in deze administratie")
        status_voor = rij.status
        verlopen = (
            rij.status == WebhookStatus.MISLUKT.value and rij.wacht_op_ontvanger_sinds is not None
        ) or is_verlopen_of_geweigerd(rij.status, rij.laatste_fout)
        if rij.status != WebhookStatus.WACHT_OP_ONTVANGER.value and not verlopen:
            raise NuOpnieuwNietMogelijk(
                f"rij staat op {rij.status} en wacht niet op de ontvanger — 'Nu opnieuw' geldt alleen voor een rij die "
                "wacht, ná 14 dagen wachten mislukt is, of ná de 7-dagen-storingscadans / een 4xx-weigering mislukt is "
                "(anders: webhook-herzenden / webhook-redrive)"
            )
        sinds_oud = rij.wacht_op_ontvanger_sinds
        oud = {
            "status": rij.status,
            "wacht_op_ontvanger_sinds": sinds_oud.isoformat() if sinds_oud else None,
            "wacht_pogingen": rij.wacht_pogingen,
            "volgende_poging_op": rij.volgende_poging_op.isoformat() if rij.volgende_poging_op else None,
            "laatste_fout": rij.laatste_fout,
        }
        if verlopen:
            rij.status = WebhookStatus.OPENSTAAND.value
            rij.wacht_op_ontvanger_sinds = None
            rij.wacht_pogingen = 0
            # Vers storingsbudget (7 dagen): een mens-klik is een nieuw begin, net als herzenden/redrive.
            rij.pogingen = 0
        rij.volgende_poging_op = None
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="webhook_uitgaand",
            record_id=rij.id,
            actie="webhook_nu_opnieuw",
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde={"status": rij.status, "referentie": (rij.payload.get("data") or {}).get("referentie")},
            administratie_id=administratie_id,
        )
    rapport = lever_rijen_direct_af(rij_ids=[outbox_id], administratie_id=administratie_id, nu=nu, transport=transport)
    if rapport.overgeslagen_reden:
        uitkomst = f"niet verstuurd — {rapport.overgeslagen_reden}"
    else:
        uitkomst = rapport.per_rij.get(outbox_id, "niet geraakt (al geclaimd)")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        status_na = session.get(WebhookUitgaand, outbox_id).status  # type: ignore[union-attr]
    return NuOpnieuwResultaat(outbox_id=outbox_id, status_voor=status_voor, status_na=status_na, uitkomst=uitkomst)


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
                if (
                    rapport.afgeleverd
                    or rapport.poging_mislukt
                    or rapport.storing_verlopen
                    or rapport.wacht_op_ontvanger
                ):
                    logger.info(
                        "Webhook-afleveraar: %s afgeleverd, %s poging(en) mislukt, %s ná 7 dagen mislukt, %s wacht(en)",
                        rapport.afgeleverd,
                        rapport.poging_mislukt,
                        rapport.storing_verlopen,
                        rapport.wacht_op_ontvanger,
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
    (de config-failsafe laat rijen dan sowieso openstaand).

    In productie start de lus bewust NIET (GCP-draaiboek F2.4): Cloud Run throttlet CPU buiten
    request-afhandeling en schaalt naar nul, dus een pollende achtergrondthread is daar
    onbetrouwbaar — de aflevering draait er als Cloud Scheduler → Cloud Run-job op dezelfde
    verwerk-functie (`python -m app.cli webhook-afleveren`, F3)."""
    global _afleveraar
    if settings.environment == "production":
        logger.info("In-process webhook-afleveraar niet gestart (production — Cloud Run-job levert af, F3)")
        return
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
