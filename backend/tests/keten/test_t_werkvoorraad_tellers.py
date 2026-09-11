"""Gouden set — werkvoorraad-tellers-cache (blok 6 run 11-09 middag). Op échte casusdocumenten: de cache die de
klantenlijst leest (set-based, `actor_id`) is ná élke stap exact de telling over de brontabellen — upload (Spot →
te_controleren), UBL-bundel geboekt (Universal Nederland → terminaal, telt niet), vraag gesteld en afgehandeld (Spot →
vragen 1 / te_controleren 0 en terug). `herreken_alle(dry_run=True)` meldt nul afwijkingen = het bewijs dat de
incrementele hooks de definitie volgen."""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.documenten import boeken, boekvoorstel, service, vragen
from app.werkvoorraad import tellers
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import GB_HUUR_MATERIEEL, PROJECT_26084, TAXRATE_HOOG, Keten


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


def _klant(keten: Keten) -> service.WerkvoorraadKlant:
    [klant] = service.werkvoorraad_overzicht(
        administratie_ids_met_naam=[(keten.administratie_id, "Universal")], actor_id=keten.actor
    )
    return klant


def _geen_afwijkingen(keten: Keten) -> None:
    rapport = tellers.herreken_alle(administratie_ids=[keten.administratie_id], dry_run=True)
    assert rapport.afwijkingen == [], [(a.teller, a.cache, a.telling) for a in rapport.afwijkingen]


def test_cache_volgt_de_telling_door_de_keten(keten: Keten) -> None:
    # Cache bestaat (zoals ná de nachtelijke run) — vóór er documenten zijn.
    tellers.herreken(keten.administratie_id)
    assert _klant(keten).te_controleren == 0

    # 1. Spot Services (PDF via AI-stub) → te_controleren.
    spot = Casus(casussen.C_SPOT)
    keten.ai.registreer(spot.pdf(), spot.ai_antwoord())
    spot_id = keten.upload(spot.pdf_bestandsnaam(), spot.pdf()).document_id
    klant = _klant(keten)
    assert (klant.te_controleren, klant.klaar_om_te_boeken, klant.vragen) == (1, 0, 0)
    _geen_afwijkingen(keten)

    # 2. Universal Nederland (UBL + PDF = bundel) → geboekt = terminaal, telt niet mee.
    a = Casus(casussen.A_UNIVERSAL_NEDERLAND)
    geboekt = keten.mail([(a.xml_bestandsnaam(), a.xml()), (a.pdf_bestandsnaam(), a.pdf())]).bijlagen[0].document_id
    assert _klant(keten).te_controleren == 2
    _sla_op(keten, geboekt, vendor=keten.vendors["universal_nederland"], ledger=GB_HUUR_MATERIEEL, project=PROJECT_26084)
    boeken.boek_document(administratie_id=keten.administratie_id, document_id=geboekt, actor_id=keten.actor)
    klant = _klant(keten)
    assert (klant.te_controleren, klant.klaar_om_te_boeken) == (1, 0)
    _geen_afwijkingen(keten)

    # 3. Vraag op Spot → vragen 1, te_controleren 0; afgehandeld → terug.
    vraag = vragen.stel_vraag(
        administratie_id=keten.administratie_id, document_id=spot_id, actor_id=keten.actor, vraag_tekst="Welk project?"
    )
    klant = _klant(keten)
    assert (klant.te_controleren, klant.vragen) == (0, 1)
    _geen_afwijkingen(keten)
    vragen.handel_vraag_af(administratie_id=keten.administratie_id, vraag_id=vraag.id, actor_id=keten.actor)
    klant = _klant(keten)
    assert (klant.te_controleren, klant.vragen) == (1, 0)
    _geen_afwijkingen(keten)
    assert Decimal(klant.spiegel_taken) == 0
