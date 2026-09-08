"""Casus (d) — één PDF met twee facturen van Universal Nederland (RLZ-2080143038 pagina 1–6, RLZ-2080143039 pagina
7–9), mail "deel 8" 02-09. Productie: bron a276062b → splitsingsvoorstel → bevestigd → deel1 4e5c99d5 (later
verwijderd), deel2 6d93888d (geboekt RLZ-25-00003214). De splitsing gaat ALTIJD eerst ter controle, nooit stil."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.session import scoped_session
from app.documenten.models import DocumentStatus
from app.intake import splitsing
from app.intake.models import IntakeSplitsing
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import Keten

CASUS = Casus(casussen.D_SPLITSING)
PDF = CASUS.pdf_bestandsnaam()


@pytest.fixture
def voorstel(keten: Keten):
    pdf = CASUS.pdf()
    assert CASUS.pdf_paginas() == 9
    keten.splitsing.registreer(pdf, CASUS.splitsing_antwoord())
    keten.ai.registreer_op_marker("RLZ-2080143038", CASUS.ai_antwoord("ai_antwoord_deel1.json"))
    keten.ai.registreer_op_marker("RLZ-2080143039", CASUS.ai_antwoord("ai_antwoord_deel2.json"))
    resultaat = keten.mail([(PDF, pdf)], onderwerp="Facturen universal steigerbouw deel 8")
    bron_id = resultaat.bijlagen[0].document_id
    with scoped_session(None) as session:
        rij = session.scalars(select(IntakeSplitsing).where(IntakeSplitsing.bron_document_id == bron_id)).one()
        splitsing_id, voorstel_json = rij.id, rij.voorstel
    return resultaat, bron_id, splitsing_id, voorstel_json


class TestSplitsingsvoorstel:
    def test_bron_naar_verzamelbak_met_voorstel_twee_delen(self, keten: Keten, voorstel) -> None:
        resultaat, bron_id, _, voorstel_json = voorstel
        assert resultaat.bijlagen[0].uitkomst == "splitsingsvoorstel"
        assert "2 facturen herkend" in (resultaat.bijlagen[0].detail or "")
        assert keten.rij(bron_id)["status"] == "niet_toegewezen"
        assert keten.rij(bron_id)["administratie_id"] is None
        assert voorstel_json["paginas"] == 9
        assert [(f["start_pagina"], f["eind_pagina"], f["factuurnummer"]) for f in voorstel_json["facturen"]] == [
            (1, 6, "RLZ-2080143038"),
            (7, 9, "RLZ-2080143039"),
        ]
        assert keten.ai.aanroepen == [], "vóór de bevestiging gaat geen deel naar de factuur-AI"
        assert str(bron_id) not in keten.standaardlijst_ids()


class TestBevestigen:
    def test_delen_doorlopen_de_normale_keten(self, keten: Keten, voorstel) -> None:
        _, bron_id, splitsing_id, _ = voorstel
        delen = splitsing.bevestig_splitsing(
            splitsing_id=splitsing_id,
            actor_id=keten.actor,
            delen=[
                splitsing.SplitsDeelInput(start_pagina=1, eind_pagina=6, tenaamstelling="Universal Steigerbouw B.V."),
                splitsing.SplitsDeelInput(start_pagina=7, eind_pagina=9, tenaamstelling="Universal Steigerbouw B.V."),
            ],
            opslag=keten.opslag,
        )
        assert [d.uitkomst for d in delen] == ["toegewezen", "toegewezen"]
        assert keten.rij(bron_id)["status"] == "gesplitst"
        assert len(keten.ai.aanroepen) == 2

        deel1, deel2 = (d.document_id for d in delen)
        assert keten.status(deel1) == DocumentStatus.TE_CONTROLEREN
        assert keten.status(deel2) == DocumentStatus.TE_CONTROLEREN
        ids = keten.standaardlijst_ids()
        assert {str(deel1), str(deel2)} <= ids and str(bron_id) not in ids

        v1, v2 = keten.prefill(deel1), keten.prefill(deel2)
        assert (v1.referentie, v1.totaalbedrag) == ("RLZ-2080143038", Decimal("2540.14"))
        assert (v2.referentie, v2.totaalbedrag) == ("RLZ-2080143039", Decimal("373.27"))
        assert v1.vendor_id == v2.vendor_id == keten.vendors["universal_nederland"]
        assert v1.vervaldatum is not None and v1.vervaldatum.isoformat() == "2026-08-31"
        # Twee delen van één PDF met verschillende referenties zijn geen duplicaat van elkaar.
        assert keten.rij(deel2)["mogelijk_duplicaat_van_id"] is None
        keten.open_controlescherm(deel2)
        checks = keten.checks(deel2)
        assert checks["Duplicaat (module)"][0] and checks["Duplicaatcheck"][0]
        assert checks["Regeltelling vs totaal"][0]

    def test_bron_document_blijft_terugvindbaar_met_herkomst(self, keten: Keten, voorstel) -> None:
        _, bron_id, splitsing_id, _ = voorstel
        splitsing.bevestig_splitsing(
            splitsing_id=splitsing_id,
            actor_id=keten.actor,
            delen=[
                splitsing.SplitsDeelInput(start_pagina=1, eind_pagina=6, tenaamstelling="Universal Steigerbouw B.V."),
                splitsing.SplitsDeelInput(start_pagina=7, eind_pagina=9, tenaamstelling="Universal Steigerbouw B.V."),
            ],
            opslag=keten.opslag,
        )
        with scoped_session(None) as session:
            rij = session.get(IntakeSplitsing, splitsing_id)
            assert rij is not None and rij.status == "bevestigd"
            assert len(rij.besluit_detail["delen"]) == 2
            assert all(d["uitkomst"] == "toegewezen" for d in rij.besluit_detail["delen"])
        assert isinstance(bron_id, uuid.UUID)
