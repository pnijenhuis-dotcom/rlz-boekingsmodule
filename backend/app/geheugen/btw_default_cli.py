"""CLI btw-default per grootboekrekening (vervolg-opdracht Cowork/Peter 14-09; migratie 0143) — geregistreerd vanuit
app/cli.py (2 regels), zelfde patroon als app/autoboek_kandidaten/cli_cmd.py.

- `btw-default-rapport --administratie <naam|uuid> [--alles]` — LEES-ONLY nameting-instrument (in de allowlist van
  scripts/gcp/nameting.sh): per grootboekrekening de RLZ-default (0142, `PreferentialTaxRate`), de historie-default
  (0143: tarief, n, aandeel) of "geen" mét de verdeling; kop mét het aantal boekingsregels (inkoop + bank, 15-09) in
  het venster en de datum van de laatste afleiding. Schrijft niets. Standaard alleen rekeningen mét een default óf
  mét regels; `--alles` toont
  ook de rest. Meetrecept "werkt in productie": staat op LHG 4404 een historie-default?

Productie-uitvoering (regel Peter 08-09): uitsluitend op de gedeployde job-image via
`scripts/gcp/nameting.sh btw-default-rapport --administratie "L.H.G. Holding"`.
"""

from __future__ import annotations

import argparse
import re
import sys
import uuid

COMMANDO_RAPPORT = "btw-default-rapport"
COMMANDOS = (COMMANDO_RAPPORT,)


def register(subparsers) -> None:  # noqa: ANN001 — argparse-subparsers-actie
    rapport = subparsers.add_parser(
        COMMANDO_RAPPORT,
        help="LEES-ONLY nameting btw-default per grootboekrekening (14-09): RLZ-default / historie-default (n, aandeel) / "
        "geen — per administratie (naam of uuid). Schrijft niets.",
    )
    rapport.add_argument("--administratie", required=True, help="Naam (ilike, eenduidig) of UUID van de administratie.")
    rapport.add_argument(
        "--alles", action="store_true", help="Toon ook rekeningen zonder default én zonder regels in het venster."
    )


def dispatch(args: argparse.Namespace) -> int | None:
    """None = niet ons commando (cli.py gaat verder); anders de exit-code."""
    if args.commando == COMMANDO_RAPPORT:
        return rapport(args)
    return None


def _kaal(tekst: str) -> str:
    return re.sub(r"[^a-z0-9]", "", tekst.lower())


def _zoek_administratie(term: str) -> tuple[uuid.UUID, str] | None:
    from sqlalchemy import select

    from app.db.models import Administratie
    from app.db.session import scoped_session

    with scoped_session(None) as session:
        try:
            rij = session.get(Administratie, uuid.UUID(term))
            return (rij.id, rij.naam) if rij is not None else None
        except ValueError:
            pass
        kandidaten = list(session.scalars(select(Administratie).where(Administratie.naam.ilike(f"%{term}%"))))
        if not kandidaten:
            # Les rlz-lezen 14-09: "LHG Holding" ≠ "L.H.G. Holding B.V." — vergelijk zonder leestekens/spaties.
            kaal = _kaal(term)
            kandidaten = [k for k in session.scalars(select(Administratie)) if kaal and kaal in _kaal(k.naam)]
        exact = [k for k in kandidaten if k.naam.lower() == term.lower()]
        if len(exact) == 1:
            return exact[0].id, exact[0].naam
        if len(kandidaten) == 1:
            return kandidaten[0].id, kandidaten[0].naam
        if kandidaten:
            print(
                "FOUT  administratie niet eenduidig: " + ", ".join(sorted(k.naam for k in kandidaten)), file=sys.stderr
            )
        return None


def rapport(args: argparse.Namespace) -> int:
    from sqlalchemy import func, select

    from app.db.models import Grootboekrekening
    from app.db.session import scoped_session
    from app.geheugen.grootboek_btw_historie import HISTORIE_DAGEN, MIN_AANDEEL, MIN_REGELS, tellingen_per_rekening
    from app.geheugen.models import BoekingObservatie
    from app.sync.models import TaxRateCache
    from app.tijd import vandaag_nl

    gevonden = _zoek_administratie(args.administratie)
    if gevonden is None:
        print(f"FOUT  administratie {args.administratie!r} onbekend", file=sys.stderr)
        return 2
    administratie_id, naam = gevonden
    vandaag = vandaag_nl()
    with scoped_session(administratie_id) as session:
        tarieven = {
            t.id: t.naam
            for t in session.scalars(select(TaxRateCache).where(TaxRateCache.administratie_id == administratie_id))
        }
        rekeningen = list(
            session.scalars(
                select(Grootboekrekening)
                .where(
                    Grootboekrekening.administratie_id == administratie_id,
                    Grootboekrekening.verdwenen_uit_bron_op.is_(None),
                    Grootboekrekening.is_totaalrekening.is_(False),
                )
                .order_by(Grootboekrekening.code)
            )
        )
        tellingen = tellingen_per_rekening(session, administratie_id=administratie_id, vandaag=vandaag)
        totaal_observaties, laatste_datum = session.execute(
            select(func.count(), func.max(BoekingObservatie.bron_datum)).where(
                BoekingObservatie.administratie_id == administratie_id
            )
        ).one()
        berekend_op = max((r.historie_berekend_op for r in rekeningen if r.historie_berekend_op), default=None)

    in_venster = sum(sum(t.values()) for t in tellingen.values())
    print(f"Btw-default per grootboekrekening — {naam} ({administratie_id})")
    print(
        f"boekingsgeheugen: {totaal_observaties} observaties totaal (laatste {laatste_datum or '—'}), "
        f"{in_venster} boekingsregels (inkoop + bank) mét tarief in het venster van {HISTORIE_DAGEN} dagen; "
        f"regel: ≥ {MIN_REGELS} regels én één tarief ≥ {MIN_AANDEEL * 100:.0f} %; "
        f"laatste afleiding: {berekend_op.isoformat(timespec='minutes') if berekend_op else 'nog nooit'}"
    )
    print(f"{'code':<8}{'rekening':<40}{'RLZ-default':<28}{'historie-default':<44}verdeling")

    def tarief(t_id: uuid.UUID | None) -> str:
        if t_id is None:
            return "geen"
        return tarieven.get(t_id, f"onbekend tarief {str(t_id)[:8]}…")

    met_rlz = met_historie = met_regels_zonder = 0
    getoond = 0
    for r in rekeningen:
        verdeling = tellingen.get(r.ledger_id, {})
        n = sum(verdeling.values())
        if r.standaard_taxrate_id is not None:
            met_rlz += 1
        if r.historie_taxrate_id is not None:
            met_historie += 1
        elif n:
            met_regels_zonder += 1
        if not args.alles and r.standaard_taxrate_id is None and r.historie_taxrate_id is None and not n:
            continue
        getoond += 1
        if r.historie_taxrate_id is not None:
            aandeel = f"{(r.historie_taxrate_aandeel or 0) * 100:.0f} %"
            historie = f"{tarief(r.historie_taxrate_id)} ({r.historie_taxrate_n}×, {aandeel})"
        elif r.historie_taxrate_n:
            aandeel = f"{(r.historie_taxrate_aandeel or 0) * 100:.0f} %"
            historie = f"geen ({r.historie_taxrate_n} regels, hoogste {aandeel})"
        elif n:
            historie = f"geen (nog niet afgeleid; {n} regels nu)"
        else:
            historie = "geen (geen regels)"
        verdeling_tekst = ", ".join(
            f"{tarief(t)} {k}×" for t, k in sorted(verdeling.items(), key=lambda kv: (-kv[1], str(kv[0])))
        )
        print(f"{r.code:<8}{r.naam[:38]:<40}{tarief(r.standaard_taxrate_id)[:26]:<28}{historie[:42]:<44}{verdeling_tekst}")
    print(
        f"\n{len(rekeningen)} rekeningen ({getoond} getoond): {met_rlz} mét RLZ-default, {met_historie} mét "
        f"historie-default, {met_regels_zonder} mét regels zonder default, "
        f"{len(rekeningen) - met_rlz - met_historie - met_regels_zonder} zonder regels."
    )
    return 0
