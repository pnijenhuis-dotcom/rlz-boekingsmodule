"""CLI `pandenregister-afleiden` (bundel 10-09 blok D2; run 2 VGG 12-09 blok 3: `--pandenlijst <csv>`, bankmutaties).

Default DRY-RUN (leest RLZ + DB, schrijft niets); `--schrijf` zet pand- en pand_boeking-VOORSTELLEN in de DB — nooit
een bevestiging, nooit een RLZ-/Odoo-write. Productie uitsluitend op de gedeployde job-image (regel Peter 08-09);
nameting lees-only via `scripts/gcp/nameting.sh pandenregister-afleiden --administratie Vastgoedgroep`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def register_panden(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = subparsers.add_parser(
        "pandenregister-afleiden",
        help=(
            "Pandenregister afleiden uit RLZ (aankoop = memoriaal RLZ-06 met adres + notaris-PDF/dossier of betaling "
            "aan notaris, verkoop = verkoopfactuur/bank-ontvangst van een notaris, aanbetaling, vaste lasten, 31-12 = "
            "balans; adressen geclusterd of gebonden aan een pandenlijst). Default dry-run; --schrijf slaat "
            "VOORSTELLEN op."
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
    p.add_argument(
        "--pandenlijst",
        dest="pandenlijst",
        default=None,
        help=(
            "CSV (UTF-8, ; of ,) met kolommen adres|straat, huisnummer, [toevoeging], [postcode], [plaats], "
            "[salesforce_id]: afgeleide adressen worden aan precies één lijst-pand gebonden (meerduidig = gemeld, niet "
            "gebonden). Zonder lijst: clusteren op huisnummer + straatgelijkenis."
        ),
    )
    p.add_argument(
        "--zonder-bankmutaties",
        dest="zonder_bankmutaties",
        action="store_true",
        help="PaymentTransactions niet lezen (alleen documenten).",
    )


def run_panden(args: argparse.Namespace) -> int:
    from app.migratie.cli_cmd import zoek_administratie
    from app.panden import service
    from app.panden.pandenlijst import CsvPandenlijst, PandenlijstFout
    from app.rlz.credentials import GeenRlzCredentials

    if args.schrijf and args.dry_run:
        print("FOUT  --schrijf en --dry-run sluiten elkaar uit", file=sys.stderr)
        return 2
    gevonden = zoek_administratie(args.administratie)
    if gevonden is None:
        print(f"FOUT  administratie {args.administratie!r} onbekend", file=sys.stderr)
        return 2
    administratie_id, naam, _ = gevonden
    lijst: CsvPandenlijst | None = None
    if getattr(args, "pandenlijst", None):
        lijst = CsvPandenlijst(args.pandenlijst)
        try:
            aantal = len(lijst.panden())
        except (OSError, PandenlijstFout) as exc:
            print(f"FOUT  pandenlijst niet leesbaar: {exc}", file=sys.stderr)
            return 2
        print(
            f"Pandenlijst {args.pandenlijst}: {aantal} panden"
            + (f", {len(lijst.overgeslagen)} regels overgeslagen" if lijst.overgeslagen else "")
        )
        for regel in lijst.overgeslagen:
            print(f"  OVERGESLAGEN {regel}", file=sys.stderr)
    try:
        rapport = service.leid_af(
            administratie_id,
            dry_run=not args.schrijf,
            max_bijlage_checks=args.max_bijlage_checks,
            pandenlijst_bron=lijst,
            met_bankmutaties=not getattr(args, "zonder_bankmutaties", False),
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
