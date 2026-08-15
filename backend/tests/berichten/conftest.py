from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.accordering import service as accordering_service
from tests.accordering.conftest import (  # noqa: F401
    accordeur_1,
    accordeur_2,
    actieve_gebruiker,
    administratie_id,
    beheerder_id,
    gescoopte_gebruiker,
    klaar_document,
    maak_accordeur,
    opslag,
    zet_schema,
)
from tests.documenten.conftest import _opslag_naar_tmp  # noqa: F401


def maak_apparaat(admin_engine: Engine, gebruiker_id: uuid.UUID, naam: str = "iPhone test") -> uuid.UUID:
    """Geregistreerd passkey-apparaat (webauthn_credential) — de binding voor push-subscripties."""
    apparaat_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.webauthn_credential "
                "(id, gebruiker_id, credential_id, public_key, sign_count, apparaat_naam, is_dev_stub) "
                "VALUES (:id, :gid, :cred, :pub, 0, :naam, true)"
            ),
            {"id": apparaat_id, "gid": gebruiker_id, "cred": apparaat_id.bytes, "pub": b"pub", "naam": naam},
        )
    return apparaat_id


@pytest.fixture
def ter_accordering_bij_1(
    administratie_id: uuid.UUID,  # noqa: F811
    beheerder_id: uuid.UUID,  # noqa: F811
    accordeur_1: uuid.UUID,  # noqa: F811
    klaar_document: uuid.UUID,  # noqa: F811
) -> uuid.UUID:
    """Eén document ter accordering, aan de beurt bij accordeur_1."""
    zet_schema(
        administratie_id=administratie_id,
        beheerder_id=beheerder_id,
        lagen=[
            accordering_service.LaagInput(volgnummer=1, accordeur_gebruiker_id=accordeur_1, bedrag_drempel=None)
        ],
    )
    accordering_service.bied_ter_accordering_aan(
        administratie_id=administratie_id,
        document_id=klaar_document,
        actor_id=beheerder_id,
        actor_rol="beheerder",
    )
    return klaar_document
