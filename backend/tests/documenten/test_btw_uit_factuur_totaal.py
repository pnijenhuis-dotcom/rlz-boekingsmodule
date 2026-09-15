"""Bugfix 15-09 — btw-code uit het FACTUURTOTAAL in het boekvoorstel (documenten/boekvoorstel.py): de regels van een
AI-voorstel dragen ná controle.py de factuur-afgeleide code (bron 'factuur', groen) en een AI-voorstel zónder regels
geeft de afleiding door aan de één-regel-terugval. Pure prefill-functies, geen DB."""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.documenten import boekvoorstel

HOOG = uuid.uuid4()


def _ai_voorstel(regels: list[dict], *, totaal_taxrate: uuid.UUID | None = HOOG) -> dict:
    return {
        "bron": "ai",
        "totaal_excl": "69.41",
        "totaal_incl": "83.99",
        "btw_bedrag": "14.58",
        "btw_factuur_totaal": {
            "taxrate_id": str(totaal_taxrate) if totaal_taxrate else None,
            "reden": None if totaal_taxrate else "geen_match",
        },
        "regels": regels,
    }


def test_regels_met_factuur_totaal_afleiding_worden_groene_factuur_regels() -> None:
    regels = [
        {
            "omschrijving": "Abonnement",
            "netto_bedrag": "45.00",
            "btw_bedrag": "9.45",
            "taxrate_id": str(HOOG),
            "btw_bron": "factuur",
            "btw_afleiding_reden": None,
            "btw_afleiding_basis": "factuur_totaal",
            "btw_bedrag_berekend": True,
        },
        {
            "omschrijving": "Extra data",
            "netto_bedrag": "24.41",
            "btw_bedrag": "5.13",
            "taxrate_id": str(HOOG),
            "btw_bron": "factuur",
            "btw_afleiding_reden": None,
            "btw_afleiding_basis": "factuur_totaal",
            "btw_bedrag_berekend": True,
        },
    ]
    prefill = boekvoorstel._regels_prefill(_ai_voorstel(regels))
    assert [(r.taxrate_id, r.btw_bron, r.btw_bewust_leeg, r.btw_bedrag) for r in prefill] == [
        (HOOG, "factuur", False, Decimal("9.45")),
        (HOOG, "factuur", False, Decimal("5.13")),
    ]
    samengevoegd = boekvoorstel._samengevoegde_regel(_ai_voorstel(regels))
    assert samengevoegd is not None and (samengevoegd.taxrate_id, samengevoegd.btw_bron) == (HOOG, "factuur")
    assert (samengevoegd.netto_bedrag, samengevoegd.btw_bedrag) == (Decimal("69.41"), Decimal("14.58"))


def test_ai_voorstel_zonder_regels_geeft_de_factuur_code_aan_de_een_regel_terugval() -> None:
    prefill = boekvoorstel._regels_prefill(_ai_voorstel([]))
    assert len(prefill) == 1
    regel = prefill[0]
    assert (regel.taxrate_id, regel.btw_bron) == (HOOG, "factuur")
    assert (regel.netto_bedrag, regel.btw_bedrag) == (Decimal("69.41"), Decimal("14.58"))


def test_zonder_afleiding_blijft_de_een_regel_terugval_leeg_ook_voor_ubl_voorstellen() -> None:
    leeg = boekvoorstel._regels_prefill(_ai_voorstel([], totaal_taxrate=None))
    assert leeg[0].taxrate_id is None and leeg[0].btw_bron is None
    ubl = boekvoorstel._regels_prefill({"bron": "ubl", "totaal_excl": "100.00", "totaal_incl": "121.00"})
    assert ubl[0].taxrate_id is None and ubl[0].btw_bron is None
