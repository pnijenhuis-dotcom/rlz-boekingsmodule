"""Verbruiksstand van een verplichting (③, geld — dus in CODE en ín de transactie):

- `boek_document` schrijft het bedrag van de gematchte factuur bij op `verbruikt_bedrag_excl` en
  markeert de match verrekend;
- een NIET-geboekte factuur telt niet mee (het verbruik-alleen-geboekt-besluit uit CONTRACT_B);
- tegenboeken (volledig én "tegenboeken én opnieuw boeken") draait het verbruik terug en zet
  `verrekend_op` op NULL, zodat een herboeking opnieuw verrekent;
- vervallen (⑥) stopt nieuwe matches maar laat het al verrekende verbruik staan.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.db.session import scoped_session
from app.documenten import boeken, boekvoorstel, tegenboeken
from app.documenten import service as documenten_service
from app.documenten.models import DocumentStatus
from app.documenten.storage import LokaleBestandsopslag
from app.verplichting import match as match_motor
from app.verplichting import match_pipeline
from app.verplichting import service as verplichting_service
from app.verplichting.models import Verplichting, VerplichtingMatch
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.verplichting.conftest import OFFERTEBEDRAG, VENDOR_ID

AANGIFTE_Q3_INGEDIEND = {"Status": 2, "StartDate": "2026-09-01T00:00:00", "Date": "2026-12-31T00:00:00"}


def _regel(netto: str, project_id: uuid.UUID | None) -> boekvoorstel.BoekvoorstelRegelData:
    return boekvoorstel.BoekvoorstelRegelData(
        ledger_id=uuid.uuid4(),
        taxrate_id=uuid.uuid4(),
        project_id=project_id,
        netto_bedrag=Decimal(netto),
        btw_bedrag=(Decimal(netto) * Decimal("0.21")).quantize(Decimal("0.01")),
        omschrijving="Steigerwerk Koningstraat",
    )


def maak_factuur(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    project_id: uuid.UUID | None,
    netto: str,
    referentie: str,
    bestandsnaam: str = "factuur.pdf",
) -> uuid.UUID:
    resultaat = documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=bestandsnaam,
        inhoud=f"%PDF-1.4 {referentie}".encode(),
        actor_id=actor_id,
        opslag=opslag,
    )
    netto_dec = Decimal(netto)
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=actor_id,
        vendor_id=VENDOR_ID,
        referentie=referentie,
        factuurdatum=date(2026, 9, 15),
        totaalbedrag=(netto_dec * Decimal("1.21")).quantize(Decimal("0.01")),
        regels=[_regel(netto, project_id)],
    )
    match_pipeline.bereken_match(administratie_id=administratie_id, document_id=resultaat.document_id)
    return resultaat.document_id


def verbruik(administratie_id: uuid.UUID, verplichting_id: uuid.UUID) -> Decimal:
    with scoped_session(administratie_id) as session:
        rij = session.get(Verplichting, verplichting_id)
        assert rij is not None
        return Decimal(rij.verbruikt_bedrag_excl)


def match_rij(administratie_id: uuid.UUID, document_id: uuid.UUID) -> VerplichtingMatch:
    with scoped_session(administratie_id) as session:
        rij = session.get(VerplichtingMatch, document_id)
        assert rij is not None
        session.expunge(rij)
        return rij


@pytest.fixture
def boeken_aan(beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    beheer_service.zet_boeken_ingeschakeld(
        actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
    )


@pytest.fixture
def offerte(offerte_via_accordering, administratie_id, beheerder_id) -> uuid.UUID:
    """De offerte is via de bestaande accorderingsflow goedgekeurd; DAARNA gaat de klant-
    accorderingspoort uit, zodat de facturen in dit bestand rechtstreeks geboekt kunnen worden
    (de accorderingsflow zelf staat in test_accordering_verplichting.py)."""
    from app.accordering import service as accordering_service

    accordering_service.instellingen_opslaan(
        administratie_id=administratie_id,
        actor_id=beheerder_id,
        actor_rol="beheerder",
        ingeschakeld=False,
        lagen=[],
    )
    return offerte_via_accordering


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> FakeBoekClient:
    fake = FakeBoekClient(aangiften=[AANGIFTE_Q3_INGEDIEND])
    monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
    monkeypatch.setattr(tegenboeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)
    return fake


class TestMatchRun:
    def test_factuur_op_hetzelfde_project_matcht_binnen(
        self, administratie_id, gescoopte_gebruiker, opslag, offerte, project_id
    ):
        document_id = maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            project_id=project_id,
            netto="12400.00",
            referentie="CF-2026-101",
        )
        rij = match_rij(administratie_id, document_id)
        assert rij.uitkomst == match_motor.BINNEN
        assert rij.verplichting_document_id == offerte
        assert rij.bedrag_excl == Decimal("12400.00")
        assert rij.verbruik_na == Decimal("12400.00")
        assert rij.verrekend_op is None  # nog niet geboekt

    def test_open_factuur_telt_niet_mee_in_het_verbruik(
        self, administratie_id, gescoopte_gebruiker, opslag, offerte, project_id
    ):
        """Besluit CONTRACT_B (beslispunt Peter): `verbruik_voor` telt uitsluitend het verrekende,
        geboekte verbruik — een tweede open factuur ziet de eerste dus nog niet."""
        maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            project_id=project_id,
            netto="40000.00",
            referentie="CF-2026-102",
            bestandsnaam="factuur-1.pdf",
        )
        tweede = maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            project_id=project_id,
            netto="40000.00",
            referentie="CF-2026-103",
            bestandsnaam="factuur-2.pdf",
        )
        rij = match_rij(administratie_id, tweede)
        assert rij.uitkomst == match_motor.BINNEN
        assert rij.verbruik_voor == Decimal("0.00")
        assert verbruik(administratie_id, offerte) == Decimal("0.00")


class TestVerrekenenBijBoeken:
    def test_boeken_schrijft_verbruik_bij_en_markeert_verrekend(
        self,
        administratie_id,
        gescoopte_gebruiker,
        opslag,
        offerte,
        project_id,
        boeken_aan,
        fake_client,
        admin_engine: Engine,
    ):
        document_id = maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            project_id=project_id,
            netto="12400.00",
            referentie="CF-2026-201",
        )
        boeken.boek_document(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
        )
        assert verbruik(administratie_id, offerte) == Decimal("12400.00")
        assert match_rij(administratie_id, document_id).verrekend_op is not None
        # Audit-spoor oud→nieuw (kernprincipe 4).
        with admin_engine.connect() as conn:
            aantal = conn.execute(
                text(
                    "SELECT count(*) FROM platform.audit_event "
                    "WHERE actie = 'verplichting_verbruik_bijgewerkt' AND record_id = :id"
                ),
                {"id": offerte},
            ).scalar_one()
        assert aantal == 1

    def test_tweede_geboekte_factuur_gaat_cumulatief_buiten_de_offerte(
        self,
        administratie_id,
        gescoopte_gebruiker,
        opslag,
        offerte,
        project_id,
        boeken_aan,
        fake_client,
    ):
        eerste = maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            project_id=project_id,
            netto="40000.00",
            referentie="CF-2026-301",
            bestandsnaam="factuur-a.pdf",
        )
        boeken.boek_document(
            administratie_id=administratie_id, document_id=eerste, actor_id=gescoopte_gebruiker
        )
        tweede = maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            project_id=project_id,
            netto="11900.00",
            referentie="CF-2026-302",
            bestandsnaam="factuur-b.pdf",
        )
        rij = match_rij(administratie_id, tweede)
        assert rij.uitkomst == match_motor.BUITEN
        assert rij.verbruik_voor == Decimal("40000.00")
        assert rij.verbruik_na == Decimal("51900.00")
        assert rij.overschrijding_excl == Decimal("3400.00")
        assert match_motor.MEERWERK_HANDELING in rij.details["melding"]

    def test_herberekening_na_boeken_houdt_de_stand_stabiel(
        self,
        administratie_id,
        gescoopte_gebruiker,
        opslag,
        offerte,
        project_id,
        boeken_aan,
        fake_client,
    ):
        document_id = maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            project_id=project_id,
            netto="12400.00",
            referentie="CF-2026-401",
        )
        boeken.boek_document(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
        )
        match_pipeline.bereken_match(administratie_id=administratie_id, document_id=document_id)
        rij = match_rij(administratie_id, document_id)
        assert rij.uitkomst == match_motor.BINNEN
        assert rij.verbruik_voor == Decimal("0.00")
        assert rij.verbruik_na == Decimal("12400.00")
        assert verbruik(administratie_id, offerte) == Decimal("12400.00")


class TestTerugdraaienBijTegenboeken:
    def test_volledig_tegenboeken_draait_het_verbruik_terug(
        self,
        administratie_id,
        gescoopte_gebruiker,
        opslag,
        offerte,
        project_id,
        boeken_aan,
        fake_client,
    ):
        document_id = maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            project_id=project_id,
            netto="12400.00",
            referentie="CF-2026-501",
        )
        boeken.boek_document(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
        )
        assert verbruik(administratie_id, offerte) == Decimal("12400.00")
        tegenboeken.voer_tegenboeking_uit(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            soort="volledig",
            reden="factuur hoort niet bij deze offerte",
        )
        assert verbruik(administratie_id, offerte) == Decimal("0.00")
        assert match_rij(administratie_id, document_id).verrekend_op is None

    def test_tegenboeken_en_opnieuw_boeken_verrekent_opnieuw(
        self,
        administratie_id,
        gescoopte_gebruiker,
        opslag,
        offerte,
        project_id,
        boeken_aan,
        fake_client,
        admin_engine: Engine,
    ):
        document_id = maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            project_id=project_id,
            netto="12400.00",
            referentie="CF-2026-601",
        )
        boeken.boek_document(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
        )
        tegenboeken.voer_tegenboeking_uit(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            soort="vervang",
            reden="verkeerd bedrag geboekt, opnieuw doen",
        )
        assert verbruik(administratie_id, offerte) == Decimal("0.00")
        with admin_engine.connect() as conn:
            status = conn.execute(
                text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}
            ).scalar_one()
        assert status == DocumentStatus.TE_CONTROLEREN.value
        # Herboeking verrekent opnieuw.
        boeken.boek_document(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
        )
        assert verbruik(administratie_id, offerte) == Decimal("12400.00")

    def test_verbruik_wordt_nooit_negatief(
        self, administratie_id, gescoopte_gebruiker, opslag, offerte, project_id
    ):
        """Clamp-vangnet: handmatig verlaagd verbruik + terugdraaien mag nooit onder nul zakken."""
        document_id = maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            project_id=project_id,
            netto="12400.00",
            referentie="CF-2026-701",
        )
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            match_pipeline.verreken_in_sessie(
                session,
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
            )
        assert verbruik(administratie_id, offerte) == Decimal("12400.00")
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            verplichting = session.get(Verplichting, offerte)
            verplichting.verbruikt_bedrag_excl = Decimal("100.00")
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            match_pipeline.draai_verbruik_terug_in_sessie(
                session,
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
                reden="test-clamp",
            )
        assert verbruik(administratie_id, offerte) == Decimal("0.00")


class TestVervallen:
    def test_vervallen_stopt_nieuwe_matches_maar_laat_verrekende_ongemoeid(
        self,
        administratie_id,
        gescoopte_gebruiker,
        opslag,
        offerte,
        project_id,
        boeken_aan,
        fake_client,
    ):
        geboekt = maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            project_id=project_id,
            netto="12400.00",
            referentie="CF-2026-801",
            bestandsnaam="factuur-geboekt.pdf",
        )
        boeken.boek_document(
            administratie_id=administratie_id, document_id=geboekt, actor_id=gescoopte_gebruiker
        )
        open_factuur = maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            project_id=project_id,
            netto="5000.00",
            referentie="CF-2026-802",
            bestandsnaam="factuur-open.pdf",
        )
        assert match_rij(administratie_id, open_factuur).uitkomst == match_motor.BINNEN

        verplichting_service.laat_vervallen(
            administratie_id=administratie_id,
            document_id=offerte,
            actor_id=gescoopte_gebruiker,
            reden="opdracht ingetrokken",
        )
        # ⑥: nieuwe matches stoppen …
        na = match_rij(administratie_id, open_factuur)
        assert na.uitkomst == match_motor.GEEN_VERPLICHTING
        assert na.verplichting_document_id is None
        # … de al verrekende factuur blijft ongemoeid (verbruik + koppeling blijven staan).
        assert verbruik(administratie_id, offerte) == Decimal("12400.00")
        geboekte_match = match_rij(administratie_id, geboekt)
        assert geboekte_match.verrekend_op is not None
        assert geboekte_match.verplichting_document_id == offerte


class TestTellerEnChip:
    def test_buiten_offerte_teller_telt_open_documenten(
        self, administratie_id, gescoopte_gebruiker, opslag, offerte, project_id
    ):
        # Geen match (ander project) → telt mee als "buiten offerte".
        maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            project_id=uuid.uuid4(),
            netto="1000.00",
            referentie="CF-2026-901",
            bestandsnaam="ander-project.pdf",
        )
        klanten = documenten_service.werkvoorraad_overzicht(
            administratie_ids_met_naam=[(administratie_id, "Test BV")]
        )
        assert klanten[0].buiten_offerte == 1

    def test_chipdata_in_de_documentenlijst(
        self, administratie_id, gescoopte_gebruiker, opslag, offerte, project_id
    ):
        document_id = maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            project_id=project_id,
            netto="12400.00",
            referentie="CF-2026-902",
        )
        items = documenten_service.lijst_documenten(administratie_id=administratie_id)
        rij = next(i for i in items if i.document.id == document_id)
        assert rij.verplichting_match is not None
        assert rij.verplichting_match.uitkomst == match_motor.BINNEN
        assert rij.verplichting_match.offertenummer == "26140-OFF-01"


class TestOfferteMatchVoorDeAccordeur:
    def test_alleen_binnen_of_buiten_is_zichtbaar(
        self, administratie_id, gescoopte_gebruiker, opslag, offerte, project_id
    ):
        binnen = maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            project_id=project_id,
            netto="12400.00",
            referentie="CF-2026-903",
            bestandsnaam="binnen.pdf",
        )
        data = verplichting_service.offerte_match_kort(
            administratie_id=administratie_id, document_id=binnen
        )
        assert data is not None
        assert data.uitkomst == match_motor.BINNEN
        assert data.verplichting is not None
        assert data.verplichting.offertenummer == "26140-OFF-01"
        assert data.verplichting.totaal_excl == OFFERTEBEDRAG
        assert data.percentage_na == 26

        geen = maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            project_id=uuid.uuid4(),
            netto="500.00",
            referentie="CF-2026-904",
            bestandsnaam="geen.pdf",
        )
        assert (
            verplichting_service.offerte_match_kort(administratie_id=administratie_id, document_id=geen)
            is None
        )


class TestKoppelen:
    def test_handmatige_koppeling_wint_bij_meerdere_kandidaten(
        self, admin_engine: Engine, administratie_id, gescoopte_gebruiker, opslag, offerte, project_id, beheerder_id
    ):
        """"Koppel offerte…" (②): met twee lopende offertes op hetzelfde project kiest de mens, en
        die keuze blijft daarna staan."""
        from tests.verplichting.conftest import (
            laat_accorderen,
            maak_accordeur,
            sla_offerte_op,
            upload_verplichting,
        )

        accordeur = maak_accordeur(admin_engine, beheerder_id, administratie_id, "Tweede Accordeur")
        from app.accordering import service as accordering_service

        accordering_service.instellingen_opslaan(
            administratie_id=administratie_id,
            actor_id=beheerder_id,
            actor_rol="beheerder",
            ingeschakeld=True,
            lagen=[
                accordering_service.LaagInput(volgnummer=1, accordeur_gebruiker_id=accordeur, bedrag_drempel=None)
            ],
        )
        tweede = upload_verplichting(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag, bestandsnaam="offerte-2.pdf"
        )
        sla_offerte_op(
            administratie_id=administratie_id,
            document_id=tweede,
            actor_id=gescoopte_gebruiker,
            project_id=project_id,
            offertenummer="26140-OFF-09",
            totaalbedrag_excl=Decimal("10000.00"),
        )
        laat_accorderen(
            administratie_id=administratie_id,
            document_id=tweede,
            kantoor_id=gescoopte_gebruiker,
            accordeur_id=accordeur,
        )
        accordering_service.instellingen_opslaan(
            administratie_id=administratie_id,
            actor_id=beheerder_id,
            actor_rol="beheerder",
            ingeschakeld=False,
            lagen=[],
        )

        document_id = maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            project_id=project_id,
            netto="3000.00",
            referentie="CF-2026-950",
        )
        assert match_rij(administratie_id, document_id).uitkomst == match_motor.MEERDERE_KANDIDATEN

        data = verplichting_service.koppel_verplichting(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            verplichting_document_id=tweede,
        )
        assert data.uitkomst == match_motor.BINNEN
        assert data.handmatig_gekoppeld is True
        assert data.verplichting is not None and data.verplichting.offertenummer == "26140-OFF-09"
        # Herberekening houdt de handmatige keuze vast.
        match_pipeline.bereken_match(administratie_id=administratie_id, document_id=document_id)
        assert match_rij(administratie_id, document_id).verplichting_document_id == tweede

    def test_koppelen_aan_een_vervallen_verplichting_is_409(
        self, administratie_id, gescoopte_gebruiker, opslag, offerte, project_id
    ):
        verplichting_service.laat_vervallen(
            administratie_id=administratie_id,
            document_id=offerte,
            actor_id=gescoopte_gebruiker,
            reden="ingetrokken",
        )
        document_id = maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            project_id=project_id,
            netto="1000.00",
            referentie="CF-2026-951",
        )
        with pytest.raises(verplichting_service.OngeldigeVerplichtingActie):
            verplichting_service.koppel_verplichting(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
                verplichting_document_id=offerte,
            )

    def test_koppelen_na_boeken_is_409(
        self, administratie_id, gescoopte_gebruiker, opslag, offerte, project_id, boeken_aan, fake_client
    ):
        """Een verrekende match is bevroren — corrigeren gaat via tegenboeken."""
        document_id = maak_factuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            project_id=project_id,
            netto="1000.00",
            referentie="CF-2026-952",
        )
        boeken.boek_document(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
        )
        with pytest.raises(verplichting_service.OngeldigeVerplichtingActie):
            verplichting_service.koppel_verplichting(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
                verplichting_document_id=None,
            )
