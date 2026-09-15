"""Peter 15-09 (casus Olieman 32948 / Bouwadvies Oost Nederland): de offerte wachtte nog op één accordeur en de
factuur werd al geboekt. (1) Zolang de offerte niet goedgekeurd is meldt de match zichtbaar "gevonden maar niet
toetsbaar: nog niet goedgekeurd (wacht op accordering)" mét verwijzing — geen stil `geen_verplichting`. (2) Bij het
GOEDKEUREN worden de
open én al geboekte facturen van dezelfde leverancier alsnog gematcht; een geboekte factuur wordt achteraf verrekend
(verbruik bijgeschreven, tijdlijnregel "achteraf gekoppeld aan offerte …", audit). Termijn: "1e termijn 20.000 van
85.000"."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.accordering import service as accordering_service
from app.beheer import service as beheer_service
from app.db.session import scoped_session
from app.documenten import boeken, tegenboeken
from app.documenten.models import Document, DocumentGebeurtenis, DocumentStatus
from app.verplichting import match as match_motor
from app.verplichting import match_pipeline
from app.verplichting import service as verplichting_service
from app.verplichting.models import Verplichting
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.verplichting.conftest import (
    laat_accorderen,
    maak_accordeur,
    sla_offerte_op,
    upload_verplichting,
)
from tests.verplichting.test_verbruik import maak_factuur, match_rij, verbruik

OFFERTE_85K = Decimal("85000.00")


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> FakeBoekClient:
    fake = FakeBoekClient(aangiften=[])
    monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
    monkeypatch.setattr(tegenboeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
    return fake


def _accordering(
    administratie_id: uuid.UUID, beheerder_id: uuid.UUID, *, aan: bool, accordeur: uuid.UUID | None = None
):
    accordering_service.instellingen_opslaan(
        administratie_id=administratie_id,
        actor_id=beheerder_id,
        actor_rol="beheerder",
        ingeschakeld=aan,
        lagen=(
            [accordering_service.LaagInput(volgnummer=1, accordeur_gebruiker_id=accordeur, bedrag_drempel=None)]
            if aan and accordeur
            else []
        ),
    )


class TestOliemanTermijnfactuur:
    def test_wachtende_offerte_is_zichtbaar_en_na_goedkeuring_achteraf_verrekend(
        self, administratie_id, beheerder_id, gescoopte_gebruiker, opslag, vendors, admin_engine: Engine, fake_client
    ) -> None:
        beheer_service.zet_boeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        _accordering(administratie_id, beheerder_id, aan=False)

        # De offerte staat er al, maar wacht nog op de accordeur (ter accordering).
        accordeur = maak_accordeur(admin_engine, beheerder_id, administratie_id, "J. de Groot")
        offerte = upload_verplichting(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            bestandsnaam="offerte-uitweg-30.pdf",
        )
        sla_offerte_op(
            administratie_id=administratie_id,
            document_id=offerte,
            actor_id=gescoopte_gebruiker,
            project_id=None,
            offertenummer="OFF-2026-085",
            totaalbedrag_excl=OFFERTE_85K,
            datum=date(2026, 8, 20),
            geldig_tot=date(2026, 12, 31),
            omschrijving="Werk Uitweg 30 Woerdense Verlaat",
        )
        # De ronde loopt (ter accordering) — accordering uit zetten zou de ronde herberekenen, dus de status wordt hier
        # gezet zoals `bied_ter_accordering_aan` dat doet; de accorderingsflow zelf staat in
        # test_accordering_verplichting.
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            session.get(Document, offerte).status = DocumentStatus.TER_ACCORDERING

        # 1e termijnfactuur zonder project (Bouwadvies heeft geen projecten).
        factuur = maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            project_id=None,
            netto="20000.00",
            referentie="32948",
            bestandsnaam="factuur-32948.pdf",
        )
        rij = match_rij(administratie_id, factuur)
        assert rij.uitkomst == match_motor.NIET_TOETSBAAR and rij.verplichting_document_id == offerte
        assert rij.details["wachtende_reden"] == "nog niet goedgekeurd (wacht op accordering)"
        data = verplichting_service.haal_match_op(administratie_id=administratie_id, document_id=factuur)
        assert data.uitkomst == match_motor.NIET_TOETSBAAR and data.verplichting is not None
        assert (
            data.verplichting.offertenummer == "OFF-2026-085"
            and data.niet_toetsbaar_reden == rij.details["wachtende_reden"]
        )

        # De factuur wordt gewoon geboekt (nooit blokkerend) — nog niets verrekend.
        boeken.boek_document(administratie_id=administratie_id, document_id=factuur, actor_id=gescoopte_gebruiker)
        assert match_rij(administratie_id, factuur).verrekend_op is None
        assert verbruik(administratie_id, offerte) == Decimal("0.00")

        # Dán keurt de accordeur de offerte goed (zoals accordering/service 'm vastlegt + de bestaande post-commit-hook)
        # → herberekening + achteraf verrekenen.
        with scoped_session(administratie_id, actor_id=accordeur) as session:
            session.get(Document, offerte).status = DocumentStatus.GEACCORDEERD
            verplichting_service.leg_goedkeuring_vast_in_sessie(
                session, administratie_id=administratie_id, document_id=offerte, actor_id=accordeur
            )
        match_pipeline.herbereken_na_verplichting_wijziging(
            administratie_id=administratie_id, verplichting_document_id=offerte
        )
        rij = match_rij(administratie_id, factuur)
        assert rij.uitkomst == match_motor.BINNEN and rij.verplichting_document_id == offerte
        assert rij.verrekend_op is not None and rij.verbruik_na == Decimal("20000.00")
        assert rij.details["termijn"] == 1 and "(1e termijn, € 20.000,00)" in rij.details["melding"]
        assert verbruik(administratie_id, offerte) == Decimal("20000.00")
        data = verplichting_service.haal_match_op(administratie_id=administratie_id, document_id=factuur)
        assert data.termijn == 1 and data.percentage_na == 24 and data.niet_toetsbaar_reden is None
        with scoped_session(administratie_id) as session:
            regels = [
                g.detail.get("reden")
                for g in session.query(DocumentGebeurtenis).filter(DocumentGebeurtenis.document_id == factuur)
                if g.detail
            ]
        assert any(r and r.startswith("achteraf gekoppeld aan offerte OFF-2026-085 (1e termijn)") for r in regels)
        with admin_engine.connect() as conn:
            aantal = conn.execute(
                text(
                    "SELECT count(*) FROM platform.audit_event "
                    "WHERE actie = 'verplichting_achteraf_gekoppeld' AND record_id = :id"
                ),
                {"id": factuur},
            ).scalar_one()
        assert aantal == 1

        # Tweede termijn ná de goedkeuring: gewoon binnen, 2e termijn, cumulatief.
        tweede = maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            project_id=None,
            netto="30000.00",
            referentie="32971",
            bestandsnaam="factuur-32971.pdf",
        )
        rij2 = match_rij(administratie_id, tweede)
        assert rij2.uitkomst == match_motor.BINNEN and rij2.details["termijn"] == 2
        assert rij2.verbruik_voor == Decimal("20000.00") and rij2.verbruik_na == Decimal("50000.00")

    def test_herhaalde_herberekening_verrekent_niet_dubbel(
        self, administratie_id, beheerder_id, gescoopte_gebruiker, opslag, vendors, admin_engine: Engine, fake_client
    ) -> None:
        beheer_service.zet_boeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        _accordering(administratie_id, beheerder_id, aan=False)
        factuur = maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            project_id=None,
            netto="20000.00",
            referentie="32948",
            bestandsnaam="factuur-32948.pdf",
        )
        boeken.boek_document(administratie_id=administratie_id, document_id=factuur, actor_id=gescoopte_gebruiker)
        accordeur = maak_accordeur(admin_engine, beheerder_id, administratie_id, "J. de Groot")
        _accordering(administratie_id, beheerder_id, aan=True, accordeur=accordeur)
        offerte = upload_verplichting(administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag)
        sla_offerte_op(
            administratie_id=administratie_id,
            document_id=offerte,
            actor_id=gescoopte_gebruiker,
            project_id=None,
            offertenummer="OFF-2026-085",
            totaalbedrag_excl=OFFERTE_85K,
        )
        laat_accorderen(
            administratie_id=administratie_id,
            document_id=offerte,
            kantoor_id=gescoopte_gebruiker,
            accordeur_id=accordeur,
        )
        assert verbruik(administratie_id, offerte) == Decimal("20000.00")
        # Nog een keer herberekenen (bv. ná een tweede wijziging): bevroren stand, geen tweede verrekening.
        match_pipeline.herbereken_na_verplichting_wijziging(
            administratie_id=administratie_id, verplichting_document_id=offerte
        )
        assert verbruik(administratie_id, offerte) == Decimal("20000.00")
        with admin_engine.connect() as conn:
            aantal = conn.execute(
                text(
                    "SELECT count(*) FROM platform.audit_event "
                    "WHERE actie = 'verplichting_achteraf_gekoppeld' AND record_id = :id"
                ),
                {"id": factuur},
            ).scalar_one()
        assert aantal == 1
        with scoped_session(administratie_id) as session:
            assert session.get(Verplichting, offerte).verbruikt_bedrag_excl == Decimal("20000.00")
        assert match_rij(administratie_id, factuur).document_id == factuur and DocumentStatus.GEBOEKT
