"""`btw-default-rapport` (app/geheugen/btw_default_cli.py, lees-only nameting-instrument, 0143): administratie op naam
of uuid, per rekening RLZ-default / historie-default (n, aandeel) / geen mét verdeling; schrijft niets."""

from __future__ import annotations

import argparse
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select, text

from app.db.models import Grootboekrekening
from app.db.session import scoped_session
from app.geheugen import btw_default_cli, grootboek_btw_historie
from app.geheugen.models import BoekingObservatie
from app.sync.models import TaxRateCache

HOOG = uuid.UUID("55555555-0000-0000-0000-000000000021")
LAAG = uuid.UUID("55555555-0000-0000-0000-000000000009")
GB_4404 = uuid.UUID("44444444-0000-0000-0000-000000004404")
GB_4403 = uuid.UUID("44444444-0000-0000-0000-000000004403")
GB_4000 = uuid.UUID("44444444-0000-0000-0000-000000004000")


def _args(**kw) -> argparse.Namespace:
    return argparse.Namespace(commando="btw-default-rapport", administratie=kw.get("administratie"), alles=kw.get("alles", False))


def test_rapport_per_rekening(administratie_id: uuid.UUID, admin_engine, capsys) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.administratie SET naam = 'L.H.G. Holding B.V.' WHERE id = :id"), {"id": administratie_id}
        )
    with scoped_session(administratie_id) as session:
        for id_, naam in ((HOOG, "NL, Hoog Tarief"), (LAAG, "NL, Laag Tarief")):
            session.add(TaxRateCache(id=id_, administratie_id=administratie_id, naam=naam, percentage=Decimal("0.21"), brondata={}))
        for ledger_id, code, rlz in ((GB_4404, "4404", None), (GB_4403, "4403", None), (GB_4000, "4000", LAAG)):
            session.add(
                Grootboekrekening(
                    ledger_id=ledger_id, administratie_id=administratie_id, code=code, naam=f"Rekening {code}", soort=2,
                    is_totaalrekening=False, standaard_taxrate_id=rlz,
                )
            )
        recent = date(2026, 9, 1)
        for gb, btw, n in ((GB_4404, HOOG, 9), (GB_4404, LAAG, 1), (GB_4403, HOOG, 2)):
            for _ in range(n):
                session.add(
                    BoekingObservatie(
                        id=uuid.uuid4(), administratie_id=administratie_id, vendor_id=uuid.uuid4(), gb_id=gb, btw_id=btw,
                        bron="rlz_seed", bron_datum=recent, boekstuk_ref="R",
                    )
                )
    grootboek_btw_historie.herbereken_voor(administratie_id, vandaag=recent + timedelta(days=13))

    assert btw_default_cli.rapport(_args(administratie="lhg holding")) == 0
    uit = capsys.readouterr().out
    assert "L.H.G. Holding B.V." in uit and "12 inkoopregels mét tarief" in uit
    assert "4404" in uit and "NL, Hoog Tarief (10×, 90 %)" in uit and "NL, Hoog Tarief 9×, NL, Laag Tarief 1×" in uit
    assert "geen (2 regels, hoogste 100 %)" in uit
    assert "4000" in uit and "NL, Laag Tarief" in uit  # RLZ-default zichtbaar
    assert "3 rekeningen (3 getoond): 1 mét RLZ-default, 1 mét historie-default, 1 mét regels zonder default, 0 zonder regels." in uit

    # Op uuid werkt ook; onbekende naam = exit 2; het rapport schreef niets.
    assert btw_default_cli.rapport(_args(administratie=str(administratie_id))) == 0
    assert btw_default_cli.rapport(_args(administratie="bestaat-niet-xyz")) == 2
    with scoped_session(administratie_id) as session:
        assert session.scalars(select(Grootboekrekening).where(Grootboekrekening.ledger_id == GB_4404)).one().historie_taxrate_n == 10
