"""CLI `veldwerkers-dubbelen` (opdracht Peter 21-09) — LEES-ONLY kandidatenrapport dubbele veldwerkers op HARDE sleutels
(KvK, IBAN via crediteur, e-mail) binnen één administratie. Naamgelijkenis en planningspatroon zijn NOOIT een signaal
(correctie Peter 21-09: broers in één ploeg zijn normaal). Geen write, geen RLZ-call, geen samenvoegen. In de
nameting-allowlist (`scripts/gcp/nameting.sh`) en als dispatch-onderdeel in `nameting.yml`."""

from __future__ import annotations

import argparse
import sys
import uuid

VELDWERKERS_DUBBELEN_COMMANDOS = ("veldwerkers-dubbelen",)


def register_veldwerkers_dubbelen(subparsers) -> None:  # noqa: ANN001
    p = subparsers.add_parser(
        "veldwerkers-dubbelen",
        help="Opdracht 21-09: LEES-ONLY — dubbele veldwerkers per administratie op harde sleutels alleen (zelfde KvK, "
        "IBAN via de crediteur-koppeling of e-mail). Naam/planning nooit een signaal. Geen write, geen samenvoegen.",
    )
    p.add_argument("--administratie", default=None, metavar="UUID|NAAMDEEL", help="Eén administratie (naam of id).")
    p.add_argument("--alles", action="store_true", help="Alle actieve administraties mét uren-&-meerwerk-opt-in.")


def _rapport(args: argparse.Namespace) -> int:
    from app.db.models import Administratie
    from app.db.session import scoped_session
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID
    from app.projecten.cli_cmd import _administraties
    from app.uren import dubbelen

    if bool(args.administratie) == bool(args.alles):
        print("kies precies één van --administratie <naam|id> of --alles", file=sys.stderr)
        return 2
    if args.alles:
        with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
            gekozen: list[tuple[uuid.UUID, str]] = [
                (a.id, a.naam) for a in session.scalars(select_opt_in(Administratie).order_by(Administratie.naam))
            ]
    else:
        alle = _administraties(args.administratie)
        if alle is None:
            return 2
        gekozen = alle
    print(
        f"Dubbele veldwerkers — {len(gekozen)} administratie(s). LEES-ONLY op harde sleutels (KvK, IBAN via crediteur, "
        "e-mail); naamgelijkenis/planningspatroon telt NOOIT (correctie Peter 21-09). Geen write, geen samenvoegen."
    )
    totaal_kandidaten = totaal_veldwerkers = fouten = 0
    for aid, naam in gekozen:
        try:
            with scoped_session(aid, actor_id=SYSTEEM_ACTOR_ID) as session:
                r = dubbelen.rapport_voor_administratie(session, administratie_id=aid, administratie_naam=naam)
            print("\n".join(dubbelen.rapportregels(r)))
            totaal_kandidaten += len(r.kandidaten)
            totaal_veldwerkers += r.aantal_veldwerkers
        except Exception as exc:  # noqa: BLE001 — één kapotte administratie stopt de rest niet, wél zichtbaar
            fouten += 1
            print(f"== {naam} ({aid}) — FOUT: {exc}")
    print(
        f"\nTOTAAL {totaal_kandidaten} kandidaat-cluster(s) over {totaal_veldwerkers} veldwerker(s) in "
        f"{len(gekozen)} administratie(s) · {fouten} fout(en). Beoordelen = klikpunt Peter; deze CLI schrijft niets."
    )
    return 0 if fouten == 0 else 1


def select_opt_in(model):  # noqa: ANN001, ANN201
    from sqlalchemy import select

    return select(model).where(model.actief.is_(True), model.uren_meerwerk_ingeschakeld.is_(True))


def run_veldwerkers_dubbelen(args: argparse.Namespace) -> int:
    if args.commando == "veldwerkers-dubbelen":
        return _rapport(args)
    raise ValueError(f"onbekend commando {args.commando!r}")
