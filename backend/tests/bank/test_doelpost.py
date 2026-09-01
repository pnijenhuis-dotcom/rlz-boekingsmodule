"""Doel-post-specs voor de voorstel-kaart (blok E5, 01/02-09): puur uit de cache-rij — documentsoort-label,
boekstuknummer (ReceiptNumber > Reference2), tegenpartij, factuurdatum; ontbrekend = None (kaart laat de
regel weg, nooit gokken). Plus: de matchmotor blijft ongewijzigd (OpenPost-extra's zijn optioneel)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.bank import doelpost, matchmotor


class TestSpecsUitCache:
    def test_volledig_uit_document_expand(self) -> None:
        specs = doelpost.specs_uit_cache(
            entity_naam="Hans Anders Nederland B.V.",
            brondata={"Document": {"id": "x", "DocumentType": 10, "ReceiptNumber": "RLZ-01-00000942", "Entity": {"Name": "x"}}},
            referentie2="RLZ-01-00000999 01-09-2026",
            boekdatum=date(2026, 9, 1),
        )
        assert specs == doelpost.DoelPostSpecs(
            tegenpartij_naam="Hans Anders Nederland B.V.",
            documentsoort="Verkoopfactuur",
            boekstuknummer="RLZ-01-00000942",
            factuurdatum=date(2026, 9, 1),
        )

    def test_boekstuk_uit_reference2_en_naam_uit_entity_als_cache_naam_leeg(self) -> None:
        specs = doelpost.specs_uit_cache(
            entity_naam=None,
            brondata={"Document": {"DocumentType": 1, "Entity": {"Name": "Bouwbedrijf Verhagen B.V."}}},
            referentie2="RLZ-01-00000921 14-08-2026",
            boekdatum=None,
        )
        assert specs.tegenpartij_naam == "Bouwbedrijf Verhagen B.V."
        assert specs.documentsoort == "Inkoopfactuur"
        assert specs.boekstuknummer == "RLZ-01-00000921"
        assert specs.factuurdatum is None

    def test_ontbrekende_velden_blijven_none_nooit_gokken(self) -> None:
        specs = doelpost.specs_uit_cache(entity_naam=None, brondata=None, referentie2=None, boekdatum=None)
        assert specs == doelpost.DoelPostSpecs(None, None, None, None)
        assert doelpost.documentsoort_label(4) is None  # onbekend type = geen label
        assert doelpost.documentsoort_label("19") == "Bankboeking"
        assert doelpost.boekstuknummer_uit({"ReceiptNumber": "  "}, "geen boekstuk hier") is None

    def test_matchmotor_openpost_extra_velden_zijn_optioneel(self) -> None:
        # Géén motorwijziging: de bestaande constructie zonder specs blijft geldig.
        post = matchmotor.OpenPost(
            id=uuid.uuid4(), bedrag=Decimal("10.00"), referentie="F-1", referentie2=None, rlz_document_id=None
        )
        assert post.tegenpartij_naam is None and post.documentsoort is None and post.factuurdatum is None
