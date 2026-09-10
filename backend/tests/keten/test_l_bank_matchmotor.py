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


# --- blok B bundel 10-09: historie-regel (stap 3b) op de C.V.-casus -----------------------------------------------


@pytest.fixture
def cv_historie(administratie_id: uuid.UUID, admin_engine: Engine, cv_bank: dict) -> uuid.UUID:
    """Vijfde open mutatie (huur, geen open post) + drie eerdere RLZ-grootboekboekingen in de historie-cache
    (`fixtures/l_bank_cv_08-09/historie.json`). De vier bestaande mutaties blijven ongewijzigd."""
    from datetime import date, timedelta

    data = CASUS.bank_historie()
    gb = data["grootboek"]
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.grootboekrekening "
                "(ledger_id, administratie_id, code, naam, soort, is_totaalrekening) "
                "VALUES (:id, :aid, :code, :naam, 2, false)"
            ),
            {"id": uuid.UUID(gb["ledger_id"]), "aid": administratie_id, "code": gb["code"], "naam": gb["naam"]},
        )
        for b in data["boekingen"]:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.bank_historie_boeking "
                    "(id, administratie_id, payment_transaction_id, datum, "
                    "tegenrekening_iban, omschrijving, tegenpartij_naam, ledger_id, taxrate_id, bron) VALUES "
                    "(:id, :aid, :tx, :datum, :iban, :oms, :naam, :ledger, NULL, :bron)"
                ),
                {
                    "id": uuid.uuid4(),
                    "aid": administratie_id,
                    "tx": uuid.UUID(b["payment_transaction_id"]),
                    "datum": date.today() - timedelta(days=b["dagen_terug"]),
                    "iban": data["mutatie"]["tegenrekening_iban"],
                    "oms": b["omschrijving"],
                    "naam": data["mutatie"]["tegenpartij_naam"],
                    "ledger": uuid.UUID(gb["ledger_id"]),
                    "bron": b["bron"],
                },
            )
    m = data["mutatie"]
    return maak_bank_mutatie(
        admin_engine,
        administratie_id=administratie_id,
        mutatie_id=uuid.UUID(m["id"]),
        bedrag=m["bedrag"],
        tegenpartij_naam=m["tegenpartij_naam"],
        omschrijving=m["omschrijving"],
        tegenrekening_iban=m["tegenrekening_iban"],
        boekdatum=(date.today() - timedelta(days=m["dagen_terug"])).isoformat(),
    )


class TestHistorieRegelOpDeCv:
    def test_huur_zonder_open_post_krijgt_groene_historie_regel_3_van_3(
        self, administratie_id: uuid.UUID, cv_bank: dict, cv_historie: uuid.UUID
    ) -> None:
        rij = next(
            r
            for r in voorstellen.open_mutaties_met_voorstellen(administratie_id=administratie_id)
            if r.mutatie.id == cv_historie
        )
        assert rij.voorstel.soort == VoorstelSoort.HISTORIE_REGEL, rij.voorstel
        assert rij.voorstel.kleur == "groen"
        assert rij.voorstel.bron == "historie: 3 van 3 op 4400 Huur onroerend goed"
        assert (rij.voorstel.historie_k, rij.voorstel.historie_n) == (3, 3)
        assert rij.voorstel.ledger_id == uuid.UUID(CASUS.bank_historie()["grootboek"]["ledger_id"])
        # Concrete boekregels (btw-splitsing in code): één regel die het mutatiebedrag exact dekt.
        assert len(rij.regel_boekregels) == 1 and rij.regel_boekregels[0].netto_bedrag == Decimal("-1815.00")
        assert rij.ai_toets is None  # nog niet getoetst — de nachtelijke autoflow doet dat

    def test_de_vier_bestaande_cv_mutaties_krijgen_geen_historie_voorstel(
        self, administratie_id: uuid.UUID, cv_bank: dict, cv_historie: uuid.UUID
    ) -> None:
        """A/B blijven handmatig, TransIP/NPG groen op de open post — de historie raakt ze niet (andere IBAN/kern)."""
        per_sleutel = _per_sleutel(administratie_id, cv_bank)
        assert per_sleutel["A"].voorstel.soort == VoorstelSoort.HANDMATIG
        assert per_sleutel["B"].voorstel.soort == VoorstelSoort.HANDMATIG
        assert per_sleutel["TRANSIP"].voorstel.soort == VoorstelSoort.EXACTE_MATCH
        assert per_sleutel["NPG"].voorstel.soort == VoorstelSoort.EXACTE_MATCH

    def test_dto_draagt_historie_velden_en_ai_toets_kolommen(
        self, administratie_id: uuid.UUID, cv_bank: dict, cv_historie: uuid.UUID
    ) -> None:
        """Wat de frontend (VoorstelKaart/BankDetailScreen) krijgt: soort historie_regel, historie_k/n, ai_toets_*."""
        from app.bank import schemas
        from app.bank.router import _voorstel_response

        rij = next(
            r
            for r in voorstellen.open_mutaties_met_voorstellen(administratie_id=administratie_id)
            if r.mutatie.id == cv_historie
        )
        dto = _voorstel_response(rij)
        assert (dto.soort, dto.historie_k, dto.historie_n) == ("historie_regel", 3, 3)
        assert dto.ledger_id is not None and dto.regels[0].ledger_id == dto.ledger_id
        assert set(schemas.MutatieResponse.model_fields) >= {"ai_toets_uitkomst", "ai_toets_reden", "ai_toets_op"}
