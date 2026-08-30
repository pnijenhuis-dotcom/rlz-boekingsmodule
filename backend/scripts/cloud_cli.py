#!/usr/bin/env python3
"""Dunne wrapper om een `app.cli`-commando tegen de CLOUD-DB te draaien vanaf deze Mac (recept
memory "voorraad-BV's alleen in de cloud" + verkenning/poc_voorraad_uitstroom.py, 29/30-08).

Waarom: de vijf voorraad-administraties bestaan alleen in rlz-sql2; CLI-runs ertegen lopen via de
Cloud SQL Auth Proxy (5434) en de credential-store-unwrap via KMS. Zijn de Application Default
Credentials verlopen ("Reauthentication is needed"), dan gebruikt deze wrapper de actieve
gcloud-GEBRUIKERStoken (`gcloud auth print-access-token`; nooit geprint of opgeslagen) — alleen
unwrap, er wordt niets gewrapt. Failsafes: nooit per ongeluk tegen de lokale dev-DB (5433).

Draaien (proxy eerst, gcloud ingelogd, secrets leesbaar):
    cloud-sql-proxy rlz-boekhouding:europe-west4:rlz-sql2 --port 5434 --gcloud-auth &
    cd backend
    APP_DATABASE_URL="postgresql+psycopg://boekhouding_app:\
$(gcloud secrets versions access latest --secret=APP_DB_PASSWORD)@127.0.0.1:5434/boekhouding" \
    KMS_MASTERKEY_SLEUTEL="projects/rlz-boekhouding/locations/europe-west4/keyRings/rlz/cryptoKeys/masterkey" \
    ANTHROPIC_API_KEY="$(gcloud secrets versions access latest --secret=ANTHROPIC_API_KEY)" \
        .venv/bin/python scripts/cloud_cli.py voorraad-hernormaliseer
(ANTHROPIC_API_KEY = het productie-secret zodat de AI-kostenmeter in de cloud-DB klopt; weglaten =
geen AI-normalisatie, alleen het deterministische pad.) Voorwaarde: de cloud-DB staat op de
migratie-head die de code verwacht (deploy-pipeline: migratie-job vóór de revisie)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _failsafes() -> None:
    url = os.environ.get("APP_DATABASE_URL", "")
    if not url:
        raise SystemExit("FAILSAFE: APP_DATABASE_URL niet gezet — zie docstring. Gestopt.")
    if ":5433/" in url or "localhost:5433" in url:
        raise SystemExit("FAILSAFE: APP_DATABASE_URL wijst naar de lokale dev-DB (5433); de cloud-proxy staat op 5434.")
    if not os.environ.get("KMS_MASTERKEY_SLEUTEL"):
        raise SystemExit(
            "FAILSAFE: KMS_MASTERKEY_SLEUTEL niet gezet — de cloud-credential-store is alleen via KMS te ontsleutelen."
        )
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "LET OP: ANTHROPIC_API_KEY niet gezet — alleen het deterministische pad, geen AI-normalisatie.",
            file=sys.stderr,
        )


def _kms_via_gcloud_gebruiker() -> None:
    from google.cloud import kms
    from google.oauth2.credentials import Credentials

    from app.security import envelope

    token = subprocess.run(["gcloud", "auth", "print-access-token"], check=True, capture_output=True, text=True).stdout
    client = kms.KeyManagementServiceClient(credentials=Credentials(token=token.strip()))
    provider = envelope.KmsMasterKeyProvider(os.environ["KMS_MASTERKEY_SLEUTEL"], client=client)
    envelope.standaard_masterkey_provider = lambda: provider  # type: ignore[assignment]


def main(argv: list[str]) -> int:
    _failsafes()
    if not argv:
        raise SystemExit(
            "Gebruik: cloud_cli.py <app.cli-commando> [args] — bv. voorraad-hernormaliseer [--administratie-id X]"
        )
    _kms_via_gcloud_gebruiker()
    from app import cli

    return cli.main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
