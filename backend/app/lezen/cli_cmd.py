"""CLI `db-lezen` (Feiten eerst, 17-09) — lees-only, in de nameting-allowlist.

  db-lezen                                  → overzicht van de querybibliotheek
  db-lezen <query> [--param k=v …] [--administratie <uuid|naamdeel>] [--json] [--max-rijen N]
  db-lezen --sql "<SELECT …>" --als <e-mail van een actieve Beheerder>   → vrije SELECT, UITSLUITEND op de leesreplica
Exit 0 = uitvoer (markdown + optioneel JSON); 2 = ongeldige invoer/onbekende query/parameter; 3 = geen leesreplica; 1 = fout."""

from __future__ import annotations

import argparse
import sys
import uuid

DB_LEZEN_COMMANDO = "db-lezen"


def register_db_lezen(subparsers) -> None:  # noqa: ANN001
    p = subparsers.add_parser(
        DB_LEZEN_COMMANDO,
        help="Lees-only querybibliotheek op de eigen DB (Feiten eerst 17-09); --sql = vrije SELECT op de leesreplica.",
    )
    p.add_argument("query", nargs="?", default=None, help="Querynaam uit app/lezen/queries/ (leeg = overzicht).")
    p.add_argument("--param", action="append", default=[], help="k=v (herhaalbaar).")
    p.add_argument("--administratie", default=None, help="UUID of (deel van de) naam — beperkt scope-queries tot één administratie.")
    p.add_argument("--sql", default=None, help="Vrije SELECT (alleen mét leesreplica, alleen als Beheerder via --als).")
    p.add_argument("--als", default=None, help="E-mail van een actieve Beheerder namens wie de vrije SELECT leest (audit).")
    p.add_argument("--json", action="store_true", help="Óók JSON achter de markdown-tabel.")
    p.add_argument("--max-rijen", type=int, default=None, dest="max_rijen")


def _params(items: list[str]) -> dict[str, str]:
    uit: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"--param verwacht k=v, kreeg {item!r}")
        k, v = item.split("=", 1)
        uit[k.strip()] = v.strip()
    return uit


def _administratie_id(tekst: str) -> uuid.UUID:
    from app.rlz.lezen_cli import _zoek_administraties

    try:
        return uuid.UUID(tekst)
    except ValueError:
        pass
    treffers = _zoek_administraties(tekst)
    if len(treffers) != 1:
        raise ValueError(f"--administratie {tekst!r} is niet eenduidig ({len(treffers)} treffers)")
    return treffers[0][0]


def _beheerder_id(e_mail: str) -> uuid.UUID:
    from sqlalchemy import select

    from app.db.models import Gebruiker, GebruikerRol, GebruikerStatus
    from app.db.session import scoped_session

    with scoped_session(None) as session:
        rij = session.scalars(select(Gebruiker).where(Gebruiker.e_mail == e_mail.strip().lower())).first()
        if rij is None or rij.rol != GebruikerRol.BEHEERDER or rij.status != GebruikerStatus.ACTIEF:
            raise ValueError(f"--als {e_mail!r} is geen actieve Beheerder")
        return rij.id


def run_db_lezen(args: argparse.Namespace, *, uit=None) -> int:  # noqa: ANN001
    from app.lezen import bibliotheek, service
    from app.lezen.sql_poort import GeenSelect
    from app.lezen.uitvoer import MAX_RIJEN_CLI, als_json, als_markdown

    uit = uit or sys.stdout
    if args.sql:
        if not args.als:
            print("db-lezen: --sql vereist --als <e-mail van een actieve Beheerder> (audit: namens wie er gelezen wordt)", file=sys.stderr)
            return 2
        try:
            actor = _beheerder_id(args.als)
            adm = _administratie_id(args.administratie) if args.administratie else None
            u = service.voer_sql_uit(args.sql, actor_id=actor, administratie_id=adm, max_rijen=args.max_rijen or MAX_RIJEN_CLI)
        except GeenSelect as exc:
            print(f"db-lezen: geweigerd — {exc}", file=sys.stderr)
            return 2
        except service.GeenLeesreplica as exc:
            print(f"db-lezen: {exc}", file=sys.stderr)
            return 3
        except (ValueError, service.GeenBeheerder) as exc:
            print(f"db-lezen: {exc}", file=sys.stderr)
            return 2
        print(als_markdown(u.resultaat), file=uit)
        if args.json:
            print(als_json(u.resultaat), file=uit)
        return 0
    if not args.query:
        print(f"{'query':<28} {'v':<3} {'scope':<14} parameters — doel", file=uit)
        for q in service.overzicht():
            print(f"{q['naam']:<28} {q['versie']:<3} {q['scope']:<14} {', '.join(q['parameters']) or '-'} — {q['doel']}", file=uit)
        return 0
    try:
        params = _params(args.param)
        adm = _administratie_id(args.administratie) if args.administratie else None
        u = service.voer_query_uit(args.query, params, administratie_id=adm, max_rijen=args.max_rijen or MAX_RIJEN_CLI)
    except (bibliotheek.OnbekendeQuery, service.OntbrekendeParameter, ValueError) as exc:
        print(f"db-lezen: {exc}", file=sys.stderr)
        return 2
    print(f"== db-lezen {u.query} v{u.versie} ({u.duur_ms} ms) ==", file=uit)
    print(als_markdown(u.resultaat), file=uit)
    if args.json:
        print(als_json(u.resultaat), file=uit)
    return 0
