"""CLI-commando werkvoorraad-tellers (blok 6 run 11-09 middag) — geregistreerd vanuit app/cli.py (2 regels).

- `werkvoorraad-tellers-herrekenen [--administratie <uuid>]` — volledige herberekening van de tellers-cache
  (`werkvoorraad_teller_cache`) uit de brontabellen; loopt óók dagelijks mee in `sync-alles` (ná de signaalmotoren).
- `… --dry-run` — LEES-ONLY nameting: vergelijkt cache ↔ telling en rapporteert afwijkingen per administratie × teller;
  schrijft niets (nameting-allowlist `scripts/gcp/nameting.sh`).

Productie-uitvoering (regel Peter 08-09): uitsluitend op de gedeployde job-image, bv.
`scripts/gcp/nameting.sh werkvoorraad-tellers-herrekenen --dry-run`."""

from __future__ import annotations

import argparse
import sys
import uuid

COMMANDO = "werkvoorraad-tellers-herrekenen"


def register(subparsers) -> None:  # noqa: ANN001 — argparse-subparsers-actie
    parser = subparsers.add_parser(
        COMMANDO,
        help="Werkvoorraad-tellers-cache (blok 6 11-09) volledig herrekenen uit de brontabellen (loopt óók dagelijks "
        "mee in sync-alles); --dry-run = lees-only vergelijking cache ↔ telling.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Alleen vergelijken en afwijkingen tonen; niets gewijzigd.",
    )
    parser.add_argument("--administratie", default=None, metavar="UUID", help="Beperk de run tot deze administratie.")


def dispatch(args: argparse.Namespace) -> int | None:
    """None = niet ons commando (cli.py gaat verder); anders de exit-code."""
    if args.commando != COMMANDO:
        return None
    administratie_ids = None
    if args.administratie:
        try:
            administratie_ids = [uuid.UUID(args.administratie)]
        except ValueError as exc:
            print(f"FOUT: ongeldige UUID ({exc})", file=sys.stderr)
            return 1
    return rapporteer_herrekenen(dry_run=bool(args.dry_run), administratie_ids=administratie_ids)


def rapporteer_herrekenen(*, dry_run: bool, administratie_ids: list[uuid.UUID] | None = None) -> int:
    """Draai de herberekening en print het rapport (zelfde vorm als de overige sync-alles-blokken). Exit 1 alleen bij
    een fout in een administratie — afwijkingen zijn de REDEN van deze run (dagelijks) en geen fout; bij --dry-run
    (nameting) is exit 1 wél 'er zijn afwijkingen', zodat een meting zichtbaar rood kan zijn."""
    from app.werkvoorraad import tellers

    rapport = tellers.herreken_alle(administratie_ids=administratie_ids, dry_run=dry_run)
    for a in rapport.afwijkingen:
        cache = "ontbreekt" if a.cache is None else str(a.cache)
        print(f"AFWIJKING  {a.naam} ({a.administratie_id}): {a.teller} cache={cache} telling={a.telling}")
    for fout in rapport.fouten:
        print(f"FOUT       {fout}", file=sys.stderr)
    werkwoord = "vergeleken (dry-run, niets geschreven)" if dry_run else "herrekend"
    print(
        f"\n{rapport.administraties} administraties {werkwoord}: {len(rapport.afwijkingen)} afwijkende tellers bij "
        f"{rapport.administraties_met_afwijking} administraties, {rapport.ontbrekend} zonder (complete) cache, "
        f"{len(rapport.fouten)} fouten."
    )
    if rapport.fouten:
        return 1
    return 1 if (dry_run and rapport.afwijkingen) else 0
