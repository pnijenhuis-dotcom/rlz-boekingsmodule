# ruff: noqa: E501 — lange assert-regels bewust (één feit per regel)
"""Casus (ao) — Vastly-verkoopfacturen volledig automatisch (Peter 28/29-09: "deze huurfacturen horen daar sowieso niet
in te staan (ik wil ze niet eens zien). De koppeling met de boekhouding staat en dan moet het gewoon als omzet geboekt
worden, punt"; herzien 01-10: "ik wil gewoon dat de vastly facturen automatisch per BV op de juiste GB geboekt worden …
100% auto zonder menselijke tussenstap … hou het simpel"). Productie 23-09/28-09: 23 UBL's `te_controleren` + 9 in de
verzamelbak (Van Rooijen/Schaalje, geen KvK). Doelgedrag door de hele keten (IMAP-intake → UBL → register → UBL-extractie
→ autoboek → RLZ-stub):

1. verhuurder mét KvK die in `administratie_identiteit` staat → toegewezen zónder tenaamstelling-match, registerrij
   bron 'identiteit', direct GEBOEKT (omzetrekening: AccountingCost 8000 uit de UBL; btw: E 0 % vrijgesteld + S 21 %
   deterministisch), webhook `factuur_geboekt`, chip 'automatisch', nul AI-calls;
2. dezelfde factuur zonder AccountingCost → GEWEIGERD `omzetrekening_ontbreekt`, nooit op een afgeleide rekening (01-10;
   de terugval van 29-09 is afgezet) → bevinding `vastly_omzetrekening_ontbreekt` per document mét "Opnieuw aanbieden";
3. verhuurder zónder KvK mét het platform-administratie-id in de UBL (`RLZ-ADMINISTRATIE:<uuid>`, §2d-notitie 01-10) →
   toegewezen (bron 'ubl'), direct GEBOEKT — géén mens;
4. onbekende verhuurder (geen KvK, geen id) → NIET in de verzamelbak-lijst, wél de kantoorbrede bevinding
   `vastly_entiteit_niet_gekoppeld` "melden bij Vastly"; de koppelroute bestaat niet meer (404)."""

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

    def test_zonder_accountingcost_wordt_geweigerd_nooit_afgeleid(self, vastgoed_keten: Keten) -> None:
        keten = vastgoed_keten
        ubl = _ubl().replace(b"<cbc:AccountingCost>8000</cbc:AccountingCost>", b"").replace(b"RUB-2026-0099", b"RUB-2026-0100")
        [rij] = keten.mail([(XML_NAAM.replace("0099", "0100"), ubl)], afzender="facturen@vastly.example").bijlagen
        assert keten.status(rij.document_id) == DocumentStatus.TE_CONTROLEREN
        with keten.admin_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM boekhouding.vastly_omzetrekening")).scalar_one() == 0, "nooit een afgeleide rekening (01-10)"
            [reden] = [r[0] for r in conn.execute(text("SELECT nieuwe_waarde->>'reden' FROM platform.audit_event WHERE actie = 'autoboeken_geweigerd' AND record_id = :id"), {"id": rij.document_id})]
        assert reden.startswith("omzetrekening_ontbreekt: regel 1 (huur): geen grootboekcode (cbc:AccountingCost)") and "melden bij Vastly" in reden
        # > 1 dag oud → bevinding per document mét alleen "Opnieuw aanbieden"; de herzending door Vastly boekt 'm daarna.
        with keten.admin_engine.begin() as conn:
            conn.execute(text("UPDATE boekhouding.document SET aangemaakt_op = now() - interval '2 days' WHERE id = :id"), {"id": rij.document_id})
        v = Verzamelaar()
        v.start_blok(vastly_reconciliatie.BLOK)
        assert vastly_reconciliatie.cli_blok(argparse.Namespace(), v, stdout=lambda s: None) == 1
        [b] = [b for b in v.bevindingen if b.detail.get("afwijking_soort") == "vastly_omzetrekening_ontbreekt"]
        assert b.administratie_id == keten.administratie_id and b.detail["document_id"] == str(rij.document_id)
        assert keten.ai.aanroepen == []

    def test_administratie_id_in_ubl_boekt_zonder_kvk_en_zonder_mens(self, vastgoed_keten: Keten) -> None:
        keten = vastgoed_keten
        element = f"<cac:AdditionalDocumentReference><cbc:ID>RLZ-ADMINISTRATIE:{keten.administratie_id}</cbc:ID><cbc:DocumentDescription>Platform-administratie van de verhuurder (RLZ-boekhoudkoppeling)</cbc:DocumentDescription></cac:AdditionalDocumentReference>".encode()
        ubl = (
            _ubl()
            .replace(b"</cac:AdditionalDocumentReference>", b"</cac:AdditionalDocumentReference>" + element, 1)
            .replace(b'<cbc:CompanyID schemeID="0106">87654321</cbc:CompanyID></cac:PartyLegalEntity></cac:Party></cac:AccountingSupplierParty>', b"</cac:PartyLegalEntity></cac:Party></cac:AccountingSupplierParty>")
            .replace(b"Rubicon Investments B.V.", b"B. van Rooijen")
            .replace(b"RUB-2026-0099", b"BG-2026-0027")
        )
        [rij] = keten.mail([("factuur-BG-2026-0027-ubl.xml", ubl)], afzender="bvrooijen1983@gmail.example").bijlagen
        assert rij.uitkomst == "toegewezen" and (rij.detail or "").startswith("entiteitenregister:ubl → "), rij
        assert keten.status(rij.document_id) == DocumentStatus.GEBOEKT
        assert keten.ai.aanroepen == []
        with keten.admin_engine.connect() as conn:
            assert conn.execute(text("SELECT sleutel_soort, sleutel, bron FROM boekhouding.vastly_entiteit_koppeling")).one() == ("naam", "b van rooijen", "ubl")

    def test_onbekende_verhuurder_is_bevinding_melden_bij_vastly_zonder_koppelknop(self, vastgoed_keten: Keten) -> None:
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
        assert b.detail["reden"] == "UBL draagt geen administratie-id en geen bekende KvK — melden bij Vastly"
        # 01-10: geen koppelknop meer — de route bestaat niet; de UBL hoort het administratie-id te dragen.
        resp = keten.api.post(
            "/reconciliatie/vastly/entiteit-koppelen",
            json={"sleutel_soort": "naam", "sleutel": "b van rooijen", "administratie_id": str(keten.administratie_id)},
            headers=keten.headers,
        )
        assert resp.status_code == 404, resp.text
        assert keten.status(rij.document_id) == DocumentStatus.NIET_TOEGEWEZEN
        assert keten.ai.aanroepen == []
        with scoped_session(None) as session:
            besluit = entiteit.resolve_administratie(session, entiteit.EntiteitSleutels(kvk=None, naam_norm="b van rooijen", weergave=None))
        assert besluit.administratie_id is None and besluit.weigering == entiteit.WEIGERING_GEEN_ID_GEEN_KVK
