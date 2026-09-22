# ruff: noqa: F811 — pytest-fixtures als parameters
"""Casus (aj) — ter accordering, intussen buiten de module geboekt (Peter 22-09, casus Bouwadvies Oost Nederland /
Beter Assemblage F/2026/01235): harde checks doorstaan 16-09, drie lagen klikten akkoord t/m 21-09 19:15, en pas de
boekstap ná het laatste akkoord zag RLZ-04-00000518 — dezelfde factuur was tussendoor rechtstreeks in Reeleezee geboekt.
Doelgedrag: de dagelijkse reconciliatie toetst élk wachtend document VERS tegen RLZ (geen checks-cache), maakt dezelfde
ochtend een actie-bevinding `intussen_extern_geboekt` mét boekstuk/bedrag/datum, de accordeur-app toont "kantoor
beoordeelt; akkoord niet nodig" en weigert een akkoord (409), en "Afwijzen — al geboekt als …" trekt de ronde in mét de
tijdlijnregel "niet meer nodig: al geboekt in Reeleezee (…)" en wijst het document af via de bestaande afwijs-route.
Gespeeld met de BDO-UBL (casus h) als de wachtende factuur en één externe RLZ-rij als het buiten-de-module-stuk."""

from __future__ import annotations

import argparse
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from app import cli
from app.accordering import service as accordering_service
from app.accordering.models import AccorderingStatus
from app.berichten import mail
from app.documenten import boekvoorstel, intussen_extern_geboekt, reconciliatie
from app.documenten.models import DocumentStatus
from app.reconciliatie import run as run_service
from tests.accordering.conftest import accordeur_1, accordeur_2, zet_schema  # noqa: F401
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import GB_ADVIES, PROJECT_26084, TAXRATE_HOOG, Keten

CASUS = Casus(casussen.H_BDO)
EXTERN_ID = str(uuid.UUID("aa11aa11-0000-4000-8000-000000000518"))
BOEKSTUK = "RLZ-04-00000518"


@pytest.fixture(autouse=True)
def _geen_mail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mail, "verzend_mail", lambda **kw: None)


def _laag(volgnummer: int, accordeur: uuid.UUID) -> accordering_service.LaagInput:
    return accordering_service.LaagInput(volgnummer=volgnummer, accordeur_gebruiker_id=accordeur, bedrag_drempel=None)


@pytest.fixture
def bdo_bij_de_klant(
    keten: Keten, beheerder_id: uuid.UUID, accordeur_1: uuid.UUID, accordeur_2: uuid.UUID
) -> uuid.UUID:
    """BDO via de mail-intake, boekvoorstel opgeslagen, twee accorderingslagen, laag 1 al akkoord — het document wacht
    op laag 2 (zoals Bouwadvies tussen 16-09 en 21-09)."""
    keten.rlz.duplicaten = []  # bij intake en bij het aanbieden staat er nog niets in RLZ
    pdf = CASUS.pdf()
    resultaat = keten.mail([(CASUS.xml_bestandsnaam(), CASUS.xml(ingesloten_pdf=pdf)), (CASUS.pdf_bestandsnaam(), pdf)])
    document_id = resultaat.bijlagen[0].document_id
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
                ledger_id=GB_ADVIES,
                taxrate_id=TAXRATE_HOOG,
                project_id=PROJECT_26084,
                netto_bedrag=Decimal("5500.00"),
                btw_bedrag=Decimal("1155.00"),
                omschrijving="Samenstellen jaarrekening 2025",
            )
        ],
    )
    zet_schema(
        administratie_id=keten.administratie_id,
        beheerder_id=beheerder_id,
        lagen=[_laag(1, accordeur_1), _laag(2, accordeur_2)],
    )
    accordering_service.bied_ter_accordering_aan(
        administratie_id=keten.administratie_id, document_id=document_id, actor_id=keten.actor, actor_rol="boekhouding"
    )
    accordering_service.geef_akkoord(
        administratie_id=keten.administratie_id, document_id=document_id, actor_id=accordeur_1
    )
    assert keten.status(document_id) is DocumentStatus.TER_ACCORDERING
    return document_id


def _buiten_de_module_geboekt(keten: Keten, document_id: uuid.UUID) -> None:
    """Iemand boekt dezelfde factuur rechtstreeks in Reeleezee (zelfde crediteur + referentie, Status 2 Open)."""
    with keten.admin_engine.connect() as conn:
        referentie = conn.execute(
            text("SELECT referentie FROM boekhouding.boekvoorstel WHERE document_id = :id"), {"id": document_id}
        ).scalar_one()
    keten.rlz.duplicaten = [
        {
            "id": EXTERN_ID,
            "Reference": referentie,
            "InvoiceReference": referentie,
            "ReceiptNumber": BOEKSTUK,
            "BaseInvoiceAmount": 6655.00,
            "Status": 2,
            "Date": "2026-08-26T00:00:00",
        }
    ]


def _dagelijkse_run(keten: Keten, monkeypatch: pytest.MonkeyPatch) -> None:
    """De échte dagelijkse run van het documenten-blok (CLI-plumbing, bevindingen vastgelegd) tegen dezelfde
    RLZ-kant."""
    monkeypatch.setattr(
        cli.reconciliatie,
        "reconcilieer_alle_administraties",
        lambda: {
            keten.administratie_id: reconciliatie.reconcilieer_administratie(
                administratie_id=keten.administratie_id, client=keten.rlz
            )
        },
    )
    monkeypatch.setattr(cli.storno_detectie, "detecteer_en_meld_gestorneerd_alle", lambda: {})
    run_service.voer_uit(
        blokken=[("documenten", cli._reconciliatie)], args=argparse.Namespace(), bron="cli", stdout=lambda t: None
    )


def _wachtrij(accordeur: uuid.UUID, keten: Keten) -> list:
    return accordering_service.wachtrij_voor_accordeur(actor_id=accordeur, administratie_ids=[keten.administratie_id])


class TestIntussenBuitenDeModuleGeboekt:
    def test_zonder_extern_stuk_blijft_de_wachtrij_gewoon_open(
        self, keten: Keten, bdo_bij_de_klant: uuid.UUID, accordeur_2: uuid.UUID, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _dagelijkse_run(keten, monkeypatch)
        rapport = reconciliatie.reconcilieer_administratie(administratie_id=keten.administratie_id, client=keten.rlz)
        assert [a for a in rapport.afwijkingen if a.soort == intussen_extern_geboekt.SOORT] == []
        [item] = _wachtrij(accordeur_2, keten)
        assert item.document_id == bdo_bij_de_klant and item.extern_geboekt is None

    def test_treffer_geeft_bevinding_banner_409_en_afwijzen_trekt_de_ronde_in(
        self,
        keten: Keten,
        bdo_bij_de_klant: uuid.UUID,
        accordeur_2: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        document_id = bdo_bij_de_klant
        # 1. Tussen laag 1 en laag 2 boekt iemand de factuur rechtstreeks in Reeleezee; de ochtendrun ziet het VERS
        #    (de checks-cache van het aanbieden speelt geen rol) en maakt één actie-bevinding mét boekstuk/bedrag/datum.
        _buiten_de_module_geboekt(keten, document_id)
        _dagelijkse_run(keten, monkeypatch)
        rapport = reconciliatie.reconcilieer_administratie(administratie_id=keten.administratie_id, client=keten.rlz)
        [afwijking] = [a for a in rapport.afwijkingen if a.soort == intussen_extern_geboekt.SOORT]
        assert afwijking.document_id == document_id
        assert afwijking.context["extern_boekstuk"] == BOEKSTUK
        assert afwijking.context["extern_id"] == EXTERN_ID
        assert afwijking.context["extern_stand"] == "geboekt"
        assert afwijking.context["document_status"] == "ter_accordering"
        assert list(rapport.hercontrole_overgeslagen) == []

        # 2. Accordeur 2 ziet de banner en telt niet meer in "te accorderen"; een akkoord wordt geweigerd (409-kern).
        [item] = _wachtrij(accordeur_2, keten)
        assert item.extern_geboekt is not None
        assert intussen_extern_geboekt.banner_tekst(item.extern_geboekt) == (
            f"Al geboekt in Reeleezee ({BOEKSTUK}) — kantoor beoordeelt; akkoord niet nodig"
        )
        with pytest.raises(accordering_service.WachtOpKantoor):
            accordering_service.geef_akkoord(
                administratie_id=keten.administratie_id, document_id=document_id, actor_id=accordeur_2
            )
        assert keten.status(document_id) is DocumentStatus.TER_ACCORDERING

        # 3. Kantoor: "Afwijzen — al geboekt als RLZ-04-…" over de API — ronde vervalt mét de letterlijke reden,
        #    document afgewezen via de bestaande afwijs-route mét voorgevulde reden + kruisverwijzing, wachtrij leeg.
        r = keten.api.post(
            f"/reconciliatie/documenten/{document_id}/extern-geboekt/afwijzen",
            headers=keten.headers,
            json={
                "administratie_id": str(keten.administratie_id),
                "extern_id": EXTERN_ID,
                "extern_boekstuk": BOEKSTUK,
                "systeem": "Reeleezee",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "afgewezen" and body["accordering_vervallen"] is True
        assert body["reden"] == f"Al geboekt in Reeleezee als {BOEKSTUK} (buiten de module)"
        assert keten.status(document_id) is DocumentStatus.AFGEWEZEN
        tijdlijn = keten.tijdlijn(document_id)  # de detail-dicts van de tijdlijnregels, oudste eerst
        vervallen = [d for d in tijdlijn if d.get("accordering_vervallen")]
        assert len(vervallen) == 1
        assert vervallen[0]["reden"] == f"niet meer nodig: al geboekt in Reeleezee ({BOEKSTUK})"
        assert vervallen[0].get(intussen_extern_geboekt.VERVALLEN_MARKER) is True
        afwijzing = keten.afwijzing(document_id)
        assert afwijzing is not None and str(afwijzing["duplicaat_van_rlz_document_id"]) == EXTERN_ID
        with keten.admin_engine.connect() as conn:
            status = conn.execute(
                text("SELECT status FROM boekhouding.document_accordering WHERE document_id = :d"), {"d": document_id}
            ).scalar_one()
        assert status == AccorderingStatus.VERVALLEN.value
        assert _wachtrij(accordeur_2, keten) == []
        assert keten.rlz.puts == []  # de module heeft nooit een tweede boeking geschreven
        assert str(document_id) not in keten.standaardlijst_ids()
