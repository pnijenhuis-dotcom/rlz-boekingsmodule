"""Casus (ae) — btw-bedrag volgt het tarief + BUA (opdracht Peter 18-09, screenshot Rituals Nieuwegein bon 88-186308,
BLOW): één regel 4510 Representatiekosten mét "0% · NL, Nul", netto 96,36, btw 20,24 — 11/11 groen, Boeken actief. Dat
is een onmogelijke combinatie (€ 20,24 voorbelasting op een 0 %-code). Sinds 18-09: (1) zonder BUA-kenmerk wint "factuur
berekend" (21 %, 96,36/20,24) en is de nieuwe harde check groen; (2) mét kenmerk `btw_aftrek_uitgesloten` op 4510 zet de
prefill 0 % + btw in de kosten (116,60/0,00, chip "aftrek uitgesloten (4510)"); (3) de Rituals-stand zelf (0 % mét
20,24)
is ROOD mét de acties "Btw in kosten (0 %)" en "Zet 21 %"; de actie toegepast → groen."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import update

from app.db.models import Grootboekrekening
from app.db.session import scoped_session
from app.documenten.checks import ACTIE_BTW_IN_KOSTEN, ACTIE_ZET_TARIEF, NAAM_BTW_TARIEF
from app.documenten.regel_prefill import BTW_BRON_GROOTBOEK_AFTREK_UITGESLOTEN
from app.geheugen.models import BoekingObservatie
from app.geheugen.normalisatie import normaliseer_regel_sleutel
from app.sync.models import VendorCache
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import TAXRATE_HOOG, TAXRATE_NUL, Keten

CASUS = Casus(casussen.AE_RITUALS_BUA)
PDF = CASUS.pdf_bestandsnaam()
VENDOR_RITUALS = uuid.UUID("33333333-0000-0000-0000-000000000099")
GB_REPRESENTATIE = uuid.UUID("44444444-0000-0000-0000-000000004510")
OMSCHRIJVING = "Relatiegeschenk — cadeauset (representatie)"


@pytest.fixture
def rituals(keten: Keten) -> uuid.UUID:
    """Stamgegevens zoals BLOW ze kent: crediteur Rituals, rekening 4510 en het regel-geheugen dat déze omschrijving op
    4510 zet (geen btw-stem — anders wint het geheugen op de btw); "NL, Nul tarief" zit in de keten-seed."""
    with scoped_session(keten.administratie_id) as session:
        session.add(
            VendorCache(
                id=VENDOR_RITUALS,
                administratie_id=keten.administratie_id,
                naam="Rituals Nieuwegein",
                brondata={"Name": "Rituals Nieuwegein"},
            )
        )
        session.add(
            Grootboekrekening(
                ledger_id=GB_REPRESENTATIE,
                administratie_id=keten.administratie_id,
                code="4510",
                naam="Representatiekosten",
                soort=2,
                is_totaalrekening=False,
            )
        )
        session.add(
            BoekingObservatie(
                id=uuid.uuid4(),
                administratie_id=keten.administratie_id,
                vendor_id=VENDOR_RITUALS,
                regel_sleutel=normaliseer_regel_sleutel(OMSCHRIJVING),
                gb_id=GB_REPRESENTATIE,
                btw_id=None,
                bron="app",
                bron_datum=date(2025, 11, 20),
                boekstuk_ref="RLZ-04-00004510",
            )
        )
    pdf = CASUS.pdf()
    keten.ai.registreer(pdf, CASUS.ai_antwoord())
    return keten.upload(PDF, pdf).document_id


def _zet_kenmerk(keten: Keten) -> None:
    with scoped_session(keten.administratie_id) as session:
        session.execute(
            update(Grootboekrekening)
            .where(Grootboekrekening.ledger_id == GB_REPRESENTATIE)
            .values(btw_aftrek_uitgesloten=True)
        )


def _put(keten: Keten, document_id: uuid.UUID, dto: dict, regel: dict) -> dict:
    body = {
        "vendor_id": dto["vendor_id"],
        "referentie": dto["referentie"],
        "factuurdatum": dto["factuurdatum"],
        "totaalbedrag": dto["totaalbedrag"],
        "regels": [regel],
        "regels_samenvoegen": False,
    }
    resp = keten.api.put(
        f"/administraties/{keten.administratie_id}/documenten/{document_id}/boekvoorstel",
        json=body,
        headers=keten.headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _check(rapport: dict, naam: str) -> dict:
    return next(r for r in rapport["resultaten"] if r["naam"] == naam)


class TestBtwVolgtHetTarief:
    def test_zonder_kenmerk_wint_factuur_berekend_21_procent_en_check_groen(
        self, keten: Keten, rituals: uuid.UUID
    ) -> None:
        voorstel = keten.prefill(rituals)
        assert voorstel.vendor_id == VENDOR_RITUALS
        regel = voorstel.regels[0]
        assert regel.ledger_id == GB_REPRESENTATIE and regel.gb_bron == "geheugen"
        assert (regel.taxrate_id, regel.btw_bron, regel.btw_in_kosten) == (TAXRATE_HOOG, "factuur", False)
        assert (regel.netto_bedrag, regel.btw_bedrag) == (Decimal("96.36"), Decimal("20.24"))
        checks = keten.checks(rituals)
        ok, melding = checks[NAAM_BTW_TARIEF]
        assert ok, melding

    def test_met_bua_kenmerk_0_procent_en_btw_in_de_kosten(self, keten: Keten, rituals: uuid.UUID) -> None:
        _zet_kenmerk(keten)
        voorstel = keten.prefill(rituals)
        regel = voorstel.regels[0]
        assert regel.taxrate_id == TAXRATE_NUL
        assert regel.btw_bron == BTW_BRON_GROOTBOEK_AFTREK_UITGESLOTEN
        assert regel.btw_bron_detail == "aftrek uitgesloten (4510)"
        assert regel.btw_in_kosten is True
        assert (regel.netto_bedrag, regel.btw_bedrag) == (Decimal("116.60"), Decimal("0.00"))
        assert (regel.prefill_herkomst or {}).get("btw") == BTW_BRON_GROOTBOEK_AFTREK_UITGESLOTEN
        # Controlescherm: de autosave persisteert de stand, de DTO draagt de chip en de check is groen.
        dto = keten.open_controlescherm(rituals)
        r0 = dto["regels"][0]
        assert (r0["taxrate_id"], r0["btw_bron"], r0["btw_in_kosten"]) == (
            str(TAXRATE_NUL),
            BTW_BRON_GROOTBOEK_AFTREK_UITGESLOTEN,
            True,
        )
        assert (r0["netto_bedrag"], r0["btw_bedrag"]) == ("116.60", "0.00")
        assert dto["leverancier_land"] == "NL" and dto["leverancier_land_bron"] == "uit btw-nummer factuur"
        ok, melding = keten.checks(rituals)[NAAM_BTW_TARIEF]
        assert ok, melding
        # De regeltelling sluit óók: 116,60 + 0,00 = 116,60.
        ok, melding = keten.checks(rituals)["Regeltelling vs totaal"]
        assert ok, melding
        # Heropenen houdt chip en stand (snapshot-herstel).
        opnieuw = keten.open_controlescherm(rituals)
        assert opnieuw["regels"][0]["btw_in_kosten"] is True

    def test_rituals_stand_0_procent_met_btw_is_rood_met_twee_acties_en_actie_maakt_groen(
        self, keten: Keten, rituals: uuid.UUID
    ) -> None:
        dto = keten.open_controlescherm(rituals)
        regel = dict(dto["regels"][0])
        # De stand van het screenshot: 0 % · NL, Nul mét netto 96,36 en btw 20,24 (mens zette 0 % zonder herrekening).
        regel.update({"taxrate_id": str(TAXRATE_NUL), "netto_bedrag": "96.36", "btw_bedrag": "20.24"})
        uit = _put(keten, rituals, dto, regel)
        check = _check(uit["checks"], NAAM_BTW_TARIEF)
        assert check["ok"] is False
        assert "regel 1: 0 % · NL, Nul tarief met btw € 20.24 op netto € 96.36 — verwacht € 0.00" in check["melding"]
        acties = {a["code"]: a for a in check["acties"]}
        assert set(acties) == {ACTIE_BTW_IN_KOSTEN, ACTIE_ZET_TARIEF}
        assert (
            acties[ACTIE_BTW_IN_KOSTEN]["taxrate_id"] == str(TAXRATE_NUL) and acties[ACTIE_BTW_IN_KOSTEN]["regel"] == 1
        )
        assert (
            acties[ACTIE_ZET_TARIEF]["taxrate_id"] == str(TAXRATE_HOOG) and "21 %" in acties[ACTIE_ZET_TARIEF]["label"]
        )
        assert uit["checks"]["geblokkeerd"] is True
        # Actie "Btw in kosten (0 %)" toegepast: netto 116,60, btw 0,00 → groen, en de regeltelling sluit.
        regel.update({"netto_bedrag": "116.60", "btw_bedrag": "0.00"})
        uit = _put(keten, rituals, uit["boekvoorstel"], regel)
        assert _check(uit["checks"], NAAM_BTW_TARIEF)["ok"] is True
        assert _check(uit["checks"], "Regeltelling vs totaal")["ok"] is True
        # Alternatief "Zet 21 %": 96,36/20,24 op Hoog → óók groen.
        regel.update({"taxrate_id": str(TAXRATE_HOOG), "netto_bedrag": "96.36", "btw_bedrag": "20.24"})
        uit = _put(keten, rituals, uit["boekvoorstel"], regel)
        assert _check(uit["checks"], NAAM_BTW_TARIEF)["ok"] is True

    def test_geen_grijze_hint_meer_in_de_frontend(self) -> None:
        """Guard (regel 3, 18-09): de hint `regel-btw-berekend-hint` ("tarief geeft € … — factuur leidend") is VOLLEDIG
        vervangen door de harde check — hij mag nergens meer in de kantoor-frontend voorkomen."""
        from pathlib import Path

        frontend = Path(__file__).resolve().parents[3] / "frontend" / "src"
        treffers = [p for p in frontend.rglob("*.ts*") if "regel-btw-berekend-hint" in p.read_text(encoding="utf-8")]
        assert treffers == [], f"grijze btw-hint bestaat nog in: {[str(p) for p in treffers]}"
