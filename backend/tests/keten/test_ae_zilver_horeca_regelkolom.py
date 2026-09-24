"""Casus (ae) — Zilver Horeca Fac-25-022711 (BLOW, BUG 18-09, Peter: "hij splitst nu per regel zonder het vinkje?").

De factuur draagt per regel een btw-KOLOM ("9%" artikelen, "0%" Emballage/statiegeld) en géén btw-bedrag; kop zonder
totaal;
de meegefotografeerde pinbon zegt 738,27; twee regelbedragen liggen onder de bon (afgedekt). Doelgedrag:
(1) kolom is de basis: 9 % → laag-tarief, 0 % → "NL, Nul tarief" (nooit verlegd/vrijgesteld), regel-btw = netto × p;
(2) afgedekt → `bedrag_niet_gelezen` (chip), geen btw-code geraden; (3) pinbon niet toetsbaar → totaal leeg, status
oranje;
(4) modus volgt de data: de mens slaat losse regels op terwijl de voorkeur "samenvoegen" wordt → leesroute
`regels_samenvoegen`
False + `regels_modus_hersteld` True + één tijdlijnregel bij het openen (getest in tests/documenten — de
keten-administratie
heeft projectplicht). Fixtures: fixtures/ae_zilver_horeca_regelkolom/."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.documenten.boekvoorstel import BTW_BRON_FACTUUR_REGEL
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import TAXRATE_LAAG, TAXRATE_NUL, VENDORS, Keten

CASUS = Casus(casussen.AE_ZILVER_REGELKOLOM)
PDF = CASUS.pdf_bestandsnaam()
GB_DIVERSE_INKOPEN = uuid.UUID("44444444-0000-0000-0000-000000007049")


@pytest.fixture
def document_id(keten: Keten) -> uuid.UUID:
    pdf = CASUS.pdf()
    keten.ai.registreer(pdf, CASUS.ai_antwoord())
    return keten.upload(PDF, pdf).document_id


class TestRegelkolomEnPinbon:
    def test_veldvoorstel_leest_de_kolom_en_rekent_de_regelbtw(self, keten: Keten, document_id: uuid.UUID) -> None:
        vv = keten.document(document_id).veldvoorstel
        per_o = {(r["omschrijving"], r["netto_bedrag"]): r for r in vv["regels"]}
        twix = per_o[("Twix 32 x 50 gram", "17.95")]
        emballage = per_o[("Emballage ( 24 Stuks )", "10.80")]
        assert (twix["taxrate_id"], twix["btw_bron"], twix["btw_afleiding_basis"]) == (
            str(TAXRATE_LAAG),
            BTW_BRON_FACTUUR_REGEL,
            "kolom",
        )
        assert (twix["btw_bedrag"], twix["btw_bedrag_berekend"]) == ("1.62", True)
        assert (emballage["taxrate_id"], emballage["btw_bedrag"], emballage["btw_kolom_percentage"]) == (
            str(TAXRATE_NUL),
            "0.00",
            "0.0000",
        )
        balisto = per_o[("Balisto Yobbery 20 x 37 Gr", None)]
        # Afgedekt bedrag: geen btw-bedrag; de kolom "9%" is wél een factuurfeit → btw-code klaar voor de mens.
        assert (balisto["bedrag_niet_gelezen"], balisto["niet_gelezen_reden"]) == (True, "afgedekt")
        assert (balisto["taxrate_id"], balisto["btw_bedrag"]) == (str(TAXRATE_LAAG), None)
        # Pinbon: twee regels zonder bedrag → niet toetsbaar → géén totaal overgenomen, wél zichtbaar.
        assert vv["totaal_incl"] is None and vv["totaal_bron"] is None
        assert (vv["totaal_pinbon"], vv["totaal_pinbon_status"]) == ("738.27", "niet_toetsbaar")

    def test_prefill_en_controlescherm_dragen_kolomtarief_niet_gelezen_en_pinbon(
        self, keten: Keten, document_id: uuid.UUID
    ) -> None:
        voorstel = keten.prefill(document_id)
        assert voorstel.totaalbedrag is None and voorstel.totaal_pinbon == Decimal("738.27")
        assert voorstel.totaal_pinbon_status == "niet_toetsbaar" and voorstel.totaal_bron is None
        per_o = {(r.omschrijving, r.netto_bedrag): r for r in voorstel.regels}
        emballage = per_o[("Emballage ( 24 Stuks )", Decimal("10.80"))]
        assert (emballage.taxrate_id, emballage.btw_bron, emballage.factuur_btw_percentage) == (
            TAXRATE_NUL,
            BTW_BRON_FACTUUR_REGEL,
            Decimal("0.0000"),
        )
        assert emballage.btw_bedrag == Decimal("0.00")
        twix = per_o[("Twix 32 x 50 gram", Decimal("17.95"))]
        assert (twix.taxrate_id, twix.btw_bedrag, twix.factuur_btw_percentage) == (
            TAXRATE_LAAG,
            Decimal("1.62"),
            Decimal("0.0900"),
        )
        balisto = per_o[("Balisto Yobbery 20 x 37 Gr", None)]
        assert balisto.bedrag_niet_gelezen is True and balisto.taxrate_id == TAXRATE_LAAG and balisto.btw_bedrag is None
        # Keten-administratie = projectplicht → hard gesplitst (geen vinkje); geen totaal → ook geen één-regel-variant.
        assert (voorstel.regels_samenvoegen, voorstel.samenvoegen_toegestaan, voorstel.samengevoegde_regel) == (
            False,
            False,
            None,
        )
        assert voorstel.regels_modus_hersteld is False  # niets opgeslagen: niets te herstellen

        dto = keten.open_controlescherm(document_id)
        regels = {(r["omschrijving"], r["netto_bedrag"]): r for r in dto["regels"]}
        assert regels[("Emballage ( 24 Stuks )", "10.80")]["btw_bron"] == BTW_BRON_FACTUUR_REGEL
        assert regels[("Emballage ( 24 Stuks )", "10.80")]["factuur_btw_percentage"] in ("0.0000", "0", "0.00")
        assert regels[("Balisto Yobbery 20 x 37 Gr", None)]["bedrag_niet_gelezen"] is True
        assert (
            dto["totaal_pinbon"] == "738.27"
            and dto["totaal_pinbon_status"] == "niet_toetsbaar"
            and dto["totaalbedrag"] is None
        )


class TestOpslaanHoudtDeKolomtarievenVast:
    def test_losse_regels_opgeslagen_blijven_consistent_en_houden_het_kolomtarief(
        self, keten: Keten, document_id: uuid.UUID
    ) -> None:
        """De modus-herstel-casus zelf (voorkeur "samenvoegen" + losse regels opgeslagen) staat in
        tests/documenten/test_regel_prefill_factuur_regel_18_09.py — de keten-administratie heeft projectplicht en kent
        geen
        samenvoegen. Hier: ná opslaan blijven vinkje/hint/tabel één stand (gesplitst, geen herstel nodig) en houdt
        Emballage
        het 0 %-kolomtarief — niet het geheugen-tarief."""
        dto = keten.open_controlescherm(document_id)
        vendor_id = VENDORS["telecom"][0]
        body = {
            "vendor_id": str(vendor_id),
            "referentie": dto["referentie"],
            "factuurdatum": dto["factuurdatum"],
            "totaalbedrag": None,
            "regels": [
                {
                    **{k: r[k] for k in ("taxrate_id", "project_id", "netto_bedrag", "btw_bedrag", "omschrijving")},
                    "ledger_id": str(GB_DIVERSE_INKOPEN),
                }
                for r in dto["regels"]
            ],
            "regels_samenvoegen": True,  # wordt onder projectplicht bewust genegeerd (hard gesplitst)
        }
        resp = keten.api.put(
            f"/administraties/{keten.administratie_id}/documenten/{document_id}/boekvoorstel",
            json=body,
            headers=keten.headers,
        )
        assert resp.status_code == 200, resp.text

        opnieuw = keten.open_controlescherm(document_id)
        assert len(opnieuw["regels"]) == 6
        assert (opnieuw["regels_samenvoegen"], opnieuw["samenvoegen_toegestaan"], opnieuw["regels_modus_hersteld"]) == (
            False,
            False,
            False,
        )
        # BUG 23-09 (Van Rumpt 2025135): bij ≥ 2 opgeslagen regels berekent de server de één-regel-variant uit díe
        # regels of geeft een reden. Onder projectplicht is samenvoegen hard uitgesloten → géén variant en géén
        # reden-chip (er valt niets te kiezen), het veld reist wél mee op de DTO.
        assert "samenvoegen_niet_mogelijk_reden" in opnieuw and opnieuw["samenvoegen_niet_mogelijk_reden"] is None
        assert opnieuw["samengevoegde_regel"] is None
        emballage = next(
            r
            for r in opnieuw["regels"]
            if r["omschrijving"] == "Emballage ( 24 Stuks )" and r["netto_bedrag"] == "10.80"
        )
        assert emballage["taxrate_id"] == str(TAXRATE_NUL)
        assert not [g for g in keten.tijdlijn(document_id) if "weergave_hersteld" in g], (
            "niets te herstellen = geen regel"
        )
