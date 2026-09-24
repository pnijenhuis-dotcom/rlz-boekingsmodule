# ruff: noqa: E501 — lange assert-/stub-regels bewust (patroon tests/keten)
"""Byte-identieke dubbelencheck VÓÓR de AI-stap (BUG Peter 24-09, guard D4; `app/intake/dubbel_voor_ai.py`): een PDF die
kantoorbreed al bestaat kost geen AI-geld meer — 0 AI-calls (mock-teller); origineel in een administratie → het exemplaar
wordt daar afgevoerd als duplicaat (kruisverwijzing), origineel in de bak → huls `samengevoegd`; tijdlijn beide kanten, audit;
hetzelfde bericht = bestaande rij zonder nieuwe registratie; een door een mens verwijderd origineel telt niet."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.config import settings
from app.extractie import splitsing as splitsing_extractie
from app.extractie.splitsing import FactuurSegment
from app.intake import verwerking
from app.main import app
from app.security.tokens import create_access_token
from tests.documenten.test_ai_extractie import _fake_extractie
from tests.intake.conftest import bouw_eml, bouw_pdf

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol='boekhouding')}"}


def _rij(admin_engine: Engine, document_id: uuid.UUID):
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT administratie_id, status, samengevoegd_in_id, intake_bericht_id FROM boekhouding.document WHERE id = :id"
            ),
            {"id": document_id},
        ).one()


def _redenen(admin_engine: Engine, document_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        return [
            r[0] or ""
            for r in conn.execute(
                text(
                    "SELECT detail->>'reden' FROM boekhouding.document_gebeurtenis WHERE document_id = :d ORDER BY tijdstip, id"
                ),
                {"d": document_id},
            )
        ]


def _audits(admin_engine: Engine, actie: str) -> list[dict]:
    with admin_engine.connect() as conn:
        return [
            dict(r._mapping)
            for r in conn.execute(
                text(
                    "SELECT nieuwe_waarde, administratie_id FROM platform.audit_event WHERE actie = :a ORDER BY tijdstip"
                ),
                {"a": actie},
            )
        ]


@pytest.fixture
def ai_aan(intake_ai_aan: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr("app.extractie.service.extraheer_inkoopfactuur", lambda pdf, **kw: _fake_extractie())


@pytest.fixture
def splitsing_teller(monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    aanroepen: list[bytes] = []

    def stub(inhoud, paginas, client=None, verbruik_referentie=None, mail_context=None):
        aanroepen.append(inhoud)
        return [FactuurSegment(1, paginas, "BLOW B.V.", "Bouwmaat", "F-1", 0.95, documentsoort="factuur")]

    monkeypatch.setattr(splitsing_extractie, "detecteer_facturen", stub)
    return aanroepen


class TestDubbelVoorAi:
    def test_byte_identiek_aan_document_in_administratie_kost_geen_ai_call(
        self,
        ai_aan: None,
        splitsing_teller: list[bytes],
        administratie_heet_blow: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        pdf = bouw_pdf(1)
        eerste = verwerking.verwerk_eml(
            bouw_eml(bijlagen=[("factuur.pdf", pdf, "application", "pdf")], message_id="<a@x>"),
            actor_id=gescoopte_gebruiker,
        )
        assert eerste.bijlagen[0].uitkomst == "toegewezen" and len(splitsing_teller) == 1
        origineel = eerste.bijlagen[0].document_id

        # Dezelfde bytes via een ánder bericht (forward / herstelrun / tweede afzender): geen AI, wél een spoor.
        tweede = verwerking.verwerk_eml(
            bouw_eml(
                afzender="collega@kempengroep.nl",
                bijlagen=[("Fwd factuur.pdf", pdf, "application", "pdf")],
                message_id="<b@x>",
            ),
            actor_id=gescoopte_gebruiker,
            kanaal="facturen_kempengroep",
        )
        assert len(splitsing_teller) == 1, "geen tweede AI-call"
        b = tweede.bijlagen[0]
        assert b.uitkomst == "dubbel" and b.document_id != origineel and "byte-identiek" in (b.detail or "")
        huls = _rij(admin_engine, b.document_id)
        # Origineel in een administratie → bestaande regel categorie (a): afgevoerd als duplicaat mét kruisverwijzing.
        assert huls.status == "afgevoerd_duplicaat" and huls.samengevoegd_in_id is None
        assert huls.administratie_id == administratie_heet_blow and huls.intake_bericht_id == tweede.bericht_id
        with admin_engine.connect() as conn:
            afw = conn.execute(
                text("SELECT duplicaat_van_document_id, automatisch FROM boekhouding.afwijzing WHERE document_id = :d"),
                {"d": b.document_id},
            ).one()
        assert afw.duplicaat_van_document_id == origineel and afw.automatisch is True
        assert any("dubbel vóór extractie herkend (bespaard)" in x for x in _redenen(admin_engine, origineel))
        assert any("dubbel vóór extractie herkend (bespaard)" in x for x in _redenen(admin_engine, b.document_id))
        audits = _audits(admin_engine, "ai_dubbel_voor_extractie")
        assert len(audits) == 1 and audits[0]["nieuwe_waarde"]["origineel_document_id"] == str(origineel)
        assert (
            audits[0]["nieuwe_waarde"]["zelfde_bericht"] is False
            and audits[0]["administratie_id"] == administratie_heet_blow
        )
        # Het exemplaar telt in geen werkvoorraad-lijst mee; het origineel toont 'm als samengevoegd exemplaar.
        lijst = client.get(
            f"/administraties/{administratie_heet_blow}/documenten", headers=_bearer(gescoopte_gebruiker)
        ).json()
        ids = {d["id"] for d in lijst["documenten"]}
        assert str(origineel) in ids and str(b.document_id) not in ids

    def test_zelfde_bericht_twee_identieke_bijlagen_een_ai_call_geen_tweede_rij(
        self,
        ai_aan: None,
        splitsing_teller: list[bytes],
        administratie_heet_blow: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        pdf = bouw_pdf(1)
        r = verwerking.verwerk_eml(
            bouw_eml(
                bijlagen=[("factuur.pdf", pdf, "application", "pdf"), ("factuur (1).pdf", pdf, "application", "pdf")]
            ),
            actor_id=gescoopte_gebruiker,
        )
        assert [b.uitkomst for b in r.bijlagen] == ["toegewezen", "dubbel"] and len(splitsing_teller) == 1
        assert r.bijlagen[1].document_id == r.bijlagen[0].document_id
        with admin_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM boekhouding.document")).scalar_one() == 1
        assert _audits(admin_engine, "ai_dubbel_voor_extractie")[0]["nieuwe_waarde"]["zelfde_bericht"] is True

    def test_byte_identiek_aan_verzamelbak_rij_wordt_huls_in_de_bak(
        self, ai_aan: None, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        aanroepen: list[bytes] = []

        def onbekend(inhoud, paginas, client=None, verbruik_referentie=None, mail_context=None):
            aanroepen.append(inhoud)
            return [FactuurSegment(1, paginas, "Onbekende Partij", None, None, 0.9, documentsoort="factuur")]

        monkeypatch.setattr(splitsing_extractie, "detecteer_facturen", onbekend)
        pdf = bouw_pdf(2)
        eerste = verwerking.verwerk_eml(
            bouw_eml(bijlagen=[("x.pdf", pdf, "application", "pdf")], message_id="<1@y>"), actor_id=gescoopte_gebruiker
        )
        assert eerste.bijlagen[0].uitkomst == "verzamelbak"
        tweede = verwerking.verwerk_eml(
            bouw_eml(bijlagen=[("x.pdf", pdf, "application", "pdf")], message_id="<2@y>"), actor_id=gescoopte_gebruiker
        )
        assert tweede.bijlagen[0].uitkomst == "dubbel" and len(aanroepen) == 1
        huls = _rij(admin_engine, tweede.bijlagen[0].document_id)
        assert (
            huls.status == "samengevoegd"
            and huls.samengevoegd_in_id == eerste.bijlagen[0].document_id
            and huls.administratie_id is None
        )
        # De bak toont alleen het origineel, mét het samengevoegde exemplaar als chip.
        bak = client.get("/verzamelbak", headers=_bearer(gescoopte_gebruiker)).json()["items"]
        assert [i["document_id"] for i in bak] == [str(eerste.bijlagen[0].document_id)]
        assert bak[0]["samengevoegd_document_id"] == str(tweede.bijlagen[0].document_id)

    def test_verwijderd_origineel_telt_niet_normale_pad(
        self,
        ai_aan: None,
        splitsing_teller: list[bytes],
        administratie_heet_blow: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        pdf = bouw_pdf(1)
        eerste = verwerking.verwerk_eml(
            bouw_eml(bijlagen=[("f.pdf", pdf, "application", "pdf")], message_id="<1@z>"), actor_id=gescoopte_gebruiker
        )
        doc = eerste.bijlagen[0].document_id
        resp = client.post(
            f"/administraties/{administratie_heet_blow}/documenten/{doc}/verwijderen",
            json={"reden": "per ongeluk geüpload"},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 200, resp.text
        tweede = verwerking.verwerk_eml(
            bouw_eml(bijlagen=[("f.pdf", pdf, "application", "pdf")], message_id="<2@z>"), actor_id=gescoopte_gebruiker
        )
        assert tweede.bijlagen[0].uitkomst == "toegewezen" and len(splitsing_teller) == 2
