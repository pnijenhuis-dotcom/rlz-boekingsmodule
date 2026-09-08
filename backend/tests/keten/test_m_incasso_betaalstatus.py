"""Casus (m) — synthetische incasso-factuur Kempen Telecom Diensten KTD-2026-09-0417 (blok 3 bundel 08-09, B3; herkomst
in fixtures/m_incasso_factuur/bron.json): het betaalwijze-blok onder het totaal ("wordt automatisch geincasseerd … op of
rond 25-09-2026"). Doelgedrag: intake → extractie (stub) → deterministische incasso-detectie → prefill betaalstatus
"Wordt automatisch geïncasseerd" + verwachte betaaldatum 25-09-2026 (herkomst factuur) → chip-DTO; via het declaraties@-
kanaal wint het kanaal ("Betaald per bank"); de harde check "Betaalstatus (declaraties)" blokkeert zodra een declaratie
zonder bruikbare status staat; de mens wint mét audit; de RLZ-boeking zet de QuickPaymentSelection vóór actie 17."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.documenten import boeken
from app.documenten.models import DocumentStatus
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import GB_ADVIES, PROJECT_26049, TAXRATE_HOOG, Keten

CASUS = Casus(casussen.M_INCASSO)
PDF = CASUS.pdf_bestandsnaam()
INCASSO = "Wordt automatisch geïncasseerd"
PER_BANK = "Betaald per bank"


@pytest.fixture
def incasso_upload(keten: Keten) -> uuid.UUID:
    """Losse upload (facturen-pad): alleen de factuur zelf bepaalt de betaalstatus."""
    pdf = CASUS.pdf()
    keten.ai.registreer(pdf, CASUS.ai_antwoord())
    return keten.upload(PDF, pdf).document_id


@pytest.fixture
def declaratie(keten: Keten) -> uuid.UUID:
    """Dezelfde factuur via het declaraties@-postvak: het kanaal wint van de factuur."""
    pdf = CASUS.pdf()
    keten.ai.registreer(pdf, CASUS.ai_antwoord())
    resultaat = keten.mail(
        [(PDF, pdf)],
        afzender="medewerker@kempengroep.nl",
        onderwerp="Declaratie telefoonkosten",
        message_id=f"<decl-{uuid.uuid4()}@kempengroep.nl>",
        kanaal="declaraties",
    )
    assert [r.uitkomst for r in resultaat.bijlagen] == ["toegewezen"], resultaat.bijlagen
    return resultaat.bijlagen[0].document_id


def _put_boekvoorstel(keten: Keten, document_id: uuid.UUID, **wijzigingen) -> dict:
    """PUT zoals het controlescherm 'm stuurt: de GET-stand terug mét de wijziging(en)."""
    dto = keten.open_controlescherm(document_id)
    body = {
        "vendor_id": dto["vendor_id"],
        "referentie": dto["referentie"],
        "factuurdatum": dto["factuurdatum"],
        "vervaldatum": dto["vervaldatum"],
        "totaalbedrag": dto["totaalbedrag"],
        "regels": dto["regels"],
        "regels_samenvoegen": False,
        **wijzigingen,
    }
    resp = keten.api.put(
        f"/administraties/{keten.administratie_id}/documenten/{document_id}/boekvoorstel",
        json=body,
        headers=keten.headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _audit_acties(admin_engine: Engine, document_id: uuid.UUID) -> list[tuple[str, dict | None, dict | None]]:
    with admin_engine.connect() as conn:
        return [
            (r.actie, r.oude_waarde, r.nieuwe_waarde)
            for r in conn.execute(
                text(
                    "SELECT actie, oude_waarde, nieuwe_waarde FROM platform.audit_event "
                    "WHERE record_id = :id AND actie = 'boekvoorstel_betaalstatus_gewijzigd' ORDER BY tijdstip"
                ),
                {"id": document_id},
            )
        ]


class TestIncassoUitDeFactuur:
    def test_extractie_detecteert_incasso_deterministisch(self, keten: Keten, incasso_upload: uuid.UUID) -> None:
        assert keten.status(incasso_upload) == DocumentStatus.TE_CONTROLEREN
        veldvoorstel = keten.document(incasso_upload).veldvoorstel
        assert veldvoorstel["betaalwijze_tekst"].startswith("Het factuurbedrag")
        assert veldvoorstel["incasso"] == {
            "betaalstatus": INCASSO,
            "verwachte_betaaldatum": "2026-09-25",
            "bron_tekst": veldvoorstel["incasso"]["bron_tekst"],
        }
        assert "geincasseerd" in veldvoorstel["incasso"]["bron_tekst"]

    def test_prefill_en_chip_dto(self, keten: Keten, incasso_upload: uuid.UUID) -> None:
        dto = keten.open_controlescherm(incasso_upload)
        assert dto["betaalstatus"] == INCASSO
        assert dto["betaalstatus_herkomst"] == "factuur"
        assert dto["verwachte_betaaldatum"] == "2026-09-25"
        assert "geincasseerd" in dto["betaalstatus_bron_tekst"]
        assert dto["intake_kanaal"] is None  # losse upload
        assert len(dto["betaalstatus_opties"]) == 8 and dto["betaalstatus_opties"][2] == PER_BANK
        voorstel = keten.prefill(incasso_upload)
        assert voorstel.vendor_id == keten.vendors["telecom"]
        assert voorstel.betaalstatus == INCASSO and voorstel.verwachte_betaaldatum == date(2026, 9, 25)
        assert voorstel.totaalbedrag == Decimal("289.19")
        # A10: de autosave persisteerde de betaalstatus in de kolommen (checks + boekmotor zien dezelfde stand).
        assert voorstel.opgeslagen and voorstel.prefill_automatisch

    def test_check_niet_blokkerend_buiten_declaraties(self, keten: Keten, incasso_upload: uuid.UUID) -> None:
        keten.open_controlescherm(incasso_upload)
        checks = keten.checks(incasso_upload)
        ok, melding = checks["Betaalstatus (declaraties)"]
        assert ok and INCASSO in melding
        # Volgorde: direct ná Afdeling, vóór Projectverdeling (beide takken identiek).
        namen = [r["naam"] for r in keten.checks_dto(incasso_upload)["resultaten"]]
        assert namen.index("Afdeling") + 1 == namen.index("Betaalstatus (declaraties)")

    def test_mens_wint_met_audit_en_terug_naar_automatisch(
        self, keten: Keten, incasso_upload: uuid.UUID, admin_engine: Engine
    ) -> None:
        na = _put_boekvoorstel(keten, incasso_upload, betaalstatus="Betaald met PIN")["boekvoorstel"]
        assert (na["betaalstatus"], na["betaalstatus_herkomst"]) == ("Betaald met PIN", "mens")
        assert na["verwachte_betaaldatum"] == "2026-09-25"  # de incassodatum blijft als datalaag staan
        acties = _audit_acties(admin_engine, incasso_upload)
        assert acties[-1] == (
            "boekvoorstel_betaalstatus_gewijzigd",
            {"betaalstatus": INCASSO, "herkomst": "factuur"},
            {"betaalstatus": "Betaald met PIN", "herkomst": "mens"},
        )
        # Zelfde waarde nogmaals = geen nieuw audit-event; "" = terug naar de automatische afleiding.
        _put_boekvoorstel(keten, incasso_upload, betaalstatus="Betaald met PIN")
        assert len(_audit_acties(admin_engine, incasso_upload)) == len(acties)
        terug = _put_boekvoorstel(keten, incasso_upload, betaalstatus="")["boekvoorstel"]
        assert (terug["betaalstatus"], terug["betaalstatus_herkomst"]) == (INCASSO, "factuur")

    def test_onbekend_label_is_409(self, keten: Keten, incasso_upload: uuid.UUID) -> None:
        dto = keten.open_controlescherm(incasso_upload)
        resp = keten.api.put(
            f"/administraties/{keten.administratie_id}/documenten/{incasso_upload}/boekvoorstel",
            json={"vendor_id": dto["vendor_id"], "regels": dto["regels"], "betaalstatus": "Betaald met giro"},
            headers=keten.headers,
        )
        assert resp.status_code == 409 and "Onbekende betaalstatus" in resp.text

    def test_boeken_zet_quickpaymentselection_voor_actie_17(self, keten: Keten, incasso_upload: uuid.UUID) -> None:
        # Regels compleet maken (grootboek + btw) zodat de harde checks doorstaan; daarna de echte boekactie.
        dto = keten.open_controlescherm(incasso_upload)
        # Universal is een projectadministratie (project per regel hard) — een telecomfactuur landt op een project.
        regels = [
            {**r, "ledger_id": str(GB_ADVIES), "taxrate_id": str(TAXRATE_HOOG), "project_id": str(PROJECT_26049)}
            for r in dto["regels"]
        ]
        na = _put_boekvoorstel(keten, incasso_upload, regels=regels)
        assert not na["checks"]["geblokkeerd"], [r for r in na["checks"]["resultaten"] if not r["ok"]]
        resultaat = boeken.boek_document(
            administratie_id=keten.administratie_id, document_id=incasso_upload, actor_id=keten.actor
        )
        assert resultaat.status == DocumentStatus.GEBOEKT, resultaat
        assert len(keten.rlz.betaalstatus_gezet) == 1
        gezet = keten.rlz.betaalstatus_gezet[0]
        assert gezet["selection_id"] == "1a7732dc-053c-4ea1-87b9-2e0cb863ea19"  # "Wordt automatisch geïncasseerd"
        assert keten.rlz.geboekte_acties == [uuid.UUID(gezet["id"])]
        tijdlijn = keten.tijdlijn(incasso_upload)
        geboekt = next(d for d in tijdlijn if d.get("rlz_boekstuknummer"))
        assert geboekt["betaalstatus"] == INCASSO and geboekt["betaalstatus_herkomst"] == "factuur"


class TestDeclaratiesKanaal:
    def test_kanaal_wint_van_de_factuur(self, keten: Keten, declaratie: uuid.UUID) -> None:
        dto = keten.open_controlescherm(declaratie)
        assert dto["intake_kanaal"] == "declaraties"
        assert (dto["betaalstatus"], dto["betaalstatus_herkomst"]) == (PER_BANK, "kanaal")
        checks = keten.checks(declaratie)
        ok, melding = checks["Betaalstatus (declaraties)"]
        assert ok and "Declaratie" in melding and PER_BANK in melding

    def test_check_blokkeert_declaratie_zonder_bruikbare_status(self, keten: Keten, declaratie: uuid.UUID) -> None:
        # De mens zet 'm terug op "Nog te betalen" — voor een declaratie is dat fout: de check blokkeert zichtbaar.
        na = _put_boekvoorstel(keten, declaratie, betaalstatus="Nog te betalen")
        assert (na["boekvoorstel"]["betaalstatus"], na["boekvoorstel"]["betaalstatus_herkomst"]) == (
            "Nog te betalen",
            "mens",
        )
        rij = next(r for r in na["checks"]["resultaten"] if r["naam"] == "Betaalstatus (declaraties)")
        assert not rij["ok"] and "Nog te betalen" in rij["melding"]
        assert na["checks"]["geblokkeerd"]

    def test_intake_bericht_draagt_het_kanaal(self, keten: Keten, declaratie: uuid.UUID, admin_engine: Engine) -> None:
        with admin_engine.connect() as conn:
            kanaal = conn.execute(
                text(
                    "SELECT b.kanaal FROM boekhouding.intake_bericht b JOIN boekhouding.document d "
                    "ON d.intake_bericht_id = b.id WHERE d.id = :id"
                ),
                {"id": declaratie},
            ).scalar_one()
        assert kanaal == "declaraties"


class TestFrontendFixture:
    def test_exporteer_voor_het_harnas(self, keten: Keten, incasso_upload: uuid.UUID) -> None:
        keten.open_controlescherm(incasso_upload)
        keten.exporteer("m_incasso_factuur", incasso_upload)
