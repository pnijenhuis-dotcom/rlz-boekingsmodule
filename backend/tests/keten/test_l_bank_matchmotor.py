"""Casus (l) — bankmatchmotor Administratiekantoor Nijenhuis C.V. 08-09 (blok 2 bundel 08-09).

Productie 08-09 toonde twee foute voorstellen van de oude substring-matchmotor (geval A: € 12.500 BIJ van een
privépersoon → verkoopfactuur 2352 Tupker Beheer omdat "2352" in het betalingskenmerk zat; geval B: afschrijving
DNA Notaris → verkoopfactuur 2337 Kempen Chalets, tekenfout). De twee goede matches (TransIP 24-08, NPG 2026053)
moeten groen blijven. Deze test draait de motor via de SERVICELAAG (`voorstellen.open_mutaties_met_voorstellen`,
mét de DB-caches `bank_mutatie` + `payment_item_cache` zoals de sync ze vult) op de fixture-set
`fixtures/l_bank_cv_08-09/` — geen RLZ-call, geen AI."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.bank import voorstellen
from app.bank.matchmotor import VoorstelSoort
from tests.bank.conftest import maak_bank_mutatie, maak_payment_item
from tests.keten import casussen
from tests.keten.casussen import Casus

CASUS = Casus(casussen.L_BANK_CV)
CV_NAAM = "Administratiekantoor Nijenhuis C.V."


@pytest.fixture
def cv_bank(administratie_id: uuid.UUID, admin_engine: Engine) -> dict[str, dict[str, uuid.UUID]]:
    """De testadministratie als de C.V., mét de vier onverwerkte mutaties en vier open posten uit de fixture."""
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.administratie SET naam = :naam WHERE id = :id"),
            {"naam": CV_NAAM, "id": administratie_id},
        )
    mutaties = {
        m["sleutel"]: maak_bank_mutatie(
            admin_engine,
            administratie_id=administratie_id,
            mutatie_id=uuid.UUID(m["id"]),
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
        )
        for p in CASUS.bank_open_posten()
    }
    return {"mutaties": mutaties, "posten": posten}


def _per_sleutel(administratie_id: uuid.UUID, cv_bank: dict) -> dict[str, voorstellen.MutatieMetVoorstel]:
    op_id = {m.mutatie.id: m for m in voorstellen.open_mutaties_met_voorstellen(administratie_id=administratie_id)}
    return {sleutel: op_id[mutatie_id] for sleutel, mutatie_id in cv_bank["mutaties"].items()}


class TestProductiegevallenGevenGeenOpenPostVoorstel:
    def test_geval_a_bijschrijving_privepersoon_matcht_niet_op_substring_van_het_kenmerk(
        self, administratie_id: uuid.UUID, cv_bank: dict
    ) -> None:
        rij = _per_sleutel(administratie_id, cv_bank)["A"]
        assert rij.mutatie.bedrag == Decimal("12500.00")
        assert rij.voorstel.soort == VoorstelSoort.HANDMATIG, rij.voorstel
        assert rij.voorstel.payment_item_id is None and rij.open_post is None
        assert "naam + referentie" not in rij.voorstel.bron

    def test_geval_b_afschrijving_matcht_nooit_een_verkoopfactuur(
        self, administratie_id: uuid.UUID, cv_bank: dict
    ) -> None:
        rij = _per_sleutel(administratie_id, cv_bank)["B"]
        assert rij.mutatie.bedrag == Decimal("-99.99")
        assert rij.voorstel.soort == VoorstelSoort.HANDMATIG, rij.voorstel
        assert rij.voorstel.payment_item_id is None

    def test_de_verkoopfacturen_2352_en_2337_blijven_onaangeroerd_open(
        self, administratie_id: uuid.UUID, cv_bank: dict
    ) -> None:
        voorgesteld = {
            rij.voorstel.payment_item_id
            for rij in voorstellen.open_mutaties_met_voorstellen(administratie_id=administratie_id)
            if rij.voorstel.payment_item_id is not None
        }
        assert cv_bank["posten"]["2352"] not in voorgesteld
        assert cv_bank["posten"]["2337"] not in voorgesteld


class TestGoedeMatchesBlijvenGroen:
    def test_transip_24_08_is_groen_op_naam_nummer_bedrag(self, administratie_id: uuid.UUID, cv_bank: dict) -> None:
        rij = _per_sleutel(administratie_id, cv_bank)["TRANSIP"]
        assert rij.voorstel.soort == VoorstelSoort.EXACTE_MATCH, rij.voorstel
        assert rij.voorstel.kleur == "groen"
        assert rij.voorstel.bron == "naam + nummer + bedrag"
        assert rij.voorstel.payment_item_id == cv_bank["posten"]["TRANSIP"]
        assert rij.open_post is not None and rij.open_post.documentsoort == "Inkoopfactuur"

    def test_npg_2026053_is_groen_op_naam_nummer_bedrag(self, administratie_id: uuid.UUID, cv_bank: dict) -> None:
        rij = _per_sleutel(administratie_id, cv_bank)["NPG"]
        assert rij.voorstel.soort == VoorstelSoort.EXACTE_MATCH, rij.voorstel
        assert rij.voorstel.bron == "naam + nummer + bedrag"
        assert rij.voorstel.payment_item_id == cv_bank["posten"]["NPG"]

    def test_alleen_de_groene_gevallen_zijn_auto_afletter_kandidaat(
        self, administratie_id: uuid.UUID, cv_bank: dict
    ) -> None:
        """Wat `afletteren.verwerk_exacte_matches_automatisch` zou oppakken (achter de opt-in): exact TransIP + NPG."""
        kandidaten = {
            sleutel
            for sleutel, rij in _per_sleutel(administratie_id, cv_bank).items()
            if rij.voorstel.soort == VoorstelSoort.EXACTE_MATCH and rij.voorstel.payment_item_id is not None
        }
        assert kandidaten == {"TRANSIP", "NPG"}
