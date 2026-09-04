"""Verplichting door de BESTAANDE klant-accorderingsflow (⑥, besluit Peter 04-09): aanbieden mét de
verplichting-checks, drempels op het bedrag EXCLUSIEF btw, staande goedkeuring UITGESLOTEN, laatste
akkoord → terminale status `geaccordeerd` ZONDER boeking, en afwijzen via het bestaande pad."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.accordering import service as accordering_service
from app.documenten.models import DocumentStatus
from app.verplichting import service as verplichting_service
from tests.accordering.conftest import maak_accordeur
from tests.verplichting.conftest import (
    OFFERTEBEDRAG,
    document_status,
    sla_offerte_op,
    upload_verplichting,
)


def _laag(volgnummer: int, accordeur: uuid.UUID, drempel: str | None = None) -> accordering_service.LaagInput:
    return accordering_service.LaagInput(
        volgnummer=volgnummer,
        accordeur_gebruiker_id=accordeur,
        bedrag_drempel=Decimal(drempel) if drempel else None,
    )


@pytest.fixture
def accordeurs(admin_engine: Engine, beheerder_id, administratie_id) -> tuple[uuid.UUID, uuid.UUID]:
    return (
        maak_accordeur(admin_engine, beheerder_id, administratie_id, "J. de Groot"),
        maak_accordeur(admin_engine, beheerder_id, administratie_id, "M. Peters"),
    )


def _zet_lagen(*, administratie_id, beheerder_id, lagen) -> None:
    accordering_service.instellingen_opslaan(
        administratie_id=administratie_id,
        actor_id=beheerder_id,
        actor_rol="beheerder",
        ingeschakeld=True,
        lagen=lagen,
    )


def _offerte(*, administratie_id, gescoopte_gebruiker, opslag, project_id=None, bedrag=OFFERTEBEDRAG):
    document_id = upload_verplichting(
        administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag
    )
    sla_offerte_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=gescoopte_gebruiker,
        project_id=project_id,
        totaalbedrag_excl=bedrag,
    )
    return document_id


class TestAanbieden:
    def test_blokkerende_checks_houden_de_offerte_bij_het_kantoor(
        self, administratie_id, beheerder_id, gescoopte_gebruiker, opslag, accordeurs
    ):
        _zet_lagen(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeurs[0])])
        document_id = upload_verplichting(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag
        )  # nog geen voorstel → verplichte velden rood
        with pytest.raises(accordering_service.ChecksNietGroen):
            accordering_service.bied_ter_accordering_aan(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
                actor_rol="boekhouding",
            )

    def test_drempel_wordt_op_het_bedrag_exclusief_btw_geevalueerd(
        self, administratie_id, beheerder_id, gescoopte_gebruiker, opslag, vendors, accordeurs
    ):
        """Laag 2 geldt bóven € 50.000; een offerte van € 48.500 excl. hoeft alleen laag 1."""
        _zet_lagen(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(1, accordeurs[0]), _laag(2, accordeurs[1], "50000.00")],
        )
        document_id = _offerte(
            administratie_id=administratie_id, gescoopte_gebruiker=gescoopte_gebruiker, opslag=opslag
        )
        resultaat = accordering_service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        vereist = {s.volgnummer: s.vereist for s in resultaat.accordering.stappen}
        assert vereist == {1: True, 2: False}

    def test_hoger_bedrag_trekt_de_tweede_laag_erbij(
        self, administratie_id, beheerder_id, gescoopte_gebruiker, opslag, vendors, accordeurs
    ):
        _zet_lagen(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(1, accordeurs[0]), _laag(2, accordeurs[1], "50000.00")],
        )
        document_id = _offerte(
            administratie_id=administratie_id,
            gescoopte_gebruiker=gescoopte_gebruiker,
            opslag=opslag,
            bedrag=Decimal("62000.00"),
        )
        resultaat = accordering_service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        vereist = {s.volgnummer: s.vereist for s in resultaat.accordering.stappen}
        assert vereist == {1: True, 2: True}


class TestAkkoord:
    def test_laatste_akkoord_geeft_geaccordeerd_zonder_boeking(
        self, admin_engine: Engine, administratie_id, beheerder_id, gescoopte_gebruiker, opslag, vendors, accordeurs
    ):
        _zet_lagen(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeurs[0])])
        document_id = _offerte(
            administratie_id=administratie_id, gescoopte_gebruiker=gescoopte_gebruiker, opslag=opslag
        )
        accordering_service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        assert document_status(admin_engine, document_id) == DocumentStatus.TER_ACCORDERING.value
        resultaat = accordering_service.geef_akkoord(
            administratie_id=administratie_id, document_id=document_id, actor_id=accordeurs[0]
        )
        assert resultaat.alles_akkoord is True
        assert resultaat.geboekt is False and resultaat.boek_fout is None
        assert document_status(admin_engine, document_id) == DocumentStatus.GEACCORDEERD.value
        voorstel = verplichting_service.haal_voorstel_op(
            administratie_id=administratie_id, document_id=document_id
        )
        assert voorstel.goedgekeurd is not None
        assert voorstel.goedgekeurd.bedrag_excl == OFFERTEBEDRAG
        assert voorstel.goedgekeurd.op is not None

    def test_sequentiele_lagen_blijven_gelden(
        self, admin_engine: Engine, administratie_id, beheerder_id, gescoopte_gebruiker, opslag, vendors, accordeurs
    ):
        _zet_lagen(
            administratie_id=administratie_id,
            beheerder_id=beheerder_id,
            lagen=[_laag(1, accordeurs[0]), _laag(2, accordeurs[1])],
        )
        document_id = _offerte(
            administratie_id=administratie_id, gescoopte_gebruiker=gescoopte_gebruiker, opslag=opslag
        )
        accordering_service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        with pytest.raises(accordering_service.NietAanDeBeurt):
            accordering_service.geef_akkoord(
                administratie_id=administratie_id, document_id=document_id, actor_id=accordeurs[1]
            )
        accordering_service.geef_akkoord(
            administratie_id=administratie_id, document_id=document_id, actor_id=accordeurs[0]
        )
        assert document_status(admin_engine, document_id) == DocumentStatus.TER_ACCORDERING.value
        accordering_service.geef_akkoord(
            administratie_id=administratie_id, document_id=document_id, actor_id=accordeurs[1]
        )
        assert document_status(admin_engine, document_id) == DocumentStatus.GEACCORDEERD.value

    def test_staande_goedkeuring_is_uitgesloten(
        self, administratie_id, beheerder_id, gescoopte_gebruiker, opslag, vendors, accordeurs
    ):
        """⑥: een offerte is per definitie een nieuw aanbod — nooit "voortaan automatisch"."""
        _zet_lagen(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeurs[0])])
        document_id = _offerte(
            administratie_id=administratie_id, gescoopte_gebruiker=gescoopte_gebruiker, opslag=opslag
        )
        accordering_service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        with pytest.raises(accordering_service.StaandeRegelNietMogelijk):
            accordering_service.geef_akkoord(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=accordeurs[0],
                staande_regel_aanmaken=True,
            )

    def test_bestaande_staande_regel_wordt_niet_toegepast_op_een_verplichting(
        self, admin_engine: Engine, administratie_id, beheerder_id, gescoopte_gebruiker, opslag, vendors, accordeurs
    ):
        """Zelfs mét een handmatig geseede regel voor crediteur + exact bedrag blijft de offerte bij
        de accordeur liggen — geen automatisch akkoord voor verplichtingen."""
        from tests.verplichting.conftest import VENDOR_ID

        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.staande_goedkeuring "
                    "(id, administratie_id, accordeur_gebruiker_id, vendor_id, bedrag, actief) "
                    "VALUES (:id, :aid, :acc, :vid, :bedrag, true)"
                ),
                {
                    "id": uuid.uuid4(),
                    "aid": administratie_id,
                    "acc": accordeurs[0],
                    "vid": VENDOR_ID,
                    "bedrag": OFFERTEBEDRAG,
                },
            )
        _zet_lagen(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeurs[0])])
        document_id = _offerte(
            administratie_id=administratie_id, gescoopte_gebruiker=gescoopte_gebruiker, opslag=opslag
        )
        resultaat = accordering_service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        assert resultaat.alles_akkoord is False
        assert document_status(admin_engine, document_id) == DocumentStatus.TER_ACCORDERING.value


class TestAfwijzen:
    def test_accordeur_wijst_af_met_reden(
        self, admin_engine: Engine, administratie_id, beheerder_id, gescoopte_gebruiker, opslag, vendors, accordeurs
    ):
        _zet_lagen(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeurs[0])])
        document_id = _offerte(
            administratie_id=administratie_id, gescoopte_gebruiker=gescoopte_gebruiker, opslag=opslag
        )
        accordering_service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        accordering_service.wijs_af(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=accordeurs[0],
            reden="te duur, opnieuw laten calculeren",
        )
        assert document_status(admin_engine, document_id) == DocumentStatus.AFGEWEZEN.value
        voorstel = verplichting_service.haal_voorstel_op(
            administratie_id=administratie_id, document_id=document_id
        )
        assert voorstel.goedgekeurd is None

    def test_afwijzen_zonder_reden_geweigerd(
        self, administratie_id, beheerder_id, gescoopte_gebruiker, opslag, vendors, accordeurs
    ):
        _zet_lagen(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeurs[0])])
        document_id = _offerte(
            administratie_id=administratie_id, gescoopte_gebruiker=gescoopte_gebruiker, opslag=opslag
        )
        accordering_service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        with pytest.raises(accordering_service.RedenVerplicht):
            accordering_service.wijs_af(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=accordeurs[0],
                reden="  ",
            )


class TestWachtrij:
    def test_verplichting_kaart_in_de_wachtrij(
        self, administratie_id, beheerder_id, gescoopte_gebruiker, opslag, vendors, project_id, accordeurs
    ):
        _zet_lagen(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeurs[0])])
        document_id = _offerte(
            administratie_id=administratie_id,
            gescoopte_gebruiker=gescoopte_gebruiker,
            opslag=opslag,
            project_id=project_id,
        )
        accordering_service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        items = accordering_service.wachtrij_voor_accordeur(
            actor_id=accordeurs[0], administratie_ids=[administratie_id]
        )
        assert len(items) == 1
        item = items[0]
        assert item.soort == "verplichting"
        assert item.verplichting is not None
        assert item.verplichting.soort_label == "offerte"
        assert item.verplichting.totaal_excl == OFFERTEBEDRAG
        assert item.verplichting.project_naam == "26140 Koningstraat (Confide)"
        assert item.leverancier_naam == "Confide Bouw B.V."
        assert item.staande_regel_kandidaat is False
        assert item.offerte_match is None
