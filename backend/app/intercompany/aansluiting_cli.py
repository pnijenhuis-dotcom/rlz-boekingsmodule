"""Lees-only CLI `ic-aansluiting-rapport` (run D 02-10 blok D): de IC-aansluiting per richting zoals het dagelijkse
blok `intercompany` 'm toetst — zelfde motor (`factuurmatch.cli_blok` zonder verzamelaar: niets vastgelegd, geen
acceptatie-overdracht, geen mail), gefilterd op `--richting "<verkoper>><ontvanger>"` (uuid's of naamdelen; één deel =
de administratie aan één van beide kanten) en/of `--administratie`. Uitsluitend GET/search_read naar RLZ/Odoo. Staat in
de nameting-allowlist (`scripts/gcp/nameting.sh`) en is het CLI-deel van het dispatch-onderdeel `ic-aansluiting`."""

from __future__ import annotations

import argparse
import sys
import uuid

COMMANDO = "ic-aansluiting-rapport"


def register(subparsers) -> None:  # noqa: ANN001
    p = subparsers.add_parser(
        COMMANDO,
        help="Lees-only: IC-aansluiting per richting (verkoop bij A ↔ inkoop bij B, alle richtingen binnen een "
        "handelsgroep; gesplitste bron RLZ/Odoo rond de kanteldatum) — zelfde motor als blok intercompany, niets "
        "vastgelegd.",
    )
    p.add_argument(
        "--richting",
        default=None,
        help='"<verkoper>><ontvanger>" (uuid of naamdeel per kant, bv. "Universal Nederland>Steigerbouw"); één deel '
        "zonder '>' = alle richtingen mét die administratie",
    )
    p.add_argument("--administratie", default=None, help="uuid of naamdeel — alleen richtingen mét deze administratie")
    p.add_argument("--venster-dagen", type=int, default=None, dest="ic_venster_dagen", help="default 400")


def dispatch(args: argparse.Namespace) -> int | None:
    if getattr(args, "commando", None) != COMMANDO:
        return None
    return run_cli(args)


def run_cli(args: argparse.Namespace, *, zoek=None, blok=None, stdout=print) -> int:  # noqa: ANN001
    from app.intercompany import factuurmatch

    if zoek is None:
        from app.cli import _zoek_administraties as zoek
    administratie_ids: list[uuid.UUID] | None = None
    if args.administratie:
        gevonden = zoek(args.administratie)
        if len(gevonden) != 1:
            if not gevonden:
                print(f"FOUT: geen administratie gevonden voor {args.administratie!r}", file=sys.stderr)
            else:
                print(f"FOUT: {args.administratie!r} is niet eenduidig:", file=sys.stderr)
                for aid, naam in gevonden:
                    print(f"    {aid}  {naam}", file=sys.stderr)
            return 2
        administratie_ids = [gevonden[0][0]]
    blok_args = argparse.Namespace(
        administratie_ids=administratie_ids,
        ic_richting=args.richting or None,
        ic_venster_dagen=getattr(args, "ic_venster_dagen", None),
    )
    stdout(
        "IC-AANSLUITING per richting — LEES-ONLY (geen run-rij, geen bevindingen, geen mail); "
        f"richting={args.richting or 'alle'} administratie={args.administratie or 'alle'}"
    )
    return (blok or factuurmatch.cli_blok)(blok_args, None, stdout=stdout)
