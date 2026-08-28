# ruff: noqa: F811 — pytest-fixtures als parameters (patroon tests/accordering)
"""Afdelingen binnen een administratie (bouwrun 28-08 blok A, mockup afdelingen.html, migratie
0084): toggle + terugval "Algemeen", beheer (aanmaken/archiveren), harde check, prefill-geheugen
per leverancier, accorderingsroute per afdeling, staande goedkeuringen binnen de afdeling,
wachtrij-scoping en het vervallen van rondes bij afdeling-/routewijziging."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.accordering import service as accordering_service
from app.afdelingen import service
from app.documenten import boekvoorstel
from app.main import app
from app.security.tokens import create_access_token
from tests.accordering.conftest import (  # noqa: F401
    TOTAAL,
    VENDOR_ID,
    accordeur_1,
    accordeur_2,
    actieve_gebruiker,
    administratie_id,
    beheerder_id,
    document_status,
    gescoopte_gebruiker,
    klaar_document,
    maak_klaar_document,
    opslag,
    zet_schema,
)

client = TestClient(app)


def _laag(volgnummer: int, accordeur: uuid.UUID, drempel: str | None = None) -> accordering_service.LaagInput:
    return accordering_service.LaagInput(
        volgnummer=volgnummer, accordeur_gebruiker_id=accordeur, bedrag_drempel=Decimal(drempel) if drempel else None
    )


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


@pytest.fixture
def afdelingen_aan(beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> uuid.UUID:  # noqa: F811
    """Toggle aan → terugval bestaat; geeft de id van 'Algemeen' terug."""
    service.zet_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
    terugval = next(a for a in service.lijst(administratie_id=administratie_id) if a.is_terugval)
    return terugval.id


def _maak_afdeling(beheerder_id: uuid.UUID, administratie_id: uuid.UUID, naam: str) -> uuid.UUID:
    return service.maak_aan(actor_id=beheerder_id, administratie_id=administratie_id, naam=naam).id


def _zet_afdeling(administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID, afdeling_id):
    huidig = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
    return boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        vendor_id=huidig.vendor_id,
        referentie=huidig.referentie,
        factuurdatum=huidig.factuurdatum,
        totaalbedrag=huidig.totaalbedrag,
        regels=[
            boekvoorstel.BoekvoorstelRegelData(
                ledger_id=r.ledger_id,
                taxrate_id=r.taxrate_id,
                project_id=r.project_id,
                netto_bedrag=r.netto_bedrag,
                btw_bedrag=r.btw_bedrag,
                omschrijving=r.omschrijving,
            )
            for r in huidig.regels
        ],
        afdeling_id=afdeling_id,
    )


def _check(administratie_id: uuid.UUID, document_id: uuid.UUID, naam: str):
    rapport = boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_id)
    return next(r for r in rapport.resultaten if r.naam == naam)


class TestToggleEnBeheer:
    def test_toggle_aan_maakt_terugval_algemeen_en_audit(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        assert service.lijst(administratie_id=administratie_id) == []
        service.zet_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
        lijst = service.lijst(administratie_id=administratie_id)
        assert [(a.naam, a.is_terugval, a.actief) for a in lijst] == [("Algemeen", True, True)]
        assert lijst[0].route == ()  # volgt de administratie-route
        # Idempotent: nogmaals aan → nog steeds precies één terugval.
        service.zet_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
        assert len(service.lijst(administratie_id=administratie_id)) == 1
        with admin_engine.connect() as conn:
            acties = list(
                conn.execute(
                    text("SELECT actie FROM platform.audit_event WHERE record_id = :id ORDER BY tijdstip"),
                    {"id": administratie_id},
                ).scalars()
            )
        assert acties.count("afdelingen_ingeschakeld_gewijzigd") == 2

    def test_aanmaken_vereist_toggle_en_unieke_naam(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, afdelingen_aan: uuid.UUID
    ) -> None:
        buitendienst = _maak_afdeling(beheerder_id, administratie_id, "Buitendienst")
        with pytest.raises(service.AfdelingFout, match="bestaat al"):
            _maak_afdeling(beheerder_id, administratie_id, " buitendienst ")
        service.zet_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=False)
        with pytest.raises(service.AfdelingFout, match="staan uit"):
            _maak_afdeling(beheerder_id, administratie_id, "Receptie")
        # Uit laat alles staan — niets verdwijnt.
        assert {a.id for a in service.lijst(administratie_id=administratie_id)} >= {buitendienst, afdelingen_aan}

    def test_archiveren_nooit_verwijderen_terugval_beschermd(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, afdelingen_aan: uuid.UUID, accordeur_1: uuid.UUID
    ) -> None:
        receptie = _maak_afdeling(beheerder_id, administratie_id, "Receptie")
        accordering_service.afdeling_route_opslaan(
            administratie_id=administratie_id,
            afdeling_id=receptie,
            actor_id=beheerder_id,
            actor_rol="beheerder",
            lagen=[_laag(1, accordeur_1)],
        )
        with pytest.raises(service.AfdelingFout, match="terugval"):
            service.archiveer(actor_id=beheerder_id, administratie_id=administratie_id, afdeling_id=afdelingen_aan)
        service.archiveer(actor_id=beheerder_id, administratie_id=administratie_id, afdeling_id=receptie)
        rij = next(a for a in service.lijst(administratie_id=administratie_id) if a.id == receptie)
        assert rij.actief is False and rij.gearchiveerd_op is not None
        assert rij.route == ()  # eigen lagen mee gedeactiveerd
        with pytest.raises(service.AfdelingFout, match="al gearchiveerd"):
            service.archiveer(actor_id=beheerder_id, administratie_id=administratie_id, afdeling_id=receptie)
        # Een gearchiveerde afdeling krijgt geen route meer.
        with pytest.raises(accordering_service.OngeldigeAanbieding, match="gearchiveerd"):
            accordering_service.afdeling_route_opslaan(
                administratie_id=administratie_id,
                afdeling_id=receptie,
                actor_id=beheerder_id,
                actor_rol="beheerder",
                lagen=[_laag(1, accordeur_1)],
            )

    def test_terugval_heeft_geen_eigen_route(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, afdelingen_aan: uuid.UUID, accordeur_1: uuid.UUID
    ) -> None:
        with pytest.raises(accordering_service.OngeldigeAanbieding, match="administratie"):
            accordering_service.afdeling_route_opslaan(
                administratie_id=administratie_id,
                afdeling_id=afdelingen_aan,
                actor_id=beheerder_id,
                actor_rol="beheerder",
                lagen=[_laag(1, accordeur_1)],
            )
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        lagen, _ = accordering_service.afdeling_route_ophalen(
            administratie_id=administratie_id, afdeling_id=afdelingen_aan
        )
        assert [laag.accordeur_gebruiker_id for laag in lagen] == [accordeur_1]


class TestHardeCheck:
    def test_toggle_uit_zwijgt_toggle_aan_blokkeert_tot_actieve_afdeling(
        self,
        beheerder_id: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        klaar_document: uuid.UUID,
    ) -> None:
        assert _check(administratie_id, klaar_document, "Afdeling").ok is True
        service.zet_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
        resultaat = _check(administratie_id, klaar_document, "Afdeling")
        assert resultaat.ok is False
        assert "ontbreekt" in resultaat.melding
        receptie = _maak_afdeling(beheerder_id, administratie_id, "Receptie")
        _zet_afdeling(administratie_id, klaar_document, gescoopte_gebruiker, receptie)
        resultaat = _check(administratie_id, klaar_document, "Afdeling")
        assert resultaat.ok is True and "Receptie" in resultaat.melding
        service.archiveer(actor_id=beheerder_id, administratie_id=administratie_id, afdeling_id=receptie)
        resultaat = _check(administratie_id, klaar_document, "Afdeling")
        assert resultaat.ok is False and "gearchiveerd" in resultaat.melding

    def test_afdeling_van_andere_administratie_geweigerd(
        self,
        beheerder_id: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        klaar_document: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        andere = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Andere', :rlz)"),
                {"id": andere, "rlz": str(uuid.uuid4())},
            )
        service.zet_ingeschakeld(actor_id=beheerder_id, administratie_id=andere, ingeschakeld=True)
        vreemde = next(a.id for a in service.lijst(administratie_id=andere))
        with pytest.raises(boekvoorstel.BoekvoorstelFout, match="Onbekende afdeling"):
            _zet_afdeling(administratie_id, klaar_document, gescoopte_gebruiker, vreemde)


class TestPrefillGeheugen:
    def test_laatste_keuze_per_leverancier_wint_alleen_zonder_eigen_keuze(
        self,
        beheerder_id: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        afdelingen_aan: uuid.UUID,
        admin_engine: Engine,
        opslag,  # noqa: F811
    ) -> None:
        buitendienst = _maak_afdeling(beheerder_id, administratie_id, "Buitendienst")
        receptie = _maak_afdeling(beheerder_id, administratie_id, "Receptie")
        eerste = maak_klaar_document(gescoopte_gebruiker, administratie_id, admin_engine, opslag, naam="a.pdf")
        _zet_afdeling(administratie_id, eerste, gescoopte_gebruiker, buitendienst)
        tweede = maak_klaar_document(gescoopte_gebruiker, administratie_id, admin_engine, opslag, naam="b.pdf")
        data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=tweede)
        assert data.afdeling_id is None  # voorstel, geen invulling
        assert data.afdeling_prefill_id == buitendienst
        assert data.afdeling_prefill_leverancier == "Energieleverancier B.V."
        # Laatste keuze wint.
        _zet_afdeling(administratie_id, tweede, gescoopte_gebruiker, receptie)
        derde = maak_klaar_document(gescoopte_gebruiker, administratie_id, admin_engine, opslag, naam="c.pdf")
        assert (
            boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=derde).afdeling_prefill_id
            == receptie
        )
        # Eigen keuze aanwezig → geen prefill meer; gearchiveerde afdeling → nooit voorgesteld.
        data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=tweede)
        assert data.afdeling_id == receptie and data.afdeling_prefill_id is None
        service.archiveer(actor_id=beheerder_id, administratie_id=administratie_id, afdeling_id=receptie)
        assert (
            boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=derde).afdeling_prefill_id
            is None
        )
        # Toggle uit → geen prefill (veld onzichtbaar).
        service.zet_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=False)
        assert (
            boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=derde).afdeling_prefill_id
            is None
        )


class TestRoutePerAfdeling:
    def test_afdelingsroute_vervangt_administratieroute_terugval_volgt_administratie(
        self,
        beheerder_id: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        afdelingen_aan: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
        admin_engine: Engine,
        opslag,  # noqa: F811
    ) -> None:
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        buitendienst = _maak_afdeling(beheerder_id, administratie_id, "Buitendienst")
        accordering_service.afdeling_route_opslaan(
            administratie_id=administratie_id,
            afdeling_id=buitendienst,
            actor_id=beheerder_id,
            actor_rol="beheerder",
            lagen=[_laag(1, accordeur_2), _laag(2, accordeur_1, "5000.00")],
        )
        # Instellingen-lijst toont de route per afdeling; de administratie-route blijft ongemoeid.
        rij = next(a for a in service.lijst(administratie_id=administratie_id) if a.id == buitendienst)
        assert [(laag.volgnummer, laag.accordeur_gebruiker_id) for laag in rij.route] == [
            (1, accordeur_2),
            (2, accordeur_1),
        ]
        _, admin_lagen, _ = accordering_service.instellingen_ophalen(administratie_id=administratie_id)
        assert [laag.accordeur_gebruiker_id for laag in admin_lagen] == [accordeur_1]

        doc_buiten = maak_klaar_document(gescoopte_gebruiker, administratie_id, admin_engine, opslag, naam="b.pdf")
        _zet_afdeling(administratie_id, doc_buiten, gescoopte_gebruiker, buitendienst)
        resultaat = accordering_service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=doc_buiten,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        assert [(s.accordeur_gebruiker_id, s.vereist) for s in resultaat.accordering.stappen] == [
            (accordeur_2, True),
            (accordeur_1, False),  # drempel € 5.000 niet gehaald
        ]

        doc_algemeen = maak_klaar_document(gescoopte_gebruiker, administratie_id, admin_engine, opslag, naam="a.pdf")
        _zet_afdeling(administratie_id, doc_algemeen, gescoopte_gebruiker, afdelingen_aan)
        resultaat = accordering_service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=doc_algemeen,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        assert [s.accordeur_gebruiker_id for s in resultaat.accordering.stappen] == [accordeur_1]

        # Wachtrij: kaart per afdeling — accordeur_2 ziet alleen Buitendienst, accordeur_1 alleen Algemeen.
        items_2 = accordering_service.wachtrij_voor_accordeur(
            actor_id=accordeur_2, administratie_ids=[administratie_id]
        )
        assert [(i.document_id, i.afdeling_naam) for i in items_2] == [(doc_buiten, "Buitendienst")]
        items_1 = accordering_service.wachtrij_voor_accordeur(
            actor_id=accordeur_1, administratie_ids=[administratie_id]
        )
        assert [(i.document_id, i.afdeling_naam) for i in items_1] == [(doc_algemeen, "Algemeen")]

    def test_zonder_afdeling_of_zonder_route_gaat_niets_naar_de_klant(
        self,
        beheerder_id: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        afdelingen_aan: uuid.UUID,
        accordeur_1: uuid.UUID,
        klaar_document: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        # Al klaar_om_te_boeken zonder afdeling (toggle ging later aan): de afdeling-poort bijt tóch.
        with pytest.raises(accordering_service.ChecksNietGroen) as exc:
            accordering_service.bied_ter_accordering_aan(
                administratie_id=administratie_id,
                document_id=klaar_document,
                actor_id=gescoopte_gebruiker,
                actor_rol="boekhouding",
            )
        assert any(r.naam == "Afdeling" and not r.ok for r in exc.value.rapport.resultaten)
        assert document_status(admin_engine, klaar_document) == "klaar_om_te_boeken"
        # Afdeling zónder eigen route = expliciete fout, nooit stil op de administratie-route.
        receptie = _maak_afdeling(beheerder_id, administratie_id, "Receptie")
        _zet_afdeling(administratie_id, klaar_document, gescoopte_gebruiker, receptie)
        with pytest.raises(accordering_service.GeenLagenIngesteld, match="Receptie"):
            accordering_service.bied_ter_accordering_aan(
                administratie_id=administratie_id,
                document_id=klaar_document,
                actor_id=gescoopte_gebruiker,
                actor_rol="boekhouding",
            )

    def test_afdeling_wijzigen_na_aanbieden_laat_ronde_vervallen_met_reden(
        self,
        beheerder_id: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        afdelingen_aan: uuid.UUID,
        accordeur_1: uuid.UUID,
        klaar_document: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        receptie = _maak_afdeling(beheerder_id, administratie_id, "Receptie")
        accordering_service.afdeling_route_opslaan(
            administratie_id=administratie_id,
            afdeling_id=receptie,
            actor_id=beheerder_id,
            actor_rol="beheerder",
            lagen=[_laag(1, accordeur_1)],
        )
        _zet_afdeling(administratie_id, klaar_document, gescoopte_gebruiker, afdelingen_aan)
        accordering_service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            actor_rol="boekhouding",
        )
        assert document_status(admin_engine, klaar_document) == "ter_accordering"
        # Zelfde afdeling opnieuw opslaan = geen wijziging → ronde blijft.
        _zet_afdeling(administratie_id, klaar_document, gescoopte_gebruiker, afdelingen_aan)
        assert document_status(admin_engine, klaar_document) == "ter_accordering"
        _zet_afdeling(administratie_id, klaar_document, gescoopte_gebruiker, receptie)
        assert document_status(admin_engine, klaar_document) == "klaar_om_te_boeken"
        with admin_engine.connect() as conn:
            statussen = list(
                conn.execute(
                    text("SELECT status FROM boekhouding.document_accordering WHERE document_id = :d"),
                    {"d": klaar_document},
                ).scalars()
            )
            reden = conn.execute(
                text(
                    "SELECT detail->>'reden' FROM boekhouding.document_gebeurtenis WHERE document_id = :d "
                    "AND detail ? 'accordering_vervallen' ORDER BY tijdstip DESC LIMIT 1"
                ),
                {"d": klaar_document},
            ).scalar_one()
        assert statussen == ["vervallen"]
        assert reden == accordering_service.AFDELING_GEWIJZIGD_REDEN

    def test_routewijziging_raakt_alleen_rondes_van_die_route(
        self,
        beheerder_id: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        afdelingen_aan: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
        admin_engine: Engine,
        opslag,  # noqa: F811
    ) -> None:
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        buitendienst = _maak_afdeling(beheerder_id, administratie_id, "Buitendienst")
        accordering_service.afdeling_route_opslaan(
            administratie_id=administratie_id,
            afdeling_id=buitendienst,
            actor_id=beheerder_id,
            actor_rol="beheerder",
            lagen=[_laag(1, accordeur_2)],
        )
        doc_a = maak_klaar_document(gescoopte_gebruiker, administratie_id, admin_engine, opslag, naam="a.pdf")
        doc_b = maak_klaar_document(gescoopte_gebruiker, administratie_id, admin_engine, opslag, naam="b.pdf")
        _zet_afdeling(administratie_id, doc_a, gescoopte_gebruiker, afdelingen_aan)
        _zet_afdeling(administratie_id, doc_b, gescoopte_gebruiker, buitendienst)
        for d in (doc_a, doc_b):
            accordering_service.bied_ter_accordering_aan(
                administratie_id=administratie_id, document_id=d, actor_id=gescoopte_gebruiker, actor_rol="boekhouding"
            )
        # Afdelingsroute Buitendienst wijzigt → alleen doc_b vervalt.
        vervallen = accordering_service.afdeling_route_opslaan(
            administratie_id=administratie_id,
            afdeling_id=buitendienst,
            actor_id=beheerder_id,
            actor_rol="beheerder",
            lagen=[_laag(1, accordeur_1)],
        )
        assert vervallen == 1
        assert document_status(admin_engine, doc_a) == "ter_accordering"
        assert document_status(admin_engine, doc_b) == "klaar_om_te_boeken"
        # Opnieuw aanbieden + administratie-route wijzigen → alleen doc_a (Algemeen volgt de administratie).
        accordering_service.bied_ter_accordering_aan(
            administratie_id=administratie_id, document_id=doc_b, actor_id=gescoopte_gebruiker, actor_rol="boekhouding"
        )
        vervallen = zet_schema(
            administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_2)]
        )
        assert vervallen == 1
        assert document_status(admin_engine, doc_a) == "klaar_om_te_boeken"
        assert document_status(admin_engine, doc_b) == "ter_accordering"
        # Toggle uit → álle rondes.
        vervallen = zet_schema(
            administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[], ingeschakeld=False
        )
        assert vervallen == 1
        assert document_status(admin_engine, doc_b) == "klaar_om_te_boeken"


class TestStaandeGoedkeuringBinnenAfdeling:
    def test_staande_regel_telt_alleen_in_de_afdeling_waar_ze_is_afgegeven(
        self,
        beheerder_id: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        afdelingen_aan: uuid.UUID,
        accordeur_1: uuid.UUID,
        admin_engine: Engine,
        opslag,  # noqa: F811
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.documenten import boeken
        from tests.documenten.fake_rlz_client import FakeBoekClient

        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        buitendienst = _maak_afdeling(beheerder_id, administratie_id, "Buitendienst")
        receptie = _maak_afdeling(beheerder_id, administratie_id, "Receptie")
        for afd in (buitendienst, receptie):
            accordering_service.afdeling_route_opslaan(
                administratie_id=administratie_id,
                afdeling_id=afd,
                actor_id=beheerder_id,
                actor_rol="beheerder",
                lagen=[_laag(1, accordeur_1)],
            )

        def aanbieden(naam: str, afdeling: uuid.UUID):
            doc = maak_klaar_document(gescoopte_gebruiker, administratie_id, admin_engine, opslag, naam=naam)
            _zet_afdeling(administratie_id, doc, gescoopte_gebruiker, afdeling)
            return doc, accordering_service.bied_ter_accordering_aan(
                administratie_id=administratie_id,
                document_id=doc,
                actor_id=gescoopte_gebruiker,
                actor_rol="boekhouding",
            )

        doc1, _ = aanbieden("1.pdf", buitendienst)
        akkoord = accordering_service.geef_akkoord(
            administratie_id=administratie_id, document_id=doc1, actor_id=accordeur_1, staande_regel_aanmaken=True
        )
        assert akkoord.staande_regel_id is not None
        regels, _ = accordering_service.staande_regels(administratie_id=administratie_id)
        assert [r.afdeling_id for r in regels] == [buitendienst]
        # Zelfde leverancier + bedrag in Buitendienst → automatisch akkoord.
        _, res_zelfde = aanbieden("2.pdf", buitendienst)
        assert res_zelfde.alles_akkoord is True
        # …maar in Receptie niet: de regel geldt alleen binnen Buitendienst.
        _, res_ander = aanbieden("3.pdf", receptie)
        assert res_ander.alles_akkoord is False
        assert res_ander.accordering.stappen[0].besluit is None
        lijst = {a.id: a.staande_goedkeuringen for a in service.lijst(administratie_id=administratie_id)}
        assert lijst[buitendienst] == 1 and lijst[receptie] == 0


class TestEndpoints:
    def test_lezen_scope_schrijven_beheerder(
        self,
        beheerder_id: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
    ) -> None:
        resp = client.put(
            f"/administraties/{administratie_id}/afdelingen-instelling",
            json={"ingeschakeld": True},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert resp.status_code == 403
        resp = client.put(
            f"/administraties/{administratie_id}/afdelingen-instelling",
            json={"ingeschakeld": True},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 200, resp.text
        resp = client.post(
            f"/administraties/{administratie_id}/afdelingen",
            json={"naam": "Buitendienst"},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 201, resp.text
        buitendienst = resp.json()["id"]
        resp = client.post(
            f"/administraties/{administratie_id}/afdelingen",
            json={"naam": "Buitendienst"},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 409
        # Route per afdeling via het endpoint, lijst voor een gescoopte controleur.
        resp = client.put(
            f"/administraties/{administratie_id}/afdelingen/{buitendienst}/accordering/route",
            json={"lagen": [{"volgnummer": 1, "accordeur_gebruiker_id": str(accordeur_1), "bedrag_drempel": None}]},
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["rondes_vervallen"] == 0
        resp = client.get(
            f"/administraties/{administratie_id}/afdelingen", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ingeschakeld"] is True
        namen = {a["naam"]: a for a in body["afdelingen"]}
        assert namen["Algemeen"]["is_terugval"] is True
        assert [laag["accordeur_gebruiker_id"] for laag in namen["Buitendienst"]["route"]] == [str(accordeur_1)]
        # Accordeur (externe rol) komt er niet in — router-brede kantoorpoort.
        resp = client.get(
            f"/administraties/{administratie_id}/afdelingen", headers=_bearer(accordeur_1, rol="klant_accordeur")
        )
        assert resp.status_code == 403
        resp = client.post(
            f"/administraties/{administratie_id}/afdelingen/{buitendienst}/archiveren",
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert resp.status_code == 204
