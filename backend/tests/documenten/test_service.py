from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.auth import service as auth_service
from app.db.session import scoped_session, session_factory_for
from app.documenten import service
from app.documenten.models import Document, DocumentStatus
from app.documenten.service import _schrijf_overgang
from app.documenten.statusmachine import OngeldigeStatusovergang
from app.documenten.storage import LokaleBestandsopslag
from tests.documenten.test_ubl import _VOORBEELD_UBL


def _gebeurtenissen(admin_engine: Engine, document_id: uuid.UUID) -> list[tuple[str | None, str]]:
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text(
                "SELECT van_status, naar_status FROM boekhouding.document_gebeurtenis "
                "WHERE document_id = :id ORDER BY tijdstip"
            ),
            {"id": document_id},
        ).all()
    return [(van, naar) for van, naar in rijen]


def _audit_acties(admin_engine: Engine, document_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT actie FROM platform.audit_event WHERE tabel = 'document' AND record_id = :id "
                    "ORDER BY tijdstip"
                ),
                {"id": document_id},
            )
            .scalars()
            .all()
        )


def test_upload_pdf_doorloopt_extractie_stub_naar_te_controleren(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, admin_engine: Engine
) -> None:
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="factuur.pdf",
        inhoud=b"%PDF-1.4 fake",
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    )

    assert resultaat.status == DocumentStatus.TE_CONTROLEREN
    assert resultaat.mogelijk_duplicaat_van_id is None
    assert _gebeurtenissen(admin_engine, resultaat.document_id) == [
        (None, "ontvangen"),
        ("ontvangen", "extractie_bezig"),
        ("extractie_bezig", "te_controleren"),
    ]
    assert _audit_acties(admin_engine, resultaat.document_id) == [
        "document_ontvangen",
        "status_extractie_bezig",
        "status_te_controleren",
    ]
    assert opslag.bestaat(pad=f"{administratie_id}/{resultaat.document_id}.pdf")


def test_upload_ubl_xml_voegt_veldvoorstel_toe(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, admin_engine: Engine
) -> None:
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="factuur.xml",
        inhoud=_VOORBEELD_UBL,
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    )
    assert resultaat.status == DocumentStatus.TE_CONTROLEREN

    with admin_engine.connect() as conn:
        detail = conn.execute(
            text(
                "SELECT detail FROM boekhouding.document_gebeurtenis "
                "WHERE document_id = :id AND naar_status = 'te_controleren'"
            ),
            {"id": resultaat.document_id},
        ).scalar_one()
    assert detail["veldvoorstel"]["factuurnummer"] == "2026-0642"
    assert detail["veldvoorstel"]["regelaantal"] == 2


def test_niet_ubl_xml_zet_parse_fout_in_detail(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, admin_engine: Engine
) -> None:
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="geen-factuur.xml",
        inhoud=b"<root>niet een UBL-factuur</root>",
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    )
    assert resultaat.status == DocumentStatus.TE_CONTROLEREN  # de stub blokkeert niet op een parse-fout

    with admin_engine.connect() as conn:
        detail = conn.execute(
            text(
                "SELECT detail FROM boekhouding.document_gebeurtenis "
                "WHERE document_id = :id AND naar_status = 'te_controleren'"
            ),
            {"id": resultaat.document_id},
        ).scalar_one()
    assert "ubl_parse_fout" in detail


def test_duplicaat_detectie_binnen_dezelfde_administratie(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
) -> None:
    eerste = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="factuur.pdf",
        inhoud=b"identieke inhoud",
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    )
    tweede = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="factuur-kopie.pdf",
        inhoud=b"identieke inhoud",
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    )
    assert eerste.mogelijk_duplicaat_van_id is None
    assert tweede.mogelijk_duplicaat_van_id == eerste.document_id


def test_duplicaat_detectie_is_per_administratie(
    gescoopte_gebruiker: uuid.UUID,
    administratie_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    admin_engine: Engine,
    beheerder_id: uuid.UUID,
) -> None:
    andere_administratie_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Andere klant', :rlz)"),
            {"id": andere_administratie_id, "rlz": f"rlz-{andere_administratie_id}"},
        )
    # Via de servicelaag (niet rechtstreeks SQL): de audit-trigger op gebruiker_administratie
    # vereist een gezette app.current_actor_id (migratie 0002), die voeg_scope_toe() zelf regelt.
    auth_service.voeg_scope_toe(
        actor_id=beheerder_id, doel_gebruiker_id=gescoopte_gebruiker, administratie_id=andere_administratie_id
    )

    eerste = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="factuur.pdf",
        inhoud=b"zelfde bytes, andere klant",
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    )
    tweede = service.upload_document(
        administratie_id=andere_administratie_id,
        bestandsnaam="factuur.pdf",
        inhoud=b"zelfde bytes, andere klant",
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    )
    assert eerste.mogelijk_duplicaat_van_id is None
    assert tweede.mogelijk_duplicaat_van_id is None


def test_rls_document_is_niet_zichtbaar_voor_andere_administratie(
    gescoopte_gebruiker: uuid.UUID,
    administratie_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    admin_engine: Engine,
    app_engine: Engine,
) -> None:
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="factuur.pdf",
        inhoud=b"scoped content",
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    )

    andere_administratie_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Andere klant', :rlz)"),
            {"id": andere_administratie_id, "rlz": f"rlz-{andere_administratie_id}"},
        )

    factory = session_factory_for(app_engine)
    with scoped_session(andere_administratie_id, actor_id=gescoopte_gebruiker, session_factory=factory) as session:
        aantal = session.execute(
            text("SELECT count(*) FROM boekhouding.document WHERE id = :id"), {"id": resultaat.document_id}
        ).scalar_one()
    assert aantal == 0

    with scoped_session(administratie_id, actor_id=gescoopte_gebruiker, session_factory=factory) as session:
        aantal = session.execute(
            text("SELECT count(*) FROM boekhouding.document WHERE id = :id"), {"id": resultaat.document_id}
        ).scalar_one()
    assert aantal == 1


def test_ongeldige_overgang_via_service_faalt(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
) -> None:
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="factuur.pdf",
        inhoud=b"weer andere inhoud",
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    )
    with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
        document = session.get(Document, resultaat.document_id)
        assert document is not None
        with pytest.raises(OngeldigeStatusovergang):
            _schrijf_overgang(session, document=document, naar=DocumentStatus.GEBOEKT, actor_id=gescoopte_gebruiker)
