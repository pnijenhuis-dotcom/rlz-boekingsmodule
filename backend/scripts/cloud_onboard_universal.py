"""Cloud-onboarding Universal Steigerbouw als VERGANKELIJKE TEST (besluit Peter 2026-08-21).

Doel: uren & meerwerk (veldwerker-flows, keuring, meerwerk, TestFlight-app) écht in de cloud
kunnen kliktesten. Alle cloud-testdata is vergankelijk en verdwijnt/wordt overschreven bij de
tranche-2-restore — bewust besluit, zie BESLISSINGEN "UNIVERSAL CLOUD-TEST-ONBOARDING".

Smoketest-protocol (onboarding-batch 15-08) MINUS de TEST-boeking:
1. admin-pin: de Universal-login (verkenning/.env) ziet exact de éne verwachte administratie;
2. platform.administratie-rij aanmaken (get-or-create) + credential server-side versleuteld de
   store in (envelope encryption — KMS VERPLICHT: een lokaal gewrapte credential kan de
   cloud-runtime nooit ontsleutelen, dus zonder KMS_MASTERKEY_SLEUTEL stopt dit script hard);
3. rechten-probe (10 endpoints, store-first credential-resolutie = meteen het bewijs dat de
   KMS-wrap klopt);
4. syncs Ledgers/TaxRates/Vendors/Projects (de échte Universal-projecten in de project_cache);
5. uren & meerwerk-opt-in AAN; álle overige toggles blijven UIT (verificatieblok print ze).

GEEN RLZ-writes: dit script doet uitsluitend GET's tegen RLZ (geen TEST-boeking — het echte
werk draait lokaal; boeken_ingeschakeld en alle autoboek-/afletter-toggles blijven UIT).

Draaien (patroon + failsafes cloud_seed_accordering.py):
    cloud-sql-proxy rlz-boekhouding:europe-west4:rlz-sql2 --port 5434 --gcloud-auth &
    cd backend
    APP_DATABASE_URL="postgresql+psycopg://boekhouding_app:\
$(gcloud secrets versions access latest --secret=APP_DB_PASSWORD)@127.0.0.1:5434/boekhouding" \
    KMS_MASTERKEY_SLEUTEL="projects/rlz-boekhouding/locations/europe-west4/keyRings/rlz/cryptoKeys/masterkey" \
        .venv/bin/python scripts/cloud_onboard_universal.py

Idempotent/herdraaibaar: administratie get-or-create, credential-upsert, probe-upsert,
sync-upserts, toggle idempotent. Actor = de actieve Beheerder in de doel-database."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from sqlalchemy import select, text

REPO = Path(__file__).resolve().parents[2]

UNIVERSAL_PREFIX = "UNIVERSAL"
UNIVERSAL_RLZ_ADMIN_ID = "3d954fc7-fe8d-4067-8cfb-73b4fe48c0ac"


def _controleer_database_doel() -> None:
    """Zelfde failsafe als de cloud-seed-scripts: expliciet doel, nooit de lokale dev-database."""
    url = os.environ.get("APP_DATABASE_URL", "")
    if not url:
        raise SystemExit(
            "FAILSAFE: APP_DATABASE_URL is niet gezet — zie de docstring voor het recept. "
            "Gestopt zonder database-verbinding."
        )
    if ":5433/" in url:
        raise SystemExit(
            "FAILSAFE: APP_DATABASE_URL wijst naar poort 5433 (lokale PG16). De Auth "
            "Proxy-conventie is poort 5434 — gestopt, niets gedaan."
        )
    print(f"Database-doel: {url.split('@')[-1]}")


def _controleer_kms() -> None:
    """Hard: de credential moet met de CLOUD-masterkey (KMS) gewrapt worden, anders kan de
    cloud-runtime 'm nooit unwrappen en faalt elke sync/boekpoging daar stil-laat."""
    sleutel = os.environ.get("KMS_MASTERKEY_SLEUTEL", "")
    if "cryptoKeys" not in sleutel:
        raise SystemExit(
            "FAILSAFE: KMS_MASTERKEY_SLEUTEL is niet (correct) gezet — de wrap zou de lokale "
            "dev-masterkey gebruiken en de cloud-runtime kan die nooit ontsleutelen. Gestopt."
        )
    print(f"KMS-masterkey: {sleutel}")


def main() -> int:
    _controleer_database_doel()
    _controleer_kms()
    # RLZ-login uit verkenning/.env (alleen de RLZ_UNIVERSAL_*-vars worden gebruikt; bestaande
    # proces-env zoals APP_DATABASE_URL wint — load_dotenv overschrijft niet).
    load_dotenv(REPO / "verkenning" / ".env")

    # App-imports pas ná de env-checks (app.config leest de omgeving bij import).
    from app.beheer import service as beheer_service
    from app.credentialstore.service import (
        _zorg_voor_administratie,
        voer_rechten_probe_uit,
        zet_credential,
    )
    from app.db.models import Administratie, Gebruiker
    from app.db.session import scoped_session
    from app.rlz.client import RlzClient
    from app.rlz.credentials import BEKENDE_ADMINISTRATIES, lees_env_login
    from app.sync import service as sync_service

    login = lees_env_login(UNIVERSAL_PREFIX)
    if login is None:
        raise SystemExit("FAILSAFE: UNIVERSAL-login niet gevuld in verkenning/.env — gestopt.")
    username, wachtwoord = login

    bekend = next(a for a in BEKENDE_ADMINISTRATIES if a.prefix == UNIVERSAL_PREFIX)
    assert bekend.rlz_admin_id == UNIVERSAL_RLZ_ADMIN_ID, "registry wijkt af van de verwachte GUID"

    # Actor: de actieve Beheerder in de dóel-database (cloud) — precies één verwacht.
    with scoped_session(None) as session:
        beheerders = session.scalars(
            select(Gebruiker).where(Gebruiker.rol == "beheerder", Gebruiker.status == "actief")
        ).all()
        if len(beheerders) != 1:
            raise SystemExit(f"FAILSAFE: verwacht precies 1 actieve Beheerder, gevonden: {len(beheerders)}")
        beheerder_id = beheerders[0].id
        print(f"Actor (Beheerder): {beheerders[0].e_mail} ({beheerder_id})")

    # 1. ADMIN-PIN vóór alles: deze login hoort exact de éne Universal-administratie te zien.
    pin_client = RlzClient(username=username, password=wachtwoord)
    try:
        administraties = pin_client.list_administrations()
    finally:
        pin_client.close()
    ids = sorted(a["id"] for a in administraties)
    if ids != [UNIVERSAL_RLZ_ADMIN_ID]:
        raise SystemExit(f"FAILSAFE admin-pin: login ziet {ids}, verwacht [{UNIVERSAL_RLZ_ADMIN_ID}] — gestopt.")
    print(f"Admin-pin OK: login ziet exact {UNIVERSAL_RLZ_ADMIN_ID} ({bekend.naam})")

    # 2. Administratie-rij + credential (upsert; wrap via KMS door de env hierboven).
    administratie_id = _zorg_voor_administratie(bekend)
    zet_credential(
        actor_id=beheerder_id,
        administratie_id=administratie_id,
        webservice_username=username,
        wachtwoord=wachtwoord,
    )
    print(f"Credential in de store (administratie_id={administratie_id})")

    # 3. Rechten-probe — resolutie is store-first, dus dit bewijst meteen de KMS-unwrap.
    rapport = voer_rechten_probe_uit(administratie_id=administratie_id, actor_id=beheerder_id)
    ok = sum(1 for v in rapport.values() if v == "ok")
    print(f"Rechten-probe: {ok}/{len(rapport)} ok — {rapport}")
    if ok != len(rapport):
        raise SystemExit("FAILSAFE: rechten-probe niet volledig ok — gestopt vóór de syncs.")

    # 4. Syncs (read-only richting RLZ).
    resultaat = sync_service.sync_alles_voor_administratie(administratie_id=administratie_id)
    print(
        f"Sync OK: ledgers={resultaat.ledgers}, taxrates={resultaat.taxrates}, "
        f"vendors={resultaat.vendors}, projects={resultaat.projects}"
    )

    # 5. Uren & meerwerk AAN (geauditeerd via de vaste beheer-service).
    beheer_service.zet_uren_meerwerk_ingeschakeld(
        actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
    )

    # Verificatieblok: álle *_ingeschakeld-kolommen op de administratie-rij printen zodat
    # zichtbaar is dat uitsluitend uren_meerwerk AAN staat (kader: geen boeken/autoboek).
    with scoped_session(None) as session:
        kolommen = [
            r[0]
            for r in session.execute(
                text(
                    "select column_name from information_schema.columns "
                    "where table_schema='platform' and table_name='administratie' "
                    "and column_name like '%_ingeschakeld' order by column_name"
                )
            )
        ]
        rij = session.get(Administratie, administratie_id)
        print("\nVerificatie toggles Universal (cloud):")
        onverwacht_aan: list[str] = []
        for kolom in ["boeken_ingeschakeld", *[k for k in kolommen if k != "boeken_ingeschakeld"]]:
            waarde = getattr(rij, kolom)
            print(f"  {kolom} = {'AAN' if waarde else 'uit'}")
            if waarde and kolom != "uren_meerwerk_ingeschakeld":
                onverwacht_aan.append(kolom)
        if onverwacht_aan:
            raise SystemExit(f"FAILSAFE: onverwacht AAN: {onverwacht_aan}")
        if not rij.uren_meerwerk_ingeschakeld:
            raise SystemExit("FAILSAFE: uren_meerwerk_ingeschakeld staat niet aan.")
    print("\nKlaar: Universal onboarded als vergankelijke cloud-TEST (geen RLZ-writes gedaan).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
