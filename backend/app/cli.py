from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

from app.auth import service
from app.credentialstore import service as credentialstore_service
from app.documenten import reconciliatie
from app.sync import service as sync_service

# Dev-gemak: de RLZ_/UNIVERSAL_/TESTADMIN_/KEMPEN_/RUBICON_-logins staan in verkenning/.env
# (nooit in backend/.env, zie CLAUDE.md), en niets anders laadt dat bestand als de CLI los
# gedraaid wordt (buiten pytest, waar tests/integration/conftest.py dit al voor zijn eigen tests
# doet). Alleen relevant voor import-env-credentials; in Cloud Run bestaat dit pad niet en is
# load_dotenv() dan een stille no-op — echte credentials komen daar via Secret Manager-env-vars.
load_dotenv(Path(__file__).resolve().parents[2] / "verkenning" / ".env")


def _bootstrap_beheerder(args: argparse.Namespace) -> int:
    try:
        resultaat = service.bootstrap_eerste_beheerder(naam=args.naam, e_mail=args.e_mail)
    except service.AuthError as exc:
        print(f"FOUT: {exc}", file=sys.stderr)
        return 1
    print(f"Eerste Beheerder aangemaakt: {resultaat.gebruiker_id} ({args.e_mail})")
    print(f"Uitnodigingstoken (eenmalig, verloopt {resultaat.verloopt_op.isoformat()}):")
    print(resultaat.token)
    print(
        "Rond de activatie af via POST /auth/uitnodigingen/accepteren met dit token, "
        "gevolgd door de TOTP-enrollment (POST /auth/totp/bevestigen)."
    )
    return 0


def _sync_alles(args: argparse.Namespace) -> int:
    """Nachtelijke sync-entrypoint (fase-vervolg: Cloud Scheduler -> Cloud Run job roept dit
    commando aan). Eén administratie zonder werkende .env-credentials laat de rest niet
    stoppen — zie sync_alle_administraties()."""
    resultaten = sync_service.sync_alle_administraties()
    fouten = 0
    for administratie_id, resultaat in resultaten.items():
        if isinstance(resultaat, str):
            fouten += 1
            print(f"FOUT  {administratie_id}: {resultaat}", file=sys.stderr)
            continue
        print(
            f"OK    {administratie_id}: ledgers={resultaat.ledgers}, taxrates={resultaat.taxrates}, "
            f"vendors={resultaat.vendors}, projects={resultaat.projects}"
        )
    print(f"\n{len(resultaten) - fouten}/{len(resultaten)} administraties gesynchroniseerd.")
    return 1 if fouten else 0


def _reconciliatie(args: argparse.Namespace) -> int:
    """Boeken-failsafe (b) (CLAUDE.md-taak 2.4): vergelijk elk lokaal GEBOEKT document met de
    werkelijke RLZ-staat en rapporteer afwijkingen. Eén administratie zonder werkende
    credentials laat de rest niet stoppen — zie reconcilieer_alle_administraties()."""
    resultaten = reconciliatie.reconcilieer_alle_administraties()
    fouten = 0
    afwijkingen_totaal = 0
    for administratie_id, resultaat in resultaten.items():
        if isinstance(resultaat, str):
            fouten += 1
            print(f"FOUT       {administratie_id}: {resultaat}", file=sys.stderr)
            continue
        if not resultaat.afwijkingen:
            print(f"OK         {administratie_id}: {resultaat.aantal_gecontroleerd} gecontroleerd, geen afwijkingen")
            continue
        afwijkingen_totaal += len(resultaat.afwijkingen)
        print(
            f"AFWIJKING  {administratie_id}: {resultaat.aantal_gecontroleerd} gecontroleerd, "
            f"{len(resultaat.afwijkingen)} afwijking(en)"
        )
        for a in resultaat.afwijkingen:
            print(f"    - document={a.document_id} rlz_document={a.rlz_document_id} soort={a.soort}: {a.detail}")
    print(
        f"\n{len(resultaten) - fouten}/{len(resultaten)} administraties gecontroleerd, "
        f"{afwijkingen_totaal} afwijking(en) totaal."
    )
    return 1 if (fouten or afwijkingen_totaal) else 0


def _importeer_env_credentials(args: argparse.Namespace) -> int:
    """Eenmalige overzet-hulp: de bekende .env-logins de credential-store in (zie
    app/credentialstore/service.py::importeer_env_credentials voor welke prefixen en waarom
    sommige bewust overgeslagen worden)."""
    beheerder_id = uuid.UUID(args.beheerder_id)
    resultaten = credentialstore_service.importeer_env_credentials(actor_id=beheerder_id)
    for prefix, uitkomst in resultaten.items():
        print(f"{prefix}: {uitkomst}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="RLZ Boekingsmodule beheer-CLI")
    subparsers = parser.add_subparsers(dest="commando", required=True)

    bootstrap_parser = subparsers.add_parser(
        "bootstrap-beheerder",
        help="Maak de allereerste Beheerder aan — weigert als er al een Beheerder bestaat.",
    )
    bootstrap_parser.add_argument("--naam", required=True)
    bootstrap_parser.add_argument("--e-mail", required=True, dest="e_mail")

    subparsers.add_parser(
        "sync-alles",
        help="Sync Ledgers/TaxRates/Vendors/Projects voor alle administraties (nachtelijke sync).",
    )

    subparsers.add_parser(
        "reconciliatie",
        help="Vergelijk geboekte documenten met de werkelijke RLZ-staat en rapporteer afwijkingen.",
    )

    import_parser = subparsers.add_parser(
        "import-env-credentials",
        help="Zet de bekende .env-logins (RLZ_/UNIVERSAL_/TESTADMIN_/KEMPEN_/RUBICON_) eenmalig "
        "in de credential-store.",
    )
    import_parser.add_argument(
        "--beheerder-id", required=True, help="UUID van de Beheerder die deze import uitvoert (audit_event-actor)."
    )

    args = parser.parse_args(argv)

    if args.commando == "bootstrap-beheerder":
        return _bootstrap_beheerder(args)
    if args.commando == "sync-alles":
        return _sync_alles(args)
    if args.commando == "reconciliatie":
        return _reconciliatie(args)
    if args.commando == "import-env-credentials":
        return _importeer_env_credentials(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
