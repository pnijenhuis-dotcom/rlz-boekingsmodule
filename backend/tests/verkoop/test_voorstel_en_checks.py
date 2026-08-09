"""Verkoopvoorstel-prefill (deterministisch uit de UBL) + de harde verkoop-checks, elk met hun
weiger-reden — geldlogica eerst (werkwijze: tests verplicht op mapping/totalen/idempotentie)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.db.session import scoped_session
from app.documenten.storage import LokaleBestandsopslag
from app.verkoop import voorstel as voorstel_service
from app.verkoop.models import VerkoopBoeking
from tests.verkoop.conftest import (
    OMZET_LEDGER_ID,
    TAXRATE_21_ID,
    FakeVerkoopClient,
    bouw_vastly_creditnote_ubl,
    bouw_vastly_verkoop_ubl,
    upload_verkoopfactuur,
)


def _check(rapport, naam: str):
    return next(r for r in rapport.resultaten if r.naam == naam)


class TestPrefillUitUbl:
    def test_prefill_resolvet_gb_code_en_btw(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
    ) -> None:
        document_id = upload_verkoopfactuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            inhoud=bouw_vastly_verkoop_ubl(),
        )
        data = voorstel_service.haal_verkoop_voorstel_op(
            administratie_id=administratie_id, document_id=document_id
        )
        assert data.opgeslagen is False
        assert data.debiteur_naam == "J. van den Berg"
        assert data.factuurnummer == "VF-2026-0042"
        assert data.totaalbedrag_incl == Decimal("1210.00")
        assert data.is_creditnota is False
        [regel] = data.regels
        assert regel.gb_code == "8000"
        assert regel.ledger_id == OMZET_LEDGER_ID
        assert regel.gb_code_status == "bekend"
        assert regel.taxrate_id == TAXRATE_21_ID
        assert regel.netto_bedrag == Decimal("1000.00")
        assert regel.btw_bedrag == Decimal("210.00")

    def test_onbekende_code_en_totaalrekening_zijn_onbekend(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
    ) -> None:
        document_id = upload_verkoopfactuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            inhoud=bouw_vastly_verkoop_ubl(
                regels=[
                    {"naam": "A", "netto": "100.00", "pct": "21.00", "categorie": "S", "gb_code": "9999"},
                    {"naam": "B", "netto": "100.00", "pct": "21.00", "categorie": "S", "gb_code": "0800"},
                    {"naam": "C", "netto": "100.00", "pct": "21.00", "categorie": "S", "gb_code": None},
                ]
            ),
        )
        data = voorstel_service.haal_verkoop_voorstel_op(
            administratie_id=administratie_id, document_id=document_id
        )
        statussen = [r.gb_code_status for r in data.regels]
        assert statussen == ["onbekend", "onbekend", "ontbreekt"]
        assert all(r.ledger_id is None for r in data.regels)

    def test_creditnota_prefill_draagt_herleiding(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
    ) -> None:
        document_id = upload_verkoopfactuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            inhoud=bouw_vastly_creditnote_ubl(),
        )
        data = voorstel_service.haal_verkoop_voorstel_op(
            administratie_id=administratie_id, document_id=document_id
        )
        assert data.is_creditnota is True
        assert data.gecrediteerd_factuurnummer == "VF-2026-0042"

    def test_opslaan_bewaart_keuzes_en_creditvlag_blijft_brongegeven(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
    ) -> None:
        document_id = upload_verkoopfactuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            inhoud=bouw_vastly_verkoop_ubl(),
        )
        prefill = voorstel_service.haal_verkoop_voorstel_op(
            administratie_id=administratie_id, document_id=document_id
        )
        opgeslagen = voorstel_service.sla_verkoop_voorstel_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            debiteur_naam="J. van den Berg",
            factuurnummer=prefill.factuurnummer,
            factuurdatum=prefill.factuurdatum,
            totaalbedrag_incl=prefill.totaalbedrag_incl,
            regels=[
                voorstel_service.VerkoopRegelInput(
                    omschrijving=r.omschrijving,
                    netto_bedrag=r.netto_bedrag,
                    btw_bedrag=r.btw_bedrag,
                    gb_code=r.gb_code,
                    ledger_id=r.ledger_id,
                    taxrate_id=r.taxrate_id,
                )
                for r in prefill.regels
            ],
        )
        assert opgeslagen.opgeslagen is True
        assert opgeslagen.is_creditnota is False  # brongegeven uit de UBL, niet muteerbaar
        assert opgeslagen.regels[0].herkomst == "opgeslagen"
        assert opgeslagen.regels[0].ledger_id == OMZET_LEDGER_ID


def _compleet_opslaan(*, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    prefill = voorstel_service.haal_verkoop_voorstel_op(
        administratie_id=administratie_id, document_id=document_id
    )
    voorstel_service.sla_verkoop_voorstel_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        debiteur_naam=prefill.debiteur_naam,
        factuurnummer=prefill.factuurnummer,
        factuurdatum=prefill.factuurdatum,
        totaalbedrag_incl=prefill.totaalbedrag_incl,
        regels=[
            voorstel_service.VerkoopRegelInput(
                omschrijving=r.omschrijving,
                netto_bedrag=r.netto_bedrag,
                btw_bedrag=r.btw_bedrag,
                gb_code=r.gb_code,
                ledger_id=r.ledger_id or OMZET_LEDGER_ID,
                taxrate_id=r.taxrate_id or TAXRATE_21_ID,
            )
            for r in prefill.regels
        ],
    )


class TestHardeChecks:
    @pytest.fixture
    def verkoop_document(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
    ) -> uuid.UUID:
        return upload_verkoopfactuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            inhoud=bouw_vastly_verkoop_ubl(),
        )

    def test_happy_path_alle_checks_groen(
        self, administratie_id: uuid.UUID, verkoop_document: uuid.UUID
    ) -> None:
        rapport = voorstel_service.voer_verkoop_checks_uit(
            administratie_id=administratie_id, document_id=verkoop_document, client=FakeVerkoopClient()
        )
        assert rapport.geblokkeerd is False, [(r.naam, r.melding) for r in rapport.resultaten if not r.ok]

    def test_onbekende_gb_code_blokkeert(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
    ) -> None:
        document_id = upload_verkoopfactuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            inhoud=bouw_vastly_verkoop_ubl(
                regels=[{"naam": "Huur", "netto": "1000.00", "pct": "21.00", "categorie": "S", "gb_code": "9999"}]
            ),
        )
        rapport = voorstel_service.voer_verkoop_checks_uit(
            administratie_id=administratie_id, document_id=document_id, client=FakeVerkoopClient()
        )
        assert rapport.geblokkeerd
        assert _check(rapport, "gb_code_bekend").ok is False
        assert "9999" in _check(rapport, "gb_code_bekend").melding

    def test_lokaal_duplicaat_blokkeert(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        verkoop_document: uuid.UUID,
    ) -> None:
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            session.add(
                VerkoopBoeking(
                    administratie_id=administratie_id,
                    document_id=verkoop_document,  # ander document simuleren kan niet zonder FK — zie hieronder
                    factuurnummer="VF-2026-0042",
                    is_creditnota=False,
                    totaalbedrag_incl=Decimal("1210.00"),
                    debiteur_customer_id=uuid.uuid4(),
                    debiteur_naam="J. van den Berg",
                    verkoop_rlz_id=uuid.uuid4(),
                    geboekt_door=gescoopte_gebruiker,
                )
            )
        # De duplicaatquery sluit het eigen document uit — een tweede document met hetzelfde
        # nummer moet blokkeren. Upload dus een tweede document met hetzelfde factuurnummer.
        rapport = voorstel_service.voer_verkoop_checks_uit(
            administratie_id=administratie_id, document_id=verkoop_document, client=FakeVerkoopClient()
        )
        assert _check(rapport, "duplicaat").ok is True  # eigen registratie telt niet als duplicaat

    def test_duplicaat_ander_document_blokkeert(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        verkoop_document: uuid.UUID,
    ) -> None:
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            session.add(
                VerkoopBoeking(
                    administratie_id=administratie_id,
                    document_id=verkoop_document,
                    factuurnummer="VF-2026-0042",
                    is_creditnota=False,
                    totaalbedrag_incl=Decimal("1210.00"),
                    debiteur_customer_id=uuid.uuid4(),
                    debiteur_naam="J. van den Berg",
                    verkoop_rlz_id=uuid.uuid4(),
                    geboekt_door=gescoopte_gebruiker,
                )
            )
        tweede = upload_verkoopfactuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            inhoud=bouw_vastly_verkoop_ubl(huurder="Andere Huurder"),
            bestandsnaam="vastly-verkoop-2.xml",
        )
        rapport = voorstel_service.voer_verkoop_checks_uit(
            administratie_id=administratie_id, document_id=tweede, client=FakeVerkoopClient()
        )
        assert _check(rapport, "duplicaat").ok is False

    def test_rlz_duplicaat_hit_blokkeert(
        self, administratie_id: uuid.UUID, verkoop_document: uuid.UUID
    ) -> None:
        client = FakeVerkoopClient(
            receipt_duplicaten=[{"id": str(uuid.uuid4()), "Description": "VASTLY-VERKOOP VF-2026-0042 · Huur"}]
        )
        rapport = voorstel_service.voer_verkoop_checks_uit(
            administratie_id=administratie_id, document_id=verkoop_document, client=client
        )
        assert _check(rapport, "duplicaat").ok is False

    def test_rlz_check_faalt_fail_closed(
        self, administratie_id: uuid.UUID, verkoop_document: uuid.UUID
    ) -> None:
        client = FakeVerkoopClient(faal_op="receipts_duplicaatcheck")
        rapport = voorstel_service.voer_verkoop_checks_uit(
            administratie_id=administratie_id, document_id=verkoop_document, client=client
        )
        resultaat = _check(rapport, "duplicaat")
        assert resultaat.ok is False
        assert "fail-closed" in resultaat.melding

    def test_creditnota_zonder_geboekt_origineel_blokkeert(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
    ) -> None:
        document_id = upload_verkoopfactuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            inhoud=bouw_vastly_creditnote_ubl(),
        )
        rapport = voorstel_service.voer_verkoop_checks_uit(
            administratie_id=administratie_id, document_id=document_id, client=FakeVerkoopClient()
        )
        resultaat = _check(rapport, "creditnota_herleiding")
        assert resultaat.ok is False
        assert "VF-2026-0042" in resultaat.melding

    def test_regelsom_die_niet_sluit_blokkeert(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        verkoop_document: uuid.UUID,
    ) -> None:
        prefill = voorstel_service.haal_verkoop_voorstel_op(
            administratie_id=administratie_id, document_id=verkoop_document
        )
        voorstel_service.sla_verkoop_voorstel_op(
            administratie_id=administratie_id,
            document_id=verkoop_document,
            actor_id=gescoopte_gebruiker,
            debiteur_naam=prefill.debiteur_naam,
            factuurnummer=prefill.factuurnummer,
            factuurdatum=prefill.factuurdatum,
            totaalbedrag_incl=Decimal("9999.99"),
            regels=[
                voorstel_service.VerkoopRegelInput(
                    omschrijving=r.omschrijving,
                    netto_bedrag=r.netto_bedrag,
                    btw_bedrag=r.btw_bedrag,
                    gb_code=r.gb_code,
                    ledger_id=r.ledger_id,
                    taxrate_id=r.taxrate_id,
                )
                for r in prefill.regels
            ],
        )
        rapport = voorstel_service.voer_verkoop_checks_uit(
            administratie_id=administratie_id, document_id=verkoop_document, client=FakeVerkoopClient()
        )
        assert _check(rapport, "regelsom").ok is False


class TestAutovraag:
    def test_onbekende_code_stelt_automatische_vraag(
        self,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
    ) -> None:
        from sqlalchemy import select

        from app.db.models import Administratie
        from app.db.systeem_actor import SYSTEEM_ACTOR_ID
        from app.documenten.models import Vraag
        from app.verkoop import autovraag

        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            administratie = session.get(Administratie, administratie_id)
            administratie.eigenaar_gebruiker_id = beheerder_id
        document_id = upload_verkoopfactuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            inhoud=bouw_vastly_verkoop_ubl(
                regels=[{"naam": "Huur", "netto": "100.00", "pct": "21.00", "categorie": "S", "gb_code": "9999"}]
            ),
        )
        # De upload zelf stelt de vraag al via _na_extractie_hook (post-commit) — precies het
        # bedoelde gedrag; een tweede aanroep is een no-op (ErIsAlEenOpenVraag).
        with scoped_session(administratie_id) as session:
            vraag = session.scalars(select(Vraag).where(Vraag.document_id == document_id)).one()
            assert vraag.gesteld_door == SYSTEEM_ACTOR_ID
            assert "9999" in vraag.vraag_tekst
        assert (
            autovraag.stel_gb_code_vraag_indien_nodig(
                administratie_id=administratie_id, document_id=document_id
            )
            is False
        )

    def test_bekende_codes_geen_vraag(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        rekeningschema: None,
    ) -> None:
        from app.verkoop import autovraag

        document_id = upload_verkoopfactuur(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            inhoud=bouw_vastly_verkoop_ubl(),
        )
        assert (
            autovraag.stel_gb_code_vraag_indien_nodig(
                administratie_id=administratie_id, document_id=document_id
            )
            is False
        )
