"""Cloud-bootstrap eerste Beheerder (F2-slotverificatie, docs/GCP_UITROL.md §F2).

Elke VERSE omgeving (lege database) kent dit bootstrap-moment: er bestaat nog geen enkele
gebruiker, dus de normale Beheerder-only uitnodigingsflow kan nergens beginnen. Dit script
draait lokaal via de Cloud SQL Auth Proxy en hergebruikt de bestaande flows
(auth_service.bootstrap_eerste_beheerder — weigert zodra er al een Beheerder bestaat):
het maakt uitsluitend de gebruiker + een eenmalige uitnodigingsrij aan en print de
ACTIVEERLINK. Wachtwoord + TOTP stelt Peter zelf in via die link (de cloud is een verse
omgeving — bewust geen hergebruik van lokale secrets, en er verlaat geen wachtwoord dit
script; het eenmalige token in de link is het ontworpen kanaal, patroon
kliktest_accordeur_seed).

Draaien (zie GCP_UITROL §F2-slotverificatie voor het volledige recept):
    cloud-sql-proxy rlz-boekhouding:europe-west4:rlz-sql --port 5434 &
    APP_DATABASE_URL="postgresql+psycopg://boekhouding_app:<APP_DB_PASSWORD>@127.0.0.1:5434/boekhouding" \
        .venv/bin/python scripts/cloud_bootstrap_beheerder.py --app-url https://<service-url>

Idempotent in de bruikbare zin: bestaat de Beheerder al maar is de link verlopen zonder
activatie (status uitgenodigd), dan wordt een verse uitnodigingsrij uitgegeven; is hij al
actief, dan doet het script niets. Failsafes: APP_DATABASE_URL moet EXPLICIET gezet zijn
(nooit stil de lokale dev-database raken — het script laadt bewust geen enkel .env-bestand)
en poort 5433 (lokale PG16) wordt geweigerd."""

from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STANDAARD_APP_URL = "https://app.administratiekantoornijenhuis.nl"
STANDAARD_NAAM = "Peter Nijenhuis"
STANDAARD_EMAIL = "peter@ak-nijenhuis.nl"  # lowercase = de genormaliseerde vorm (migratie 0049)


def _controleer_database_doel() -> None:
    """Vóór enige app-import (de engine bindt settings.app_database_url bij import):
    de database-URL moet expliciet gezet zijn en mag niet de lokale dev-poort raken."""
    url = os.environ.get("APP_DATABASE_URL", "")
    if not url:
        raise SystemExit(
            "FAILSAFE: APP_DATABASE_URL is niet gezet. Dit script richt zich uitsluitend op "
            "een expliciet aangewezen (cloud-)database via de Cloud SQL Auth Proxy — zie de "
            "docstring voor het recept. Gestopt zonder database-verbinding."
        )
    if ":5433/" in url:
        raise SystemExit(
            "FAILSAFE: APP_DATABASE_URL wijst naar poort 5433 (de lokale PG16). De Auth "
            "Proxy-conventie is poort 5434 (GCP_UITROL §F1.2) — gestopt, niets gedaan."
        )
    print(f"Database-doel: {url.split('@')[-1]}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap de allereerste Beheerder in een verse (cloud-)omgeving en print de activeerlink."
    )
    parser.add_argument("--app-url", default=STANDAARD_APP_URL, dest="app_url",
                        help=f"Basis-URL van de draaiende app (default {STANDAARD_APP_URL}; "
                        "vóór het domein: de run.app-URL van de Cloud Run-service).")
    parser.add_argument("--naam", default=STANDAARD_NAAM)
    parser.add_argument("--e-mail", default=STANDAARD_EMAIL, dest="e_mail")
    args = parser.parse_args()

    _controleer_database_doel()

    # Imports pas ná de failsafe: het app-pakket bindt de database-engine bij import.
    from sqlalchemy import select

    from app.auth import service as auth_service
    from app.db.models import Gebruiker, GebruikerRol, GebruikerStatus, Uitnodiging
    from app.db.session import scoped_session

    token: str | None = None
    with scoped_session(None) as session:
        beheerder = session.scalars(
            select(Gebruiker).where(Gebruiker.rol == GebruikerRol.BEHEERDER)
        ).first()
        if beheerder is not None:
            if beheerder.status == GebruikerStatus.ACTIEF:
                print(f"Er is al een actieve Beheerder ({beheerder.e_mail}) — niets te doen.")
                return 0
            if beheerder.status != GebruikerStatus.UITGENODIGD:
                print(
                    f"FOUT: Beheerder {beheerder.e_mail} heeft status '{beheerder.status.value}' — "
                    "een half afgeronde activatie lost dit script bewust niet op (mens kijkt).",
                    file=sys.stderr,
                )
                return 1
            # Verse link voor een verlopen/kwijtgeraakte uitnodiging — zelfde hash-patroon
            # als auth_service; het token verlaat dit script alleen via stdout.
            token = secrets.token_urlsafe(32)
            session.add(
                Uitnodiging(
                    id=uuid.uuid4(),
                    gebruiker_id=beheerder.id,
                    token_hash=hashlib.sha256(token.encode()).hexdigest(),
                    aangemaakt_door=beheerder.id,
                    verloopt_op=datetime.now(UTC) + timedelta(hours=72),
                )
            )
            print(f"Nieuwe uitnodigingslink voor de bestaande, nog niet geactiveerde Beheerder ({beheerder.e_mail}).")

    if token is None:
        try:
            resultaat = auth_service.bootstrap_eerste_beheerder(naam=args.naam, e_mail=args.e_mail)
        except auth_service.AuthError as exc:
            print(f"FOUT: {exc}", file=sys.stderr)
            return 1
        token = resultaat.token
        print(f"Eerste Beheerder aangemaakt: {args.e_mail} ({resultaat.gebruiker_id})")

    print()
    print("ACTIVEERLINK (72 uur geldig, eenmalig — Peter stelt hiermee wachtwoord + TOTP in):")
    print(f"  {args.app_url.rstrip('/')}/activeren?token={token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
