from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

from app.auth import service
from app.beheer import service as beheer_service
from app.credentialstore import service as credentialstore_service
from app.documenten import reconciliatie
from app.geheugen import seed as geheugen_seed
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


def _zet_boeken(args: argparse.Namespace, *, ingeschakeld: bool) -> int:
    """Boeken-failsafe (a), per-administratie deel — hergebruikt app.beheer.service (zelfde
    servicefunctie als het instellingen-scherm straks aanroept), met de Beheerder als actor
    (zelfde patroon als bootstrap-beheerder/import-env-credentials: BEHEERDER_ID-parameter),
    dus met het gebruikelijke audit_event erbij."""
    try:
        administratie_id = uuid.UUID(args.administratie_id)
        beheerder_id = uuid.UUID(args.beheerder_id)
    except ValueError as exc:
        print(f"FOUT: ongeldige UUID ({exc})", file=sys.stderr)
        return 1
    try:
        resultaat = beheer_service.zet_boeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=ingeschakeld
        )
    except beheer_service.BeheerFout as exc:
        print(f"FOUT: {exc}", file=sys.stderr)
        return 1
    print(f"boeken_ingeschakeld={resultaat} voor administratie {administratie_id}")
    if resultaat and not beheer_service.haal_globale_kill_switch_op():
        print("WAARSCHUWING: de globale kill switch staat uit — boeken blijft effectief uit tot die ook aan staat.")
    return 0


def _boeken_aan(args: argparse.Namespace) -> int:
    return _zet_boeken(args, ingeschakeld=True)


def _boeken_uit(args: argparse.Namespace) -> int:
    return _zet_boeken(args, ingeschakeld=False)


def _boeken_status(args: argparse.Namespace) -> int:
    kill_switch_aan = beheer_service.haal_globale_kill_switch_op()
    print(f"Globale kill switch: {'AAN' if kill_switch_aan else 'UIT'}")
    print()
    overzicht = beheer_service.overzicht_boeken_status()
    if not overzicht:
        print("(geen administraties geregistreerd)")
        return 0
    print(f"{'toggle':<6} {'effectief':<11} administratie")
    for item in overzicht:
        effectief_aan = kill_switch_aan and item.boeken_ingeschakeld
        print(
            f"{'AAN' if item.boeken_ingeschakeld else 'uit':<6} "
            f"{'AAN' if effectief_aan else 'uit':<11} {item.administratie_id}  {item.naam}"
        )
    return 0


def _zet_ai_extractie(args: argparse.Namespace, *, ingeschakeld: bool) -> int:
    """AVG-gate voor AI-extractie (migratie 0014) — zelfde patroon als de boeken-toggle:
    hergebruikt app.beheer.service met de Beheerder als audit_event-actor. Default UIT; bedoeld
    om alleen de test-administratie/eigen facturen aan te zetten tot de AVG-volgorde rond is
    (docs/BOUWPLAN.md)."""
    try:
        administratie_id = uuid.UUID(args.administratie_id)
        beheerder_id = uuid.UUID(args.beheerder_id)
    except ValueError as exc:
        print(f"FOUT: ongeldige UUID ({exc})", file=sys.stderr)
        return 1
    try:
        resultaat = beheer_service.zet_ai_extractie_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=ingeschakeld
        )
    except beheer_service.BeheerFout as exc:
        print(f"FOUT: {exc}", file=sys.stderr)
        return 1
    print(f"ai_extractie_ingeschakeld={resultaat} voor administratie {administratie_id}")
    return 0


def _ai_extractie_aan(args: argparse.Namespace) -> int:
    return _zet_ai_extractie(args, ingeschakeld=True)


def _ai_extractie_uit(args: argparse.Namespace) -> int:
    return _zet_ai_extractie(args, ingeschakeld=False)


def _importeer_env_credentials(args: argparse.Namespace) -> int:
    """Eenmalige overzet-hulp: de bekende .env-logins de credential-store in (zie
    app/credentialstore/service.py::importeer_env_credentials voor welke prefixen en waarom
    sommige bewust overgeslagen worden)."""
    beheerder_id = uuid.UUID(args.beheerder_id)
    resultaten = credentialstore_service.importeer_env_credentials(actor_id=beheerder_id)
    for prefix, uitkomst in resultaten.items():
        print(f"{prefix}: {uitkomst}")
    return 0


def _seed_boekingsgeheugen(args: argparse.Namespace) -> int:
    """Achtergrond-batch (CLI/Cloud Run job, nooit synchroon in een request): RLZ-seed van het
    boekingsgeheugen uit PurchaseInvoices+Lines. Idempotent en hervatbaar — gewoon opnieuw
    draaien na een afgebroken run."""
    rapport = geheugen_seed.seed_boekingsgeheugen(
        administratie_id=uuid.UUID(args.administratie_id),
        maanden=args.maanden,
    )
    print(
        f"Seed {rapport.administratie_id}: {rapport.aantal_facturen_bekeken} facturen bekeken, "
        f"{rapport.aantal_facturen_geseed} geseed, {rapport.observaties_nieuw} nieuwe observaties, "
        f"{rapport.observaties_bestonden_al} bestonden al, "
        f"{rapport.overgeslagen_zonder_entity} overgeslagen zonder crediteur, "
        f"{rapport.overgeslagen_zonder_bruikbare_regels} zonder bruikbare regels."
    )
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

    seed_parser = subparsers.add_parser(
        "seed-boekingsgeheugen",
        help="RLZ-seed van het boekingsgeheugen (PurchaseInvoices+Lines) voor één administratie — "
        "idempotent, hervatbaar, achtergrond-batch.",
    )
    seed_parser.add_argument("--administratie-id", required=True, dest="administratie_id")
    seed_parser.add_argument(
        "--maanden", type=int, default=None,
        help="Recency-cap in maanden (default: settings.boekingsgeheugen_seed_maanden).",
    )

    subparsers.add_parser(
        "reconciliatie",
        help="Vergelijk geboekte documenten met de werkelijke RLZ-staat en rapporteer afwijkingen.",
    )

    boeken_aan_parser = subparsers.add_parser(
        "boeken-aan",
        help="Zet de boeken-toggle AAN voor één administratie (failsafe a, per-administratie deel).",
    )
    boeken_aan_parser.add_argument("--administratie-id", required=True, dest="administratie_id")
    boeken_aan_parser.add_argument(
        "--beheerder-id", required=True, dest="beheerder_id", help="UUID van de Beheerder (audit_event-actor)."
    )

    boeken_uit_parser = subparsers.add_parser(
        "boeken-uit",
        help="Zet de boeken-toggle UIT voor één administratie.",
    )
    boeken_uit_parser.add_argument("--administratie-id", required=True, dest="administratie_id")
    boeken_uit_parser.add_argument(
        "--beheerder-id", required=True, dest="beheerder_id", help="UUID van de Beheerder (audit_event-actor)."
    )

    subparsers.add_parser(
        "boeken-status",
        help="Overzicht: globale kill switch + per-administratie boeken-toggle.",
    )

    for naam, hulp in (
        ("ai-extractie-aan", "Zet de AI-extractie-gate (AVG) AAN voor één administratie."),
        ("ai-extractie-uit", "Zet de AI-extractie-gate (AVG) UIT voor één administratie."),
    ):
        ai_parser = subparsers.add_parser(naam, help=hulp)
        ai_parser.add_argument("--administratie-id", required=True, dest="administratie_id")
        ai_parser.add_argument(
            "--beheerder-id", required=True, dest="beheerder_id", help="UUID van de Beheerder (audit_event-actor)."
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
    if args.commando == "seed-boekingsgeheugen":
        return _seed_boekingsgeheugen(args)
    if args.commando == "boeken-aan":
        return _boeken_aan(args)
    if args.commando == "boeken-uit":
        return _boeken_uit(args)
    if args.commando == "boeken-status":
        return _boeken_status(args)
    if args.commando == "ai-extractie-aan":
        return _ai_extractie_aan(args)
    if args.commando == "ai-extractie-uit":
        return _ai_extractie_uit(args)
    if args.commando == "import-env-credentials":
        return _importeer_env_credentials(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
