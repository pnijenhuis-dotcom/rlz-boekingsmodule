"""Lijst-aanvulling Peter 08-09 (blok 11): de standaardlijst toont uitsluitend kantoor-actie-statussen
(te_controleren, klaar_om_te_boeken, handmatig_afmaken, boeken_mislukt, twijfel-duplicaat, verzamelbak); `geboekt`
valt onder "Toon afgehandelde documenten" (grijs, mét boekstuknummer) en telt niet in "Alle"; `ter_accordering` en
open-vraag-statussen staan in een aparte groep "Wachten op anderen" die niet in "Alle" meetelt.
Opgebouwd met échte casusdocumenten: Spot (te_controleren), Universal Nederland (geboekt), BDO (ter accordering),
Floor (vraag open)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.accordering import service as accordering_service
from app.documenten import boeken, boekvoorstel, deeplink, vragen
from app.documenten.models import DocumentStatus
from tests.accordering.conftest import maak_accordeur, zet_schema
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import GB_ADVIES, GB_HUUR_MATERIEEL, PROJECT_25011, PROJECT_26084, TAXRATE_HOOG, Keten


def _sla_op(keten: Keten, document_id: uuid.UUID, *, vendor: uuid.UUID, ledger: uuid.UUID, project: uuid.UUID) -> None:
    voorstel = keten.prefill(document_id)
    regel = voorstel.regels[0]
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=keten.administratie_id,
        document_id=document_id,
        actor_id=keten.actor,
        vendor_id=vendor,
        referentie=voorstel.referentie,
        factuurdatum=voorstel.factuurdatum,
        totaalbedrag=voorstel.totaalbedrag,
        regels=[
            boekvoorstel.BoekvoorstelRegelData(
                ledger_id=ledger,
                taxrate_id=TAXRATE_HOOG,
                project_id=project,
                netto_bedrag=regel.netto_bedrag,
                btw_bedrag=regel.btw_bedrag,
                omschrijving="regel",
            )
        ],
    )


@pytest.fixture
def statussen(keten: Keten, beheerder_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """Vier échte documenten in vier statussen."""
    spot = Casus(casussen.C_SPOT)
    keten.ai.registreer(spot.pdf(), spot.ai_antwoord())
    te_controleren = keten.upload(spot.pdf_bestandsnaam(), spot.pdf()).document_id

    a = Casus(casussen.A_UNIVERSAL_NEDERLAND)
    geboekt = keten.mail([(a.xml_bestandsnaam(), a.xml()), (a.pdf_bestandsnaam(), a.pdf())]).bijlagen[0].document_id
    _sla_op(keten, geboekt, vendor=keten.vendors["universal_nederland"], ledger=GB_HUUR_MATERIEEL, project=PROJECT_26084)
    boeken.boek_document(administratie_id=keten.administratie_id, document_id=geboekt, actor_id=keten.actor)

    bdo = Casus(casussen.H_BDO)
    pdf = bdo.pdf()
    ter_accordering = keten.mail(
        [(bdo.xml_bestandsnaam(), bdo.xml(ingesloten_pdf=pdf)), (bdo.pdf_bestandsnaam(), pdf)]
    ).bijlagen[0].document_id
    _sla_op(keten, ter_accordering, vendor=keten.vendors["bdo"], ledger=GB_ADVIES, project=PROJECT_26084)
    accordeur = maak_accordeur(keten.admin_engine, beheerder_id, keten.administratie_id, "S. Bakker")
    zet_schema(
        administratie_id=keten.administratie_id,
        beheerder_id=beheerder_id,
        lagen=[accordering_service.LaagInput(volgnummer=1, accordeur_gebruiker_id=accordeur, bedrag_drempel=None)],
    )
    accordering_service.bied_ter_accordering_aan(
        administratie_id=keten.administratie_id, document_id=ter_accordering, actor_id=keten.actor, actor_rol="boekhouding"
    )

    floor = Casus(casussen.B_FLOOR)
    pdf = floor.pdf()
    vraag_open = keten.mail(
        [(floor.xml_bestandsnaam(), floor.xml(ingesloten_pdf=pdf)), (floor.pdf_bestandsnaam(), pdf)],
        onderwerp="deel 5",
    ).bijlagen[0].document_id
    vragen.stel_vraag(
        administratie_id=keten.administratie_id,
        document_id=vraag_open,
        actor_id=keten.actor,
        vraag_tekst="Welk project hoort bij lift 16.5m Zwolle — 25011 of het nieuwe werk?",
    )
    ids = {"te_controleren": te_controleren, "geboekt": geboekt, "ter_accordering": ter_accordering, "vraag_open": vraag_open}
    assert {naam: keten.status(d) for naam, d in ids.items()} == {
        "te_controleren": DocumentStatus.TE_CONTROLEREN,
        "geboekt": DocumentStatus.GEBOEKT,
        "ter_accordering": DocumentStatus.TER_ACCORDERING,
        "vraag_open": DocumentStatus.VRAAG_OPEN,
    }
    return ids


class TestStandaardlijst:
    def test_kantoor_actie_status_staat_in_de_standaardlijst(self, keten: Keten, statussen) -> None:
        ids = keten.standaardlijst_ids()
        assert str(statussen["te_controleren"]) in ids

    def test_geboekt_document_toont_boekstuk_onder_toon_afgehandeld(self, keten: Keten, statussen) -> None:
        rij = keten.lijst_rij(statussen["geboekt"], toon_afgehandeld="true")
        assert rij is not None and rij["status"] == "geboekt"
        assert rij["geboekt_in_rlz"]["boekstuknummer"]
        assert Decimal(rij["totaalbedrag"]) == Decimal("212.21")

    # Blok 11 (08-09) staat: `geboekt` is afgehandeld — niet in de standaardlijst, wél achter de toggle mét teller.
    def test_geboekt_niet_in_standaardlijst_wel_onder_toggle(self, keten: Keten, statussen) -> None:
        assert str(statussen["geboekt"]) not in keten.standaardlijst_ids()
        lijst = keten.lijst(toon_afgehandeld="true")
        assert str(statussen["geboekt"]) in {d["id"] for d in lijst["documenten"]}
        assert lijst["afgehandeld"].get("geboekt") == 1
        assert lijst["afgehandeld"]["totaal"] >= 1

    def test_wachten_op_anderen_is_een_aparte_groep(self, keten: Keten, statussen, beheerder_id: uuid.UUID) -> None:
        """Blok 11 (08-09): `groep=kantoor` = de standaardlijst/"Alle" zonder ter_accordering; `groep=wachten` = wat op
        anderen wacht; de groep-tellers reizen mee in élke lijst-response. Dialoog open tot Afgehandeld (Peter 16-09):
        een open vraag telt op de AFGELEIDE kant — beurt bij kantoor/niemand (casus Floor zonder eigenaar) = kantoorwerk,
        beurt bij een klant-accordeur = wachten op anderen."""
        kantoor = keten.lijst(groep="kantoor")
        kantoor_ids = {d["id"] for d in kantoor["documenten"]}
        assert str(statussen["te_controleren"]) in kantoor_ids
        assert str(statussen["ter_accordering"]) not in kantoor_ids
        assert str(statussen["vraag_open"]) in kantoor_ids  # open vraag, kantoor aan zet
        assert str(statussen["geboekt"]) not in kantoor_ids
        wachten = keten.lijst(groep="wachten")
        assert {d["id"] for d in wachten["documenten"]} == {str(statussen["ter_accordering"])}
        assert kantoor["groepen"]["kantoor"] == 2
        assert kantoor["groepen"]["wachten"] == 1
        assert kantoor["groepen"]["afgehandeld"] >= 1  # het geboekte document
        # Dezelfde vraag aan de klant-accordeur gericht → de beurt ligt bij de klant → wachten op anderen.
        open_vraag = vragen.lijst_vragen(
            administratie_id=keten.administratie_id, status=vragen.VraagStatus.OPEN, document_id=statussen["vraag_open"]
        )[0]
        vragen.trek_vraag_in(administratie_id=keten.administratie_id, vraag_id=open_vraag.id, actor_id=keten.actor)
        accordeur = maak_accordeur(keten.admin_engine, beheerder_id, keten.administratie_id, "Sophia Accordeur")
        vragen.stel_vraag(
            administratie_id=keten.administratie_id,
            document_id=statussen["vraag_open"],
            actor_id=keten.actor,
            vraag_tekst="Is de lift door u opgedragen?",
            toegewezen_aan=accordeur,
        )
        kantoor2 = keten.lijst(groep="kantoor")
        assert str(statussen["vraag_open"]) not in {d["id"] for d in kantoor2["documenten"]}
        wachten2 = keten.lijst(groep="wachten")
        assert {d["id"] for d in wachten2["documenten"]} == {
            str(statussen["ter_accordering"]),
            str(statussen["vraag_open"]),
        }
        assert (kantoor2["groepen"]["kantoor"], kantoor2["groepen"]["wachten"]) == (1, 2)

    def test_ter_accordering_rij_toont_wie_aan_de_beurt_is(self, keten: Keten, statussen) -> None:
        rij = keten.lijst_rij(statussen["ter_accordering"], toon_afgehandeld="true")
        assert rij is not None and rij["status"] == "ter_accordering"
        assert rij["accordeur_aan_de_beurt"] is not None and rij["accordeur_aan_de_beurt"]["naam"] == "S. Bakker"

    def test_vraag_open_rij_niet_toegewezen_zonder_eigenaar(self, keten: Keten, statussen) -> None:
        rij = keten.lijst_rij(statussen["vraag_open"], toon_afgehandeld="true")
        assert rij is not None and rij["status"] == "vraag_open"
        assert rij["toegewezen_aan"] is None  # casus j: geen eigenaar → vraag loopt door, niet toegewezen
        assert PROJECT_25011 is not None


class TestAllesEnZoeken:
    """Feedbackrun A blok 8 (FV-20, Peter 25-09): "Alle" toonde niet alles. `groep=alles` = kantoor ∪ wachten ∪
    afgehandeld (server-side gepagineerd, `totaal`), en het zoekveld zoekt daar server-side (`q`) — de BDO-factuur die
    bij de klant ter accordering ligt (wachten op anderen) én de geboekte Universal-Nederland-factuur zijn zo vindbaar;
    de standaardlijst ("Open") blijft kantoorwerk."""

    def test_groep_alles_is_de_unie_met_totaal_en_pagina(self, keten: Keten, statussen) -> None:
        alles = keten.lijst(groep="alles")
        ids = {d["id"] for d in alles["documenten"]}
        assert ids >= {str(v) for v in statussen.values()}, "alles = te_controleren + geboekt + ter_accordering + vraag"
        assert alles["totaal"] == len(alles["documenten"]) and alles["limit"] == 200 and alles["offset"] == 0
        assert alles["groepen"]["alles"] == (
            alles["groepen"]["kantoor"] + alles["groepen"]["wachten"] + alles["groepen"]["afgehandeld"]
        )
        # Élke rij draagt zijn status (statuschip): de geboekte rij mét boekstuk, de ter-accordering-rij mét accordeur.
        per_id = {d["id"]: d for d in alles["documenten"]}
        assert per_id[str(statussen["geboekt"])]["status"] == "geboekt"
        assert per_id[str(statussen["geboekt"])]["geboekt_in_rlz"]["boekstuknummer"]
        assert per_id[str(statussen["ter_accordering"])]["accordeur_aan_de_beurt"]["naam"] == "S. Bakker"
        # Paginering: twee pagina's van 2 dekken samen minstens de vier casusdocumenten, zonder overlap.
        p1 = {d["id"] for d in keten.lijst(groep="alles", limit=2, offset=0)["documenten"]}
        p2 = {d["id"] for d in keten.lijst(groep="alles", limit=2, offset=2)["documenten"]}
        assert len(p1) == 2 and not (p1 & p2)
        # De standaardlijst ("Open") blijft kantoorwerk: geboekt en ter accordering horen daar niet in.
        assert str(statussen["geboekt"]) not in keten.standaardlijst_ids()

    def test_zoeken_vindt_wachten_op_anderen_en_geboekt(self, keten: Keten, statussen) -> None:
        bij_klant = keten.lijst(groep="alles", q="BDO")
        assert {d["id"] for d in bij_klant["documenten"]} == {str(statussen["ter_accordering"])}
        assert bij_klant["totaal"] == 1
        geboekt = keten.lijst(groep="alles", q="RLZ-2080143037")
        assert {d["id"] for d in geboekt["documenten"]} == {str(statussen["geboekt"])}
        assert geboekt["documenten"][0]["status"] == "geboekt"
        assert keten.lijst(groep="alles", q="bestaat-niet-xyz")["documenten"] == []


class TestDocumentlinkVolgtDeSoort:
    """Bundelrun 24-09 blok 7a (BUG 23-09, Van Boxtel): de vraag-thread linkte hard naar `/documenten/…`. De vraag-data
    draagt nu de documentsoort en de server-spiegel `deeplink.document_pad` kiest het scherm — voor de Floor-vraag
    (inkoopfactuur) blijft dat het inkoop-controlescherm; een kassarapport gaat naar het omzetreview-scherm."""

    def test_vraag_data_draagt_de_soort_en_de_link_volgt_die(self, keten: Keten, statussen) -> None:
        vraag_ids = vragen.open_vraag_ids_van_document(
            administratie_id=keten.administratie_id, document_id=statussen["vraag_open"]
        )
        assert vraag_ids
        data = [v for v in vragen.lijst_vragen(administratie_id=keten.administratie_id) if v.id == vraag_ids[0]]
        assert data and data[0].document_soort == "inkoopfactuur"
        pad = deeplink.document_pad(keten.administratie_id, statussen["vraag_open"], data[0].document_soort)
        assert pad == f"/documenten/{keten.administratie_id}/{statussen['vraag_open']}"
        assert deeplink.document_pad(keten.administratie_id, statussen["vraag_open"], "kassarapport") == (
            f"/omzet/{keten.administratie_id}/{statussen['vraag_open']}"
        )
