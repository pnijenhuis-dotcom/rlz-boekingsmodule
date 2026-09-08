"""Blok 4 (bundel 08-09) — geanonimiseerde fixture Spot Services 2026-608 (Universal Steigerbouw): 12 gelezen regels
waarvan 9 tariefstaffel-regels (aantal 0, bedrag 0, btw 0) en 3 échte, projectnummer 26049 alleen op regel 1, "Btw
verlegd" in het totaalblok, btw 0. Pure controlelaag + veldvoorstel_regels — geen DB."""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.documenten import veldvoorstel_regels as vr
from app.extractie.controle import TaxRateKandidaat, bouw_veldvoorstel
from app.extractie.service import AiFactuurExtractie, AiRegel, AiVeld

HOOG = TaxRateKandidaat(id=uuid.uuid4(), percentage=Decimal("0.21"), is_favoriet=True)
VERLEGD = TaxRateKandidaat(id=uuid.uuid4(), percentage=Decimal("0"), is_verlegd=True)
NUL = TaxRateKandidaat(id=uuid.uuid4(), percentage=Decimal("0"))


def _veld(waarde: str | None, zekerheid: float = 0.93) -> AiVeld:
    return AiVeld(waarde=waarde, zekerheid=zekerheid)


def _staffel(omschrijving: str, prijs: str) -> AiRegel:
    return AiRegel(
        omschrijving=omschrijving,
        netto_bedrag="0.00",
        btw_bedrag="0.00",
        hoeveelheid="0",
        eenheid="uur",
        stuksprijs=prijs,
        zekerheid=0.9,
    )


def spot_services_extractie(*, kop_proj: str | None = None, regel1_proj: str | None = "26049") -> AiFactuurExtractie:
    """De fixture: 3 echte regels (inhuur montage/demontage/transport) + 9 tariefstaffel-regels, totaal 4.320,00 excl,
    btw 0, verlegd."""
    regels = [
        AiRegel(
            omschrijving="Inhuur montage steiger week 35",
            netto_bedrag="2400.00",
            btw_bedrag="0.00",
            hoeveelheid="48",
            eenheid="uur",
            stuksprijs="50.00",
            zekerheid=0.93,
            project_tekst=regel1_proj,
        ),
        _staffel("Uurtarief montage dag", "50.00"),
        _staffel("Uurtarief montage avond", "62.50"),
        _staffel("Uurtarief montage weekend", "75.00"),
        AiRegel(
            omschrijving="Inhuur demontage steiger week 35",
            netto_bedrag="1600.00",
            btw_bedrag="0.00",
            hoeveelheid="32",
            eenheid="uur",
            stuksprijs="50.00",
            zekerheid=0.93,
        ),
        _staffel("Uurtarief demontage dag", "50.00"),
        _staffel("Uurtarief demontage avond", "62.50"),
        _staffel("Uurtarief demontage weekend", "75.00"),
        AiRegel(
            omschrijving="Transport materieel",
            netto_bedrag="320.00",
            btw_bedrag="",
            hoeveelheid="2",
            eenheid="rit",
            stuksprijs="160.00",
            zekerheid=0.9,
        ),
        _staffel("Toeslag hoogwerker per dag", "95.00"),
        _staffel("Toeslag nachtwerk per uur", "18.00"),
        AiRegel(
            omschrijving="Reiskosten per km",
            netto_bedrag="0.00",
            btw_bedrag="",
            hoeveelheid="",
            eenheid="km",
            stuksprijs="0.35",
            zekerheid=0.85,
        ),
    ]
    return AiFactuurExtractie(
        kop={
            "leverancier_naam": _veld("Spot Services"),
            "factuurnummer": _veld("2026-608"),
            "factuurdatum": _veld("2026-09-01"),
            "valuta": _veld("EUR"),
            "totaal_excl": _veld("4320.00"),
            "totaal_incl": _veld("4320.00"),
            "btw_bedrag": _veld("0.00"),
            "btw_verlegd_vermelding": _veld("BTW verlegd"),
            "project_tekst": _veld(kop_proj, zekerheid=0.9 if kop_proj else 0.0),
        },
        regels=regels,
        bsn_verwijderd=0,
        volledig=True,
    )


def spot_services_veldvoorstel(**kw) -> dict:
    return bouw_veldvoorstel(
        spot_services_extractie(**kw), vendors=[], taxrates=[HOOG, VERLEGD, NUL], zekerheid_drempel=0.8
    )


class TestVeldvoorstelMarkering:
    def test_twaalf_regels_gelezen_negen_tariefstaffel_bron_compleet(self) -> None:
        vv = spot_services_veldvoorstel()
        assert vv["regelaantal"] == 12 and len(vv["regels"]) == 12  # de bron blijft compleet
        assert vv["tariefstaffel_aantal"] == 9
        vlaggen = [r[vr.VLAG_TARIEFSTAFFEL] for r in vv["regels"]]
        assert vlaggen == [False, True, True, True, False, True, True, True, False, True, True, True]
        # De staffels dragen hun stuksprijs (tariefkaart) nog gewoon.
        assert vv["regels"][1]["stuksprijs"] == "50.00" and vv["regels"][1]["eenheid"] == "uur"

    def test_regelsom_klopt_op_excl_basis_met_verlegd(self) -> None:
        vv = spot_services_veldvoorstel()
        controle = vv["controle"]
        # Btw per regel ontbreekt op twee regels → basis excl: Σnetto (4320) vs totaal excl (4320).
        assert controle["regelsom_basis"] == "excl"
        assert controle["regelsom"] == "4320.00" and controle["regelsom_wijkt_af"] is False
        assert vv["btw_verlegd_vermelding"] == "BTW verlegd"
        # 0 % blijft in de controlelaag leeg (btw_nul) — het verlegd-voorstel komt pas bij de prefill.
        assert vv["regels"][0]["taxrate_id"] is None and vv["regels"][0]["btw_afleiding_reden"] == "btw_nul"


class TestBoekbareRegels:
    def test_drie_boekbare_regels_som_ongewijzigd(self) -> None:
        vv = spot_services_veldvoorstel()
        boekbaar = vr.boekbare_regels(vv)
        assert [r["omschrijving"] for r in boekbaar] == [
            "Inhuur montage steiger week 35",
            "Inhuur demontage steiger week 35",
            "Transport materieel",
        ]
        assert sum(Decimal(r["netto_bedrag"]) for r in boekbaar) == Decimal("4320.00")

    def test_negatieve_regel_en_gratis_regel_blijven(self) -> None:
        assert not vr.is_nulregel(netto=Decimal("-56.44"), btw=Decimal("0"), hoeveelheid=Decimal("0"))
        assert not vr.is_nulregel(netto=Decimal("0"), btw=Decimal("0"), hoeveelheid=Decimal("1"))  # gratis levering
        assert not vr.is_nulregel(netto=None, btw=None, hoeveelheid=None)  # niets gelezen ≠ nulregel
        assert vr.is_nulregel(netto=Decimal("0"), btw=None, hoeveelheid=None)
        assert vr.is_nulregel(netto=Decimal("0.00"), btw=Decimal("0"), hoeveelheid=Decimal("0"))

    def test_ouder_veldvoorstel_zonder_vlag_krijgt_hetzelfde_predicaat(self) -> None:
        oud = {
            "regels": [
                {"omschrijving": "Echt", "netto_bedrag": "100.00", "btw_bedrag": "21.00", "hoeveelheid": "1"},
                {"omschrijving": "Staffel", "netto_bedrag": "0.00", "btw_bedrag": "0.00", "hoeveelheid": "0,00"},
                {"omschrijving": "Staffel 2", "netto_bedrag": "0.00", "btw_bedrag": None, "hoeveelheid": ""},
            ]
        }
        assert [r["omschrijving"] for r in vr.boekbare_regels(oud)] == ["Echt"]

    def test_louter_nulregels_blijven_staan(self) -> None:
        alleen_nul = {"regels": [{"netto_bedrag": "0.00", "btw_bedrag": "0.00", "hoeveelheid": "0"}]}
        assert vr.boekbare_regels(alleen_nul) == alleen_nul["regels"]  # nooit stil een leeg voorstel

    def test_parse_hoeveelheid(self) -> None:
        assert vr.parse_hoeveelheid("0") == 0 and vr.parse_hoeveelheid("0,00") == 0
        assert vr.parse_hoeveelheid("12 st") == 12 and vr.parse_hoeveelheid("3x") == 3
        assert vr.parse_hoeveelheid("") is None and vr.parse_hoeveelheid(None) is None
        assert vr.parse_hoeveelheid("uur") is None


class TestKopProjectTekst:
    def test_kop_wint(self) -> None:
        assert vr.kop_project_tekst(spot_services_veldvoorstel(kop_proj="26050")) == "26050"

    def test_enig_regelnummer_wordt_kop(self) -> None:
        assert vr.kop_project_tekst(spot_services_veldvoorstel()) == "26049"

    def test_twee_verschillende_regelnummers_geen_default(self) -> None:
        vv = spot_services_veldvoorstel()
        vv["regels"][4]["project_tekst"] = "26051"
        assert vr.kop_project_tekst(vv) is None

    def test_zelfde_nummer_anders_geschreven_is_een(self) -> None:
        vv = spot_services_veldvoorstel()
        vv["regels"][4]["project_tekst"] = " 26049 "
        assert vr.kop_project_tekst(vv) == "26049"

    def test_nummer_alleen_op_een_tariefstaffel_telt_niet(self) -> None:
        vv = spot_services_veldvoorstel(regel1_proj=None)
        vv["regels"][1]["project_tekst"] = "26049"
        assert vr.kop_project_tekst(vv) is None
