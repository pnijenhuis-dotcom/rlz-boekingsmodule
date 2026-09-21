# ruff: noqa: F811 — pytest-fixtures als parameters
"""Casus (ah) — "Corrigeren…" op een GEBOEKT document (opdracht Peter 21-09, aanleiding BLOW RLZ-04-00000357/358 fout
btw-bedrag; "ik kan de storno-knop niet meer vinden"): de module boekt de échte BDO-UBL (casus h), corrigeert 'm vanuit
de module (actie 19 op het externe stuk + terug naar klaar_om_te_boeken mét reden) en boekt daarna opnieuw op een vers
GUID — het oude concept blijft in RLZ staan (nooit verwijderen) en is als eigen keten uitgezonderd van het duplicaatsignaal.
Gespeeld door de echte servicelaag: prefill → boekvoorstel → boeken → corrigeren (standaard port-resolutie via de
credential-seam) → checks → boeken."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.documenten import boeken, boekvoorstel, corrigeren
from app.documenten.models import DocumentStatus
from app.documenten.rlz_ids import rlz_herboeking_id
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import GB_ADVIES, PROJECT_26084, TAXRATE_HOOG, Keten

CASUS = Casus(casussen.H_BDO)
REDEN = "btw-bedrag verkeerd gelezen — TEST gouden set ah"


@pytest.fixture
def bdo_geboekt(keten: Keten, monkeypatch: pytest.MonkeyPatch) -> uuid.UUID:
    """BDO via de mail, geprefilld, opgeslagen en geboekt (cyclus 0) — de stand van Peters BLOW-stukken."""
    monkeypatch.setattr(corrigeren, "client_voor_rlz_admin_id", lambda rlz_admin_id: keten.rlz)
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
    boeken.boek_document(administratie_id=keten.administratie_id, document_id=document_id, actor_id=keten.actor)
    assert keten.status(document_id) == DocumentStatus.GEBOEKT
    return document_id


class TestCorrigerenInDeKeten:
    def test_corrigeren_zet_terug_naar_concept_en_klaar_om_te_boeken(self, keten: Keten, bdo_geboekt: uuid.UUID) -> None:
        oud_guid = rlz_herboeking_id(bdo_geboekt, 0)
        assert keten.rlz._invoices[str(oud_guid)]["Status"] == 2
        toets = corrigeren.toets(administratie_id=keten.administratie_id, document_id=bdo_geboekt)
        assert toets.beschikbaar and toets.blokkades == [], [b.als_dict() for b in toets.blokkades]

        r = corrigeren.corrigeer(
            administratie_id=keten.administratie_id, document_id=bdo_geboekt, actor_id=keten.actor, reden=REDEN
        )

        assert r.status is DocumentStatus.KLAAR_OM_TE_BOEKEN and r.boek_cyclus == 1
        assert r.gestorneerd == [str(oud_guid)] and r.oud_boekstuknummer
        # RLZ: hetzelfde stuk terug naar concept via actie 19 — geen delete, geen creditstuk.
        assert keten.rlz.correcties == [oud_guid]
        assert keten.rlz._invoices[str(oud_guid)]["Status"] == 1
        assert keten.status(bdo_geboekt) == DocumentStatus.KLAAR_OM_TE_BOEKEN
        # Bron van de gele balk: de laatste tijdlijnregel draagt reden + vorige boeking.
        corr = next(d["gecorrigeerd"] for d in reversed(keten.tijdlijn(bdo_geboekt)) if "gecorrigeerd" in d)
        assert corr["reden"] == REDEN and corr["oud_boekstuknummer"] == r.oud_boekstuknummer
        # De standaardlijst (kantoorwerk) toont 'm weer.
        assert str(bdo_geboekt) in keten.standaardlijst_ids()

    def test_tweede_klik_is_geen_tweede_storno(self, keten: Keten, bdo_geboekt: uuid.UUID) -> None:
        corrigeren.corrigeer(
            administratie_id=keten.administratie_id, document_id=bdo_geboekt, actor_id=keten.actor, reden=REDEN
        )
        with pytest.raises(corrigeren.AlGecorrigeerd):
            corrigeren.corrigeer(
                administratie_id=keten.administratie_id, document_id=bdo_geboekt, actor_id=keten.actor, reden=REDEN
            )
        assert len(keten.rlz.correcties) == 1

    def test_herboeking_op_vers_guid_met_oud_concept_uitgezonderd(self, keten: Keten, bdo_geboekt: uuid.UUID) -> None:
        corrigeren.corrigeer(
            administratie_id=keten.administratie_id, document_id=bdo_geboekt, actor_id=keten.actor, reden=REDEN
        )
        # De harde checks draaien vers ná de correctie (boek_cyclus zit in de externe vingerafdruk) en zijn groen:
        # het eigen oude concept (zelfde referentie, zelfde crediteur) is als eigen keten uitgezonderd.
        checks = keten.checks(bdo_geboekt)
        rood = {naam: melding for naam, (ok, melding) in checks.items() if not ok}
        assert not rood, rood
        boeken.boek_document(administratie_id=keten.administratie_id, document_id=bdo_geboekt, actor_id=keten.actor)
        assert keten.status(bdo_geboekt) == DocumentStatus.GEBOEKT
        assert keten.rlz._invoices[str(rlz_herboeking_id(bdo_geboekt, 1))]["Status"] == 2
        assert keten.rlz._invoices[str(rlz_herboeking_id(bdo_geboekt, 0))]["Status"] == 1  # oud concept blijft
        assert [p["reference"] for p in keten.rlz.puts] == ["6088744", "6088744"]
