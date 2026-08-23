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

# 1.1 (koppelcontract v1.14, kostenflow-randvraag b): `volgnummer` per boekstand in de data —
# per rlz_document_id monotoon oplopend over factuur_geboekt- én factuur_gestorneerd-events
# (één reeks, app/documenten/boekstand.py). Ontvanger: idempotent per (rlz_document_id,
# volgnummer), hoogste volgnummer wint; 1.0-events zonder volgnummer gelden als volgnummer 0.
# 1.2 (koppelcontract v1.17, akkoord Vastly 2026-08-23): OPTIONEEL veld
# `corrigeert_document_id` — het rlz_document_id van het origineel, UITSLUITEND aanwezig op
# tegenboeking-events (creditnota-norm §3a); de herboeking bij "tegenboeken én opnieuw
# boeken" draagt het veld níét (gewoon nieuw document). Additief: events zonder het veld
# blijven geldig, oude events/replays ongewijzigd. Verwijst het id naar een bij Vastly
# onbekend origineel (van vóór de webhook-activatie), dan droppen zij het event niet maar
# vallen terug op hun gemarkeerde handmatige stap (gedragsafspraak §3a).
WEBHOOK_SCHEMA_VERSION = "1.2"
FACTUUR_GEBOEKT_EVENT = "factuur_geboekt"
# Storno-event (koppelcontract v1.14, kostenflow-randvraag c — harde eis vastgoed-S2): zelfde
# kanaal/envelope/HMAC, eigen event-naam + eigen schemaversie; het volgnummer zit in dezelfde
# reeks als factuur_geboekt zodat de ontvanger boeken→storno→herboeken kan ordenen.
FACTUUR_GESTORNEERD_EVENT = "factuur_gestorneerd"
GESTORNEERD_SCHEMA_VERSION = "1.0"
# Twee bronnen, eerlijk benoemd in de payload: een storno vanuit deze module is een direct
# event; een storno in de RLZ-UI wordt pas bij de eerstvolgende reconciliatie-run gezien
# (latentie = reconciliatie-cadans, expliciet in koppelcontract §3).
GESTORNEERD_BRON_MODULE = "module_storno"
GESTORNEERD_BRON_RLZ_UI = "rlz_ui_detectie"
# Tier-model-terugkoppeling naar Vastly (koppelcontract §3, velddefinitie DEFINITIEF v1.11):
# zelfde kanaal, zelfde envelope/HMAC, eigen event-type én een EIGEN schemaversie
# (registers/schema-versions.md: de v1.10-payload zonder bedragen is vervallen, de bump is
# verplicht zodat een ontvanger op de oude versie expliciet weigert i.p.v. verkeerd parsen).
FACTUUR_AFGELETTERD_EVENT = "factuur_afgeletterd"
AFGELETTERD_SCHEMA_VERSION = "2.0"

# Scenario-enum van het afgeletterd-event (§3 v1.11): deelbetalingen genereren wél een event
# (G-rekening-split is de standaardcase) en ont-afletteren is expliciet — nooit stil.
AFGELETTERD_SCENARIO_VOLLEDIG = "afgeletterd"
AFGELETTERD_SCENARIO_DEEL = "deel_afgeletterd"
AFGELETTERD_SCENARIO_ONT = "ont_afgeletterd"
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
    volgnummer: int,
    regels: list[WebhookRegel],
    corrigeert_document_id: uuid.UUID | None = None,
) -> dict:
    """ONGETEKENDE payload voor het "factuur geboekt"-event (koppelcontract §3 + CLAUDE.md-
    koppelvlak: RLZ-GUID, project-GUID, datum, bedragen per regel, GB, leverancier, omschrijving,
    adminId). De aanroeper (app/documenten/boeken.py) legt dit vast in
    boekhouding.webhook_uitgaand; timestamp/nonce/handtekening horen hier bewust NIET in — die
    berekent de afleveraar pas per verzendpoging (onderteken_voor_verzending), anders wijst het
    ~5 min-replay-venster van de ontvanger elke aflevering later dan ~5 min na het boeken
    (outbox-retry!) per definitie af.

    `corrigeert_document_id` (schema 1.2, §3a): alléén het tegenboek-pad geeft dit mee — het
    veld komt dan als extra sleutel in de data en ontbreekt in álle andere events (additief,
    backward-compatible; nooit als null meesturen)."""
    data = {
        "administratie_id": str(administratie_id),
        "rlz_admin_id": rlz_admin_id,
        "rlz_document_id": str(rlz_document_id),
        "rlz_boekstuknummer": rlz_boekstuknummer,
        "datum": factuurdatum.isoformat(),
        "leverancier": {"vendor_id": str(vendor_id), "naam": vendor_naam},
        "referentie": referentie,
        "volgnummer": volgnummer,
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
    if corrigeert_document_id is not None:
        data["corrigeert_document_id"] = str(corrigeert_document_id)
    return {
        "schema_version": WEBHOOK_SCHEMA_VERSION,
        "event": FACTUUR_GEBOEKT_EVENT,
        "data": data,
    }


def bouw_factuur_geboekt_verkoop_payload(
    *,
    administratie_id: uuid.UUID,
    rlz_admin_id: str,
    rlz_document_id: uuid.UUID,
    rlz_boekstuknummer: str | None,
    factuurdatum: date,
    customer_id: uuid.UUID,
    debiteur_naam: str | None,
    referentie: str,
    is_creditnota: bool,
    volgnummer: int,
    regels: list[WebhookRegel],
) -> dict:
    """ONGETEKENDE payload voor het "factuur geboekt"-event bij een VASTLY-VERKOOP-boeking
    (koppelcontract §3 v1.10: `referentie` = het Vastly-factuurnummer — vastgoeds koppelsleutel
    naar de eigen huurfactuur; bevestigd v1.11 punt 6). Zelfde event + envelope als de
    inkoopvariant; de tegenpartij is hier een debiteur (`debiteur` i.p.v. `leverancier`) en
    `soort` maakt de stroom expliciet herkenbaar voor de ontvanger. De formele opname van deze
    verkoop-veldvorm in §3 is een open contract-actie (vastgoed verwerkt nu alleen de
    verkoop-badge op `referentie`); aflevering staat sowieso default UIT."""
    data = {
        "soort": "verkoopfactuur",
        "administratie_id": str(administratie_id),
        "rlz_admin_id": rlz_admin_id,
        "rlz_document_id": str(rlz_document_id),
        "rlz_boekstuknummer": rlz_boekstuknummer,
        "datum": factuurdatum.isoformat(),
        "debiteur": {"customer_id": str(customer_id), "naam": debiteur_naam},
        "referentie": referentie,
        "is_creditnota": is_creditnota,
        "volgnummer": volgnummer,
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


def bouw_factuur_gestorneerd_payload(
    *,
    administratie_id: uuid.UUID,
    rlz_admin_id: str,
    rlz_document_id: uuid.UUID,
    rlz_boekstuknummer: str | None,
    referentie: str | None,
    volgnummer: int,
    bron: str,
    reden: str | None,
    gestorneerd_op: datetime,
) -> dict:
    """ONGETEKENDE payload voor het "factuur gestorneerd"-event (koppelcontract §3 v1.14,
    kostenflow-randvraag c — harde eis vóór vastgoeds auto-bevestiging S2):

    - `volgnummer` zit in DEZELFDE reeks als factuur_geboekt (per rlz_document_id): boeken=1,
      storno=2, herboeken=3 … — de ontvanger is idempotent per (rlz_document_id, volgnummer)
      en de hoogste stand wint, ongeacht afleveringsvolgorde.
    - `bron`: module_storno (storno vanuit deze module — direct event) of rlz_ui_detectie
      (actie 19 in de RLZ-UI, gezien door de reconciliatie — latentie = reconciliatie-cadans,
      expliciet in het contract; nooit stil).
    - `reden` alleen gevuld bij module_storno (daar is de reden verplicht); een RLZ-UI-storno
      draagt geen reden — RLZ registreert die niet.
    - `gestorneerd_op` is het actie- (module) of waarnemingsmoment (detectie)."""
    data = {
        "administratie_id": str(administratie_id),
        "rlz_admin_id": rlz_admin_id,
        "rlz_document_id": str(rlz_document_id),
        "rlz_boekstuknummer": rlz_boekstuknummer,
        "referentie": referentie,
        "volgnummer": volgnummer,
        "bron": bron,
        "reden": reden,
        "gestorneerd_op": gestorneerd_op.isoformat(),
    }
    return {
        "schema_version": GESTORNEERD_SCHEMA_VERSION,
        "event": FACTUUR_GESTORNEERD_EVENT,
        "data": data,
    }


def bouw_factuur_afgeletterd_payload(
    *,
    administratie_id: uuid.UUID,
    rlz_admin_id: str,
    rlz_document_id: uuid.UUID,
    rlz_boekstuknummer: str | None,
    referentie: str | None,
    volgnummer: int,
    betaald_bedrag: Decimal,
    open_bedrag: Decimal,
    scenario: str,
    afgeletterd_op: datetime,
) -> dict:
    """ONGETEKENDE payload voor het "factuur afgeletterd"-event — velddefinitie DEFINITIEF
    (koppelcontract §3 v1.11, besluit Peter 2026-08-08):

    - `betaald_bedrag` is CUMULATIEF betaald en `open_bedrag` wat er nog open staat — bron is
      altijd `BaseRemainingAmount`/OpenAmount, nooit `IsComplete` (bewezen stale na
      terugdraaien, api-verkenning schrijf-PoC).
    - `volgnummer` loopt per document monotoon op bij élke standwijziging; de ontvanger is
      idempotent per (rlz_document_id, volgnummer) — herlevering = no-op, en een gemiste
      tussenstand is onschadelijk omdat de bedragen cumulatief zijn.
    - `scenario`: afgeletterd | deel_afgeletterd (G-rekening-split = standaardcase) |
      ont_afgeletterd (in de RLZ-UI teruggedraaid — expliciet, nooit stil).
    - `afgeletterd_op` is het waarnemingsmoment van de standwijziging (onze sync).
    - Eigen `schema_version` (2.0): de v1.10-payload zonder bedragen is vervallen — een
      ontvanger op de oude versie weigert expliciet i.p.v. verkeerd parsen."""
    data = {
        "administratie_id": str(administratie_id),
        "rlz_admin_id": rlz_admin_id,
        "rlz_document_id": str(rlz_document_id),
        "rlz_boekstuknummer": rlz_boekstuknummer,
        "referentie": referentie,
        "volgnummer": volgnummer,
        "betaald_bedrag": str(betaald_bedrag),
        "open_bedrag": str(open_bedrag),
        "scenario": scenario,
        "afgeletterd_op": afgeletterd_op.isoformat(),
    }
    return {
        "schema_version": AFGELETTERD_SCHEMA_VERSION,
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
