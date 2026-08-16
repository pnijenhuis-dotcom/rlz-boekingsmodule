"""Nieuwe-facturen-bundelmelding (besluit Peter 2026-08-16, migratie 0054).

Poortlogica: één gebundeld bericht per accordeur bij ≥1 nieuw document, nooit dubbel voor
hetzelfde document, stille uren 20:00–08:00 Europe/Amsterdam, mislukt mag opnieuw,
volumerem, N in het bericht = totaal aantal openstaand.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine, text

from app.accordering import service as accordering_service
from app.berichten import mail, nieuwe_facturen
from app.config import settings
from app.documenten import boekvoorstel
from app.documenten import service as documenten_service
from app.documenten.storage import LokaleBestandsopslag

from .conftest import maak_apparaat  # noqa: F401 — herbruik indien push-scenario's volgen

AMS = ZoneInfo("Europe/Amsterdam")
DAG = datetime(2026, 8, 17, 12, 0, tzinfo=AMS)  # ruim binnen de meldingsuren


@pytest.fixture
def mail_log(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    verzonden: list[dict] = []
    monkeypatch.setattr(mail, "verzend_mail", lambda **kw: verzonden.append(kw))
    return verzonden


def _maak_ter_accordering_document(
    *,
    administratie_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
    beheerder_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    vendor_id: uuid.UUID,
    naam: str,
) -> uuid.UUID:
    """Tweede/derde boekklaar document ter accordering — zelfde route als de klaar_document-
    fixture (tests/accordering/conftest.py)."""
    from app.db.session import scoped_session
    from app.documenten.models import Document, DocumentStatus
    from app.documenten.service import _schrijf_overgang

    resultaat = documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=naam,
        inhoud=b"%PDF-1.4 testfactuur-extra",
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    )
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=gescoopte_gebruiker,
        vendor_id=vendor_id,
        referentie=f"F-{resultaat.document_id}",
        factuurdatum=date(2026, 7, 2),
        totaalbedrag=Decimal("60.50"),
        regels=[
            boekvoorstel.BoekvoorstelRegelData(
                ledger_id=uuid.uuid4(),
                taxrate_id=uuid.uuid4(),
                project_id=None,
                netto_bedrag=Decimal("50.00"),
                btw_bedrag=Decimal("10.50"),
                omschrijving="Extra testregel",
            )
        ],
    )
    with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
        document = session.get(Document, resultaat.document_id)
        _schrijf_overgang(
            session, document=document, naar=DocumentStatus.KLAAR_OM_TE_BOEKEN, actor_id=gescoopte_gebruiker
        )
    accordering_service.bied_ter_accordering_aan(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=beheerder_id,
        actor_rol="beheerder",
    )
    return resultaat.document_id


def test_stille_uren_versturen_niets(mail_log: list[dict]) -> None:
    avond = datetime(2026, 8, 17, 21, 30, tzinfo=AMS)
    rapport = nieuwe_facturen.verstuur_nieuwe_facturen_meldingen(nu=avond)
    assert rapport.stille_uren is True and not rapport.is_fout
    assert mail_log == []


def test_stille_uren_grenzen() -> None:
    assert nieuwe_facturen.in_stille_uren(datetime(2026, 8, 17, 20, 0, tzinfo=AMS)) is True
    assert nieuwe_facturen.in_stille_uren(datetime(2026, 8, 17, 7, 59, tzinfo=AMS)) is True
    assert nieuwe_facturen.in_stille_uren(datetime(2026, 8, 17, 8, 0, tzinfo=AMS)) is False
    assert nieuwe_facturen.in_stille_uren(datetime(2026, 8, 17, 19, 59, tzinfo=AMS)) is False
    # UTC-invoer wordt naar lokale tijd vertaald (21:00 UTC = 23:00 zomertijd).
    assert nieuwe_facturen.in_stille_uren(datetime(2026, 8, 17, 21, 0, tzinfo=UTC)) is True


def test_nieuw_document_geeft_een_gebundeld_bericht(
    administratie_id: uuid.UUID,
    ter_accordering_bij_1: uuid.UUID,
    mail_log: list[dict],
    admin_engine: Engine,
) -> None:
    rapport = nieuwe_facturen.verstuur_nieuwe_facturen_meldingen(nu=DAG)

    assert rapport.verzonden_mail == 1 and rapport.gemelde_documenten == 1 and not rapport.is_fout
    assert len(mail_log) == 1
    assert "Er staat 1 factuur voor u klaar." in mail_log[0]["tekst"]
    assert "/accordeur" in mail_log[0]["tekst"]

    with admin_engine.connect() as conn:
        rij = conn.execute(
            text("SELECT status, kanaal, verzonden_op FROM platform.accordeur_nieuw_gemeld WHERE document_id = :d"),
            {"d": ter_accordering_bij_1},
        ).one()
    assert rij.status == "verzonden" and rij.kanaal == "e-mail" and rij.verzonden_op is not None


def test_idempotent_geen_dubbel_bericht(
    administratie_id: uuid.UUID, ter_accordering_bij_1: uuid.UUID, mail_log: list[dict]
) -> None:
    nieuwe_facturen.verstuur_nieuwe_facturen_meldingen(nu=DAG)
    rapport = nieuwe_facturen.verstuur_nieuwe_facturen_meldingen(nu=DAG)
    assert rapport.verzonden_mail == 0 and rapport.accordeurs_zonder_nieuw == 1
    assert len(mail_log) == 1


def test_tweede_document_meldt_totaal(
    administratie_id: uuid.UUID,
    beheerder_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
    opslag: LokaleBestandsopslag,
    ter_accordering_bij_1: uuid.UUID,
    mail_log: list[dict],
) -> None:
    from tests.accordering.conftest import VENDOR_ID

    nieuwe_facturen.verstuur_nieuwe_facturen_meldingen(nu=DAG)
    _maak_ter_accordering_document(
        administratie_id=administratie_id,
        gescoopte_gebruiker=gescoopte_gebruiker,
        beheerder_id=beheerder_id,
        opslag=opslag,
        vendor_id=VENDOR_ID,
        naam="factuur-2.pdf",
    )
    rapport = nieuwe_facturen.verstuur_nieuwe_facturen_meldingen(nu=DAG)

    # Trigger = 1 nieuw document; N in het bericht = totaal dat nu klaarstaat (2).
    assert rapport.gemelde_documenten == 1 and rapport.verzonden_mail == 1
    assert "Er staan 2 facturen voor u klaar." in mail_log[-1]["tekst"]


def test_mislukte_verzending_probeert_volgende_run_opnieuw(
    administratie_id: uuid.UUID,
    ter_accordering_bij_1: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _faal(**kwargs) -> None:
        raise mail.MailVerzendFout("smtp down")

    monkeypatch.setattr(mail, "verzend_mail", _faal)
    rapport = nieuwe_facturen.verstuur_nieuwe_facturen_meldingen(nu=DAG)
    assert rapport.mislukt == 1 and rapport.is_fout

    verzonden: list[dict] = []
    monkeypatch.setattr(mail, "verzend_mail", lambda **kw: verzonden.append(kw))
    herhaal = nieuwe_facturen.verstuur_nieuwe_facturen_meldingen(nu=DAG)
    assert herhaal.verzonden_mail == 1 and herhaal.gemelde_documenten == 1
    assert len(verzonden) == 1


def test_volumerem_stopt_zichtbaar(
    administratie_id: uuid.UUID,
    ter_accordering_bij_1: uuid.UUID,
    mail_log: list[dict],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "nieuwe_facturen_max_berichten_per_run", 0)
    rapport = nieuwe_facturen.verstuur_nieuwe_facturen_meldingen(nu=DAG)
    assert rapport.volumerem_bereikt and rapport.is_fout
    assert mail_log == []
