"""Gouden set — bulk-acties documentenlijst (Peter 16-09, "nu moet dat 1 voor 1"; casus ProfX Journaal-kassarapporten
die als inkoopfactuur in de werkvoorraad staan). Op twee echte UBL-documenten (casus h, BDO) via de kantoor-API: bulk
"Type wijzigen → kassarapport" zet de soort, draait de extractie opnieuw via het kassarapport-pad (nooit een AI-call op
een UBL) en houdt de rijen zichtbaar in de lijst; bulk "Verwijderen…" mét één reden zet ze op verwijderd (herstelbaar,
achter de afgehandeld-toggle) en slaat een geboekt document over mét reden. Geen RLZ-/Odoo-call."""

from __future__ import annotations

import uuid

import pytest

from app.db.session import scoped_session
from app.documenten.models import Document, DocumentStatus
from app.documenten.service import _schrijf_overgang
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import Keten

CASUS = Casus(casussen.H_BDO)


@pytest.fixture
def geen_kassarapport_ai(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Het kassarapport-pad zou een AI-call doen (rapport-extractie); in de gouden set nooit een echte call — de stub
    legt de aanroep vast en valt uit zoals een ontbrekende key (fail-zichtbaar, document → handmatig afmaken)."""
    from app.extractie import rapport as rapport_extractie
    from app.extractie.client import AiExtractieFout

    aanroepen: list[str] = []

    def stub(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        aanroepen.append("kassarapport")
        raise AiExtractieFout("gouden set: geen echte AI-call")

    monkeypatch.setattr(rapport_extractie, "extraheer_kassarapport", stub)
    return aanroepen


@pytest.fixture
def twee_bdo(keten: Keten) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []
    for n in range(2):
        xml = CASUS.xml().replace(b"6088744", f"608874{n}".encode())
        resultaat = keten.mail([(f"bdo-{n}.xml", xml)])
        assert resultaat.bijlagen[0].uitkomst == "toegewezen", resultaat.bijlagen[0]
        ids.append(resultaat.bijlagen[0].document_id)
    assert len(ids) == 2
    return ids


def _bulk(keten: Keten, body: dict) -> dict:
    resp = keten.api.post(f"/administraties/{keten.administratie_id}/documenten/bulk", json=body, headers=keten.headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestBulkActiesOpDeGoudenSet:
    def test_type_wijzigen_naar_kassarapport_in_een_handeling(
        self, keten: Keten, twee_bdo: list[uuid.UUID], geen_kassarapport_ai: list[str]
    ) -> None:
        body = {"document_ids": [str(i) for i in twee_bdo], "actie": "soort_wijzigen", "soort": "kassarapport"}
        d = _bulk(keten, body)
        assert (d["gelukt"], d["overgeslagen"], d["geen_toegang"]) == (2, 0, 0)
        for document_id in twee_bdo:
            lijst_rij = keten.lijst_rij(document_id, toon_afgehandeld="true")
            assert lijst_rij is not None and lijst_rij["soort"] == "kassarapport", lijst_rij
            # Extractie liep opnieuw via het kassarapport-pad; de uitval is zichtbaar (geen stille no-op).
            assert keten.rij(document_id)["status"] in ("handmatig_afmaken", "te_controleren")
        assert keten.ai.aanroepen == [], "de inkoop-AI wordt ná de soortwissel niet meer aangeroepen"
        assert len(geen_kassarapport_ai) == 2

    def test_verwijderen_met_een_reden_slaat_geboekt_over(self, keten: Keten, twee_bdo: list[uuid.UUID]) -> None:
        a, b = twee_bdo
        with scoped_session(keten.administratie_id, actor_id=keten.actor) as session:
            doc = session.get(Document, b)
            _schrijf_overgang(session, document=doc, naar=DocumentStatus.KLAAR_OM_TE_BOEKEN, actor_id=keten.actor)
            _schrijf_overgang(session, document=doc, naar=DocumentStatus.GEBOEKT, actor_id=keten.actor)
        body = {"document_ids": [str(a), str(b)], "actie": "verwijderen", "reden": "ProfX-journaal, geen factuur"}
        d = _bulk(keten, body)
        assert (d["gelukt"], d["overgeslagen"]) == (1, 1)
        assert d["rijen"][1]["uitkomst"] == "overgeslagen" and "geboekt" in d["rijen"][1]["reden"].lower()
        assert keten.rij(a)["status"] == "verwijderd" and keten.rij(b)["status"] == "geboekt"
        # Verwijderd = afgehandeld: uit de standaardlijst, zichtbaar achter de toggle, herstelbaar.
        assert str(a) not in keten.standaardlijst_ids()
        assert keten.lijst_rij(a, toon_afgehandeld="true") is not None
