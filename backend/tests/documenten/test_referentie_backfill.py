"""Migratie 0147 + data-stap `referentie-norm-backfill` (Peter 16-09): de vergelijkingsvorm reist mee bij opslaan en
wordt voor bestaande rijen deterministisch gevuld."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import text

from app.db.session import scoped_session
from app.documenten import boekvoorstel, referentie_backfill, service
from app.documenten.models import Boekvoorstel
from app.documenten.storage import LokaleBestandsopslag


def _upload(
    administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag, referentie: str
) -> uuid.UUID:
    r = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="factuur.pdf",
        inhoud=b"%PDF-1.4 " + uuid.uuid4().bytes,
        actor_id=actor_id,
        opslag=opslag,
    )
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=r.document_id,
        actor_id=actor_id,
        vendor_id=uuid.uuid4(),
        referentie=referentie,
        factuurdatum=date(2026, 8, 10),
        totaalbedrag=Decimal("12600.00"),
        regels=[],
    )
    return r.document_id


def test_opslaan_schrijft_de_genormaliseerde_vorm(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
) -> None:
    document_id = _upload(administratie_id, gescoopte_gebruiker, opslag, "2 4594 001722")
    with scoped_session(administratie_id) as session:
        rij = session.get(Boekvoorstel, document_id)
        assert rij.referentie == "2 4594 001722" and rij.referentie_norm == "24594001722"


def test_backfill_vult_lege_en_verouderde_rijen_dry_run_schrijft_niets(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, admin_engine
) -> None:
    a = _upload(administratie_id, gescoopte_gebruiker, opslag, "2 4594 001722")
    b = _upload(administratie_id, gescoopte_gebruiker, opslag, "Factuur 2026-0042")
    with admin_engine.begin() as conn:  # simuleer rijen van vóór 0147 / met een oude normalisatie
        conn.execute(
            text("UPDATE boekhouding.boekvoorstel SET referentie_norm = NULL WHERE document_id = :id"), {"id": a}
        )
        conn.execute(
            text("UPDATE boekhouding.boekvoorstel SET referentie_norm = 'oud' WHERE document_id = :id"), {"id": b}
        )
    (droog,) = referentie_backfill.backfill(dry_run=True, administratie_id=administratie_id)
    assert droog.met_referentie == 2 and droog.te_vullen == 2 and droog.gevuld == 0
    with scoped_session(administratie_id) as session:
        assert session.get(Boekvoorstel, a).referentie_norm is None
    (echt,) = referentie_backfill.backfill(dry_run=False, administratie_id=administratie_id)
    assert echt.te_vullen == 2 and echt.gevuld == 2
    with scoped_session(administratie_id) as session:
        assert session.get(Boekvoorstel, a).referentie_norm == "24594001722"
        assert session.get(Boekvoorstel, b).referentie_norm == "202642"
    (nogmaals,) = referentie_backfill.backfill(dry_run=False, administratie_id=administratie_id)
    assert nogmaals.te_vullen == 0  # idempotent
