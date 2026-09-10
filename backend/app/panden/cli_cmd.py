"""CLI `pandenregister-afleiden` (bundel 10-09 blok D2).

Default DRY-RUN (leest RLZ + DB, schrijft niets); `--schrijf` zet pand- en pand_boeking-VOORSTELLEN in de DB — nooit
een bevestiging, nooit een RLZ-/Odoo-write. Productie uitsluitend op de gedeployde job-image (regel Peter 08-09)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def register_panden(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = subparsers.add_parser(
        "pandenregister-afleiden",
        help=(
            "Pandenregister afleiden uit RLZ (aankoop = memoriaal RLZ-06 met adres + notaris-PDF/dossier, verkoop = "
            "verkoopfactuur op een notaris). Default dry-run; --schrijf slaat VOORSTELLEN op (niets bevestigd)."
        ),
    )
    p.add_argument("--administratie", required=True, help="UUID of (deel van de) naam van de administratie.")
    p.add_argument("--schrijf", action="store_true", help="Voorstellen wegschrijven (zonder deze vlag: dry-run).")
    p.add_argument("--dry-run", action="store_true", dest="dry_run", help="Expliciet dry-run (default).")
    p.add_argument("--json-uit", dest="json_uit", default=None, help="Pad voor het JSON-rapport.")
    p.add_argument(
        "--max-bijlage-checks",
        dest="max_bijlage_checks",
        type=int,
        default=200,
        help="Maximaal aantal GET …/Uploads-checks op memorialen met adres/dossier (default 200).",
    )


def run_panden(args: argparse.Namespace) -> int:
    from app.migratie.cli_cmd import zoek_administratie
    from app.panden import service
    from app.rlz.credentials import GeenRlzCredentials

    if args.schrijf and args.dry_run:
        print("FOUT  --schrijf en --dry-run sluiten elkaar uit", file=sys.stderr)
        return 2
    gevonden = zoek_administratie(args.administratie)
    if gevonden is None:
        print(f"FOUT  administratie {args.administratie!r} onbekend", file=sys.stderr)
        return 2
    administratie_id, naam, _ = gevonden
    try:
        rapport = service.leid_af(
            administratie_id, dry_run=not args.schrijf, max_bijlage_checks=args.max_bijlage_checks
        )
    except GeenRlzCredentials as exc:
        print(f"FOUT  geen RLZ-credential voor {naam}: {exc}", file=sys.stderr)
        return 2
    print(service.als_markdown(rapport, administratie_naam=naam))
    if args.json_uit:
        Path(args.json_uit).write_text(rapport.als_json(), encoding="utf-8")
        print(f"JSON geschreven: {args.json_uit}")
    if rapport.fouten:
        print(f"{len(rapport.fouten)} collectie(s) niet gelezen — afleiding onvolledig", file=sys.stderr)
        return 1
    return 0
