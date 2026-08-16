"""Handmatige herinnering per document (beheer-mini 2026-08-16, migratie 0053).

Poortlogica: alleen bij een open ronde, alleen kantoor, dagrem (max 1/dag, mislukt mag
opnieuw), kanaal push-anders-mail met deep-link naar het document, audit + tijdlijn,
"laatst herinnerd" leesbaar per administratie.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.accordering import herinnering
from app.berichten import mail

# Fixtures (accordeur_1, ter_accordering_bij_1, administratie_id, beheerder_id, …) komen uit
# tests/berichten/conftest.py, dat ze uit tests/accordering/conftest.py herexporteert.


@pytest.fixture
def mail_log(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    verzonden: list[dict] = []

    def _fake(**kwargs) -> None:
        verzonden.append(kwargs)

    monkeypatch.setattr(mail, "verzend_mail", _fake)
    return verzonden


def test_herinnering_via_mail_met_deeplink(
    administratie_id: uuid.UUID,
    beheerder_id: uuid.UUID,
    ter_accordering_bij_1: uuid.UUID,
    mail_log: list[dict],
    admin_engine: Engine,
) -> None:
    resultaat = herinnering.stuur_handmatige_herinnering(
        administratie_id=administratie_id,
        document_id=ter_accordering_bij_1,
        actor_id=beheerder_id,
        actor_rol="beheerder",
    )

    assert resultaat.kanaal == "e-mail"
    assert len(mail_log) == 1
    assert f"/accordeur?document={ter_accordering_bij_1}" in mail_log[0]["tekst"]

    with admin_engine.connect() as conn:
        rij = conn.execute(
            text(
                "SELECT status, kanaal, verzonden_op, verzonden_door FROM boekhouding.document_herinnering "
                "WHERE document_id = :d"
            ),
            {"d": ter_accordering_bij_1},
        ).one()
    assert rij.status == "verzonden" and rij.kanaal == "e-mail"
    assert rij.verzonden_op is not None and rij.verzonden_door == beheerder_id

    with admin_engine.connect() as conn:
        audit = conn.execute(
            text("SELECT count(*) FROM platform.audit_event WHERE actie = 'accordering_herinnering_verstuurd'")
        ).scalar_one()
        tijdlijn = conn.execute(
            text(
                "SELECT count(*) FROM boekhouding.document_gebeurtenis "
                "WHERE document_id = :d AND detail ? 'accordering_herinnering'"
            ),
            {"d": ter_accordering_bij_1},
        ).scalar_one()
    assert audit == 1 and tijdlijn == 1


def test_dagrem_max_een_per_document_per_dag(
    administratie_id: uuid.UUID,
    beheerder_id: uuid.UUID,
    ter_accordering_bij_1: uuid.UUID,
    mail_log: list[dict],
) -> None:
    herinnering.stuur_handmatige_herinnering(
        administratie_id=administratie_id,
        document_id=ter_accordering_bij_1,
        actor_id=beheerder_id,
        actor_rol="beheerder",
    )
    with pytest.raises(herinnering.AlHerinnerdVandaag):
        herinnering.stuur_handmatige_herinnering(
            administratie_id=administratie_id,
            document_id=ter_accordering_bij_1,
            actor_id=beheerder_id,
            actor_rol="beheerder",
        )
    assert len(mail_log) == 1


def test_mislukte_verzending_is_zichtbaar_en_mag_opnieuw(
    administratie_id: uuid.UUID,
    beheerder_id: uuid.UUID,
    ter_accordering_bij_1: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _faal(**kwargs) -> None:
        raise mail.MailVerzendFout("smtp down")

    monkeypatch.setattr(mail, "verzend_mail", _faal)
    with pytest.raises(herinnering.HerinneringVerzendingMislukt):
        herinnering.stuur_handmatige_herinnering(
            administratie_id=administratie_id,
            document_id=ter_accordering_bij_1,
            actor_id=beheerder_id,
            actor_rol="beheerder",
        )

    # Aantoonbaar niets bezorgd — dezelfde dag opnieuw mag (re-claim van de mislukt-rij).
    verzonden: list[dict] = []
    monkeypatch.setattr(mail, "verzend_mail", lambda **kw: verzonden.append(kw))
    resultaat = herinnering.stuur_handmatige_herinnering(
        administratie_id=administratie_id,
        document_id=ter_accordering_bij_1,
        actor_id=beheerder_id,
        actor_rol="beheerder",
    )
    assert resultaat.kanaal == "e-mail" and len(verzonden) == 1


def test_geen_open_ronde_weigert(
    administratie_id: uuid.UUID, beheerder_id: uuid.UUID, mail_log: list[dict]
) -> None:
    with pytest.raises(herinnering.GeenOpenAccordering):
        herinnering.stuur_handmatige_herinnering(
            administratie_id=administratie_id,
            document_id=uuid.uuid4(),
            actor_id=beheerder_id,
            actor_rol="beheerder",
        )
    assert mail_log == []


def test_accordeur_zelf_mag_niet_herinneren(
    administratie_id: uuid.UUID,
    accordeur_1: uuid.UUID,
    ter_accordering_bij_1: uuid.UUID,
    mail_log: list[dict],
) -> None:
    from app.accordering.service import KantoorActieVereist

    with pytest.raises(KantoorActieVereist):
        herinnering.stuur_handmatige_herinnering(
            administratie_id=administratie_id,
            document_id=ter_accordering_bij_1,
            actor_id=accordeur_1,
            actor_rol="klant_accordeur",
        )
    assert mail_log == []


def test_geblokkeerde_accordeur_weigert(
    administratie_id: uuid.UUID,
    beheerder_id: uuid.UUID,
    accordeur_1: uuid.UUID,
    ter_accordering_bij_1: uuid.UUID,
    mail_log: list[dict],
    admin_engine: Engine,
) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.gebruiker SET status = 'geblokkeerd' WHERE id = :id"), {"id": accordeur_1}
        )
    with pytest.raises(herinnering.GeenActieveAccordeur):
        herinnering.stuur_handmatige_herinnering(
            administratie_id=administratie_id,
            document_id=ter_accordering_bij_1,
            actor_id=beheerder_id,
            actor_rol="beheerder",
        )
    assert mail_log == []


def test_laatst_herinnerd_per_document(
    administratie_id: uuid.UUID,
    beheerder_id: uuid.UUID,
    ter_accordering_bij_1: uuid.UUID,
    mail_log: list[dict],
) -> None:
    assert herinnering.laatst_herinnerd_per_document(administratie_id=administratie_id) == {}
    resultaat = herinnering.stuur_handmatige_herinnering(
        administratie_id=administratie_id,
        document_id=ter_accordering_bij_1,
        actor_id=beheerder_id,
        actor_rol="beheerder",
    )
    kaart = herinnering.laatst_herinnerd_per_document(administratie_id=administratie_id)
    assert kaart == {ter_accordering_bij_1: resultaat.verzonden_op}
