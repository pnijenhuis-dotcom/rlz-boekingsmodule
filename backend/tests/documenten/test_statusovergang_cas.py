"""Compare-and-set op de statusovergang (systeemfout BLOW 18-09, opdracht ic_spiegel_rood/tellers 19-09).

Productie-tijdlijn document c9ba6d8d (BLOW): drie job-executies verwerkten hetzelfde document tegelijk; om 11:05:20
zette de duplicaten-motor het op `afgevoerd_duplicaat` (tellers-cache te_controleren −1), waarna een nog open,
tragere afrondingstransactie haar in het geheugen gehouden `extractie_bezig → te_controleren` bij de commit alsnog
wegschreef: het afgevoerde duplicaat stond stil weer in de werkvoorraad zónder tijdlijnregel en de cache liep 1 achter
(LET-OP "BLOw B.V: te_controleren cache=151 telling=152"). `_schrijf_overgang` toetst sindsdien de databasestatus mét
een CAS-UPDATE (`status = van`, rijlock): de late schrijver krijgt `StatusIntussenGewijzigd` en schrijft niets."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, select, text

from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import service
from app.documenten.models import Document, DocumentGebeurtenis, DocumentStatus
from app.documenten.statusmachine import OngeldigeStatusovergang
from app.documenten.storage import LokaleBestandsopslag
from app.werkvoorraad import tellers


def _upload(administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag) -> uuid.UUID:
    return service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="cas.pdf",
        inhoud=b"%PDF-1.4 cas-test",
        actor_id=actor_id,
        opslag=opslag,
    ).document_id


def _cache(admin_engine: Engine, administratie_id: uuid.UUID, teller: str) -> int:
    with admin_engine.begin() as conn:
        return conn.execute(
            text(
                "SELECT waarde FROM boekhouding.werkvoorraad_teller_cache WHERE administratie_id = :a AND teller = :t"
            ),
            {"a": administratie_id, "t": teller},
        ).scalar_one()


def test_late_schrijver_met_verouderde_status_wordt_geweigerd_en_de_cache_blijft_kloppen(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, admin_engine: Engine
) -> None:
    doc_id = _upload(administratie_id, gescoopte_gebruiker, opslag)  # klein → synchroon te_controleren
    tellers.herreken(administratie_id)
    voor = _cache(admin_engine, administratie_id, tellers.TE_CONTROLEREN)
    assert voor >= 1

    # Sessie 2 = de trage verwerker: leest het document als te_controleren en houdt dat in het geheugen.
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as traag:
        stale = traag.get(Document, doc_id)
        assert stale is not None and stale.status == DocumentStatus.TE_CONTROLEREN

        # Sessie 1 = de collega: voert het document intussen af (commit bij het verlaten van de context).
        with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as snel:
            vers = snel.get(Document, doc_id)
            assert vers is not None
            service._schrijf_overgang(
                snel,
                document=vers,
                naar=DocumentStatus.AFGEVOERD_DUPLICAAT,
                actor_id=SYSTEEM_ACTOR_ID,
                detail={"reden": "Duplicaat van 20230872 (testopstelling)"},
            )

        # De trage verwerker schrijft ná de commit van de collega met een verouderde `van`: geweigerd.
        with pytest.raises(OngeldigeStatusovergang) as exc:
            service._schrijf_overgang(
                traag,
                document=stale,
                naar=DocumentStatus.KLAAR_OM_TE_BOEKEN,
                actor_id=SYSTEEM_ACTOR_ID,
                detail={"reden": "late afronding (testopstelling)"},
            )
        assert isinstance(exc.value, service.StatusIntussenGewijzigd)
        assert "intussen niet meer 'te_controleren'" in str(exc.value)
        traag.rollback()

    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        document = session.get(Document, doc_id)
        assert document is not None and document.status == DocumentStatus.AFGEVOERD_DUPLICAAT
        overgangen = session.scalars(
            select(DocumentGebeurtenis)
            .where(DocumentGebeurtenis.document_id == doc_id)
            .order_by(DocumentGebeurtenis.tijdstip)
        ).all()
    assert [g.naar_status for g in overgangen][-1] == DocumentStatus.AFGEVOERD_DUPLICAAT
    assert not any(g.naar_status == DocumentStatus.KLAAR_OM_TE_BOEKEN for g in overgangen)
    # Tellers-cache: precies één −1 (het afvoeren), niets van de geweigerde overgang.
    assert _cache(admin_engine, administratie_id, tellers.TE_CONTROLEREN) == voor - 1
    assert tellers.herreken(administratie_id, dry_run=True).afwijkingen == []


def test_gewone_overgang_op_een_verse_status_werkt_ongewijzigd(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
) -> None:
    doc_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        document = session.get(Document, doc_id)
        assert document is not None
        service._schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.KLAAR_OM_TE_BOEKEN,
            actor_id=SYSTEEM_ACTOR_ID,
            detail={"reden": "testopstelling: eerste overgang"},
        )
        # Twee overgangen in één sessie: de tweede ziet de eerste als `van` (CAS volgt de eigen UPDATE).
        service._schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.TE_CONTROLEREN,
            actor_id=SYSTEEM_ACTOR_ID,
            detail={"reden": "testopstelling: tweede overgang"},
        )
    detail = service.haal_document_op(administratie_id=administratie_id, document_id=doc_id)
    assert detail.document.status == DocumentStatus.TE_CONTROLEREN
