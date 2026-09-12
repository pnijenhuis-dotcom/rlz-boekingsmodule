"""CLI `migratie-schoonlijst` (bundel 10-09 blok D1) — lees-only rapport vóór een RLZ → Odoo-overstap.

Productie-regel Peter 08-09: draait uitsluitend op de gedeployde job-image
(`gcloud run jobs execute rlz-reconciliatie --args="-m,app.cli,migratie-schoonlijst,--administratie,<uuid>,…"`).
Geen writes: geen RLZ-PUT/POST, geen DB-mutatie, alleen stdout + optioneel een JSON-bestand."""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

from sqlalchemy import select

from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID


def zoek_administratie(tekst: str) -> tuple[uuid.UUID, str, str] | None:
    """(id, naam, rlz_admin_id) op UUID óf naam-substring (zelfde gemak als `bank-voorstellen-lezen`)."""
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        try:
            administratie = session.get(Administratie, uuid.UUID(tekst))
        except ValueError:
            administratie = session.scalars(select(Administratie).where(Administratie.naam.ilike(f"%{tekst}%"))).first()
        if administratie is None:
            return None
        return administratie.id, administratie.naam, administratie.rlz_admin_id


def register_migratie(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = subparsers.add_parser(
        "migratie-schoonlijst",
        help=(
            "LEES-ONLY schoonlijst vóór een RLZ → Odoo-overstap: concepten (zonder systeemhulzen en kopieën van "
            "geboekt), vermoedelijke dubbelen (bank leidend; verschillend kenmerk en bank-bevestigd apart), open "
            "bankregels, dubbele IBAN's, boekingen zonder relatie mét bijlage (markdown op stdout, optioneel JSON)."
        ),
    )
    p.add_argument("--administratie", required=True, help="UUID of (deel van de) naam van de administratie.")
    p.add_argument("--json-uit", dest="json_uit", default=None, help="Pad voor het JSON-rapport (zelfde inhoud).")
    p.add_argument(
        "--max-bijlage-checks",
        dest="max_bijlage_checks",
        type=int,
        default=200,
        help="Maximaal aantal GET …/Uploads-checks voor boekingen zonder relatie (default 200).",
    )
    p.add_argument(
        "--verwacht",
        default=None,
        help=(
            'Verwachtingen van Peter, bv. "concepten=17,dubbelen=3,open_bankregels=44,dubbele_iban=1". '
            "Sinds run 2 VGG (12-09) ook systeemhulzen_open_bank, concept_kopie_van_geboekt, "
            "zelfde_bedrag_verschillend_kenmerk en bank_bevestigd."  # run 2 VGG blok 1
        ),
    )


def run_migratie(args: argparse.Namespace) -> int:
    from app.migratie import schoonlijst
    from app.rlz.credentials import GeenRlzCredentials, client_voor_rlz_admin_id

    gevonden = zoek_administratie(args.administratie)
    if gevonden is None:
        print(f"FOUT  administratie {args.administratie!r} onbekend", file=sys.stderr)
        return 2
    administratie_id, naam, rlz_admin_id = gevonden
    try:
        verwacht = schoonlijst.parse_verwacht(args.verwacht)
    except ValueError as exc:
        print(f"FOUT  --verwacht: {exc}", file=sys.stderr)
        return 2
    try:
        client = client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)
    except GeenRlzCredentials as exc:
        print(f"FOUT  geen RLZ-credential voor {naam} ({rlz_admin_id}): {exc}", file=sys.stderr)
        return 2
    with client:
        lijst = schoonlijst.maak_schoonlijst(
            client,
            administratie_id=str(administratie_id),
            rlz_admin_id=rlz_admin_id,
            max_bijlage_checks=args.max_bijlage_checks,
            verwacht=verwacht,
        )
    print(schoonlijst.als_markdown(lijst, administratie_naam=naam))
    if args.json_uit:
        Path(args.json_uit).write_text(lijst.als_json(), encoding="utf-8")
        print(f"JSON geschreven: {args.json_uit}")
    if lijst.fouten:
        print(f"{len(lijst.fouten)} route(s) weigerden — rapport onvolledig, zie 'Fouten'", file=sys.stderr)
        return 1
    return 0
