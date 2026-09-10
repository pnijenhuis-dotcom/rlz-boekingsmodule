"""Blok 1 vervolgrun 10-09 avond: referentie-classificatie voor `rlz_dubbel` (puur, geen DB).

(a) IBAN — NL-vorm altijd (ook met spaties/kleine letters en in de genormaliseerde vorm zonder voorloopnullen), ander
landformaat alleen mét geldige mod-97; een factuurnummer dat toevallig op het landformaat lijkt is géén IBAN.
(b) Klantkenmerk — ≥ 3 documenten mét ≥ 2 verschillende bedragen; precies 3× met één bedrag = NIET uitgesloten; 2× met
twee bedragen = NIET uitgesloten. (c) Placeholder — referentie_norm ontbreekt."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from app.reconciliatie import referentie_classificatie as rc


@dataclass(frozen=True)
class _Doc:
    referentie: str | None
    referentie_norm: str | None
    bedrag: Decimal | None


def _doc(ref: str | None, bedrag: str | None, *, norm: str | None = "x") -> _Doc:
    return _Doc(referentie=ref, referentie_norm=norm, bedrag=Decimal(bedrag) if bedrag is not None else None)


class TestIban:
    @pytest.mark.parametrize(
        "ref",
        [
            "NL86INGB0662462785",  # Food service (productie 10-09)
            "NL86 INGB 0662 4627 85",
            "nl86ingb0662462785",
            "NL91ABNA0417164300",
            "BE68539007547034",  # geldig BE
            "DE89 3704 0044 0532 0130 00",  # geldig DE
            "FR1420041010050500013M02606",  # geldig FR (alfanumeriek)
        ],
    )
    def test_iban_herkend(self, ref: str) -> None:
        assert rc.lijkt_op_iban(ref) is True

    def test_genormaliseerde_nl_vorm_zonder_voorloopnullen(self) -> None:
        """`normaliseer_referentie` haalt voorloopnullen per cijfergroep weg:
        'NL86 INGB 0662 4627 85' → 'nl86ingb662462785'."""
        assert rc.lijkt_op_iban(None, "nl86ingb662462785") is True

    @pytest.mark.parametrize(
        "ref",
        [
            "2026-0042",
            "RLZ-04-00000069",
            "0817725528",  # BP Express klantnummer — géén IBAN (dat is regel (b))
            "FA2026000123457",  # landformaat-achtig, maar mod-97 klopt niet (…456 is toevallig wél geldig: 1 op 97)
            "BE68539007547035",  # één cijfer anders → checksum fout
            "",
            None,
        ],
    )
    def test_geen_iban(self, ref: str | None) -> None:
        assert rc.lijkt_op_iban(ref) is False

    def test_checksum_functie(self) -> None:
        assert rc.iban_checksum_geldig("NL91ABNA0417164300") is True
        assert rc.iban_checksum_geldig("NL91ABNA0417164301") is False
        assert rc.iban_checksum_geldig("NL") is False


class TestKlantkenmerk:
    def test_drie_documenten_twee_bedragen_is_klantkenmerk(self) -> None:
        assert rc.is_klantkenmerk([Decimal("10.00"), Decimal("20.00"), Decimal("10.00")], aantal_documenten=3) is True

    def test_precies_drie_met_een_bedrag_is_niet_uitgesloten(self) -> None:
        assert rc.is_klantkenmerk([Decimal("10.00")] * 3, aantal_documenten=3) is False

    def test_twee_met_twee_bedragen_is_niet_uitgesloten(self) -> None:
        assert rc.is_klantkenmerk([Decimal("10.00"), Decimal("20.00")], aantal_documenten=2) is False

    def test_bp_express_zeven_boekingen_verschillende_bedragen(self) -> None:
        bedragen = [Decimal(x) for x in ("81.20", "94.15", "81.20", "120.00", "77.35", "94.15", "60.10")]
        assert rc.is_klantkenmerk(bedragen, aantal_documenten=7) is True

    def test_onbekende_bedragen_tellen_niet_als_verschillend(self) -> None:
        assert rc.is_klantkenmerk([Decimal("10.00"), None, None], aantal_documenten=3) is False


class TestClassificeerGroep:
    def test_placeholder_groep(self) -> None:
        c = rc.classificeer_groep(
            [_doc("Ingescand document", "10.00", norm=None), _doc("Ingescand document", "12.00", norm=None)]
        )
        assert c.reden == rc.REDEN_PLACEHOLDER and not c.toetsbaar and c.aantal_documenten == 2

    def test_iban_groep_food_service(self) -> None:
        docs = [_doc("NL86INGB0662462785", b, norm="nl86ingb662462785") for b in ("10.00", "12.00", "10.00", "9.99")]
        c = rc.classificeer_groep(docs)
        assert c.reden == rc.REDEN_IBAN and c.aantal_documenten == 4 and c.aantal_bedragen == 3

    def test_klantkenmerk_groep_bp_express(self) -> None:
        docs = [
            _doc("0817725528", b, norm="817725528")
            for b in ("81.20", "94.15", "81.20", "120.00", "77.35", "94.15", "60.10")
        ]
        assert rc.classificeer_groep(docs).reden == rc.REDEN_KLANTKENMERK

    def test_toetsbaar_twee_exemplaren_ander_bedrag(self) -> None:
        c = rc.classificeer_groep(
            [_doc("2026-0042", "100.00", norm="202642"), _doc("2026-0042", "250.00", norm="202642")]
        )
        assert c.toetsbaar and c.reden is None and c.aantal_bedragen == 2

    def test_toetsbaar_drie_exemplaren_een_bedrag(self) -> None:
        c = rc.classificeer_groep([_doc("42", "100.00", norm="42")] * 3)
        assert c.toetsbaar and c.aantal_documenten == 3 and c.aantal_bedragen == 1

    def test_iban_gaat_voor_klantkenmerk(self) -> None:
        docs = [_doc("NL91ABNA0417164300", b, norm="nl91abna417164300") for b in ("1.00", "2.00", "3.00")]
        assert rc.classificeer_groep(docs).reden == rc.REDEN_IBAN

    def test_lege_groep(self) -> None:
        assert rc.classificeer_groep([]).toetsbaar

    def test_redenen_hebben_label_en_vaste_volgorde(self) -> None:
        assert rc.UITSLUITINGSREDENEN == (rc.REDEN_PLACEHOLDER, rc.REDEN_IBAN, rc.REDEN_KLANTKENMERK)
        assert all(r in rc.REDEN_LABEL for r in rc.UITSLUITINGSREDENEN)
