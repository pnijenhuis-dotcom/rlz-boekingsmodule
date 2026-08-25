from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine

from app.materiaal import service as materiaal
from tests.auth.conftest import beheerder_id  # noqa: F401
from tests.uren.conftest import (  # noqa: F401
    administratie_id,
    administratie_zonder_opt_in,
    detacheerder,
    gekoppelde_uitvoerder,
    gekoppelde_zzper,
    maak_gebruiker,
    maak_project,
    project_id,
    tweede_project_id,
    uitvoerder,
    zzper,
)


@pytest.fixture
def leverancier_id(administratie_id: uuid.UUID, beheerder_id: uuid.UUID) -> uuid.UUID:  # noqa: F811
    """Universal Nederland B.V. mét de standaardcatalogus uit de bestellijst (seed)."""
    return materiaal.seed_universal(administratie_id=administratie_id, actor_id=beheerder_id).leverancier_id


def product_id_op_naam(administratie_id: uuid.UUID, leverancier_id: uuid.UUID, beheerder_id: uuid.UUID, naam: str) -> uuid.UUID:
    for cat in materiaal.catalogus(administratie_id=administratie_id, leverancier_id=leverancier_id, actor_id=beheerder_id):
        for p in cat.producten:
            if p.naam == naam:
                return p.id
    raise KeyError(naam)


@pytest.fixture
def mail_log(monkeypatch):
    """Mailkanaal gemockt: verzonden berichten (naar, onderwerp, tekst, bijlagen) vastleggen."""
    from app.berichten import mail

    verzonden: list[dict] = []

    def _nep(*, naar, onderwerp, tekst, bijlagen=None):
        verzonden.append({"naar": naar, "onderwerp": onderwerp, "tekst": tekst, "bijlagen": bijlagen or []})

    monkeypatch.setattr(mail, "verzend_mail", _nep)
    return verzonden


@pytest.fixture(autouse=True)
def _lokale_opslag(tmp_path, monkeypatch):
    from app.documenten import storage

    opslag = storage.LokaleBestandsopslag(tmp_path / "materiaal")
    monkeypatch.setattr(storage, "standaard_opslag", lambda: opslag)
    return opslag


_ = Engine
