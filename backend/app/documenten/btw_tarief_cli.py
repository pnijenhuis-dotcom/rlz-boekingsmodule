"""CLI `btw-tarief-afwijking-rapport` — LEES-ONLY nameting-instrument (opdracht Peter 18-09 regel 5, in de allowlist van
scripts/gcp/nameting.sh): geboekte inkoopdocumenten sinds een datum (default 2026-08-25, de dag van het besluit
"factuur-btw leidend" dat de hint i.p.v. een check opleverde) waarvan een regel |btw − netto × percentage| > marge
draagt
(marge = `regelsom.marge_voor(1)` = 1 cent; `--marge-ct` overschrijft). Per regel: administratie, document, boekstuk,
grootboek, tarief, netto, btw, verwacht, verschil. Schrijft niets; niets wordt in RLZ gecorrigeerd — Peter beslist per
geval (storno 19 → herboeken, achter de aangiftepoort). Productie: uitsluitend via
`scripts/gcp/nameting.sh btw-tarief-afwijking-rapport [--sinds 2026-08-25] [--administratie <naam|uuid>]`.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import date
from decimal import Decimal

COMMANDO = "btw-tarief-afwijking-rapport"


def register(subparsers) -> None:  # noqa: ANN001 — argparse-subparsers-actie
    p = subparsers.add_parser(
        COMMANDO,
        help="LEES-ONLY (18-09): geboekte inkoopdocumenten sinds --sinds met een regel waarvan het btw-bedrag niet bij "
        "het "
        "tarief past (|btw − netto × p| > marge). Schrijft niets.",
    )
    p.add_argument("--sinds", default="2026-08-25", help="Geboekt op/na deze datum (ISO), default 2026-08-25.")
    p.add_argument("--administratie", default=None, help="Beperk tot één administratie (naam ilike of uuid).")
    p.add_argument("--marge-ct", type=int, default=1, dest="marge_ct", help="Marge in centen (default 1).")


def dispatch(args: argparse.Namespace) -> int | None:
    if getattr(args, "commando", None) != COMMANDO:
        return None
    return rapport(args)


def afwijkingen(
    *, sinds: date, administratie_id: uuid.UUID | None = None, marge: Decimal = Decimal("0.01")
) -> list[dict]:
    """Pure lees-query (systeem-scope over álle administraties): één statement, geen RLZ-call."""
    from sqlalchemy import and_, exists, func, select

    from app.db.models import Administratie, Grootboekrekening
    from app.db.session import scoped_session
    from app.documenten.models import Boekvoorstel, BoekvoorstelRegel, Document, DocumentGebeurtenis, DocumentStatus
    from app.documenten.regelsom import btw_uit_tarief
    from app.sync.btw import taxrate_vlaggen
    from app.sync.models import TaxRateCache

    geboekt_sinds = exists().where(
        and_(
            DocumentGebeurtenis.document_id == Document.id,
            DocumentGebeurtenis.naar_status == DocumentStatus.GEBOEKT,
            func.date(DocumentGebeurtenis.tijdstip) >= sinds,
        )
    )
    q = (
        select(
            Administratie.naam,
            Document.id,
            Boekvoorstel.referentie,
            Boekvoorstel.rlz_boekstuknummer,
            BoekvoorstelRegel.volgnummer,
            Grootboekrekening.code,
            TaxRateCache.naam.label("tarief"),
            TaxRateCache.percentage,
            TaxRateCache.brondata,
            BoekvoorstelRegel.netto_bedrag,
            BoekvoorstelRegel.btw_bedrag,
        )
        .join(Boekvoorstel, Boekvoorstel.document_id == BoekvoorstelRegel.document_id)
        .join(Document, Document.id == Boekvoorstel.document_id)
        .join(Administratie, Administratie.id == Document.administratie_id)
        .join(
            TaxRateCache,
            and_(
                TaxRateCache.id == BoekvoorstelRegel.taxrate_id,
                TaxRateCache.administratie_id == Document.administratie_id,
            ),
        )
        .outerjoin(
            Grootboekrekening,
            and_(
                Grootboekrekening.ledger_id == BoekvoorstelRegel.ledger_id,
                Grootboekrekening.administratie_id == Document.administratie_id,
            ),
        )
        .where(
            Document.status == DocumentStatus.GEBOEKT,
            Document.soort == "inkoopfactuur",
            BoekvoorstelRegel.netto_bedrag.is_not(None),
            BoekvoorstelRegel.btw_bedrag.is_not(None),
            geboekt_sinds,
        )
        .order_by(Administratie.naam, Document.id, BoekvoorstelRegel.volgnummer)
    )
    if administratie_id is not None:
        q = q.where(Document.administratie_id == administratie_id)
    uit: list[dict] = []
    with scoped_session(None) as session:
        for rij in session.execute(q).all():
            verlegd, vrijgesteld = taxrate_vlaggen(rij.brondata)
            pct = Decimal(0) if (verlegd or vrijgesteld) else rij.percentage
            if pct is None:
                continue
            verwacht = btw_uit_tarief(rij.netto_bedrag, pct)
            verschil = rij.btw_bedrag - verwacht
            if abs(verschil) <= marge:
                continue
            uit.append(
                {
                    "administratie": rij.naam,
                    "document_id": rij.id,
                    "referentie": rij.referentie,
                    "boekstuk": rij.rlz_boekstuknummer,
                    "regel": rij.volgnummer,
                    "grootboek": rij.code,
                    "tarief": rij.tarief,
                    "percentage": pct,
                    "netto": rij.netto_bedrag,
                    "btw": rij.btw_bedrag,
                    "verwacht": verwacht,
                    "verschil": verschil,
                }
            )
    return uit


def rapport(args: argparse.Namespace) -> int:
    from app.geheugen.btw_default_cli import _zoek_administratie

    try:
        sinds = date.fromisoformat(args.sinds)
    except ValueError:
        print(f"FOUT  --sinds {args.sinds!r} is geen ISO-datum", file=sys.stderr)
        return 2
    administratie_id = None
    if args.administratie:
        gevonden = _zoek_administratie(args.administratie)
        if gevonden is None:
            print(f"FOUT  administratie {args.administratie!r} onbekend", file=sys.stderr)
            return 2
        administratie_id = gevonden[0]
    marge = Decimal(args.marge_ct) / 100
    rijen = afwijkingen(sinds=sinds, administratie_id=administratie_id, marge=marge)
    print(
        f"Btw-bedrag ≠ tarief × netto — geboekte inkoopdocumenten sinds {sinds.isoformat()}, marge {args.marge_ct} ct "
        f"(lees-only; niets gecorrigeerd — Peter beslist per geval: storno 19 → herboeken, achter de aangiftepoort)"
    )
    print(
        f"{'administratie':<32}{'document':<38}{'referentie':<22}{'boekstuk':<18}{'r':<3}{'gb':<6}{'tarief':<28}{'netto':>10}{'btw':>9}{'verwacht':>10}{'verschil':>9}"
    )
    for r in rijen:
        print(
            f"{(r['administratie'] or '')[:31]:<32}{str(r['document_id']):<38}{(r['referentie'] or '')[:21]:<22}"
            f"{(r['boekstuk'] or '')[:17]:<18}{r['regel']:<3}{(r['grootboek'] or '')[:5]:<6}"
            f"{(r['tarief'] or '')[:27]:<28}"
            f"{r['netto']:>10}{r['btw']:>9}{r['verwacht']:>10}{r['verschil']:>9}"
        )
    per_adm: dict[str, int] = {}
    for r in rijen:
        per_adm[r["administratie"]] = per_adm.get(r["administratie"], 0) + 1
    print(
        f"TOTAAL     {len(rijen)} regel(s) in {len(per_adm)} administratie(s)"
        + (": " + ", ".join(f"{k} {v}" for k, v in sorted(per_adm.items())) if per_adm else "")
    )
    return 0
