"""Casus (ag) — Activa / MVA fase 1 (akkoord Peter 21-09, ontwerp §2 auto-first): een échte inkoopfactuur (BDO-UBL,
casus h) mét één regel op MVA-rekening 0107 ≥ € 450 → de kaart "Activum aanmaken?" toont de kandidaat mét voorvulling
(aanschafwaarde = regelnetto, aanschafdatum = factuurdatum, categorie inventaris → "Lineair 5 jaar", restwaarde 0,
KIA-signaal) → de mens kiest de afschrijvingsrekening en klikt "Aanmaken ná boeken" (koppeling `gepland`) → boeken via
de boekknop-route (202, achtergrond-schrijver direct) → ná de geslaagde boeking staat er precies één
`FixedAssets`-PUT in RLZ
(BalanceAccount 0107, "Lineair 5 jaar", client-GUID) → koppeling `aangemaakt` mét activumnummer, tijdlijnregel en audit.
Regel 2 (kosten 4700) blijft buiten beeld."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.activa import service as activa_service
from app.db.models import Grootboekrekening
from app.db.session import scoped_session
from app.documenten import boekvoorstel
from app.documenten.models import DocumentStatus
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import GB_ADVIES, PROJECT_26084, TAXRATE_HOOG, Keten

CASUS = Casus(casussen.H_BDO)
GB_0107 = uuid.UUID("44444444-0000-0000-0000-000000000107")
GB_0108 = uuid.UUID("44444444-0000-0000-0000-000000000108")


def _mva_rekeningen(keten: Keten) -> None:
    with scoped_session(keten.administratie_id) as session:
        for ledger_id, code, naam, is_activa in (
            (GB_0107, "0107", "Inventaris", True),
            (GB_0108, "0108", "Afschrijving inventaris", False),
        ):
            session.add(
                Grootboekrekening(
                    ledger_id=ledger_id,
                    administratie_id=keten.administratie_id,
                    code=code,
                    naam=naam,
                    soort=3,
                    is_totaalrekening=False,
                    is_activa=is_activa,
                )
            )


def _regel(ledger_id: uuid.UUID, netto: str, omschrijving: str) -> boekvoorstel.BoekvoorstelRegelData:
    n = Decimal(netto)
    return boekvoorstel.BoekvoorstelRegelData(
        ledger_id=ledger_id,
        taxrate_id=TAXRATE_HOOG,
        project_id=PROJECT_26084,
        netto_bedrag=n,
        btw_bedrag=(n * Decimal("0.21")).quantize(Decimal("0.01")),
        omschrijving=omschrijving,
    )


def test_ag_regel_op_mva_rekening_wordt_activum_in_rlz_na_boeken(keten: Keten) -> None:
    _mva_rekeningen(keten)
    pdf = CASUS.pdf()
    resultaat = keten.mail([(CASUS.xml_bestandsnaam(), CASUS.xml(ingesloten_pdf=pdf)), (CASUS.pdf_bestandsnaam(), pdf)])
    document_id = resultaat.bijlagen[0].document_id
    keten.open_controlescherm(document_id)
    voorstel = keten.prefill(document_id)
    # De controleur splitst: € 5.000 kantoorinrichting op 0107 (MVA) + € 500 advies op 4700 (kosten).
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=keten.administratie_id,
        document_id=document_id,
        actor_id=keten.actor,
        vendor_id=voorstel.vendor_id,
        referentie=voorstel.referentie,
        factuurdatum=voorstel.factuurdatum,
        totaalbedrag=voorstel.totaalbedrag,
        regels=[_regel(GB_0107, "5000.00", "Kantoorinrichting vergaderruimte"), _regel(GB_ADVIES, "500.00", "Advies")],
    )
    pad = f"/administraties/{keten.administratie_id}/documenten/{document_id}/activa-voorstel"

    # 1. De kaart toont precies één kandidaat mét voorvulling; de kostenregel telt niet.
    kaart = keten.api.get(pad, headers=keten.headers)
    assert kaart.status_code == 200, kaart.text
    dto = kaart.json()
    assert dto["document_geboekt"] is False and dto["grens"] == "450.00" and dto["onder_grens"] == []
    assert [k["regel_volgnummer"] for k in dto["kandidaten"]] == [1]
    k = dto["kandidaten"][0]
    assert k["ledger_code"] == "0107" and k["aanschafwaarde"] == "5000.00"
    assert k["aanschafdatum"] == (voorstel.factuurdatum or date.today()).isoformat()
    assert k["categorie"] == "inventaris" and k["methode_naam"] == "Lineair 5 jaar" and k["restwaarde"] == "0.00"
    assert [s["code"] for s in k["signalen"]] == ["kia_mia_mogelijk"] and k["koppeling"] is None
    assert any(o["code"] == "0108" for o in dto["afschrijving_ledger_opties"])
    # BUG 24-09 punt 1 (BLOw 23-09): zonder instelling is de afschrijvingsrekening deterministisch voorgevuld uit de
    # conventie code + 1 mét naam "Afschrijving…" (0107 → 0108), mét herkomst — de mens hoeft niets meer te kiezen.
    assert k["afschrijving_ledger_id"] == str(GB_0108) and k["afschrijving_ledger_code"] == "0108"
    assert k["afschrijving_bron"] == "conventie"

    # 2. "Aanmaken ná boeken" ZONDER body → de voorvulling wordt vastgelegd → gepland; nog niets in RLZ.
    gepland = keten.api.post(f"{pad}/1/aanmaken", json={}, headers=keten.headers)
    assert gepland.status_code == 200, gepland.text
    assert gepland.json()["kandidaten"][0]["koppeling"]["status"] == "gepland"
    assert gepland.json()["kandidaten"][0]["afschrijving_bron"] == "koppeling"
    assert keten.rlz.fixed_asset_puts == []

    # 3. Boeken via de boekknop-route (202 + directe achtergrond-schrijver) → inkoopfactuur én activum in RLZ.
    boek = keten.api.post(
        f"/administraties/{keten.administratie_id}/documenten/{document_id}/boeken", headers=keten.headers
    )
    assert boek.status_code == 202, boek.text
    assert keten.status(document_id) == DocumentStatus.GEBOEKT
    assert len(keten.rlz.puts) == 1 and keten.rlz.puts[0]["reference"] == "6088744"
    assert len(keten.rlz.fixed_asset_puts) == 1
    put = keten.rlz.fixed_asset_puts[0]
    assert put["BalanceAccount"] == {"id": str(GB_0107)} and put["DepreciationAccount"] == {"id": str(GB_0108)}
    assert put["DepreciationMethod"] == {"id": "aaaaaaaa-1111-4111-8111-000000000060"} and put["NumberOfMonths"] == 60
    assert put["TotalAmountPurchase"] == 5000.0 and put["LiquidationValue"] == 0.0 and put["Type"] == 1
    assert put["InvoiceReference"] == "6088744"
    assert put["id"] == str(activa_service.client_guid(document_id=document_id, regel_volgnummer=1, boek_cyclus=0))
    assert keten.rlz.fixed_assets[put["id"]]["DepreciationMethod"]["Description"] == "Lineair 5 jaar"

    # 4. Koppeling aangemaakt mét activumnummer; kaart + tijdlijn + audit dragen het.
    na = keten.api.get(pad, headers=keten.headers).json()
    kop = na["kandidaten"][0]["koppeling"]
    assert na["document_geboekt"] is True and kop["status"] == "aangemaakt" and kop["rlz_receipt_number"] == "1"
    assert kop["rlz_fixed_asset_id"] == put["id"]
    teksten = [d["activum"]["tekst"] for d in keten.tijdlijn(document_id) if "activum" in d]
    assert teksten == [
        "Activum gepland — wordt aangemaakt ná boeken: Kantoorinrichting vergaderruimte € 5000.00",
        "Activum aangemaakt in RLZ: Kantoorinrichting vergaderruimte € 5000.00 (Lineair 5 jaar) · nr 1",
    ]
    # Nog eens aanmaken = 409 (het activum staat in RLZ; wijzigen doet een mens dáár).
    assert keten.api.post(f"{pad}/1/aanmaken", headers=keten.headers).status_code == 409
    # Regel 2 is geen kandidaat: 422.
    assert keten.api.post(f"{pad}/2/aanmaken", headers=keten.headers).status_code == 422
