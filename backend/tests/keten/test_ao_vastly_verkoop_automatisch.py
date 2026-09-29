# ruff: noqa: E501 — lange assert-regels bewust (één feit per regel)
"""Casus (ao) — Vastly-verkoopfacturen volledig automatisch (Peter 28/29-09: "deze huurfacturen horen daar sowieso niet
in te staan (ik wil ze niet eens zien). De koppeling met de boekhouding staat en dan moet het gewoon als omzet geboekt
worden, punt"). Productie 23-09/28-09: 23 UBL's `te_controleren` (weigering "geen grootboekcode — mens kiest" / "btw
ambigu zonder onthouden keuze") + 9 in de verzamelbak (`vastly_verkoop_zonder_eenduidige_entiteit`, Van Rooijen/
Schaalje). Doelgedrag door de hele keten (IMAP-intake → entiteitenregister → UBL-extractie → autoboek → RLZ-stub):

1. verhuurder mét KvK die in `administratie_identiteit` staat → toegewezen zónder tenaamstelling-match, registerrij
   bron 'identiteit', direct GEBOEKT (omzetrekening: AccountingCost 8000 uit de UBL; btw: E 0 % vrijgesteld + S 21 %
   deterministisch), webhook `factuur_geboekt`, chip 'automatisch', nul AI-calls;
2. dezelfde factuur zonder AccountingCost → de vaste Vastly-omzetrekening van de administratie (afgeleid uit het
   rekeningschema, vastgelegd bron 'historie') → óók geboekt;
3. onbekende verhuurder (geen KvK, geen koppeling) → NIET in de verzamelbak-lijst, wél de kantoorbrede bevinding
   `vastly_entiteit_niet_gekoppeld`; "Koppel aan administratie…" → registerrij + directe boeking."""

from __future__ import annotations

import argparse
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.db.models import Grootboekrekening
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import boeken as documenten_boeken
from app.documenten.models import DocumentStatus
from app.intake import verzamelbak
from app.intercompany.models import AdministratieIdentiteit
from app.reconciliatie.run import Verzamelaar
from app.verkoop import entiteit
from app.verkoop import reconciliatie as vastly_reconciliatie
from tests.keten.casussen import FIXTURES
from tests.keten.conftest import Keten
from tests.verkoop.conftest import FakeVerkoopClient

CASUS = FIXTURES / "ao_vastly_verkoop_rub_2026_0099"
KVK = "87654321"
OMZET_8000 = uuid.UUID("11111111-1111-1111-1111-111111118000")
XML_NAAM = "factuur-RUB-2026-0099-ubl.xml"


def _ubl() -> bytes:
    return (CASUS / "factuur.xml").read_bytes()


@pytest.fixture
def vastgoed_keten(keten: Keten, monkeypatch: pytest.MonkeyPatch) -> Keten:
    """De keten-administratie als vastgoed-administratie mét KvK-identiteit en een omzetrekening 8000; de verkoop-
    boekmotor praat tegen de verkoop-stub (Customers + Receipts) via dezelfde seam als de inkoopmotor."""
    monkeypatch.setattr(documenten_boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeVerkoopClient())
    with keten.admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.administratie SET is_vastgoed = true, boeken_ingeschakeld = true WHERE id = :id"),
            {"id": keten.administratie_id},
        )
    with scoped_session(keten.administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        session.add(
            Grootboekrekening(
                ledger_id=OMZET_8000, administratie_id=keten.administratie_id, code="8000", naam="Huuropbrengsten",
                soort=1, is_totaalrekening=False,
            )
        )
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        session.add(
            AdministratieIdentiteit(
                administratie_id=keten.administratie_id, kvk=KVK, naam="Universal Steigerbouw B.V.",
                naam_norm="universal steigerbouw", bron="rlz",
            )
        )
    return keten


class TestVastlyVerkoopAutomatisch:
    def test_kvk_in_register_boekt_automatisch_zonder_ai(self, vastgoed_keten: Keten) -> None:
        keten = vastgoed_keten
        uitkomst = keten.mail([(XML_NAAM, _ubl())], afzender="facturen@vastly.example", onderwerp="Huurfactuur RUB-2026-0099")
        [rij] = uitkomst.bijlagen
        assert rij.uitkomst == "toegewezen" and "identiteit_kvk" in (rij.detail or ""), rij
        assert keten.status(rij.document_id) == DocumentStatus.GEBOEKT
        assert keten.ai.aanroepen == [], "UBL nooit door de AI"
        with keten.admin_engine.connect() as conn:
            detail = conn.execute(
                text("SELECT detail FROM boekhouding.document_gebeurtenis WHERE document_id = :id AND naar_status = 'geboekt'"),
                {"id": rij.document_id},
            ).scalar_one()
            assert detail["automatisch_geboekt"] is True and detail["bron"] == "verkoop_opt_in"
            assert conn.execute(text("SELECT event FROM boekhouding.webhook_uitgaand WHERE document_id = :id"), {"id": rij.document_id}).scalar_one() == "factuur_geboekt"
            assert conn.execute(text("SELECT sleutel_soort, sleutel, bron FROM boekhouding.vastly_entiteit_koppeling")).one() == ("kvk", KVK, "identiteit")
            regels = conn.execute(
                text("SELECT netto_bedrag, btw_bedrag FROM boekhouding.verkoop_voorstel_regel r JOIN boekhouding.verkoop_voorstel v ON v.document_id = r.document_id WHERE v.document_id = :id ORDER BY volgnummer"),
                {"id": rij.document_id},
            ).all()
        assert [(Decimal(n), Decimal(b)) for n, b in regels] == [(Decimal("1000.00"), Decimal("0.00")), (Decimal("200.00"), Decimal("42.00"))]

    def test_zonder_accountingcost_boekt_op_de_vaste_omzetrekening(self, vastgoed_keten: Keten) -> None:
        keten = vastgoed_keten
        ubl = _ubl().replace(b"<cbc:AccountingCost>8000</cbc:AccountingCost>", b"").replace(b"RUB-2026-0099", b"RUB-2026-0100")
        [rij] = keten.mail([(XML_NAAM.replace("0099", "0100"), ubl)], afzender="facturen@vastly.example").bijlagen
        assert keten.status(rij.document_id) == DocumentStatus.GEBOEKT
        with keten.admin_engine.connect() as conn:
            standen = conn.execute(text("SELECT regelsoort, ledger_id::text, bron FROM boekhouding.vastly_omzetrekening WHERE administratie_id = :a ORDER BY regelsoort"), {"a": keten.administratie_id}).all()
        assert standen == [("huur", str(OMZET_8000), "historie"), ("servicekosten", str(OMZET_8000), "historie")]

    def test_onbekende_verhuurder_is_bevinding_niet_verzamelbak_en_koppelen_boekt(self, vastgoed_keten: Keten) -> None:
        keten = vastgoed_keten
        ubl = (
            _ubl()
            .replace(b'<cbc:CompanyID schemeID="0106">87654321</cbc:CompanyID></cac:PartyLegalEntity></cac:Party></cac:AccountingSupplierParty>', b"</cac:PartyLegalEntity></cac:Party></cac:AccountingSupplierParty>")
            .replace(b"Rubicon Investments B.V.", b"B. van Rooijen")
            .replace(b"RUB-2026-0099", b"BG-2026-0026")
        )
        [rij] = keten.mail([("factuur-BG-2026-0026-ubl.xml", ubl)], afzender="bvrooijen1983@gmail.example").bijlagen
        assert rij.uitkomst == "entiteit_niet_gekoppeld", rij
        assert all(i.document_id != rij.document_id for i in verzamelbak.lijst_verzamelbak())
        v = Verzamelaar()
        v.start_blok(vastly_reconciliatie.BLOK)
        assert vastly_reconciliatie.cli_blok(argparse.Namespace(), v, stdout=lambda s: None) == 1
        [b] = [b for b in v.bevindingen if b.detail.get("afwijking_soort") == "vastly_entiteit_niet_gekoppeld"]
        assert b.administratie_id is None and b.detail["sleutel"] == "b van rooijen" and b.detail["aantal"] == 1
        # De handeling: Koppel aan administratie… → registerrij (mens) + directe boeking, nul AI-calls.
        resp = keten.api.post(
            "/reconciliatie/vastly/entiteit-koppelen",
            json={"sleutel_soort": "naam", "sleutel": "b van rooijen", "administratie_id": str(keten.administratie_id), "weergave": "B. van Rooijen"},
            headers=keten.headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["per_uitkomst"] == {"geboekt": 1}
        assert keten.status(rij.document_id) == DocumentStatus.GEBOEKT
        assert keten.ai.aanroepen == []
        with scoped_session(None) as session:
            besluit = entiteit.resolve_administratie(session, entiteit.EntiteitSleutels(kvk=None, naam_norm="b van rooijen", weergave=None))
        assert besluit.administratie_id == keten.administratie_id and besluit.bron == "koppeling_naam"
