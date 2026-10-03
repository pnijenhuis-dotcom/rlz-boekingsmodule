"""Casus (ap) — bijlagen bij de factuur (Peter 02-10 "één mail = één document … alle bijlagen vanuit de verhuur zijn
losgekoppeld van de factuur — scheelt heel veel werk"). De Universal-Nederland-verhuurmail: de RLZ-export-UBL
(casus a, mét PDF-beeld) plus een huurstaat-PDF (tekstlaag, geen factuursignalen) en een specificatie-xlsx.
Doelgedrag: één document (de UBL mét PDF-beeld), de huurstaat en de xlsx hangen eraan als bijlage (status samengevoegd,
rol 'bijlage'), géén AI-call, de detail-route draagt ze, de bijlage-route levert de bytes, de lijst telt ze als
"2 bijlagen" (niet als exemplaren) en bij boeken gaan ze als extra upload mee naast het factuurbeeld."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.documenten import boeken, boekvoorstel
from app.documenten.models import DocumentStatus
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.extractie.pdf_helper import maak_tekst_pdf
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import GB_INHUUR, PROJECT_26084, TAXRATE_HOOG, Keten

CASUS = Casus(casussen.A_UNIVERSAL_NEDERLAND)
XML, PDF = CASUS.xml_bestandsnaam(), CASUS.pdf_bestandsnaam()
CASUS_C = Casus(casussen.C_SPOT)
PDF_C = CASUS_C.pdf_bestandsnaam()
WERKBON = maak_tekst_pdf(["Werkbon 7731", "Uren montage 8", "Getekend door uitvoerder"])


class TestBijlageVolgtDuplicaatNaarOrigineel:
    """BUG 03-10 (Peter "werkdetails zonder factuur kan niet"): de factuur uit de mail is al bekend (byte-identiek
    duplicaat, afgevoerd vóór de AI-stap — casus am) → de werkbon uit diezelfde mail hangt aan het ORIGINEEL, niet aan het
    afgevoerde exemplaar en valt niet los in de werkvoorraad."""

    def test_werkbon_bij_duplicaat_factuur_hangt_aan_het_origineel(self, keten: Keten) -> None:
        pdf = CASUS_C.pdf()
        keten.ai.registreer(pdf, CASUS_C.ai_antwoord())
        eerste = keten.mail([(PDF_C, pdf)], message_id=f"<eerste-{uuid.uuid4()}@spotservices.example>")
        origineel = eerste.bijlagen[0].document_id
        assert eerste.bijlagen[0].uitkomst == "toegewezen" and origineel is not None
        ai_calls = len(keten.ai.aanroepen)

        tweede = keten.mail(
            [(f"Fwd {PDF_C}", pdf), ("werkbon-7731.pdf", WERKBON)],
            afzender="facturen@kempengroep.nl",
            onderwerp="Fwd: Factuur 2026-608 + werkbon",
            message_id=f"<tweede-{uuid.uuid4()}@kempengroep.example>",
            kanaal="facturen_kempengroep",
        )
        per_naam = {r.bestandsnaam: r for r in tweede.bijlagen}
        exemplaar = per_naam[f"Fwd {PDF_C}"]
        assert exemplaar.uitkomst == "dubbel" and exemplaar.document_id not in (None, origineel)
        assert keten.status(exemplaar.document_id).value == "afgevoerd_duplicaat"
        werkbon = per_naam["werkbon-7731.pdf"]
        assert werkbon.uitkomst == "bijlage" and werkbon.document_id == origineel, tweede.bijlagen
        assert "via duplicaat" in (werkbon.detail or "")
        assert len(keten.ai.aanroepen) == ai_calls, "geen AI-call voor duplicaat of bijlage"
        detail = keten.detail(origineel)
        assert [b["bestandsnaam"] for b in detail["bijlagen"]] == ["werkbon-7731.pdf"]
        assert keten.detail(exemplaar.document_id)["bijlagen"] == []
        assert len(keten.lijst()["documenten"]) == 1  # standaardlijst: alleen het origineel, geen losse werkbon
        assert keten.status(origineel) == DocumentStatus.TE_CONTROLEREN
HUURSTAAT = maak_tekst_pdf(["Huurstaat week 31", "Werk 26084 Opdrachtgever A", "Steigermateriaal 120 m2 per week"])
XLSX = b"PK\x03\x04specificatie-verhuur-geen-omzetbron"


@pytest.fixture
def verhuurmail(keten: Keten):
    """UBL + PDF-beeld (casus a) + huurstaat + specificatie in één mail — zoals Universal Nederland 'm stuurt."""
    pdf = CASUS.pdf()
    return keten.mail(
        [(XML, CASUS.xml(ingesloten_pdf=pdf)), (PDF, pdf), ("huurstaat-wk31.pdf", HUURSTAAT), ("specificatie.xlsx", XLSX)],
        onderwerp="Facturen universal steigerbouw verhuur week 31",
    )


class TestEenMailEenDocument:
    def test_een_document_twee_bijlagen_geen_ai(self, keten: Keten, verhuurmail) -> None:
        per_naam = {r.bestandsnaam: r for r in verhuurmail.bijlagen}
        assert per_naam[XML].uitkomst == "toegewezen" and per_naam[PDF].uitkomst == "gebundeld"
        assert per_naam["huurstaat-wk31.pdf"].uitkomst == "bijlage"
        assert per_naam["specificatie.xlsx"].uitkomst == "bijlage"
        document_id = per_naam[XML].document_id
        assert per_naam["huurstaat-wk31.pdf"].document_id == document_id
        assert keten.status(document_id) == DocumentStatus.TE_CONTROLEREN
        assert keten.ai.aanroepen == [], "een bijlage gaat nooit door de AI"
        # Alleen de factuur is werk; de bijlagen zijn samengevoegd-rijen mét rol.
        lijst = keten.lijst(toon_afgehandeld="true")["documenten"]
        per_id = {d["id"]: d for d in lijst}
        assert per_id[str(document_id)]["bijlagen"] == 2 and per_id[str(document_id)]["samengevoegde_exemplaren"] == 0
        bijlage_rijen = [d for d in lijst if d.get("samenvoeg_rol")]
        assert {d["bestandsnaam"] for d in bijlage_rijen} == {"huurstaat-wk31.pdf", "specificatie.xlsx"}
        assert all(d["status"] == "samengevoegd" and d["samengevoegd_in"]["document_id"] == str(document_id) for d in bijlage_rijen)
        assert len(keten.lijst()["documenten"]) == 1  # standaardlijst: alleen de factuur

    def test_detail_en_bijlage_route_en_prefill_ongewijzigd(self, keten: Keten, verhuurmail) -> None:
        document_id = verhuurmail.bijlagen[0].document_id
        detail = keten.detail(document_id)
        namen = [b["bestandsnaam"] for b in detail["bijlagen"]]
        assert namen == ["huurstaat-wk31.pdf", "specificatie.xlsx"]
        assert all(b["niet_eenduidig"] is False for b in detail["bijlagen"])
        resp = keten.api.get(
            f"/administraties/{keten.administratie_id}/documenten/{document_id}/bijlagen/{detail['bijlagen'][0]['id']}/bestand",
            headers=keten.headers,
        )
        assert resp.status_code == 200 and resp.content == HUURSTAAT
        # Het factuurbeeld blijft de gebundelde PDF; het voorstel komt uit de UBL zoals in casus a.
        beeld = keten.api.get(f"/administraties/{keten.administratie_id}/documenten/{document_id}/bestand", headers=keten.headers)
        assert beeld.status_code == 200 and beeld.headers["content-type"].startswith("application/pdf")
        voorstel = keten.prefill(document_id)
        assert voorstel.referentie == "RLZ-2080143037"

    def test_boeken_neemt_bijlagen_mee_als_extra_uploads(self, keten: Keten, verhuurmail, monkeypatch) -> None:
        document_id = verhuurmail.bijlagen[0].document_id
        keten.open_controlescherm(document_id)
        voorstel = keten.prefill(document_id)
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=keten.administratie_id,
            document_id=document_id,
            actor_id=keten.actor,
            vendor_id=voorstel.vendor_id,
            referentie=voorstel.referentie,
            factuurdatum=voorstel.factuurdatum,
            totaalbedrag=voorstel.totaalbedrag,
            regels=[
                boekvoorstel.BoekvoorstelRegelData(
                    ledger_id=GB_INHUUR,
                    taxrate_id=TAXRATE_HOOG,
                    project_id=PROJECT_26084,
                    netto_bedrag=Decimal("175.38"),
                    btw_bedrag=Decimal("36.83"),
                    omschrijving="Verhuur steigermateriaal",
                )
            ],
        )
        fake = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
        boeken.boek_document(administratie_id=keten.administratie_id, document_id=document_id, actor_id=keten.actor)
        assert keten.status(document_id) == DocumentStatus.GEBOEKT
        namen = sorted(u["filename"] for u in fake.uploads)
        assert namen == sorted([PDF, "huurstaat-wk31.pdf", "specificatie.xlsx"])
        assert len({str(u["entity_id"]) for u in fake.uploads}) == 1
        assert isinstance(document_id, uuid.UUID)
