#!/usr/bin/env python3
"""Masterkey-herversleuteling — de vangrail tegen de kluis-zonder-sleutel (draaiboek F1.3).

Herversleutelt de wrapped data-keys van de credential-store (platform.rlz_credential) en de
TOTP-secrets (platform.totp_secret) van een oude masterkey-provider naar een nieuwe.
platform.webauthn_credential is bewust niet opgenomen: passkeys zijn publieke sleutels,
geen envelope-data. Zie backend/app/security/herversleutel.py voor de logica en de
bewijs-gedreven classificatie (idempotent/hervatbaar).

Draaien vanuit de repo-root, met de backend-venv:

    backend/.venv/bin/python scripts/herversleutel_masterkey.py --van lokaal --naar kms
    backend/.venv/bin/python scripts/herversleutel_masterkey.py --van lokaal --naar kms --uitvoeren

Default is DRY-RUN (alleen tellen/classificeren, gegarandeerd geen schrijfactie);
--uitvoeren schrijft en commit alleen als álle rijen slagen — half herversleuteld bestaat
niet (één transactie).

Providerkeuze per kant:
  lokaal  — TOTP_MASTER_KEY uit backend/.env (of expliciet --master-key-b64-oud/-nieuw,
            bv. voor een lokale key-rotatie: beide kanten 'lokaal' met verschillende keys)
  kms     — Cloud KMS; sleutelnaam uit KMS_MASTERKEY_SLEUTEL of --kms-sleutel
            (kms→kms is bewust niet ondersteund: KMS roteert key-versies zelf en
            ontsleutelt oude versies transparant — daar is geen herversleutelrun voor nodig)

De database is settings.database_url (owner-connectie) — dit is een expliciete beheerstap,
geen app-runtime-pad. DATABASE_URL-env overschrijft zoals altijd."""

from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)  # zodat pydantic-settings backend/.env vindt, net als de app zelf


def _maak_provider(kant: str, soort: str, args: argparse.Namespace):
    from app.config import settings
    from app.security.envelope import KmsMasterKeyProvider, LocalMasterKeyProvider

    if soort == "lokaal":
        expliciet = getattr(args, f"master_key_b64_{kant}")
        if expliciet:
            return LocalMasterKeyProvider(base64.b64decode(expliciet))
        return LocalMasterKeyProvider()
    sleutel = args.kms_sleutel or settings.kms_masterkey_sleutel
    if not sleutel:
        raise SystemExit(
            "FOUT: kms-provider gevraagd maar geen sleutelnaam — zet KMS_MASTERKEY_SLEUTEL "
            "in backend/.env of geef --kms-sleutel mee (volledige CryptoKey-resourcenaam)."
        )
    return KmsMasterKeyProvider(sleutel)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--van", required=True, choices=["lokaal", "kms"], help="huidige provider van de rijen")
    parser.add_argument("--naar", required=True, choices=["lokaal", "kms"], help="doelprovider")
    parser.add_argument("--kms-sleutel", default=None, help="CryptoKey-resourcenaam (anders KMS_MASTERKEY_SLEUTEL)")
    parser.add_argument("--master-key-b64-oud", default=None, help="expliciete oude lokale masterkey (base64)")
    parser.add_argument("--master-key-b64-nieuw", default=None, help="expliciete nieuwe lokale masterkey (base64)")
    parser.add_argument(
        "--uitvoeren", action="store_true", help="daadwerkelijk schrijven (zonder deze vlag: dry-run)"
    )
    args = parser.parse_args()

    if args.van == "kms" and args.naar == "kms":
        raise SystemExit("FOUT: kms→kms is niet nodig (KMS ontsleutelt oude key-versies zelf) — zie de toelichting.")
    if args.van == "lokaal" and args.naar == "lokaal" and not (args.master_key_b64_oud and args.master_key_b64_nieuw):
        raise SystemExit(
            "FOUT: lokaal→lokaal is alleen zinvol als rotatie met twee verschillende keys — "
            "geef --master-key-b64-oud én --master-key-b64-nieuw expliciet mee."
        )

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.config import settings
    from app.security.herversleutel import herversleutel_alles

    oud = _maak_provider("oud", args.van, args)
    nieuw = _maak_provider("nieuw", args.naar, args)

    engine = create_engine(settings.database_url)
    sessie = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        resultaat = herversleutel_alles(sessie, oud=oud, nieuw=nieuw, dry_run=not args.uitvoeren)
        modus = "DRY-RUN (niets geschreven)" if resultaat.dry_run else "UITVOEREN"
        print(f"Masterkey-herversleuteling {args.van} → {args.naar} — {modus}")
        for label, telling in resultaat.per_tabel.items():
            print(
                f"  {label:15s} totaal {telling.totaal:4d} · te herversleutelen/herversleuteld "
                f"{telling.herversleuteld:4d} · al op nieuw {telling.al_op_nieuw:4d} · mislukt {telling.mislukt:4d}"
            )
            for rij in telling.mislukte_rijen:
                print(f"    MISLUKT: {rij} — geen van beide providers ontsleutelt deze rij")
        print("  webauthn_credential: n.v.t. (publieke sleutels, geen envelope-data)")
        if not resultaat.geslaagd:
            sessie.rollback()
            print("FOUT: niet alle rijen konden geclassificeerd/herversleuteld worden — NIETS gecommit.")
            return 1
        if resultaat.dry_run:
            sessie.rollback()
            print("Klaar (dry-run). Draai opnieuw met --uitvoeren om te schrijven.")
        else:
            sessie.commit()
            print("Klaar: gecommit. Bewaar de OUDE key tot een geslaagde login/sync de nieuwe staat bewezen heeft.")
        return 0
    finally:
        sessie.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
