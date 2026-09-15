"""CLI administratienaam (Peter 15-09; migratie 0144) — geregistreerd vanuit app/cli.py (2 regels), patroon
app/geheugen/btw_default_cli.py.

- `administratie-naam-bron-backfill [--schrijf] [--administratie <uuid>]` — DATA-STAP ná migratie 0144, apart van de
  DDL: per actieve administratie de LIVE bronnaam lezen (Odoo `res.company.name` / RLZ `Administrations.Name`);
  huidige naam == bronnaam → `naam_bron` = bron (voortaan volgt de module de bron), afwijkend → blijft 'mens' mét de
  bronnaam vastgelegd (chip "in Odoo heet deze administratie nu …"), bron onleesbaar → zichtbaar overgeslagen.
  DRY-RUN is de default; `--schrijf` schrijft (audit `administratie_naam_bron_backfill`). Idempotent.

Productie-uitvoering (regel Peter 08-09): uitsluitend op de gedeployde job-image, bv.
`gcloud run jobs execute rlz-sync --args="-m,app.cli,administratie-naam-bron-backfill,--schrijf"` — ná de deploy van
deze commit; de dry-run staat in de nameting-allowlist.
"""

from __future__ import annotations

import argparse
import sys
import uuid

COMMANDO_BACKFILL = "administratie-naam-bron-backfill"
COMMANDOS = (COMMANDO_BACKFILL,)


def register(subparsers) -> None:  # noqa: ANN001 — argparse-subparsers-actie
    backfill = subparsers.add_parser(
        COMMANDO_BACKFILL,
        help="Data-stap 0144 (15-09): naam_bron per administratie afleiden uit de LIVE bronnaam (Odoo/RLZ). "
        "Dry-run default; --schrijf schrijft.",
    )
    backfill.add_argument("--schrijf", action="store_true", help="Schrijf de uitkomst (default: alleen tonen).")
    backfill.add_argument("--administratie", default=None, help="UUID van één administratie (default: alle actieve).")


def dispatch(args: argparse.Namespace) -> int | None:
    """None = niet ons commando (cli.py gaat verder); anders de exit-code."""
    if args.commando == COMMANDO_BACKFILL:
        return backfill(args)
    return None


def backfill(args: argparse.Namespace) -> int:
    from app.beheer import administratienaam

    administratie_id = uuid.UUID(args.administratie) if args.administratie else None
    dry_run = not args.schrijf
    regels = administratienaam.backfill_naam_bron(dry_run=dry_run, administratie_id=administratie_id)
    print(f"administratie-naam-bron-backfill ({'DRY-RUN — niets geschreven' if dry_run else 'GESCHREVEN'}):")
    tellers: dict[str, int] = {}
    for r in regels:
        tellers[r.uitkomst] = tellers.get(r.uitkomst, 0) + 1
        label = {
            "bron_gezet": f"BRON   {r.bron:<4}",
            "blijft_mens": "MENS        ",
            "al_gezet": "AL GEZET    ",
            "overgeslagen": "OVERGESLAGEN",
        }[r.uitkomst]
        detail = f" — {r.detail}" if r.detail else ""
        print(f"{label} {r.administratie_id} {r.naam!r}{detail}")
    print(
        f"\n{len(regels)} administraties: {tellers.get('bron_gezet', 0)} bron gezet, {tellers.get('blijft_mens', 0)} "
        f"blijven mens (bron afwijkend), {tellers.get('al_gezet', 0)} al gezet, {tellers.get('overgeslagen', 0)} "
        f"overgeslagen (bron niet leesbaar)."
    )
    if tellers.get("overgeslagen"):
        print(
            "LET OP: overgeslagen administraties blijven 'mens' — de sync legt de bronnaam later alsnog vast.",
            file=sys.stderr,
        )
    return 0
