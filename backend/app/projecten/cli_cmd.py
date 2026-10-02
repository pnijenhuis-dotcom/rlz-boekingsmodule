"""LEES-ONLY CLI's projecten (blok 3 18-09, Peter's opruimpunten) — in de nameting-allowlist
(`scripts/gcp/nameting.sh`):

- `projecten-afsluit-kandidaten [--administratie X] [--maanden N] [--alles]` (herzien 19-09): dezelfde motor als de tab
  "Afsluiten? (N)" — kandidaat = stil N maanden (per administratie) / eindfactuur geboekt / naam zegt afgesloten / looptijd
  verstreken; per rij laatste activiteit + open posten, uitgestelde ("Niet afsluiten") apart. Geen actie: afsluiten
  blijft een
  klik van de mens (ook in bulk).
- `projecten-dubbele-nummers [--administratie X]`: alle dubbele projectnummers per administratie mét beide id's en de
  tellers facturen/weekstaten/planning per kant + voorstel "blijft" (klikpunt samenvoegen, nooit automatisch).
- `facturen-zonder-project (--administratie X | --alle-projectverplicht) [--jaar 2026] [--rlz]` (18-09 avond, TODO Peter
  23-08 "eerst rapport, dan beslissen"): in de module geboekte inkoopfacturen met een regel zonder project in
  project-verplichte administraties, gedekt/niet gedekt door een bevroren projectverdeling, aangifte-stand +
  herstelroute
  (voorstel, nooit uitgevoerd) + deterministisch projectvoorstel; `--rlz` = dezelfde toets op de RLZ-kant, uitsluitend GET
  (`app/projecten/zonder_project.py`).
Geen writes; RLZ alleen lezen (aangifte-status, en de regels bij `--rlz`).

- `project-dubbel-samenvoegen --administratie X --nummer N [--dry-run] [--uitvoeren] [--actor UUID|E-MAIL]` (run A
  02-10 punt 11, casus 26149 Universal Steigerbouw): SCHRIJVEND bij `--uitvoeren` — dry-run is de default en staat in
  de nameting-allowlist (alleen mét --dry-run); de echte run = `gcloud run jobs execute rlz-reconciliatie
  --args=-m,app.cli,project-dubbel-samenvoegen,--administratie,…,--nummer,26149,--uitvoeren` ná Peters "ja"
  (`app/projecten/samenvoegen.py`)."""

from __future__ import annotations

import argparse
import sys
import uuid

from sqlalchemy import select

PROJECTEN_COMMANDOS = (
    "projecten-afsluit-kandidaten",
    "projecten-dubbele-nummers",
    "facturen-zonder-project",
    "project-dubbel-samenvoegen",
)


def register_projecten(subparsers) -> None:  # noqa: ANN001
    sv = subparsers.add_parser(
        "project-dubbel-samenvoegen",
        help="Run A 02-10 punt 11: dubbel projectnummer samenvoegen — het oudste project mét koppelingen blijft, de "
        "andere worden omgehangen (weekstaten, meerwerk, planning, documenten, verdelingen, offertes, …) mét audit + "
        "tijdlijn en daarna afgesloten via de 0160-flow (RLZ IsActive false / Odoo archived). DRY-RUN is de default; "
        "--uitvoeren schrijft (alleen als job-executie ná Peters ja). Nooit verwijderen.",
    )
    sv.add_argument("--administratie", required=True, metavar="UUID|NAAMDEEL", help="Precies één administratie.")
    sv.add_argument("--nummer", required=True, metavar="NNNNN", help="Het dubbele projectnummer (cijfer-prefix).")
    sv.add_argument("--dry-run", action="store_true", help="Toon exact wat zou gebeuren (default).")
    sv.add_argument("--uitvoeren", action="store_true", help="Echt omhangen + verliezer afsluiten. Alleen ná Peters ja.")
    sv.add_argument(
        "--actor",
        default=None,
        metavar="UUID|E-MAIL",
        help="Actor voor audit/tijdlijn (default: systeem-actor; die passeert de rolpoort — de job-executie is de poort).",
    )
    kand = subparsers.add_parser(
        "projecten-afsluit-kandidaten",
        help="19-09: LEES-ONLY — afsluit-kandidaten uit dezelfde motor als de tab Afsluiten? (stil N mnd / eindfactuur / "
        "naam zegt afgesloten / looptijd verstreken) mét laatste activiteit en open posten; nooit automatisch afsluiten.",
    )
    kand.add_argument("--administratie", default=None, metavar="UUID|NAAMDEEL", help="Beperk tot één administratie.")
    kand.add_argument(
        "--maanden", type=int, default=None, help="Stil-venster in maanden (default: instelling per administratie, 6)."
    )
    kand.add_argument("--alles", action="store_true", help="Toon óók de niet-kandidaten.")
    dub = subparsers.add_parser(
        "projecten-dubbele-nummers",
        help="Blok 3 18-09: LEES-ONLY — dubbele projectnummers per administratie (beide id's, facturen/weekstaten/"
        "planning per kant, voorstel welke blijft). Klikpunt samenvoegen, nooit automatisch.",
    )
    dub.add_argument("--administratie", default=None, metavar="UUID|NAAMDEEL", help="Beperk tot één administratie.")
    zp = subparsers.add_parser(
        "facturen-zonder-project",
        help="18-09 avond: LEES-ONLY — geboekte inkoopfacturen met een regel zonder project in project-verplichte "
        "administraties (module-kant; --rlz = ook de RLZ-kant, uitsluitend GET), aangifte-stand en herstelroute als "
        "VOORSTEL. Geen write, geen statuswissel.",
    )
    zp.add_argument("--administratie", default=None, metavar="UUID|NAAMDEEL", help="Eén administratie (naam of id).")
    zp.add_argument("--alle-projectverplicht", action="store_true", help="Alle actieve administraties mét project_verplicht.")
    zp.add_argument("--jaar", type=int, default=None, help="Alleen facturen met factuurdatum in dit jaar (default: alle).")
    zp.add_argument("--rlz", action="store_true", help="Ook de RLZ-kant lezen (PurchaseInvoices + Lines, alleen GET; jaar verplicht).")


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
    """Opdracht 19-09: dezelfde motor als de tab "Afsluiten? (N)" (`app/projecten/afsluiten.py`) — aantal per reden,
    "Afgesloten …"-namen bovenaan, laatste activiteit + open posten per rij, uitgestelde rijen apart. LEES-ONLY."""
    from app.db.session import scoped_session
    from app.projecten import afsluiten

    administraties = _administraties(args.administratie)
    if administraties is None:
        return 2
    totaal = kandidaten_totaal = uitgesteld_totaal = 0
    per_reden: dict[str, int] = {r: 0 for r in afsluiten.REDENEN}
    print(
        f"Afsluit-kandidaten — {len(administraties)} administratie(s), stil-venster "
        f"{args.maanden or 'per administratie (default 6)'} mnd. LEES-ONLY, geen actie; "
        "afsluiten = Projecten › Afsluiten? (N)."
    )
    for aid, naam in administraties:
        with scoped_session(aid) as session:
            rijen = afsluiten.kandidaten_voor_administratie(
                session, administratie_id=aid, administratie_naam=naam, stil_maanden=args.maanden
            )
        if not rijen:
            continue
        totaal += len(rijen)
        kandidaten = [r for r in rijen if r.kandidaat]
        uitgesteld = [r for r in rijen if r.uitgesteld]
        kandidaten_totaal += len(kandidaten)
        uitgesteld_totaal += len(uitgesteld)
        for r in kandidaten:
            for rd in r.redenen:
                per_reden[rd] += 1
        regels = afsluiten.rapportregels(rijen, alles=args.alles)
        if regels:
            print(
                f"\n{naam} ({aid}) — {len(rijen)} lopende projecten, {len(kandidaten)} kandidaat, "
                f"{len(uitgesteld)} uitgesteld; per reden: "
                + ", ".join(
                    f"{afsluiten.REDEN_LABEL[rd]} {sum(1 for k in kandidaten if rd in k.redenen)}" for rd in afsluiten.REDENEN
                )
            )
            print("\n".join(regels))
    print(
        f"\nTotaal: {totaal} lopende projecten beoordeeld, {kandidaten_totaal} kandidaat afsluiten "
        f"({', '.join(f'{afsluiten.REDEN_LABEL[r]} {n}' for r, n in per_reden.items())}), "
        f"{uitgesteld_totaal} uitgesteld. "
        "Afsluiten = vinkjes + 'Afsluiten (N)' in Projecten › Afsluiten? — nooit automatisch."
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


def _facturen_zonder_project(args: argparse.Namespace) -> int:
    from functools import partial

    from app.db.session import scoped_session
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID
    from app.odoo.ids import is_odoo_sentinel
    from app.projecten import zonder_project as zp
    from app.rlz.aangifte import AangiftePoort
    from app.rlz.client import RlzApiError
    from app.rlz.credentials import GeenRlzCredentials, client_voor_rlz_admin_id

    if bool(args.administratie) == bool(args.alle_projectverplicht):
        print("kies precies één van --administratie <naam|id> of --alle-projectverplicht", file=sys.stderr)
        return 2
    if args.rlz and args.jaar is None:
        print("--rlz vereist --jaar (de RLZ-lezing is per jaar begrensd)", file=sys.stderr)
        return 2
    from app.db.models import Administratie

    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        if args.alle_projectverplicht:
            gekozen = [(a.id, a.naam, a.rlz_admin_id, a.project_verplicht) for a in zp.project_verplichte_administraties(session)]
        else:
            alle = _administraties(args.administratie)
            if alle is None:
                return 2
            rijen = [session.get(Administratie, aid) for aid, _ in alle]
            gekozen = [(a.id, a.naam, a.rlz_admin_id, a.project_verplicht) for a in rijen if a is not None]
    print(
        f"Facturen zonder project — {len(gekozen)} administratie(s), jaar {args.jaar or 'alle'}"
        f"{', mét RLZ-kant (alleen GET)' if args.rlz else ''}. LEES-ONLY: geen write, geen statuswissel; herstelroute = VOORSTEL."
    )
    totaal_bevinding = totaal_gedekt = 0
    routes: dict[str, int] = {}
    for aid, naam, rlz_admin_id, project_verplicht in gekozen:
        if not project_verplicht:
            print(f"\n{naam} ({aid}): project_verplicht staat UIT — niets te toetsen (alleen project-verplichte administraties).")
            continue
        with scoped_session(aid) as session:
            uitkomst = zp.module_kant(session, administratie_id=aid, administratie_naam=naam, jaar=args.jaar)
        client = None
        reden = None
        if is_odoo_sentinel(rlz_admin_id):
            reden = "Odoo-administratie — aangifte-/RLZ-toets niet van toepassing"
        else:
            try:
                client = client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)
            except GeenRlzCredentials as exc:
                reden = f"geen RLZ-credential: {exc}"
        if client is not None and any(not r.gedekt_door_verdeling for r in uitkomst.rijen):
            poort = AangiftePoort(client)
            zp.bepaal_routes(uitkomst, partial(poort.toets_boekdatum, kant="inkoop"))
        else:
            zp.bepaal_routes(uitkomst, None, reden_niet_toetsbaar=reden)
        if args.rlz:
            if client is None:
                uitkomst.rlz_melding = reden or "geen RLZ-client"
            else:
                try:
                    zp.rlz_kant(uitkomst, client, jaar=args.jaar)
                except RlzApiError as exc:
                    uitkomst.rlz_rijen = None
                    uitkomst.rlz_melding = f"RLZ-leesfout {exc.status_code}: {exc}"
        print()
        print("\n".join(zp.rapportregels(uitkomst)))
        totaal_bevinding += uitkomst.documenten_zonder_project
        totaal_gedekt += uitkomst.documenten_gedekt
        for k, v in uitkomst.routes.items():
            routes[k] = routes.get(k, 0) + v
    print(
        f"\nTotaal: {totaal_bevinding} document(en) zonder project (bevinding), {totaal_gedekt} gedekt door projectverdeling; "
        f"routes: {routes or 'geen'}. Herstellen = nieuwe opdracht ná besluit Peter; deze CLI schrijft niets."
    )
    return 0


def _actor_id(tekst: str | None) -> uuid.UUID | None:
    from app.db.models import Gebruiker
    from app.db.session import scoped_session
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID

    if not tekst:
        return SYSTEEM_ACTOR_ID
    try:
        return uuid.UUID(tekst)
    except ValueError:
        pass
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        rij = session.scalars(select(Gebruiker).where(Gebruiker.e_mail == tekst.strip().lower())).first()
        if rij is None:
            print(f"--actor {tekst!r}: geen gebruiker met dit e-mailadres", file=sys.stderr)
            return None
        return rij.id


def _dubbel_samenvoegen(args: argparse.Namespace) -> int:
    from app.projecten import samenvoegen

    if args.dry_run and args.uitvoeren:
        print("kies óf --dry-run (default) óf --uitvoeren, niet beide", file=sys.stderr)
        return 2
    nummer = " ".join(str(args.nummer).split())
    if not nummer.isdigit():
        print(f"--nummer {args.nummer!r}: alleen cijfers (cijfer-prefix van de projectnaam, bv. 26149)", file=sys.stderr)
        return 2
    administraties = _administraties(args.administratie)
    if administraties is None:
        return 2
    actor = _actor_id(args.actor)
    if actor is None:
        return 2
    (aid, naam), = administraties
    dry_run = not args.uitvoeren
    print(
        f"Dubbel projectnummer samenvoegen — {naam} ({aid}), nummer {nummer}, "
        f"modus {'DRY-RUN (niets geschreven)' if dry_run else 'UITVOEREN (omhangen + verliezer afsluiten via de 0160-flow)'}. "
        "Nooit verwijderen; RLZ/Odoo alleen via sluit_project_af (IsActive false, teruggelezen)."
    )
    uit = samenvoegen.samenvoegen(
        administratie_id=aid, administratie_naam=naam, nummer=nummer, actor_id=actor, dry_run=dry_run
    )
    print("\n".join(samenvoegen.rapportregels(uit)))
    if uit.fout and uit.verliezers:
        print(f"\nFOUT: {uit.fout}", file=sys.stderr)
        return 1
    return 0


def run_projecten(args: argparse.Namespace) -> int:
    if args.commando == "project-dubbel-samenvoegen":
        return _dubbel_samenvoegen(args)
    if args.commando == "projecten-afsluit-kandidaten":
        return _afsluit_kandidaten(args)
    if args.commando == "projecten-dubbele-nummers":
        return _dubbele_nummers(args)
    if args.commando == "facturen-zonder-project":
        return _facturen_zonder_project(args)
    raise ValueError(f"onbekend projecten-commando {args.commando!r}")
