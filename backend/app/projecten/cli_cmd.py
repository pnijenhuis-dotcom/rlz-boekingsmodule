"""LEES-ONLY CLI's projecten (blok 3 18-09, Peter's opruimpunten) — in de nameting-allowlist
(`scripts/gcp/nameting.sh`):

- `projecten-afsluit-kandidaten [--administratie X] [--dagen 90]`: per lopend project de kandidaat-stand (stil ≥ N
dagen én
  contract-m² bereikt) mét bron (laatste activiteit, gebouwd/contract-m²) — welke van de actieve VGG/Universal-projecten
  voldoen. Geen actie: afsluiten blijft een klik van de mens.
- `projecten-dubbele-nummers [--administratie X]`: alle dubbele projectnummers per administratie mét beide id's en de
  tellers facturen/weekstaten/planning per kant + voorstel "blijft" (klikpunt samenvoegen, nooit automatisch).
Geen writes, geen RLZ-calls (cache + eigen tabellen)."""

from __future__ import annotations

import argparse
import sys
import uuid

from sqlalchemy import select

PROJECTEN_COMMANDOS = ("projecten-afsluit-kandidaten", "projecten-dubbele-nummers")


def register_projecten(subparsers) -> None:  # noqa: ANN001
    kand = subparsers.add_parser(
        "projecten-afsluit-kandidaten",
        help="Blok 3 18-09: LEES-ONLY — lopende projecten die aan het afsluit-criterium voldoen (geen uren/planning/"
        "verplichting/factuur in N dagen én contract-m² bereikt) mét bron; nooit automatisch afsluiten.",
    )
    kand.add_argument("--administratie", default=None, metavar="UUID|NAAMDEEL", help="Beperk tot één administratie.")
    kand.add_argument("--dagen", type=int, default=None, help="Stil-venster in dagen (default 90).")
    kand.add_argument("--alles", action="store_true", help="Toon óók de niet-kandidaten mét reden.")
    dub = subparsers.add_parser(
        "projecten-dubbele-nummers",
        help="Blok 3 18-09: LEES-ONLY — dubbele projectnummers per administratie (beide id's, facturen/weekstaten/"
        "planning per kant, voorstel welke blijft). Klikpunt samenvoegen, nooit automatisch.",
    )
    dub.add_argument("--administratie", default=None, metavar="UUID|NAAMDEEL", help="Beperk tot één administratie.")


def _administraties(tekst: str | None) -> list[tuple[uuid.UUID, str]] | None:
    from app.db.models import Administratie
    from app.db.session import scoped_session
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID

    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        q = select(Administratie).where(Administratie.actief.is_(True))
        rijen = [(a.id, a.naam) for a in session.scalars(q.order_by(Administratie.naam))]
    if not tekst:
        return rijen
    try:
        gekozen = [r for r in rijen if r[0] == uuid.UUID(tekst)]
    except ValueError:
        gekozen = [r for r in rijen if tekst.lower() in (r[1] or "").lower()]
    if len(gekozen) != 1:
        print(f"--administratie {tekst!r}: {len(gekozen)} treffer(s) — precies één vereist", file=sys.stderr)
        return None
    return gekozen


def _afsluit_kandidaten(args: argparse.Namespace) -> int:
    from decimal import Decimal

    from app.db.session import scoped_session
    from app.projecten import status as status_service
    from app.sync.models import PROJECT_STATUS_AFGESLOTEN, ProjectCache
    from app.uren.models import ProjectSpecificatie
    from app.uren.overzichten import _gebouwd_m2

    administraties = _administraties(args.administratie)
    if administraties is None:
        return 2
    dagen = args.dagen or status_service.KANDIDAAT_DAGEN
    totaal = kandidaten_totaal = 0
    print(
        f"Afsluit-kandidaten — {len(administraties)} administratie(s), stil-venster {dagen} dagen. "
        "LEES-ONLY, geen actie."
    )
    for aid, naam in administraties:
        with scoped_session(aid) as session:
            projecten = list(
                session.scalars(
                    select(ProjectCache)
                    .where(
                        ProjectCache.administratie_id == aid,
                        ProjectCache.verdwenen_uit_bron_op.is_(None),
                        ProjectCache.is_actief.is_(True),
                        ProjectCache.status != PROJECT_STATUS_AFGESLOTEN,
                    )
                    .order_by(ProjectCache.naam)
                )
            )
            if not projecten:
                continue
            ids = {p.id for p in projecten}
            specs = {
                sp.project_id: sp
                for sp in session.scalars(
                    select(ProjectSpecificatie).where(
                        ProjectSpecificatie.administratie_id == aid, ProjectSpecificatie.project_id.in_(ids)
                    )
                )
            }
            gebouwd = {pid: _gebouwd_m2(session, aid, pid) for pid in ids}
            standen = status_service.kandidaat_afsluiten_per_project(
                session,
                administratie_id=aid,
                project_ids=ids,
                gebouwd_m2=gebouwd,
                contract_m2={pid: (specs[pid].contract_m2 if pid in specs else None) for pid in ids},
                dagen=dagen,
            )
        regels = []
        for p in projecten:
            st = standen.get(p.id)
            if st is None:
                continue
            totaal += 1
            if st.kandidaat:
                kandidaten_totaal += 1
            if st.kandidaat or args.alles:
                c = specs[p.id].contract_m2 if p.id in specs else None
                regels.append(
                    f"  {'KANDIDAAT' if st.kandidaat else 'nee      '} {p.id}  {p.naam!r}  "
                    f"gebouwd={gebouwd.get(p.id, Decimal('0'))} "
                    f"contract={c if c is not None else '—'} m²  {st.reden}"
                )
        if regels:
            print(f"\n{naam} ({aid}) — {len(projecten)} lopende projecten")
            print("\n".join(regels))
    print(
        f"\nTotaal: {totaal} lopende projecten beoordeeld, {kandidaten_totaal} kandidaat afsluiten. "
        "Afsluiten = klik in Inzicht › Projecten."
    )
    return 0


def _dubbele_nummers(args: argparse.Namespace) -> int:
    from app.db.session import scoped_session
    from app.projecten import nummer as nummer_module

    administraties = _administraties(args.administratie)
    if administraties is None:
        return 2
    totaal = 0
    print(f"Dubbele projectnummers — {len(administraties)} administratie(s). LEES-ONLY; samenvoegen = klikpunt Peter.")
    for aid, naam in administraties:
        with scoped_session(aid) as session:
            dubbel = nummer_module.dubbele_nummers(session, administratie_id=aid)
        if not dubbel:
            continue
        totaal += len(dubbel)
        print(f"\n{naam} ({aid})")
        print("\n".join(nummer_module.rapportregels(dubbel)))
    print(
        f"\nTotaal: {totaal} dubbel(e) nummer(s). Verliezer ná verhuizing op afgesloten (IsActive uit) — "
        "nooit verwijderen."
    )
    return 0


def run_projecten(args: argparse.Namespace) -> int:
    if args.commando == "projecten-afsluit-kandidaten":
        return _afsluit_kandidaten(args)
    if args.commando == "projecten-dubbele-nummers":
        return _dubbele_nummers(args)
    raise ValueError(f"onbekend projecten-commando {args.commando!r}")
