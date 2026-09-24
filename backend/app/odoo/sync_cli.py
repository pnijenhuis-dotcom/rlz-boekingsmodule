"""`odoo-stamgegevens-sync` — hersync van de stamgegevenscaches (grootboek, btw, crediteuren, projecten) van één of alle
Odoo-administraties via de BESTAANDE eerste-sync-route (`app/odoo/service.py::eerste_sync` → `sync_alles_voor_odoo_
administratie`, zichtbaar als sync-run op de detailpagina). Geen nieuwe sync-logica (opdracht Peter 24-09 blok 2:
"CLI bestaat: hergebruik de eerste-sync-route, geen nieuwe").

Aanleiding (Peter 24-09, Bonte Hoeve): de caches droegen Engelse rekeningnamen omdat de client geen `context.lang`
meegaf (TAAL-POORT in `app/odoo/client.py`). De nachtelijke `sync-alles` (job `rlz-sync`) overschrijft de namen
sowieso bij de eerstvolgende run; dit commando doet dat op verzoek voor één administratie zonder op de nacht te
wachten — schrijvend (caches + sync-run-rij), dus NIET in de nameting-allowlist; productie via
`gcloud run jobs execute rlz-sync --args="^|^-m|app.cli|odoo-stamgegevens-sync|--administratie|Bonte Hoeve"`.

    python -m app.cli odoo-stamgegevens-sync (--administratie <uuid|naamdeel> | --alles) [--dry-run]

`--dry-run` toont alleen welke Odoo-administraties gesynct zóuden worden (geen Odoo-call, geen write).
"""

from __future__ import annotations

import argparse
import sys
import uuid

COMMANDO = "odoo-stamgegevens-sync"


def register(subparsers) -> None:  # noqa: ANN001 — argparse-subparsers-actie
    p = subparsers.add_parser(
        COMMANDO,
        help="Hersync stamgegevenscaches van Odoo-administratie(s) via de bestaande eerste-sync-route "
        "(24-09: NL-namen ná de taal-poort). Schrijvend; --dry-run toont alleen de kandidaten.",
    )
    doel = p.add_mutually_exclusive_group(required=True)
    doel.add_argument("--administratie", default=None, help="Eén Odoo-administratie (uuid of naamdeel).")
    doel.add_argument("--alles", action="store_true", help="Alle actieve Odoo-administraties (backend odoo).")
    p.add_argument("--dry-run", action="store_true", dest="dry_run", help="Alleen tonen welke, niets syncen.")


def odoo_administraties(term: str | None) -> list[tuple[uuid.UUID, str]] | None:
    """(id, naam) van actieve administraties mét backend `odoo`; `term` = uuid of naamdeel (None = alle).
    None-resultaat = de term is niet eenduidig of onbekend (aanroeper meldt dat)."""
    from sqlalchemy import select

    from app.db.models import Administratie
    from app.db.session import scoped_session
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID

    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        q = select(Administratie).where(Administratie.actief.is_(True), Administratie.boekhoud_backend == "odoo")
        if term:
            try:
                q = q.where(Administratie.id == uuid.UUID(term))
            except ValueError:
                q = q.where(Administratie.naam.ilike(f"%{term}%"))
        rijen = session.scalars(q.order_by(Administratie.naam)).all()
        if term and len(rijen) != 1:
            return None
        return [(r.id, r.naam) for r in rijen]


def run(args: argparse.Namespace, *, uit=None) -> int:  # noqa: ANN001
    uit = uit or sys.stdout
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID
    from app.odoo import service as odoo_service

    kandidaten = odoo_administraties(args.administratie if not args.alles else None)
    if kandidaten is None:
        print(f"{COMMANDO}: --administratie {args.administratie!r} is geen eenduidige actieve Odoo-administratie", file=sys.stderr)
        return 2
    if not kandidaten:
        print(f"{COMMANDO}: geen actieve Odoo-administraties gevonden", file=uit)
        return 0
    print(f"{COMMANDO}: {len(kandidaten)} Odoo-administratie(s)" + (" — DRY-RUN, niets gesynct" if args.dry_run else ""), file=uit)
    fouten = 0
    for aid, naam in kandidaten:
        if args.dry_run:
            print(f"  ZOU SYNCEN  {naam} ({aid})", file=uit)
            continue
        run_id, onderdelen = odoo_service.eerste_sync(administratie_id=aid, actor_id=SYSTEEM_ACTOR_ID)
        rood = [k for k, v in onderdelen.items() if v.get("status") != "ok"]
        if rood:
            fouten += 1
            print(f"  FOUT  {naam} ({aid}) run {run_id}: {', '.join(rood)} — {onderdelen[rood[0]].get('fout')}", file=uit)
        else:
            print(
                f"  OK    {naam} ({aid}) run {run_id}: "
                + ", ".join(f"{k}={v.get('bijgewerkt', 0)} bijgewerkt" for k, v in onderdelen.items()),
                file=uit,
            )
    return 1 if fouten else 0


def dispatch(args: argparse.Namespace) -> int | None:
    if getattr(args, "commando", None) != COMMANDO:
        return None
    return run(args)
