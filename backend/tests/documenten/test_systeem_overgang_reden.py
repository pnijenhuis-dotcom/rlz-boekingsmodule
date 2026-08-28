"""Vangnet bugfix-run 28-08 (kernprincipe 4 "niets verdwijnt stil"): een statusovergang door de
systeem-actor (⚙) zónder leesbare reden mag niet meer bestaan. In dev/test hard (raise), in
productie luid (ERROR-log + placeholder-reden) maar nooit blokkerend."""

from __future__ import annotations

import logging
import uuid

import pytest
from sqlalchemy import text

from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import service
from app.documenten.models import Document, DocumentStatus
from tests.documenten.conftest import gescoopte_gebruiker, opslag  # noqa: F401


@pytest.fixture
def ontvangen_document(gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag) -> uuid.UUID:  # noqa: F811
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="vangnet.txt",  # geen PDF/UBL → synchrone (lege) extractie → te_controleren
        inhoud=b"tekst",
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    )
    return resultaat.document_id


def _laatste_detail(admin_engine, document_id: uuid.UUID) -> dict | None:
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT detail FROM boekhouding.document_gebeurtenis WHERE document_id = :id "
                "ORDER BY tijdstip DESC, id DESC LIMIT 1"
            ),
            {"id": document_id},
        ).scalar_one()


def test_systeem_overgang_zonder_reden_is_een_fout_in_dev_en_test(
    ontvangen_document: uuid.UUID, administratie_id: uuid.UUID
) -> None:
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        document = session.get(Document, ontvangen_document)
        assert document is not None and document.status == DocumentStatus.TE_CONTROLEREN
        with pytest.raises(service.SysteemOvergangZonderReden):
            service._schrijf_overgang(
                session, document=document, naar=DocumentStatus.EXTRACTIE_BEZIG, actor_id=SYSTEEM_ACTOR_ID
            )
        with pytest.raises(service.SysteemOvergangZonderReden):
            service._schrijf_overgang(
                session,
                document=document,
                naar=DocumentStatus.EXTRACTIE_BEZIG,
                actor_id=SYSTEEM_ACTOR_ID,
                detail={"reden": "   "},
            )
        with pytest.raises(service.SysteemOvergangZonderReden):
            service._schrijf_overgang(
                session,
                document=document,
                naar=DocumentStatus.EXTRACTIE_BEZIG,
                actor_id=SYSTEEM_ACTOR_ID,
                detail={"iets_anders": True},
            )


def test_systeem_overgang_met_reden_en_mens_zonder_detail_mogen(
    ontvangen_document: uuid.UUID,
    administratie_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,  # noqa: F811
    admin_engine,
) -> None:
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        document = session.get(Document, ontvangen_document)
        service._schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.EXTRACTIE_BEZIG,
            actor_id=SYSTEEM_ACTOR_ID,
            detail={"reden": "extractie gestart"},
        )
    assert _laatste_detail(admin_engine, ontvangen_document) == {"reden": "extractie gestart"}
    with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
        document = session.get(Document, ontvangen_document)
        # Menselijke handeling: de actor ís de reden — geen detail vereist.
        service._schrijf_overgang(
            session, document=document, naar=DocumentStatus.TE_CONTROLEREN, actor_id=gescoopte_gebruiker
        )
    assert _laatste_detail(admin_engine, ontvangen_document) is None


def test_in_productie_nooit_blokkerend_maar_luid(
    ontvangen_document: uuid.UUID, administratie_id: uuid.UUID, admin_engine, monkeypatch, caplog
) -> None:
    monkeypatch.setattr(service.settings, "environment", "production")
    with (
        caplog.at_level(logging.ERROR, logger="app.documenten.service"),
        scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session,
    ):
        document = session.get(Document, ontvangen_document)
        service._schrijf_overgang(
            session, document=document, naar=DocumentStatus.EXTRACTIE_BEZIG, actor_id=SYSTEEM_ACTOR_ID
        )
    detail = _laatste_detail(admin_engine, ontvangen_document)
    assert detail == {"reden": service.SYSTEEM_REDEN_ONTBREEKT}
    assert any("zonder reden" in r.message for r in caplog.records)
