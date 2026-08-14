"""Cloud-seed: accordeur-testaccount voor Peters iPhone-passkey-test (mini-opdracht 2026-08-14).

Doel van de test: activeringsflow (wachtwoord → ÉCHTE passkey → voorwaarden-akkoord) op de
cloud-omgeving met een lege wachtrij — de dev-stub is in productie hard uit (bedoeld) en
boeken kan in de cloud toch niet vóór onboarding. Dit script maakt daarom UITSLUITEND:
1. een test-administratie-rij (het schema eist er een voor de accordeur-scope; alle
   boek-/AI-/webhook-vlaggen default UIT, GEEN RLZ-credential in de credential-store);
2. het accordeur-account via de bestaande uitnodigingsflow (rol klant_accordeur, scope =
   die test-administratie) — print de ACTIVEERLINK.
Geen testdocumenten, geen accorderingslagen: een lege wachtrij is precies de bedoeling.

⚠️ VERGANKELIJK: deze seed-data (test-administratie + accordeur-account) verdwijnt bij de
tranche-2-restore van de lokale data naar de cloud — bewust, niets hiervan hoeft te blijven.

Draaien (patroon + failsafes cloud_bootstrap_beheerder.py — expliciete APP_DATABASE_URL,
poort 5433 geweigerd, geen .env geladen, herdraaibaar):
    cloud-sql-proxy rlz-boekhouding:europe-west4:rlz-sql --port 5434 &
    APP_DATABASE_URL="postgresql+psycopg://boekhouding_app:\
$(gcloud secrets versions access latest --secret=APP_DB_PASSWORD)@127.0.0.1:5434/boekhouding" \
        .venv/bin/python scripts/cloud_seed_accordeur.py --app-url https://<service-url>

Herdraaibaar: bestaat de accordeur al maar is die nog niet actief, dan komt er een verse
uitnodigingslink; is die al actief, dan doet het script niets. De actor voor de
uitnodigings-/audit-flow is de actieve Beheerder in de doel-database (geen hardcoded lokale
gebruikers-id's — de cloud kent andere id's dan dev)."""

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
ACCORDEUR_EMAIL = "accordeur-passkeytest@ak-nijenhuis.nl"  # lowercase = genormaliseerde vorm (migratie 0049)
ACCORDEUR_NAAM = "Passkey-test accordeur (iPhone Peter)"
TEST_ADMIN_RLZ_ID = "SEED-PASSKEYTEST"  # bewust géén echt RLZ-administratie-id
TEST_ADMIN_NAAM = "Test-administratie (passkey-test, verdwijnt bij tranche-2-restore)"


def _controleer_database_doel() -> None:
    """Zelfde failsafe als cloud_bootstrap_beheerder: vóór enige app-import (de engine bindt
    settings.app_database_url bij import) moet het doel expliciet zijn en nooit de lokale dev."""
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
        description="Seed een accordeur-testaccount (lege wachtrij) in de cloud-database en print de activeerlink."
    )
    parser.add_argument("--app-url", default=STANDAARD_APP_URL, dest="app_url")
    args = parser.parse_args()

    _controleer_database_doel()

    # Imports pas ná de failsafe: het app-pakket bindt de database-engine bij import.
    from sqlalchemy import select

    from app.auth import service as auth_service
    from app.db.models import Administratie, Gebruiker, GebruikerRol, GebruikerStatus, Uitnodiging
    from app.db.session import scoped_session

    # 1. Actor: de actieve Beheerder in de dóél-database (nooit een hardcoded lokale id).
    with scoped_session(None) as session:
        beheerder = session.scalars(
            select(Gebruiker).where(Gebruiker.rol == GebruikerRol.BEHEERDER, Gebruiker.status == GebruikerStatus.ACTIEF)
        ).first()
        if beheerder is None:
            print(
                "FOUT: geen actieve Beheerder in de doel-database — draai eerst "
                "cloud_bootstrap_beheerder.py en activeer dat account.",
                file=sys.stderr,
            )
            return 1
        beheerder_id = beheerder.id
        print(f"Actor: Beheerder {beheerder.e_mail} ({beheerder_id})")

    # 2. Test-administratie-rij (scope-anker; alle vlaggen default UIT, geen RLZ-credential).
    with scoped_session(None, actor_id=beheerder_id) as session:
        administratie = session.scalars(
            select(Administratie).where(Administratie.rlz_admin_id == TEST_ADMIN_RLZ_ID)
        ).one_or_none()
        if administratie is None:
            administratie_id = uuid.uuid4()
            session.add(Administratie(id=administratie_id, naam=TEST_ADMIN_NAAM, rlz_admin_id=TEST_ADMIN_RLZ_ID))
            print(f"Test-administratie aangemaakt: {TEST_ADMIN_NAAM} ({administratie_id})")
        else:
            administratie_id = administratie.id
            print(f"Test-administratie bestaat al ({administratie_id}).")

    # 3. Accordeur-account via de bestaande uitnodigingsflow — herdraaibaar.
    token: str | None = None
    with scoped_session(None, actor_id=beheerder_id) as session:
        bestaand = session.scalars(select(Gebruiker).where(Gebruiker.e_mail == ACCORDEUR_EMAIL)).one_or_none()
        if bestaand is not None:
            if bestaand.status == GebruikerStatus.ACTIEF:
                print(f"Accordeur bestaat al en is actief: {ACCORDEUR_EMAIL} — niets te doen.")
                return 0
            # Verse link voor een nog niet afgeronde activatie — zelfde hash-patroon als
            # auth_service; het token verlaat dit script alleen via stdout.
            token = secrets.token_urlsafe(32)
            session.add(
                Uitnodiging(
                    id=uuid.uuid4(),
                    gebruiker_id=bestaand.id,
                    token_hash=hashlib.sha256(token.encode()).hexdigest(),
                    aangemaakt_door=beheerder_id,
                    verloopt_op=datetime.now(UTC) + timedelta(hours=72),
                )
            )
            print(f"Nieuwe uitnodigingslink voor bestaande accordeur ({ACCORDEUR_EMAIL}).")

    if token is None:
        resultaat = auth_service.maak_uitnodiging(
            actor_id=beheerder_id,
            naam=ACCORDEUR_NAAM,
            e_mail=ACCORDEUR_EMAIL,
            rol=GebruikerRol.KLANT_ACCORDEUR,
            administratie_ids=[administratie_id],
        )
        token = resultaat.token
        print(f"Accordeur aangemaakt: {ACCORDEUR_EMAIL} ({resultaat.gebruiker_id})")

    print()
    print("ACTIVEERLINK accordeur (72 uur geldig, eenmalig — wachtwoord → échte passkey → akkoord):")
    print(f"  {args.app_url.rstrip('/')}/activeren?token={token}")
    print()
    print("NB: deze seed-data verdwijnt bij de tranche-2-restore — bewust vergankelijk.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
