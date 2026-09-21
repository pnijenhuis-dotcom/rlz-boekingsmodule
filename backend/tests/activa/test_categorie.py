"""Pure regels activa (categorie, termijn, methode-naam, fiscale signalen, MVA-rekening-toets) — geen DB, geen RLZ."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.activa import categorie as cat
from app.activa import nulmeting


class TestCategorie:
    @pytest.mark.parametrize(
        ("naam", "verwacht"),
        [
            ("Steigermateriaal", "steigermateriaal"),
            ("Steigers en toebehoren", "steigermateriaal"),
            ("Bedrijfsgebouwen", "gebouwen"),
            ("Terreinen", "gebouwen"),
            ("Pand Dorpsstraat 12", "gebouwen"),
            ("Auto's", "vervoermiddelen"),
            ("Bestelbussen", "vervoermiddelen"),
            ("Vrachtwagens", "vervoermiddelen"),
            ("Computers en software", "computers_software"),
            ("ICT-apparatuur", "computers_software"),
            ("Machines en installaties", "machines"),
            ("Gereedschappen", "machines"),
            ("Inventaris", "inventaris"),
            ("Kantoormeubilair", "inventaris"),
            ("Overige vaste activa", "onbekend"),
            ("", "onbekend"),
        ],
    )
    def test_bepaal_categorie_op_naam(self, naam: str, verwacht: str) -> None:
        assert cat.bepaal_categorie("0107", naam) == verwacht

    def test_steiger_wint_van_gebouw_en_vervoer(self) -> None:
        # Een steigerrekening met 'materiaal' + 'weg' in de naam blijft steigermateriaal (eerste treffer in volgorde).
        assert cat.bepaal_categorie("0200", "Steigermateriaal wegtransport") == "steigermateriaal"
        assert cat.bepaal_categorie("0200", "Bedrijfsauto (gebouwbeheer)") == "gebouwen"

    def test_labels_en_defaults(self) -> None:
        assert [c.code for c in cat.CATEGORIEEN] == [
            "gebouwen",
            "inventaris",
            "vervoermiddelen",
            "computers_software",
            "machines",
            "steigermateriaal",
            "onbekend",
        ]
        assert cat.PER_CODE["steigermateriaal"].default_maanden == 60  # besluit Peter 16-09
        assert cat.PER_CODE["computers_software"].default_maanden == 36
        assert cat.PER_CODE["gebouwen"].default_maanden == 360
        assert cat.label_voor("onbekend") == "Onbekend — controleer"
        assert cat.label_voor("bestaat_niet") == "Onbekend — controleer"


class TestTermijn:
    def test_instelling_wint_anders_default(self) -> None:
        assert cat.termijn_voor("inventaris", {}) == 60
        assert cat.termijn_voor("inventaris", {"inventaris": 120}) == 120
        assert cat.termijn_voor("inventaris", {"inventaris": "84"}) == 84
        assert cat.termijn_voor("inventaris", {"inventaris": "onzin"}) == 60
        assert cat.termijn_voor("onbekende_categorie", None) == 60

    def test_methode_naam_rondt_naar_boven_op_hele_jaren(self) -> None:
        assert cat.methode_naam(60) == "Lineair 5 jaar"
        assert cat.methode_naam(36) == "Lineair 3 jaar"
        assert cat.methode_naam(37) == "Lineair 4 jaar"
        assert cat.methode_naam(6) == "Lineair 1 jaar"

    def test_termijn_geldig(self) -> None:
        assert cat.termijn_geldig(12) and cat.termijn_geldig(600) and cat.termijn_geldig(60)
        assert not cat.termijn_geldig(0)
        assert not cat.termijn_geldig(13)
        assert not cat.termijn_geldig(612)
        assert not cat.termijn_geldig(True)
        assert not cat.termijn_geldig("60")


class TestFiscaleSignalen:
    def _codes(self, **kw) -> list[str]:  # noqa: ANN003
        basis = dict(categorie="inventaris", termijn_maanden=60, aanschafwaarde=Decimal("1000"), grens=Decimal("450"))
        basis.update(kw)
        return [s.code for s in cat.fiscale_signalen(**basis)]

    def test_boven_grens_altijd_kia_signaal_en_niets_anders_bij_default(self) -> None:
        assert self._codes() == ["kia_mia_mogelijk"]

    def test_termijn_korter_dan_vijf_jaar_is_signaal_behalve_gebouwen(self) -> None:
        assert self._codes(termijn_maanden=36) == ["afschrijving_boven_20pct", "kia_mia_mogelijk"]
        assert "afschrijving_boven_20pct" not in self._codes(categorie="gebouwen", termijn_maanden=36)

    def test_gebouw_bodemwaarde_en_onbekend(self) -> None:
        assert self._codes(categorie="gebouwen", termijn_maanden=360) == ["bodemwaarde_woz", "kia_mia_mogelijk"]
        assert self._codes(categorie="onbekend") == ["kia_mia_mogelijk", "categorie_onbekend"]

    def test_onder_grens_geen_kia(self) -> None:
        assert self._codes(aanschafwaarde=Decimal("100")) == []

    def test_teksten_toetsen_nooit_rekenen(self) -> None:
        teksten = [
            s.tekst
            for s in cat.fiscale_signalen(
                categorie="gebouwen", termijn_maanden=36, aanschafwaarde=Decimal("5000"), grens=Decimal("450")
            )
        ]
        assert any("art. 3.30" not in t for t in teksten)  # gebouw: geen 20 %-signaal
        assert any("adviseur beslist" in t for t in teksten)


class TestMvaRekening:
    @pytest.mark.parametrize(
        ("rij", "verwacht"),
        [
            ({"IsFixedAssetAccount": True, "AccountType": 3, "AccountNumber": "0107", "IsTotalAccount": False}, True),
            ({"IsFixedAssetAccount": True, "AccountType": 3, "AccountNumber": "3000", "IsTotalAccount": False}, False),
            ({"IsFixedAssetAccount": True, "AccountType": 2, "AccountNumber": "0107", "IsTotalAccount": False}, False),
            ({"IsFixedAssetAccount": False, "AccountType": 3, "AccountNumber": "0107", "IsTotalAccount": False}, False),
            ({"IsFixedAssetAccount": True, "AccountType": 3, "AccountNumber": "0100", "IsTotalAccount": True}, False),
            ({}, False),
        ],
    )
    def test_drie_voorwaarden_zelfde_regel_als_de_nulmeting(self, rij: dict, verwacht: bool) -> None:
        assert cat.is_mva_rekening(rij) is verwacht
        assert nulmeting.is_mva_rekening(rij) is verwacht
