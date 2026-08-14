#!/usr/bin/env python3
"""F4-kanaaltest: verifieert het INKOMENDE projectaanvraag-koppelvlak
(POST /koppelvlak/vastgoed/projectaanvragen) van buitenaf, precies zoals vastgoed het
aanroept — HMAC-SHA256 over (timestamp, nonce, canonieke data-JSON), koppelcontract §5 v1.15.
Draaiboek: docs/F4_ACTIVATIE_RUNBOOK.md.

Bewust standalone (alleen stdlib): dit script moet op de cutover-dag overal draaien,
zonder backend-venv. De handtekeningvorm is het contract zelf; drift valt direct op als
de "geldig"-check een 401 krijgt.

Twee modi:

  hmac      (default) — GEEN side-effects, kan tegen élke omgeving (ook productie):
            gebruikt een niet-bestaande administratie, dus het bewijs stopt bij de
            scope-check. Toetst: geldig secret → 404 administratie_onbekend (dus de
            HMAC-verificatie slaagde), fout secret → 401, verouderde timestamp → 400.
  volledig  — end-to-end mét RLZ-write: maakt (idempotent) het project
            "TEST F4 Kanaaltest" aan. ALLEEN tegen de RLZ-TEST-administratie draaien
            (is_vastgoed moet daar tijdelijk aan staan — runbook stap 7). Toetst ook
            herlevering (zelfde antwoord) en nonce-replay-weigering (409).

Secret via de env-var PROJECTAANVRAAG_HMAC_SECRET of een stille prompt — nooit als
argument (procesargumenten zijn zichtbaar in `ps`; besluit 0012: nooit in code/logs/chat).

Voorbeelden:
  # Lokale dev (dev-fallback-secret wordt automatisch gebruikt):
  python3 scripts/f4_kanaaltest.py --url http://localhost:8000 --dev

  # Cloud, veilig (geen side-effects):
  PROJECTAANVRAAG_HMAC_SECRET=... python3 scripts/f4_kanaaltest.py \
      --url https://app.administratiekantoornijenhuis.nl

  # End-to-end tegen de TEST-administratie:
  python3 scripts/f4_kanaaltest.py --url ... --mode volledig --administratie-id <uuid>
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac as hmac_module
import json
import os
import secrets
import sys
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta

ENDPOINT_PAD = "/koppelvlak/vastgoed/projectaanvragen"
DEV_SECRET = "dev-only-insecure-projectaanvraag-hmac-secret"
SCHEMA_VERSION = "1.0"
EVENT = "projectaanvraag"
# Vaste pand_referentie: herhaald draaien maakt nooit een tweede project (idempotente motor,
# bestond_al is een normale geslaagde uitkomst).
TEST_PAND_REFERENTIE = "TEST-F4-KANAALTEST"
TEST_NAAM_INVOER = "TEST F4 Kanaaltest"


def canonical_json(data: dict) -> str:
    """Identiek aan app/documenten/webhook.py::_canonical_json — de bytes moeten exact
    matchen met wat de ontvanger hertekent."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def bereken_handtekening(secret: str, payload_json: str, timestamp: str, nonce: str) -> str:
    bericht = f"{timestamp}.{nonce}.{payload_json}".encode()
    return hmac_module.new(secret.encode(), bericht, hashlib.sha256).hexdigest()


def bouw_envelope(
    secret: str,
    administratie_id: str,
    *,
    bericht_id: str | None = None,
    pand_referentie: str = TEST_PAND_REFERENTIE,
    naam_invoer: str = TEST_NAAM_INVOER,
    timestamp: str | None = None,
    nonce: str | None = None,
) -> dict:
    data = {
        "bericht_id": bericht_id or str(uuid.uuid4()),
        "administratie_id": administratie_id,
        "pand_referentie": pand_referentie,
        "naam_invoer": naam_invoer,
    }
    timestamp = timestamp or datetime.now(UTC).isoformat()
    nonce = nonce or secrets.token_hex(16)
    return {
        "schema_version": SCHEMA_VERSION,
        "event": EVENT,
        "timestamp": timestamp,
        "nonce": nonce,
        "data": data,
        "handtekening": bereken_handtekening(secret, canonical_json(data), timestamp, nonce),
    }


def post(url: str, envelope: dict, timeout: float = 30.0) -> tuple[int, dict]:
    verzoek = urllib.request.Request(
        url,
        data=json.dumps(envelope).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(verzoek, timeout=timeout) as antwoord:
            return antwoord.status, json.loads(antwoord.read().decode() or "{}")
    except urllib.error.HTTPError as fout:
        try:
            body = json.loads(fout.read().decode() or "{}")
        except json.JSONDecodeError:
            body = {}
        return fout.code, body


def foutcode(body: dict) -> str | None:
    detail = body.get("detail")
    return detail.get("code") if isinstance(detail, dict) else None


class Toetser:
    def __init__(self) -> None:
        self.gefaald = 0

    def check(self, naam: str, conditie: bool, detail: str) -> None:
        if conditie:
            print(f"  PASS  {naam}")
        else:
            self.gefaald += 1
            print(f"  FAIL  {naam} — {detail}")


def modus_hmac(url: str, secret: str, toetser: Toetser) -> None:
    """Geen side-effects: de administratie bestaat niet, dus na een geslaagde
    HMAC-verificatie stopt het endpoint hard op de scope-check (404) — er wordt niets
    geregistreerd en er gaat geen RLZ-call uit."""
    onbekende_administratie = str(uuid.uuid4())

    status, body = post(url, bouw_envelope(secret, onbekende_administratie))
    toetser.check(
        "geldig secret → 404 administratie_onbekend (HMAC-verificatie slaagde)",
        status == 404 and foutcode(body) == "administratie_onbekend",
        f"kreeg {status} {foutcode(body)!r} — 401 = secret-mismatch beide kanten checken",
    )

    status, body = post(url, bouw_envelope(secret + "-fout", onbekende_administratie))
    toetser.check(
        "fout secret → 401 handtekening_ongeldig",
        status == 401 and foutcode(body) == "handtekening_ongeldig",
        f"kreeg {status} {foutcode(body)!r}",
    )

    oud = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    status, body = post(url, bouw_envelope(secret, onbekende_administratie, timestamp=oud))
    toetser.check(
        "timestamp 10 min oud → 400 timestamp_buiten_venster (replay-venster)",
        status == 400 and foutcode(body) == "timestamp_buiten_venster",
        f"kreeg {status} {foutcode(body)!r}",
    )


def modus_volledig(url: str, secret: str, administratie_id: str, toetser: Toetser) -> None:
    """End-to-end mét RLZ-write — alleen tegen de RLZ-TEST-administratie (is_vastgoed
    tijdelijk aan). Het testproject blijft staan (nooit verwijderen in RLZ)."""
    envelope = bouw_envelope(secret, administratie_id)

    status, body = post(url, envelope)
    toetser.check(
        "geldige aanvraag → 200 aangemaakt/bestond_al",
        status == 200 and body.get("status") in ("aangemaakt", "bestond_al"),
        f"kreeg {status} {body.get('status')!r} {foutcode(body)!r}",
    )
    rlz_project_id = body.get("rlz_project_id")

    status, herhaal = post(url, envelope)
    toetser.check(
        "exacte herlevering → 200, zelfde rlz_project_id (idempotentie op bericht_id)",
        status == 200 and herhaal.get("rlz_project_id") == rlz_project_id,
        f"kreeg {status} {herhaal.get('rlz_project_id')!r} (verwacht {rlz_project_id!r})",
    )

    status, body = post(
        url, bouw_envelope(secret, administratie_id, nonce=envelope["nonce"])
    )
    toetser.check(
        "zelfde nonce, nieuw bericht_id → 409 nonce_hergebruikt (replay-weigering)",
        status == 409 and foutcode(body) == "nonce_hergebruikt",
        f"kreeg {status} {foutcode(body)!r}",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True, help="Basis-URL van de backend (zonder pad)")
    parser.add_argument("--mode", choices=("hmac", "volledig"), default="hmac")
    parser.add_argument(
        "--administratie-id",
        help="Vereist bij --mode volledig: de RLZ-TEST-administratie (is_vastgoed tijdelijk aan)",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Gebruik het dev-fallback-secret (alleen zinvol tegen een lokale dev-backend)",
    )
    args = parser.parse_args()

    if args.mode == "volledig" and not args.administratie_id:
        parser.error("--mode volledig vereist --administratie-id")

    if args.dev:
        secret = DEV_SECRET
    else:
        secret = os.environ.get("PROJECTAANVRAAG_HMAC_SECRET") or getpass.getpass(
            "PROJECTAANVRAAG_HMAC_SECRET (invoer blijft onzichtbaar): "
        )
    if not secret:
        print("Geen secret — afgebroken.")
        return 2

    url = args.url.rstrip("/") + ENDPOINT_PAD
    print(f"Kanaaltest ({args.mode}) tegen {url}")
    toetser = Toetser()
    if args.mode == "hmac":
        modus_hmac(url, secret, toetser)
    else:
        modus_volledig(url, secret, args.administratie_id, toetser)

    if toetser.gefaald:
        print(f"RESULTAAT: {toetser.gefaald} check(s) GEFAALD")
        return 1
    print("RESULTAAT: alle checks geslaagd")
    return 0


if __name__ == "__main__":
    sys.exit(main())
