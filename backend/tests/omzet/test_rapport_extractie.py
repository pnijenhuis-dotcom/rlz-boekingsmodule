"""Deterministische controlelaag van de rapport-extractie (app/extractie/rapport.py):
code rekent, nooit de AI — regelsom, marge, parsing en de normalisatie van de AI-uitvoer."""

from __future__ import annotations

from typing import Any

import pytest

from app.extractie.client import AiExtractieFout, ClaudeAntwoord
from app.extractie.rapport import (
    AiRapportExtractie,
    AiRapportRegel,
    AiRapportVeld,
    bouw_rapport_veldvoorstel,
    extraheer_kassarapport,
)


def _extractie(
    *,
    kop_overrides: dict[str, AiRapportVeld] | None = None,
    regels: list[AiRapportRegel] | None = None,
) -> AiRapportExtractie:
    kop = {
        "rapport_titel": AiRapportVeld("Margerapport", 0.95),
        "entiteit_naam": AiRapportVeld("BLOW B.V.", 0.9),
        "periode_start": AiRapportVeld("2025-09-15", 0.98),
        "periode_eind": AiRapportVeld("2025-09-21", 0.98),
        "totaal_omzet": AiRapportVeld("22463.36", 0.99),
        "totaal_kostprijs": AiRapportVeld("14017.29", 0.99),
    }
    kop.update(kop_overrides or {})
    if regels is None:
        regels = [
            AiRapportRegel("1. Weed", "8585.32", "13655.33", 0.99),
            AiRapportRegel("2. Hash", "2668.82", "4706.97", 0.99),
            AiRapportRegel("3. Joints", "1627.90", "2345.68", 0.98),
            AiRapportRegel("4. Edibles", "280.85", "315.00", 0.97),
            AiRapportRegel("Weed Prepacked", "854.40", "1440.38", 0.98),
        ]
    return AiRapportExtractie(kop=kop, regels=regels, bsn_verwijderd=0)


class TestBouwRapportVeldvoorstel:
    def test_sluitend_rapport_geeft_kloppende_regelsommen_en_marge(self) -> None:
        voorstel = bouw_rapport_veldvoorstel(_extractie(), zekerheid_drempel=0.8)

        assert voorstel["soort"] == "kassarapport"
        assert voorstel["periode_start"] == "2025-09-15"
        assert voorstel["periode_eind"] == "2025-09-21"
        assert voorstel["regelsom_omzet"]["sluit"] is True
        assert voorstel["regelsom_kostprijs"]["sluit"] is True
        # Marge in code berekend: 22463.36 / 14017.29 × 100 = 160.3 (mockup: "marge 160%").
        assert voorstel["marge_pct"] == "160.3"
        assert len(voorstel["regels"]) == 5
        assert voorstel["regels"][0]["omzet_bedrag"] == "13655.33"
        assert voorstel["regels"][0]["kostprijs_bedrag"] == "8585.32"

    def test_niet_sluitende_regelsom_wordt_gemarkeerd(self) -> None:
        extractie = _extractie(regels=[AiRapportRegel("Weed", "100.00", "200.00", 0.9)])
        voorstel = bouw_rapport_veldvoorstel(extractie, zekerheid_drempel=0.8)

        assert voorstel["regelsom_omzet"]["sluit"] is False
        assert voorstel["regelsom_omzet"]["som"] == "200.00"
        assert voorstel["regelsom_omzet"]["totaal"] == "22463.36"

    def test_onparseerbaar_bedrag_wordt_leeg_en_benoemd(self) -> None:
        extractie = _extractie(
            kop_overrides={"totaal_omzet": AiRapportVeld("tweeëntwintigduizend", 0.4)},
            regels=[AiRapportRegel("Weed", "8585.32", "niet leesbaar", 0.4)],
        )
        voorstel = bouw_rapport_veldvoorstel(extractie, zekerheid_drempel=0.8)

        assert voorstel["totaal_omzet"] is None
        assert voorstel["regels"][0]["omzet_bedrag"] is None
        assert "totaal_omzet" in voorstel["onparseerbaar"]
        assert "omzet regel 1" in voorstel["onparseerbaar"]
        # Zonder gelezen totaal is de regelsom niet te toetsen — expliciet, nooit stil.
        assert voorstel["regelsom_omzet"]["vergelijkbaar"] is False

    def test_geen_marge_zonder_kostprijs(self) -> None:
        extractie = _extractie(
            kop_overrides={"totaal_kostprijs": AiRapportVeld(None, 0.0)},
            regels=[AiRapportRegel("Weed", None, "22463.36", 0.9)],
        )
        voorstel = bouw_rapport_veldvoorstel(extractie, zekerheid_drempel=0.8)
        assert voorstel["marge_pct"] is None

    def test_lage_zekerheid_markeert_regel_onzeker(self) -> None:
        extractie = _extractie(regels=[AiRapportRegel("Weed", "100.00", "160.00", 0.5)])
        voorstel = bouw_rapport_veldvoorstel(extractie, zekerheid_drempel=0.8)
        assert voorstel["regels"][0]["onzeker"] is True


class _FakeClaudeClient:
    def __init__(self, antwoord: ClaudeAntwoord) -> None:
        self.antwoord = antwoord
        self.aanroepen: list[dict[str, Any]] = []

    def extraheer_json_uit_pdf(self, **kwargs: Any) -> ClaudeAntwoord:
        self.aanroepen.append(kwargs)
        return self.antwoord


class TestExtraheerKassarapport:
    def test_normaliseert_kop_en_regels(self) -> None:
        client = _FakeClaudeClient(
            ClaudeAntwoord(
                data={
                    "kop": {
                        "titel": "Margerapport",
                        "ent": "BLOW B.V.",
                        "start": "2025-09-15",
                        "eind": "2025-09-21",
                        "tot_i": "14017.29",
                        "tot_v": "22463.36",
                    },
                    "kz": {"titel": 0.9, "ent": 0.9, "start": 0.98, "eind": 0.98, "tot_i": 0.99, "tot_v": 0.99},
                    "regels": [{"c": "1. Weed", "i": "8585.32", "v": "13655.33", "z": 0.99}],
                },
                afgekapt=False,
                input_tokens=100,
                output_tokens=50,
            )
        )
        extractie = extraheer_kassarapport(b"%PDF", client=client)  # type: ignore[arg-type]

        assert extractie.kop["periode_start"].waarde == "2025-09-15"
        assert extractie.kop["totaal_omzet"].waarde == "22463.36"
        assert extractie.regels[0].categorie == "1. Weed"
        assert extractie.regels[0].omzet_bedrag == "13655.33"
        assert extractie.regels[0].kostprijs_bedrag == "8585.32"

    def test_afgekapte_respons_is_zichtbare_fout_geen_chunking(self) -> None:
        client = _FakeClaudeClient(ClaudeAntwoord(data=None, afgekapt=True, input_tokens=1, output_tokens=1))
        with pytest.raises(AiExtractieFout, match="afgekapt"):
            extraheer_kassarapport(b"%PDF", client=client)  # type: ignore[arg-type]

    def test_bsn_wordt_uit_vrije_tekst_verwijderd(self) -> None:
        client = _FakeClaudeClient(
            ClaudeAntwoord(
                data={
                    "kop": {
                        "titel": "Urenrapport BSN 111222333",
                        "ent": None,
                        "start": None,
                        "eind": None,
                        "tot_i": None,
                        "tot_v": None,
                    },
                    "kz": {"titel": 0.9, "ent": 0, "start": 0, "eind": 0, "tot_i": 0, "tot_v": 0},
                    "regels": [],
                },
                afgekapt=False,
                input_tokens=1,
                output_tokens=1,
            )
        )
        extractie = extraheer_kassarapport(b"%PDF", client=client)  # type: ignore[arg-type]
        assert "111222333" not in (extractie.kop["rapport_titel"].waarde or "")
        assert extractie.bsn_verwijderd == 1
