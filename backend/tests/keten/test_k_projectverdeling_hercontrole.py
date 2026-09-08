"""Casus (k) — pro-rato projectverdeling op échte UBL-facturen: DCTE 202611050 (verzamelfactuur week 29+30,
€ 118,75 excl.) en Kader Consultancy F212604921 (onderhoudsabonnement, € 630,00 excl.), beide 08-09 geboekt met een
pro-rato-verdeling over de omzetmaand augustus 2026. Doelgedrag blok 10 (Peter): (1) lege/ontbrekende omzetstand voor
de referentiemaand = GEEN herverdelingssignaal maar de bevinding "omzetcijfers ontbreken voor augustus 2026";
(2) afwijking onder de drempel (incl. 0 %) = geen signaal; (3) een document geboekt in de lopende maand wordt niet
hercontroleerd."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.documenten import boeken, boekvoorstel
from app.documenten.models import DocumentStatus
from app.projectverdeling import hercontrole
from app.projectverdeling import service as pv_service
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import GB_ADVIES, GB_INHUUR, TAXRATE_HOOG, Keten
from tests.projectverdeling.conftest import maak_project, seed_omzet

OMZETMAAND = date(2026, 8, 1)
DCTE, KADER = Casus(casussen.K1_DCTE), Casus(casussen.K2_KADER)


@pytest.fixture
def projecten(keten: Keten, admin_engine: Engine) -> dict[str, uuid.UUID]:
    """Drie projecten mét augustus-omzet (60/25/15 %) — de pro-rato-basis."""
    p = {
        "eindhoven": maak_project(admin_engine, keten.administratie_id, "26120 Eindhoven (BAM)"),
        "tilburg": maak_project(admin_engine, keten.administratie_id, "26127 Tilburg (Heijmans)"),
        "venlo": maak_project(admin_engine, keten.administratie_id, "26131 Venlo (Dura)"),
    }
    seed_omzet(admin_engine, keten.administratie_id, p["eindhoven"], "12000.00", date(2026, 8, 3))
    seed_omzet(admin_engine, keten.administratie_id, p["tilburg"], "5000.00", date(2026, 8, 15))
    seed_omzet(admin_engine, keten.administratie_id, p["venlo"], "3000.00", date(2026, 8, 28))
    return p


def _boek_met_verdeling(
    keten: Keten, casus: Casus, *, vendor: uuid.UUID, ledger: uuid.UUID, netto: str, btw: str, omschrijving: str
) -> uuid.UUID:
    pdf = casus.pdf()
    resultaat = keten.mail([(casus.xml_bestandsnaam(), casus.xml(ingesloten_pdf=pdf)), (casus.pdf_bestandsnaam(), pdf)])
    document_id = resultaat.bijlagen[0].document_id
    assert keten.status(document_id) == DocumentStatus.TE_CONTROLEREN
    voorstel = keten.prefill(document_id)
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
                project_id=None,
                netto_bedrag=Decimal(netto),
                btw_bedrag=Decimal(btw),
                omschrijving=omschrijving,
            )
        ],
    )
    pv_service.zet_leverancier_pro_rato(
        administratie_id=keten.administratie_id, vendor_id=vendor, actor_id=keten.actor, ingeschakeld=True
    )
    data = pv_service.sla_op(
        administratie_id=keten.administratie_id,
        document_id=document_id,
        actor_id=keten.actor,
        vaste_regels=[],
        pro_rato_periode=OMZETMAAND,
    )
    assert data is not None and data.compleet
    boeken.boek_document(administratie_id=keten.administratie_id, document_id=document_id, actor_id=keten.actor)
    assert keten.status(document_id) == DocumentStatus.GEBOEKT
    return document_id


@pytest.fixture
def dcte(keten: Keten, projecten) -> uuid.UUID:
    """DCTE: de RLZ-crediteurnaam wijkt af van de UBL-partijnaam — de mens koos de crediteur (zoals in productie)."""
    return _boek_met_verdeling(
        keten, DCTE, vendor=keten.vendors["dcte"], ledger=GB_INHUUR, netto="118.75", btw="24.94",
        omschrijving="uitgevoerde werkzaamheden week 29+30 / 2026",
    )


@pytest.fixture
def kader(keten: Keten, projecten) -> uuid.UUID:
    return _boek_met_verdeling(
        keten, KADER, vendor=keten.vendors["kader"], ledger=GB_ADVIES, netto="630.00", btw="132.30",
        omschrijving="Onderhoudsabonnement 2026",
    )


def _pv_rij(admin_engine: Engine, document_id: uuid.UUID) -> dict:
    with admin_engine.connect() as conn:
        return dict(
            conn.execute(
                text(
                    "SELECT status, pro_rato_bedrag, verdeling, hercontrole_afwijking_pct, hercontrole_verdeling, "
                    "hercontrole_op, geboekt_op FROM boekhouding.projectverdeling WHERE document_id = :id"
                ),
                {"id": document_id},
            )
            .mappings()
            .one()
        )


def _signaal_events(admin_engine: Engine, document_id: uuid.UUID) -> int:
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT count(*) FROM boekhouding.document_gebeurtenis WHERE document_id = :id "
                "AND detail ? 'projectverdeling_afwijking'"
            ),
            {"id": document_id},
        ).scalar_one()


def _verwijder_omzet_augustus(admin_engine: Engine, administratie_id: uuid.UUID) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM boekhouding.project_regel_cache WHERE administratie_id = :aid "
                "AND datum >= '2026-08-01' AND datum < '2026-09-01'"
            ),
            {"aid": administratie_id},
        )


class TestBoekenMetProRato:
    def test_dcte_en_kader_boeken_gesplitst_per_project(self, keten: Keten, dcte: uuid.UUID, kader: uuid.UUID, projecten) -> None:
        assert len(keten.rlz.puts) == 2
        for put, netto in zip(keten.rlz.puts, (Decimal("118.75"), Decimal("630.00")), strict=True):
            assert len(put["lines"]) == 3
            assert Decimal(str(round(sum(line["NetAmount"] for line in put["lines"]), 2))) == netto
            assert {line["Project"]["id"] for line in put["lines"]} == {str(p) for p in projecten.values()}
        for document_id, bedrag in ((dcte, Decimal("118.75")), (kader, Decimal("630.00"))):
            rij = _pv_rij(keten.admin_engine, document_id)
            assert rij["status"] == "geboekt" and rij["pro_rato_bedrag"] == bedrag
            assert sum(Decimal(d["bedrag"]) for d in rij["verdeling"]) == bedrag
        # Lijst: geboekt mét boekstuk, geen verdeling-chip.
        rij = keten.lijst_rij(kader, toon_afgehandeld="true")
        assert rij is not None and rij["geboekt_in_rlz"] is not None
        assert rij["projectverdeling_afwijking_pct"] is None


class TestHercontrole:
    def test_ongewijzigde_omzet_nul_procent_geen_signaal(self, keten: Keten, dcte: uuid.UUID, kader: uuid.UUID) -> None:
        tellers = hercontrole.herbereken_administratie(
            administratie_id=keten.administratie_id, vandaag=date(2026, 10, 2), forceer=True
        )
        assert tellers["signalen"] == 0 and tellers["herrekend"] == 2
        for document_id in (dcte, kader):
            rij = _pv_rij(keten.admin_engine, document_id)
            assert rij["hercontrole_afwijking_pct"] == Decimal("0.00") and rij["hercontrole_verdeling"] is None
            assert _signaal_events(keten.admin_engine, document_id) == 0
            assert keten.lijst_rij(document_id, toon_afgehandeld="true")["projectverdeling_afwijking_pct"] is None

    def test_afwijking_onder_de_drempel_geen_signaal(self, keten: Keten, kader: uuid.UUID, projecten) -> None:
        # +€ 400 op Venlo (3.000 → 3.400 van 20.400 totaal): Venlo-deel 94,50 → 105,00 = 1,67 % < 5 %.
        seed_omzet(keten.admin_engine, keten.administratie_id, projecten["venlo"], "400.00", date(2026, 8, 30))
        tellers = hercontrole.herbereken_administratie(
            administratie_id=keten.administratie_id, vandaag=date(2026, 10, 2), forceer=True
        )
        assert tellers["signalen"] == 0
        rij = _pv_rij(keten.admin_engine, kader)
        assert Decimal("0") < rij["hercontrole_afwijking_pct"] < Decimal("5")
        assert rij["hercontrole_verdeling"] is None
        assert _signaal_events(keten.admin_engine, kader) == 0

    def test_afwijking_boven_de_drempel_wel_signaal(self, keten: Keten, kader: uuid.UUID, projecten) -> None:
        # +€ 6.000 op Venlo: 3.000 → 9.000 van 26.000 → Venlo-deel 94,50 → 218,08 = 19,6 % > 5 %.
        seed_omzet(keten.admin_engine, keten.administratie_id, projecten["venlo"], "6000.00", date(2026, 8, 30))
        tellers = hercontrole.herbereken_administratie(
            administratie_id=keten.administratie_id, vandaag=date(2026, 10, 2), forceer=True
        )
        assert tellers["signalen"] == 1
        assert _signaal_events(keten.admin_engine, kader) == 1
        assert keten.lijst_rij(kader, toon_afgehandeld="true")["projectverdeling_afwijking_pct"] is not None

    def test_ontbrekende_omzet_geeft_geen_herverdelingssignaal(self, keten: Keten, dcte: uuid.UUID) -> None:
        _verwijder_omzet_augustus(keten.admin_engine, keten.administratie_id)
        tellers = hercontrole.herbereken_administratie(
            administratie_id=keten.administratie_id, vandaag=date(2026, 10, 2), forceer=True
        )
        assert tellers["signalen"] == 0
        assert _pv_rij(keten.admin_engine, dcte)["hercontrole_verdeling"] is None
        assert _signaal_events(keten.admin_engine, dcte) == 0

    def test_ontbrekende_omzet_is_een_zichtbare_bevinding(self, keten: Keten, dcte: uuid.UUID) -> None:
        _verwijder_omzet_augustus(keten.admin_engine, keten.administratie_id)
        tellers = hercontrole.herbereken_administratie(
            administratie_id=keten.administratie_id, vandaag=date(2026, 10, 2), forceer=True
        )
        assert tellers["signalen"] == 0
        assert tellers.get("omzet_ontbreekt") == 1
        teksten = " ".join(str(d) for d in keten.tijdlijn(dcte))
        assert "omzetcijfers ontbreken voor augustus 2026" in teksten

    def test_geboekt_in_lopende_maand_niet_hercontroleerd(self, keten: Keten, kader: uuid.UUID) -> None:
        geboekt_op = _pv_rij(keten.admin_engine, kader)["geboekt_op"]
        vandaag = geboekt_op.date()
        tellers = hercontrole.herbereken_administratie(administratie_id=keten.administratie_id, vandaag=vandaag)
        assert tellers["herrekend"] == 0 and tellers["overgeslagen"] >= 1
        assert _pv_rij(keten.admin_engine, kader)["hercontrole_op"] is None
