"""Data-stap ná migratie 0147 (Peter 16-09, Zenvoices-casus): vul `boekvoorstel.referentie_norm` voor bestaande rijen
met `normaliseer_referentie(referentie)`. Puur afgeleide cache-kolom (geen tijdlijn/audit — de letterlijke referentie
verandert niet); idempotent; `--dry-run` telt alleen. Per administratie in een gescoopte sessie (RLS)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select

from app.db.models import Administratie
from app.db.session import scoped_session
from app.documenten.models import Boekvoorstel, Document
from app.documenten.referentie import normaliseer_referentie


@dataclass
class BackfillUitkomst:
    administratie_id: uuid.UUID
    naam: str
    met_referentie: int = 0
    te_vullen: int = 0
    gevuld: int = 0
    voorbeelden: list[str] = field(default_factory=list)


def backfill(*, dry_run: bool, administratie_id: uuid.UUID | None = None) -> list[BackfillUitkomst]:
    with scoped_session(None) as session:
        q = select(Administratie.id, Administratie.naam).order_by(Administratie.naam)
        if administratie_id is not None:
            q = q.where(Administratie.id == administratie_id)
        administraties = session.execute(q).all()
    uitkomsten: list[BackfillUitkomst] = []
    for aid, naam in administraties:
        u = BackfillUitkomst(administratie_id=aid, naam=naam)
        with scoped_session(aid) as session:
            rijen = session.scalars(
                select(Boekvoorstel)
                .join(Document, Document.id == Boekvoorstel.document_id)
                .where(Document.administratie_id == aid, Boekvoorstel.referentie.is_not(None))
            ).all()
            for rij in rijen:
                u.met_referentie += 1
                norm = normaliseer_referentie(rij.referentie)
                if rij.referentie_norm == norm:
                    continue
                u.te_vullen += 1
                if len(u.voorbeelden) < 5:
                    u.voorbeelden.append(f"{rij.referentie!r} → {norm!r}")
                if not dry_run:
                    rij.referentie_norm = norm
                    u.gevuld += 1
            if not dry_run:
                session.flush()
        uitkomsten.append(u)
    return uitkomsten
