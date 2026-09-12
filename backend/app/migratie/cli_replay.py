"""CLI `vgg-replay` (run 2 VGG 12-09, blok 6) — replay RLZ → Odoo-move-vorm, DEFAULT DRY-RUN, lees-only.

    python -m app.cli vgg-replay --administratie <uuid|naam> [--dry-run] [--json-uit pad] [--tot JJJJ-MM-DD]
                                 [--odoo-rekeningen pad.json] [--schrijf-concept]

Productie-regel Peter 08-09: alleen op de gedeployde job-image via `scripts/gcp/nameting.sh vgg-replay …` (allowlist);
`--schrijf-concept` is run 3 — in deze run alleen argparse + melding "run 3 — geweigerd" (exit 2), nooit een write;
nameting.sh weigert de vlag bovendien hard. Exit 0 = GROEN, 1 = verschillen/niet-vertaalbaar/leesfouten, 2 =
invoerfout."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

VGG_REPLAY_COMMANDO = "vgg-replay"
SCHRIJF_CONCEPT_GEWEIGERD = (
    "--schrijf-concept is run 3 — geweigerd: deze run schrijft niets naar Odoo (dry-run is de enige modus)"
)


def register_vgg_replay(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = subparsers.add_parser(
        VGG_REPLAY_COMMANDO,
        help=(
            "LEES-ONLY replay van een RLZ-administratie naar Odoo-move-vorm (dry-run): geboekte documenten, "
            "bankregels, "
            "saldibalans RLZ vs berekend Odoo, open posten, per pand, export juli 2025. Schrijft niets."
        ),
    )
    p.add_argument("--administratie", required=True, help="UUID of (deel van de) naam van de administratie.")
    p.add_argument(
        "--dry-run", dest="dry_run", action="store_true", default=True, help="Default en enige modus in run 2."
    )
    p.add_argument(
        "--json-uit", dest="json_uit", default=None, help="Pad voor het JSON-rapport (zelfde inhoud + alle moves)."
    )
    p.add_argument(
        "--tot", default=None, help="Peildatum 'vandaag' voor de saldibalans (JJJJ-MM-DD, default vandaag NL)."
    )
    p.add_argument(
        "--odoo-rekeningen",
        dest="odoo_rekeningen",
        default=None,
        help="JSON-bestand met Odoo account.account-rijen (id, code, name) van company 6; zonder = alles ongemapt "
        "(zichtbaar).",
    )
    p.add_argument(
        "--schrijf-concept",
        dest="schrijf_concept",
        action="store_true",
        default=False,
        help="RUN 3 — in deze run geweigerd (exit 2). Nooit een Odoo-write vanuit dit commando.",
    )


def _lees_odoo_rekeningen(pad: str | None) -> list[dict[str, Any]] | None:
    if not pad:
        return None
    data = json.loads(Path(pad).read_text(encoding="utf-8"))
    rijen = data.get("accounts", data) if isinstance(data, dict) else data
    if not isinstance(rijen, list):
        raise ValueError("verwacht een lijst van account.account-rijen of {'accounts': [...]}")
    return [r for r in rijen if isinstance(r, dict) and r.get("id") is not None]


def run_vgg_replay(args: argparse.Namespace, *, zoek: Any = None, client_factory: Any = None) -> int:
    from app.migratie import replay  # noqa: PLC0415
    from app.migratie.cli_cmd import zoek_administratie  # noqa: PLC0415

    if getattr(args, "schrijf_concept", False):
        print(f"FOUT  {SCHRIJF_CONCEPT_GEWEIGERD}", file=sys.stderr)
        return 2
    tot: date | None = None
    if getattr(args, "tot", None):
        try:
            tot = date.fromisoformat(args.tot)
        except ValueError:
            print(f"FOUT  --tot {args.tot!r} is geen datum (JJJJ-MM-DD)", file=sys.stderr)
            return 2
    try:
        odoo_accounts = _lees_odoo_rekeningen(getattr(args, "odoo_rekeningen", None))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FOUT  --odoo-rekeningen: {exc}", file=sys.stderr)
        return 2
    gevonden = (zoek or zoek_administratie)(args.administratie)
    if gevonden is None:
        print(f"FOUT  administratie {args.administratie!r} onbekend", file=sys.stderr)
        return 2
    administratie_id, naam, rlz_admin_id = gevonden
    client = None
    if client_factory is not None:
        client = client_factory(rlz_admin_id)
    else:
        from app.rlz.credentials import GeenRlzCredentials, client_voor_rlz_admin_id  # noqa: PLC0415

        try:
            client = client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)
        except GeenRlzCredentials as exc:
            print(f"FOUT  geen RLZ-credential voor {naam} ({rlz_admin_id}): {exc}", file=sys.stderr)
            return 2
    try:
        rapport = replay.dry_run(
            administratie_id,
            client=client,
            tot=tot,
            odoo_accounts=odoo_accounts,
            administratie_naam=naam,
            rlz_admin_id=rlz_admin_id,
            voortgang=lambda t: print(f"..    {t}", file=sys.stderr),
        )
    finally:
        if hasattr(client, "close"):
            client.close()
    print(rapport.als_markdown())
    if args.json_uit:
        Path(args.json_uit).write_text(rapport.als_json(), encoding="utf-8")
        print(f"JSON geschreven: {args.json_uit}")
    if rapport.groen:
        return 0
    print(
        f"ROOD: {rapport.verschillen} verschil(len), {len(rapport.niet_vertaalbaar)} niet vertaalbaar, "
        f"{len(rapport.fouten)} leesfout(en) — zie rapport",
        file=sys.stderr,
    )
    return 1
