"""Casus (y) — bankmatch op KLANTREFERENTIE, Clean Care Arnhem B.V. 15-09 (Peter 15-09).

Productie 14/15-09: drie bijschrijvingen (Department of Cosmetics 1.261,43, VA Climate 91,05, Secure2Go 1.594,18) wezen
in module én RLZ naar dezelfde verkoopfactuur, maar de module zei ORANJE "naam + bedrag, nummer niet gevonden —
bevestigen": de bank noemt de klantreferentie van het document (Document.Reference = InvoiceNumber 2025689), niet RLZ's
volgnummer van de open post (PaymentItem.Reference "706"). Plus de datumfout: de kaart toonde PaymentItem.BookDate
(= vervaldatum 12-9), RLZ de échte factuurdatum Document.Date (29-8). Deze test draait de motor via de SERVICELAAG op de
fixture-set `fixtures/y_bank_klantreferentie_15-09/` (cache-rijen zoals de sync ze vult, brondata mét
Document.Reference/Date) — geen RLZ-call, geen AI."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.bank import voorstellen
from app.bank.matchmotor import VoorstelSoort
from tests.bank.conftest import maak_bank_mutatie, maak_payment_item
from tests.keten import casussen
from tests.keten.casussen import Casus

CASUS = Casus(casussen.Y_BANK_KLANTREFERENTIE)
REKENING_ID = uuid.UUID("bbbbbbbb-0000-4000-8000-000000000487")


@pytest.fixture
def clean_care(admin_engine, administratie_id: uuid.UUID) -> dict:  # noqa: ANN001
    mutaties = {
        m["sleutel"]: maak_bank_mutatie(
            admin_engine,
            administratie_id=administratie_id,
            mutatie_id=uuid.UUID(m["id"]),
            payment_account_id=REKENING_ID,
            bedrag=m["bedrag"],
            tegenpartij_naam=m["tegenpartij_naam"],
            omschrijving=m["omschrijving"],
            tegenrekening_iban=m["tegenrekening_iban"],
            boekdatum=m["boekdatum"],
        )
        for m in CASUS.bank_mutaties()
    }
    posten = {
        p["sleutel"]: maak_payment_item(
            admin_engine,
            administratie_id=administratie_id,
            item_id=uuid.UUID(p["id"]),
            bedrag=p["bedrag"],
            referentie=p["referentie"],
            documentsoort=p["documentsoort"],
            entity_naam=p["entity_naam"],
            entity_guid=uuid.UUID(p["entity_guid"]),
            boekdatum=p["boekdatum"],
            rlz_document_id=uuid.UUID(p["rlz_document_id"]),
            klantreferentie=p["klantreferentie"],
            factuurdatum=p["factuurdatum"],
        )
        for p in CASUS.bank_open_posten()
    }
    return {"mutaties": mutaties, "posten": posten}


def _per_sleutel(administratie_id: uuid.UUID, clean_care: dict) -> dict[str, voorstellen.MutatieMetVoorstel]:
    op_id = {m.mutatie.id: m for m in voorstellen.open_mutaties_met_voorstellen(administratie_id=administratie_id)}
    return {sleutel: op_id[mutatie_id] for sleutel, mutatie_id in clean_care["mutaties"].items()}


class TestKlantreferentieAlsNummer:
    @pytest.mark.parametrize(
        ("sleutel", "referentie", "bedrag"),
        [
            ("DOC", "2025689", "1261.43"),
            ("VAC", "2025682", "91.05"),
            ("S2G", "2025696", "1594.18"),
        ],
    )
    def test_drie_bijschrijvingen_zijn_groen_op_naam_referentie_bedrag(
        self, administratie_id: uuid.UUID, clean_care: dict, sleutel: str, referentie: str, bedrag: str
    ) -> None:
        m = _per_sleutel(administratie_id, clean_care)[sleutel]
        assert m.voorstel.soort is VoorstelSoort.EXACTE_MATCH and m.voorstel.kleur == "groen"
        assert m.voorstel.bron == f"naam + referentie {referentie} + bedrag"
        assert m.voorstel.payment_item_id == clean_care["posten"][sleutel]
        assert m.open_post is not None and m.open_post.bedrag == Decimal(bedrag)
        assert m.open_post.klantreferentie == referentie

    def test_kaart_toont_de_echte_factuurdatum_niet_de_vervaldatum_van_de_post(
        self, administratie_id: uuid.UUID, clean_care: dict
    ) -> None:
        doc = _per_sleutel(administratie_id, clean_care)["DOC"]
        assert doc.open_post is not None
        assert doc.open_post.factuurdatum == date(2026, 8, 29)  # Document.Date, niet BookDate 12-9 (= DueDate)
        assert doc.open_post.boekstuknummer is None or doc.open_post.boekstuknummer.startswith("RLZ-")

    def test_alle_drie_zijn_auto_afletter_kandidaat(self, administratie_id: uuid.UUID, clean_care: dict) -> None:
        per = _per_sleutel(administratie_id, clean_care)
        assert all(per[s].voorstel.kleur == "groen" for s in ("DOC", "VAC", "S2G"))
