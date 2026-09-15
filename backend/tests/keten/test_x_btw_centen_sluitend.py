"""Casus (x) — btw-cent-afronding aan de bron (reconciliatie-nazorg 15-09, besluit Peter 14-09; productiebeeld Kempen
Facilities: Lusso/Booking Experts 2–3 ct verschil tussen module en RLZ op geboekte documenten, nameting 15-09).

Gereconstrueerd Lusso-patroon op het echte KPN-document van casus (w): twee gelijke regels van € 15,55 @ 21 % — de
leverancier zet per regel 3,27 (3,2655 half-up) maar rekent de factuur-btw per totaal (31,10 × 21 % = 6,53), dus het
factuurtotaal is 37,63 terwijl Σ regels 37,64 is. De harde check "Regeltelling vs totaal" laat 1 ct door (tolerantie);
zonder cent-fix boekte RLZ 37,64 en meldde de reconciliatie de volgende ochtend `bedrag_wijkt_af` 0,01. Nu: (1) de PUT
naar RLZ sluit cent-exact op 37,63 (laatste btw-dragende regel 3,26), (2) de module-regels blijven wat de mens zag,
(3) de documenten-reconciliatie ziet géén bedragverschil, (4) een tegenboeking spiegelt dezelfde sluitende reeks."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.documenten import boeken, boekvoorstel, reconciliatie
from app.documenten.models import DocumentStatus
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import GB_HUUR_MATERIEEL, PROJECT_26084, TAXRATE_HOOG, Keten

CASUS = Casus(casussen.W_TELEFONIE_BTW_TOTAAL)
PDF = CASUS.pdf_bestandsnaam()

NETTO = Decimal("15.55")
BTW_PER_REGEL = Decimal("3.27")  # 15,55 × 21 % = 3,2655 → half-up per regel
TOTAAL_INCL = Decimal("37.63")  # 31,10 + 6,53 (btw per totaal)


@pytest.fixture
def lusso_document(keten: Keten) -> uuid.UUID:
    pdf = CASUS.pdf()
    keten.ai.registreer(pdf, CASUS.ai_antwoord())
    document_id = keten.upload(PDF, pdf).document_id
    voorstel = keten.prefill(document_id)
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=keten.administratie_id,
        document_id=document_id,
        actor_id=keten.actor,
        vendor_id=voorstel.vendor_id,
        referentie="L-2026-0917",
        factuurdatum=voorstel.factuurdatum,
        totaalbedrag=TOTAAL_INCL,
        regels=[
            boekvoorstel.BoekvoorstelRegelData(
                ledger_id=GB_HUUR_MATERIEEL,
                taxrate_id=TAXRATE_HOOG,
                project_id=PROJECT_26084,
                netto_bedrag=NETTO,
                btw_bedrag=BTW_PER_REGEL,
                omschrijving=f"Chalet {n}",
            )
            for n in (1, 2)
        ],
    )
    return document_id


class TestBtwCentenSluitendAanDeBron:
    def test_check_laat_een_cent_door_en_de_put_sluit_cent_exact(self, keten: Keten, lusso_document: uuid.UUID) -> None:
        checks = keten.checks(lusso_document)
        assert checks["Regeltelling vs totaal"][0], checks["Regeltelling vs totaal"][1]
        boeken.boek_document(administratie_id=keten.administratie_id, document_id=lusso_document, actor_id=keten.actor)
        assert keten.status(lusso_document) == DocumentStatus.GEBOEKT
        (put,) = keten.rlz.puts
        assert [line["TaxAmount"] for line in put["lines"]] == [3.27, 3.26]
        som = sum(
            (Decimal(str(line["NetAmount"])) + Decimal(str(line["TaxAmount"])) for line in put["lines"]), Decimal(0)
        )
        assert som == TOTAAL_INCL
        # De module-regels zijn niet herschreven: de mens ziet wat hij zag.
        voorstel = keten.prefill(lusso_document)
        assert [r.btw_bedrag for r in voorstel.regels] == [BTW_PER_REGEL, BTW_PER_REGEL]
        assert voorstel.totaalbedrag == TOTAAL_INCL

    def test_reconciliatie_ziet_geen_bedragverschil(self, keten: Keten, lusso_document: uuid.UUID) -> None:
        boeken.boek_document(administratie_id=keten.administratie_id, document_id=lusso_document, actor_id=keten.actor)
        rapport = reconciliatie.reconcilieer_administratie(administratie_id=keten.administratie_id, client=keten.rlz)
        assert rapport.aantal_gecontroleerd >= 1
        assert [a for a in rapport.afwijkingen if a.document_id == lusso_document] == []

    def test_zonder_cent_fix_zou_het_een_afronding_zijn_die_de_run_zelf_accepteert(self) -> None:
        """De andere helft van de nazorg (punt 1): kwam er tóch 0,01–0,05 verschil uit RLZ, dan is dat geen actie voor
        het kantoor maar een automatische acceptatie — dezelfde grens als de cent-fix."""
        afwijking = reconciliatie.ReconciliatieAfwijking(
            uuid.uuid4(),
            uuid.uuid4(),
            "bedrag_wijkt_af",
            "eigen=€37.63 rlz=€37.64",
            context={"bedrag_lokaal": "37.63", "bedrag_extern": "37.64"},
        )
        assert reconciliatie.afrondingsverschil(afwijking) == Decimal("0.01")
        from app.documenten.regelsom import CENT_TOLERANTIE

        assert CENT_TOLERANTIE == reconciliatie.AFRONDING_TOLERANTIE
