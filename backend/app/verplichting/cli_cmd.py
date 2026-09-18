"""CLI `verplichting-match-herberekenen [--administratie X] [--dry-run]` (Peter 18-09, casus Bouwadvies: verbruik =
geboekt + onderweg).

Waarom: een matchrij wordt alleen herberekend als er iets gebeurt (voorstel-opslag, koppelen, statuswissel van een
factuur op dezelfde offerte). Facturen die op de deploydag al TER ACCORDERING staan, houden hun oude stand
(onderweg = 0) tot zo'n trigger komt — de kaart in de accordeur-app zou dan blijven zeggen "€ 50.000 van
€ 1.192.922,50". Dit commando draait `bereken_match` voor élk OPEN inkoopdocument mét een binnen/buiten-matchrij
(niet terminaal, niet geboekt — de geboekte stand is bevroren) en telt wat er veranderde. `--dry-run` = alleen
tellen/tonen. Geen RLZ-/Odoo-calls, geen statuswissels; een gewijzigde stand krijgt géén tijdlijnregel (dit is nazorg
ná de regelwijziging, geen volgorde-effect tussen facturen) maar wél het gewone `berekend_op`. Schrijvend → NIET in de
nameting-allowlist; uitvoeren als `gcloud run jobs execute` op de gedeployde image (regel Peter 08-09)."""

from __future__ import annotations

import argparse
import sys
import uuid
from decimal import Decimal

from sqlalchemy import select

VERPLICHTING_COMMANDOS = ("verplichting-match-herberekenen",)


def register_verplichting(subparsers) -> None:  # noqa: ANN001
    p = subparsers.add_parser(
        "verplichting-match-herberekenen",
        help="Peter 18-09: herbereken de offerte-match van álle open inkoopdocumenten mét een binnen/buiten-match "
        "(verbruik = geboekt + onderweg). --dry-run = alleen tonen. SCHRIJVEND (matchrijen), geen RLZ-calls.",
    )
    p.add_argument("--administratie", default=None, metavar="UUID|NAAMDEEL", help="Beperk tot één administratie.")
    p.add_argument(
        "--dry-run", action="store_true", help="Niets schrijven; alleen de kandidaten en huidige stand tonen."
    )


def herbereken(*, administratie_id: uuid.UUID, dry_run: bool) -> dict:
    """Eén administratie: → {"kandidaten", "herberekend", "gewijzigd", "regels"}. Puur orkestratie rond de pipeline."""
    from app.db.session import scoped_session
    from app.documenten.models import Document
    from app.verplichting import match as match_motor
    from app.verplichting import match_pipeline
    from app.verplichting.models import VerplichtingMatch

    with scoped_session(administratie_id) as session:
        kandidaten = [
            (rij.document_id, rij.uitkomst, rij.verbruik_na)
            for rij in session.scalars(
                select(VerplichtingMatch)
                .join(Document, Document.id == VerplichtingMatch.document_id)
                .where(
                    VerplichtingMatch.administratie_id == administratie_id,
                    VerplichtingMatch.uitkomst.in_([match_motor.BINNEN, match_motor.BUITEN]),
                    VerplichtingMatch.verrekend_op.is_(None),
                    Document.status.notin_(match_pipeline.ONDERWEG_UITGESLOTEN_STATUSSEN),
                )
                .order_by(VerplichtingMatch.berekend_op)
            )
        ]
    uit = {"kandidaten": len(kandidaten), "herberekend": 0, "gewijzigd": 0, "regels": []}
    for document_id, oud_uitkomst, oud_na in kandidaten:
        if dry_run:
            uit["regels"].append(f"  {document_id}  {oud_uitkomst:7}  verbruik_na {oud_na}  (dry-run)")
            continue
        nieuw = match_pipeline.bereken_match(administratie_id=administratie_id, document_id=document_id)
        if nieuw is None:
            continue
        uit["herberekend"] += 1
        oud_na_dec = Decimal(oud_na).quantize(Decimal("0.01")) if oud_na is not None else None
        veranderd = nieuw.uitkomst != oud_uitkomst or nieuw.verbruik_na != oud_na_dec
        if veranderd:
            uit["gewijzigd"] += 1
        uit["regels"].append(
            f"  {document_id}  {oud_uitkomst:7} → {nieuw.uitkomst:7}  verbruik_na {oud_na} → {nieuw.verbruik_na}"
            + (
                f"  (onderweg {nieuw.details.get('verbruik_onderweg')}, "
                f"{nieuw.details.get('onderweg_aantal')} facturen)"
                if veranderd
                else "  (ongewijzigd)"
            )
        )
    return uit


def run_verplichting(args: argparse.Namespace) -> int:
    from app.projecten.cli_cmd import _administraties  # zelfde UUID|NAAMDEEL-selectie

    administraties = _administraties(args.administratie)
    if administraties is None:
        return 2
    totaal = {"kandidaten": 0, "herberekend": 0, "gewijzigd": 0}
    for aid, naam in administraties:
        uit = herbereken(administratie_id=aid, dry_run=args.dry_run)
        if uit["kandidaten"] == 0:
            continue
        print(f"{naam} ({aid}): {uit['kandidaten']} open gematchte factu(u)r(en)")
        for regel in uit["regels"]:
            print(regel)
        for k in totaal:
            totaal[k] += uit[k]
    print(
        f"Totaal: {totaal['kandidaten']} kandidaten, {totaal['herberekend']} herberekend, "
        f"{totaal['gewijzigd']} gewijzigd" + (" (dry-run: niets geschreven)" if args.dry_run else ""),
        file=sys.stdout,
    )
    return 0
