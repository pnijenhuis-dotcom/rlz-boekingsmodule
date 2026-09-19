"""Casus (x, 19-09) — bulk-upload op de cloud-wachtrij: één job-executie per batch, één verwerker per document.

Productie 18-09 (BLOW, 180 documenten): élke upload triggerde een eigen job-executie → 118 executies in één uur,
180 × `429 Too Many Requests`, hetzelfde document tot 8 × verwerkt, en één trage transactie zette een al afgevoerd
duplicaat stil terug in de werkvoorraad (tellers 151 ↔ 152). Op échte casusdocumenten (Spot Services + Floor via de
AI-stub, groot genoeg voor de wachtrij-route): twee uploads binnen het bundelvenster = één trigger + één
`gebundeld`-spoor; de job-drain verwerkt beide precies één keer; de tellers-cache volgt de telling; een late schrijver
mét verouderde status wordt geweigerd."""


from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import settings
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import service
from app.documenten.models import Document, DocumentGebeurtenis, DocumentStatus
from app.documenten.statusmachine import OngeldigeStatusovergang
from app.documenten.wachtrij import (
    UITKOMST_GEBUNDELD,
    UITKOMST_GESLAAGD,
    CloudRunJobExtractieWachtrij,
    reset_bundelvenster,
)
from app.werkvoorraad import tellers
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import Keten

JOB = "projects/rlz-boekhouding/locations/europe-west4/jobs/rlz-extractie-wachtrij"


def _overgangen(keten: Keten, document_id) -> list[tuple[str | None, str]]:  # noqa: ANN001
    with scoped_session(keten.administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        rijen = session.scalars(
            select(DocumentGebeurtenis)
            .where(DocumentGebeurtenis.document_id == document_id)
            .order_by(DocumentGebeurtenis.tijdstip)
        ).all()
        return [(g.van_status.value if g.van_status else None, g.naar_status.value) for g in rijen]


def test_x_bulk_upload_een_executie_per_batch_en_een_verwerker_per_document(
    keten: Keten, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ai_extractie_sync_max_bytes", 10)  # échte PDF's → wachtrij-route (zoals > 3 MB)
    reset_bundelvenster()
    tellers.herreken(keten.administratie_id)

    spot, floor = Casus(casussen.C_SPOT), Casus(casussen.B_FLOOR)
    keten.ai.registreer(spot.pdf(), spot.ai_antwoord())
    keten.ai.registreer(floor.pdf(), floor.ai_antwoord())
    triggers: list[str] = []
    sporen: list[dict] = []
    wachtrij = CloudRunJobExtractieWachtrij(
        job_resource=JOB, trigger=triggers.append, spoor=lambda **kw: sporen.append(kw)
    )

    ids = []
    for casus in (spot, floor):
        ids.append(
            service.upload_document(
                administratie_id=keten.administratie_id,
                bestandsnaam=casus.pdf_bestandsnaam(),
                inhoud=casus.pdf(),
                actor_id=keten.actor,
                opslag=keten.opslag,
                wachtrij=wachtrij,
            ).document_id
        )
    # Eén batch = één job-executie; de tweede upload is gebundeld (zichtbaar spoor, geen tweede call, geen fout).
    assert triggers == [JOB]
    assert [sp["uitkomst"] for sp in sporen] == [UITKOMST_GESLAAGD, UITKOMST_GEBUNDELD]
    assert all(keten.status(d) == DocumentStatus.EXTRACTIE_WACHTRIJ for d in ids)
    assert keten.ai.aanroepen == []

    # De job-drain (zoals de Cloud Run-job): beide documenten precies één keer, daarna niets meer.
    assert service.verwerk_extractie_wachtrij() == 2
    assert service.verwerk_extractie_wachtrij() == 0
    for d in ids:
        assert keten.status(d) == DocumentStatus.TE_CONTROLEREN
        overgangen = _overgangen(keten, d)
        assert overgangen.count(("extractie_wachtrij", "extractie_bezig")) == 1
        assert overgangen.count(("extractie_bezig", "te_controleren")) == 1
    assert len(keten.ai.aanroepen) == 2
    rapport = tellers.herreken_alle(administratie_ids=[keten.administratie_id], dry_run=True)
    assert rapport.afwijkingen == [], [(a.teller, a.cache, a.telling) for a in rapport.afwijkingen]

    # De BLOW-race (c9ba6d8d): een collega voert het Spot-document af terwijl een trage verwerker het nog als
    # te_controleren in het geheugen heeft — de late schrijver wordt geweigerd, het duplicaat blijft afgevoerd.
    spot_id = ids[0]
    with scoped_session(keten.administratie_id, actor_id=SYSTEEM_ACTOR_ID) as traag:
        stale = traag.get(Document, spot_id)
        assert stale is not None and stale.status == DocumentStatus.TE_CONTROLEREN
        with scoped_session(keten.administratie_id, actor_id=SYSTEEM_ACTOR_ID) as snel:
            vers = snel.get(Document, spot_id)
            assert vers is not None
            service._schrijf_overgang(
                snel,
                document=vers,
                naar=DocumentStatus.AFGEVOERD_DUPLICAAT,
                actor_id=SYSTEEM_ACTOR_ID,
                detail={"reden": "Duplicaat (testopstelling gouden set)"},
            )
        with pytest.raises(OngeldigeStatusovergang):
            service._schrijf_overgang(
                traag,
                document=stale,
                naar=DocumentStatus.KLAAR_OM_TE_BOEKEN,
                actor_id=SYSTEEM_ACTOR_ID,
                detail={"reden": "late afronding (testopstelling)"},
            )
        traag.rollback()
    assert keten.status(spot_id) == DocumentStatus.AFGEVOERD_DUPLICAAT
    with scoped_session(keten.administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        laatste = session.scalars(
            select(DocumentGebeurtenis)
            .where(DocumentGebeurtenis.document_id == spot_id)
            .order_by(DocumentGebeurtenis.tijdstip.desc())
        ).first()
    assert laatste is not None and laatste.naar_status == DocumentStatus.AFGEVOERD_DUPLICAAT
    rapport = tellers.herreken_alle(administratie_ids=[keten.administratie_id], dry_run=True)
    assert rapport.afwijkingen == [], [(a.teller, a.cache, a.telling) for a in rapport.afwijkingen]
