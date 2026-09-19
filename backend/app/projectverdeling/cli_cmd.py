"""CLI projectverdeling (opdracht 19-09) — LEES-ONLY:

- `projectverdeling-afgesloten-rapport (--administratie X | --alle-projectverplicht)`: per administratie (1) de actieve
  projecten mét een "Afgesloten"-naam (LET-OP afsluiten?), (2) de GEBOEKTE verdelingsdelen op projecten die nú
  afgesloten/
  inactief zijn of "Afgesloten" heten mét voorstel per rij (storno + herverdeling / laten staan) — niets uitvoeren,
  (3) wat er
  via de pro-rato-sleutel loopt dat overhead is en wat een OVH-project zou vangen (beslispunt Peter, niet zelf
  aanmaken).
  In de nameting-allowlist (`scripts/gcp/nameting.sh`). Geen write, geen RLZ-call.
"""

from __future__ import annotations

import argparse
import sys
import uuid

from sqlalchemy import select

PROJECTVERDELING_COMMANDOS = ("projectverdeling-afgesloten-rapport",)


def register_projectverdeling(subparsers) -> None:  # noqa: ANN001
    p = subparsers.add_parser(
        "projectverdeling-afgesloten-rapport",
        help="Opdracht 19-09: LEES-ONLY — geboekte verdelingsdelen op afgesloten/'Afgesloten'-projecten mét voorstel "
        "per rij, "
        "actieve projecten mét een 'Afgesloten'-naam (LET-OP) en de overhead die via de omzetsleutel loopt "
        "(OVH-beslispunt). "
        "Niets uitvoeren, geen write.",
    )
    p.add_argument("--administratie", default=None, metavar="UUID|NAAMDEEL", help="Eén administratie (naam of id).")
    p.add_argument(
        "--alle-projectverplicht", action="store_true", help="Alle actieve administraties mét project_verplicht."
    )


def _rapport(args: argparse.Namespace) -> int:
    from app.db.models import Administratie
    from app.db.session import scoped_session
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID
    from app.projecten.cli_cmd import _administraties
    from app.projectverdeling import afgesloten

    if bool(args.administratie) == bool(args.alle_projectverplicht):
        print("kies precies één van --administratie <naam|id> of --alle-projectverplicht", file=sys.stderr)
        return 2
    if args.alle_projectverplicht:
        with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
            gekozen: list[tuple[uuid.UUID, str]] = [
                (a.id, a.naam)
                for a in session.scalars(
                    select(Administratie)
                    .where(Administratie.actief.is_(True), Administratie.project_verplicht.is_(True))
                    .order_by(Administratie.naam)
                )
            ]
    else:
        alle = _administraties(args.administratie)
        if alle is None:
            return 2
        gekozen = alle
    print(
        f"Projectverdeling × afgesloten projecten — {len(gekozen)} administratie(s). LEES-ONLY: geen write, geen "
        f"RLZ-call; "
        "voorstellen zijn tekst (klikpunt Peter)."
    )
    totaal_let_op = totaal_geboekt = 0
    for aid, naam in gekozen:
        with scoped_session(aid) as session:
            let_op = afgesloten.actieve_projecten_met_afgesloten_naam(session, administratie_id=aid)
            geboekt = afgesloten.rapport_geboekt_op_afgesloten(session, administratie_id=aid)
            overhead = afgesloten.rapport_overhead_via_sleutel(session, administratie_id=aid)
            regels = afgesloten.rapportregels(
                administratie_naam=naam, administratie_id=aid, let_op=let_op, geboekt=geboekt, overhead=overhead
            )
        print()
        print("\n".join(regels))
        totaal_let_op += len(let_op)
        totaal_geboekt += len(geboekt)
    print(
        f"\nTotaal: {totaal_let_op} actief project(en) mét 'Afgesloten'-naam, {totaal_geboekt} geboekt(e) "
        f"verdelingsdeel(en) op "
        "afgesloten/'Afgesloten'-projecten. Herverdelen/afsluiten = klikpunt Peter; deze CLI schrijft niets."
    )
    return 0


def run_projectverdeling(args: argparse.Namespace) -> int:
    if args.commando == "projectverdeling-afgesloten-rapport":
        return _rapport(args)
    raise ValueError(f"onbekend projectverdeling-commando {args.commando!r}")
