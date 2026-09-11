# ruff: noqa: F811 — pytest-fixtures als parameters
"""Casus t (blok 8 run 11-09 middag): groepskenmerk als FILTER op de klantenlijst — met een écht casusdocument.

Spot Services 2026-608 staat ná upload + extractie op te_controleren in de Universal-administratie; een tweede
administratie ("Andere BV") heeft niets. De Beheerder maakt groep "Kempen groep" en kent Universal toe. Verwacht:
`GET /werkvoorraad/overzicht?groep_id=` toont alleen Universal mét dezelfde teller (te_controleren = 1) als de
ongefilterde lijst — het filter beperkt de administratie-set, nooit de telling (Kernprincipe 7: administratie is een
filter, dit is er één meer). Een onbekende groep = lege lijst, geen fout; zonder groepen verandert er niets."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.security.tokens import create_access_token
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import Keten


@pytest.fixture
def spot(keten: Keten) -> uuid.UUID:
    casus = Casus(casussen.C_SPOT)
    keten.ai.registreer(casus.pdf(), casus.ai_antwoord())
    return keten.upload(casus.pdf_bestandsnaam(), casus.pdf()).document_id


@pytest.fixture
def andere_administratie(admin_engine: Engine) -> uuid.UUID:
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Andere BV', :rlz)"),
            {"id": aid, "rlz": f"rlz-{aid}"},
        )
    return aid


def _klanten(keten: Keten, headers: dict[str, str], **params) -> dict[str, dict]:
    resp = keten.api.get("/werkvoorraad/overzicht", params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    return {k["administratie_id"]: k for k in resp.json()["klanten"]}


class TestGroepFilterKlantenlijst:
    def test_filter_beperkt_de_administratie_set_niet_de_tellers(
        self, keten: Keten, spot: uuid.UUID, andere_administratie: uuid.UUID, beheerder_id: uuid.UUID
    ) -> None:
        bh = {"Authorization": f"Bearer {create_access_token(beheerder_id, rol='beheerder')}"}
        universal = str(keten.administratie_id)

        zonder = _klanten(keten, bh)
        assert set(zonder) == {universal, str(andere_administratie)}
        assert zonder[universal]["te_controleren"] == 1  # Spot ná extractie

        g = keten.api.post("/groepen", json={"naam": "Kempen groep"}, headers=bh)
        assert g.status_code == 201, g.text
        groep_id = g.json()["id"]
        r = keten.api.put(f"/administraties/{universal}/groep", json={"groep_id": groep_id}, headers=bh)
        assert r.status_code == 200, r.text

        met = _klanten(keten, bh, groep_id=groep_id)
        assert list(met) == [universal]
        assert met[universal] == zonder[universal]  # identieke rij: filter raakt de tellers niet

        # De boekhouder mét scope ziet het filter net zo (kantoorrol volstaat), de groepsnaam in zijn administratie-DTO.
        met_bk = _klanten(keten, keten.headers, groep_id=groep_id)
        assert list(met_bk) == [universal]
        mijn = keten.api.get("/auth/administraties", headers=keten.headers).json()["administraties"]
        assert next(a for a in mijn if a["id"] == universal)["groep_naam"] == "Kempen groep"

        assert _klanten(keten, bh, groep_id=str(uuid.uuid4())) == {}
