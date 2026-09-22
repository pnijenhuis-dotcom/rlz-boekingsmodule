# ruff: noqa: F811 — pytest-fixtures als parameters
"""Niet-btw-plichtige administratie (BUG Peter 22-09, casus VGG / Studio Lacy Lion 2026-042 → RLZ-04-00000925):
(1) pure harde check "Btw in niet-btw-plichtige administratie" + de ene actie die alle regels herrekent, (2) verplichte
velden eist dan geen btw-code, de tarief-check meldt n.v.t., (3) de PUT-regels gaan zonder TaxRate als er geen code is,
(4) de prefill zet élke regel (en de samengevoegde) op bruto mét de vrijgestelde code, (5) de checks-storings-tak draagt
de nieuwe rij."""

from __future__ import annotations

import uuid
from dataclasses import replace
from decimal import Decimal as D

import pytest

from app.backends.rlz_inkoop import regels_naar_rlz_lines, tegenboek_lines
from app.beheer import btw_plichtig
from app.config import settings
from app.db.session import scoped_session
from app.documenten import boekvoorstel, service
from app.documenten.checks import (
    ACTIE_BTW_IN_KOSTEN_ALLES,
    NAAM_BTW_NIET_PLICHTIG,
    NAAM_BTW_TARIEF,
    CheckRegel,
    TariefInfo,
    check_btw_niet_plichtig,
    check_btw_past_bij_tarief,
    check_verplichte_velden,
    tarief_is_geen_btw,
    voer_harde_checks_uit,
)
from app.documenten.storage import LokaleBestandsopslag
from app.extractie.service import AiFactuurExtractie, AiRegel, AiVeld
from app.sync.models import TaxRateCache, VendorCache
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import gescoopte_gebruiker, opslag  # noqa: F401

HOOG = uuid.UUID("55555555-0000-0000-0000-000000000021")
VRIJ = uuid.UUID("55555555-0000-0000-0000-000000000010")
NUL = uuid.UUID("55555555-0000-0000-0000-000000000000")
VERLEGD = uuid.UUID("55555555-0000-0000-0000-000000000099")
EU = uuid.UUID("55555555-0000-0000-0000-000000000077")
VENDOR_ID = uuid.UUID("33333333-3333-3333-3333-333333333332")
TARIEVEN = {
    HOOG: TariefInfo(D("0.21"), "NL, Hoog Tarief", favoriet=True),
    VRIJ: TariefInfo(D("0"), "NL, Geen BTW (Vrijgesteld)", vrijgesteld=True, favoriet=True),
    NUL: TariefInfo(D("0"), "NL, Nul tarief"),
    VERLEGD: TariefInfo(D("0"), "NL, BTW verlegd (hoog)", verlegd=True),
    EU: TariefInfo(D("0"), "EU, Diensten Hoog tarief", verlegd=True, buitenland=True),
}


def _regel(taxrate, netto, btw) -> CheckRegel:
    return CheckRegel(ledger_id=uuid.uuid4(), taxrate_id=taxrate, netto_bedrag=D(netto), btw_bedrag=D(btw))


class TestPureCheck:
    def test_tarief_is_geen_btw(self) -> None:
        assert tarief_is_geen_btw(TARIEVEN[VRIJ]) and tarief_is_geen_btw(TARIEVEN[NUL])
        assert not tarief_is_geen_btw(TARIEVEN[HOOG])
        assert not tarief_is_geen_btw(TARIEVEN[VERLEGD]) and not tarief_is_geen_btw(TARIEVEN[EU])
        assert not tarief_is_geen_btw(None)
        assert tarief_is_geen_btw(TariefInfo(None, "zonder percentage"))

    def test_lacy_lion_gesplitst_is_rood_met_een_actie_voor_alle_regels(self) -> None:
        r = check_btw_niet_plichtig(
            regels=[_regel(HOOG, "1535.13", "322.38")], tarieven=TARIEVEN, geen_btw_taxrate_id=VRIJ
        )
        assert r.naam == NAAM_BTW_NIET_PLICHTIG and r.ok is False
        assert "btw € 322.38" in r.melding and "21 % · NL, Hoog Tarief" in r.melding
        assert "alleen het nettobedrag op de crediteurpost" in r.melding
        assert len(r.acties) == 1
        actie = r.acties[0]
        assert (actie.code, actie.regel, actie.taxrate_id) == (ACTIE_BTW_IN_KOSTEN_ALLES, 0, VRIJ)
        assert actie.label == "Btw in de kosten zetten (alle regels)"

    def test_bruto_met_geen_btw_code_is_groen_ook_zonder_code(self) -> None:
        assert check_btw_niet_plichtig(
            regels=[_regel(VRIJ, "1857.51", "0.00"), _regel(NUL, "10.00", "0")],
            tarieven=TARIEVEN,
            geen_btw_taxrate_id=VRIJ,
        ).ok
        # Zonder btw-code én zonder btw: in orde (RLZ kent hier misschien geen "geen btw"-code).
        assert check_btw_niet_plichtig(
            regels=[CheckRegel(ledger_id=uuid.uuid4(), taxrate_id=None, netto_bedrag=D("5"), btw_bedrag=None)],
            tarieven=TARIEVEN,
            geen_btw_taxrate_id=None,
        ).ok

    def test_verlegd_eu_en_onbekend_tarief_zijn_rood(self) -> None:
        r = check_btw_niet_plichtig(
            regels=[_regel(VERLEGD, "100", "0"), _regel(EU, "100", "0"), _regel(uuid.uuid4(), "1", "0")],
            tarieven=TARIEVEN,
            geen_btw_taxrate_id=None,
        )
        assert not r.ok
        assert "regel 1: tarief 0 % · NL, BTW verlegd (hoog)" in r.melding
        assert "regel 3: tarief niet in de gesyncte btw-codes" in r.melding
        assert r.acties[0].taxrate_id is None  # geen code → de actie maakt het tarief leeg

    def test_verplichte_velden_zonder_btw_code_en_tarief_check_nvt(self) -> None:
        regels = [CheckRegel(ledger_id=uuid.uuid4(), taxrate_id=None, netto_bedrag=D("10"), btw_bedrag=D("0"))]
        kw = dict(vendor_id=uuid.uuid4(), referentie="F1", factuurdatum=None, totaalbedrag=D("10"))
        assert "btw-code" in check_verplichte_velden(regels=regels, **kw).melding
        assert "btw-code" not in check_verplichte_velden(regels=regels, btw_plichtig=False, **kw).melding
        r = check_btw_past_bij_tarief(regels=[_regel(HOOG, "1535.13", "0")], tarieven=TARIEVEN, btw_plichtig=False)
        assert r.ok and r.naam == NAAM_BTW_TARIEF and NAAM_BTW_NIET_PLICHTIG in r.melding
        assert not check_btw_past_bij_tarief(regels=[_regel(HOOG, "1535.13", "0")], tarieven=TARIEVEN).ok

    def test_voer_harde_checks_uit_voegt_de_rij_alleen_toe_als_niet_plichtig(self) -> None:
        from app.documenten.checks import CheckResultaat

        ok = CheckResultaat("Duplicaatcheck", True, "x")
        kw = dict(
            client=None,
            vendor_id=uuid.uuid4(),
            referentie="2026-042",
            factuurdatum=None,
            totaalbedrag=D("1857.51"),
            regels=[_regel(HOOG, "1535.13", "322.38")],
            eigen_rlz_document_id=uuid.uuid4(),
            tarieven=TARIEVEN,
            duplicaat_resultaat=ok,
            duplicaat_over_crediteuren_resultaat=replace(ok, naam="Duplicaat over crediteuren"),
        )
        namen_plichtig = [r.naam for r in voer_harde_checks_uit(**kw).resultaten]
        assert NAAM_BTW_NIET_PLICHTIG not in namen_plichtig
        rapport = voer_harde_checks_uit(btw_plichtig=False, geen_btw_taxrate_id=VRIJ, **kw)
        namen = [r.naam for r in rapport.resultaten]
        assert namen.index(NAAM_BTW_NIET_PLICHTIG) == namen.index(NAAM_BTW_TARIEF) + 1
        rij = next(r for r in rapport.resultaten if r.naam == NAAM_BTW_NIET_PLICHTIG)
        assert rij.ok is False and rapport.geblokkeerd
        assert next(r for r in rapport.resultaten if r.naam == NAAM_BTW_TARIEF).ok  # n.v.t., niet dubbel rood


class TestRlzLines:
    def test_regel_zonder_taxrate_gaat_zonder_taxrate_met_taxamount_0(self) -> None:
        regel = boekvoorstel.BoekvoorstelRegelData(
            ledger_id=uuid.uuid4(),
            taxrate_id=None,
            project_id=None,
            netto_bedrag=D("1857.51"),
            btw_bedrag=D("0.00"),
            omschrijving="Schoonmaakkosten",
        )
        met_code = replace(regel, taxrate_id=VRIJ)
        voorstel = boekvoorstel.BoekvoorstelData(
            document_id=uuid.uuid4(),
            vendor_id=VENDOR_ID,
            referentie="2026-042",
            factuurdatum=None,
            totaalbedrag=D("1857.51"),
            rlz_boekstuknummer=None,
            regels=[regel, met_code],
            opgeslagen=True,
        )
        lines = regels_naar_rlz_lines(voorstel)
        assert "TaxRate" not in lines[0] and lines[0]["TaxAmount"] == 0.0 and lines[0]["NetAmount"] == 1857.51
        assert lines[1]["TaxRate"] == {"id": str(VRIJ)}
        terug = tegenboek_lines(voorstel, "TB")
        assert (
            "TaxRate" not in terug[0] and terug[0]["NetAmount"] == -1857.51 and terug[1]["TaxRate"]["id"] == str(VRIJ)
        )


# ---- prefill + checks door de keten (DB) -----------------------------------------------------------------------------


def _veld(waarde: str | None, zekerheid: float = 0.95) -> AiVeld:
    return AiVeld(waarde=waarde, zekerheid=zekerheid)


def _lacy_lion() -> AiFactuurExtractie:
    return AiFactuurExtractie(
        kop={
            "leverancier_naam": _veld("Studio Lacy Lion"),
            "factuurnummer": _veld("2026-042"),
            "factuurdatum": _veld("2026-09-11"),
            "vervaldatum": _veld("2026-10-11", zekerheid=0.5),
            "valuta": _veld("EUR"),
            "totaal_excl": _veld("1535.13"),
            "totaal_incl": _veld("1857.51"),
            "btw_bedrag": _veld("322.38"),
        },
        regels=[
            AiRegel(
                omschrijving="Schoonmaak september",
                netto_bedrag="1000.00",
                btw_bedrag="210.00",
                hoeveelheid="1",
                zekerheid=0.95,
            ),
            AiRegel(omschrijving="Ramen", netto_bedrag="535.13", btw_bedrag="112.38", hoeveelheid="1", zekerheid=0.95),
        ],
        bsn_verwijderd=0,
        volledig=True,
    )


@pytest.fixture
def stam_en_niet_plichtig(
    administratie_id: uuid.UUID, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.beheer import service as beheer_service

    beheer_service.zet_ai_extractie_ingeschakeld(
        actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
    )
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr("app.geheugen.regel_gb._client_voor", lambda *a, **k: None)
    monkeypatch.setattr(
        "app.extractie.service.extraheer_inkoopfactuur",
        lambda pdf_bytes, *, client=None, verbruik_referentie=None, mail_context=None: _lacy_lion(),
    )
    with scoped_session(administratie_id) as session:
        session.add(VendorCache(id=VENDOR_ID, administratie_id=administratie_id, naam="Studio Lacy Lion", brondata={}))
        session.add_all(
            [
                TaxRateCache(
                    id=HOOG,
                    administratie_id=administratie_id,
                    naam="NL, Hoog Tarief",
                    percentage=D("0.2100"),
                    brondata={"IsFavorite": True},
                ),
                TaxRateCache(
                    id=VRIJ,
                    administratie_id=administratie_id,
                    naam="NL, Geen BTW (Vrijgesteld)",
                    percentage=D("0"),
                    brondata={"IsExcempt": True, "IsFavorite": True},
                ),
                TaxRateCache(
                    id=NUL, administratie_id=administratie_id, naam="NL, Nul tarief", percentage=D("0"), brondata={}
                ),
            ]
        )
    btw_plichtig.zet(actor_id=beheerder_id, administratie_id=administratie_id, btw_plichtig=False)


def _upload(administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag) -> uuid.UUID:
    return service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="2026-042.pdf",
        inhoud=f"%PDF-1.4 {uuid.uuid4()}".encode(),
        actor_id=actor_id,
        opslag=opslag,
    ).document_id


def test_prefill_zet_elke_regel_bruto_met_vrijgestelde_code_en_checks_groen(
    gescoopte_gebruiker: uuid.UUID,
    administratie_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    stam_en_niet_plichtig: None,
) -> None:
    document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
    data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
    for regel in data.regels:
        assert regel.taxrate_id == VRIJ and regel.btw_bedrag == D("0.00") and regel.btw_in_kosten is True
        assert (
            regel.btw_bron == btw_plichtig.BTW_BRON_NIET_PLICHTIG and regel.btw_bron_detail == btw_plichtig.CHIP_TEKST
        )
    assert [r.netto_bedrag for r in data.regels] == [D("1210.00"), D("647.51")]
    assert sum(r.netto_bedrag for r in data.regels) == D("1857.51")  # Σ bruto = factuurtotaal incl.
    assert data.samengevoegde_regel is not None
    assert data.samengevoegde_regel.taxrate_id == VRIJ and data.samengevoegde_regel.netto_bedrag == D("1857.51")
    assert data.samengevoegde_regel.btw_bedrag == D("0.00")
    # Checks (storings-tak: geen RLZ-credential in de suite) — de nieuwe rij is groen, de tarief-check n.v.t.
    rapport = boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_id)
    per_naam = {r.naam: r for r in rapport.resultaten}
    assert per_naam[NAAM_BTW_NIET_PLICHTIG].ok, per_naam[NAAM_BTW_NIET_PLICHTIG].melding
    assert per_naam[NAAM_BTW_TARIEF].ok and "niet btw-plichtig" in per_naam[NAAM_BTW_TARIEF].melding
    assert per_naam["Regeltelling vs totaal"].ok, per_naam["Regeltelling vs totaal"].melding


def test_mens_splitst_toch_dan_blokkeert_de_check_met_actie(
    gescoopte_gebruiker: uuid.UUID,
    administratie_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    stam_en_niet_plichtig: None,
) -> None:
    document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
    data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
    regel = data.regels[0]
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=gescoopte_gebruiker,
        vendor_id=VENDOR_ID,
        referentie="2026-042",
        factuurdatum=data.factuurdatum,
        totaalbedrag=D("1857.51"),
        regels=[
            replace(
                regel,
                taxrate_id=HOOG,
                netto_bedrag=D("1535.13"),
                btw_bedrag=D("322.38"),
                ledger_id=regel.ledger_id or uuid.uuid4(),
            )
        ],
        regels_samenvoegen=False,
    )
    rapport = boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_id)
    rij = next(r for r in rapport.resultaten if r.naam == NAAM_BTW_NIET_PLICHTIG)
    assert rij.ok is False and rapport.geblokkeerd
    assert rij.acties[0].code == ACTIE_BTW_IN_KOSTEN_ALLES and rij.acties[0].taxrate_id == VRIJ
