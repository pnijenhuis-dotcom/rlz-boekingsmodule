"""BUG 18-09 (Peter, casus Zilver Horeca Fac-25-022711, BLOW): de factuur draagt per regel een btw-KOLOM "9%"/"0%" en geen
btw-bedrag; de kop draagt geen totaal, de meegefotografeerde pinbon wél ("Totaal: 738,27 EUR"); twee regelbedragen liggen
onder de bon. Deterministisch (code, geen AI):
- `parse_btw_kolom_percentage` + `leid_btw_af_uit_kolom`: kolom "0%" IS een basis → "NL, Nul tarief" (nooit verlegd/vrijgesteld
  raden), "9%" → het laag-tarief (favoriet wint bij twee 9 %-codes); regel-btw = netto × p (`btw_bedrag_berekend`).
- `toets_pinbon_totaal`: bon = Σ(netto + btw) binnen 5 ct → groen en als factuurtotaal voorgesteld (`totaal_bron` "pinbon");
  regels zonder bedrag → niet toetsbaar (oranje, niets overgenomen); som sluit niet → afwijkend.
- `ng` (niet gelezen) → `bedrag_niet_gelezen` op de regel i.p.v. een kale lege cel.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.extractie.controle import (
    BTW_BRON_FACTUUR_REGEL,
    PINBON_AFWIJKEND,
    PINBON_GROEN,
    PINBON_NIET_TOETSBAAR,
    TaxRateKandidaat,
    bouw_veldvoorstel,
    leid_btw_af_uit_kolom,
    parse_btw_kolom_percentage,
    toets_pinbon_totaal,
)
from app.extractie.service import AiFactuurExtractie, AiRegel, AiVeld

LAAG = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000009")
LAAG_VOORUIT = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000019")
NUL = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000000")
ZELF = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000100")
VERLEGD = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000200")
VRIJ = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000300")
HOOG = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000021")

# De BLOW-tarieven zoals gesynct (STAP-0 18-09, replica): twee 9 %-codes (favoriet "NL, Laag tarief"), twee 0 %-codes waarvan
# "BTW-bedrag zelf specificeren" gemengd is, verlegd en vrijgesteld op 0 %.
KANDIDATEN = [
    TaxRateKandidaat(id=HOOG, percentage=Decimal("0.2100"), is_favoriet=True),
    TaxRateKandidaat(id=LAAG, percentage=Decimal("0.0900"), is_favoriet=True),
    TaxRateKandidaat(id=LAAG_VOORUIT, percentage=Decimal("0.0900"), is_favoriet=False),
    TaxRateKandidaat(id=NUL, percentage=Decimal("0.0000"), is_favoriet=False),
    TaxRateKandidaat(id=ZELF, percentage=Decimal("0.0000"), is_favoriet=True, is_gemengd=True),
    TaxRateKandidaat(id=VERLEGD, percentage=Decimal("0.0000"), is_verlegd=True),
    TaxRateKandidaat(id=VRIJ, percentage=Decimal("0.0000"), is_vrijgesteld=True),
]


def _veld(waarde: str | None, zekerheid: float = 0.95) -> AiVeld:
    return AiVeld(waarde=waarde, zekerheid=zekerheid)


def _regel(o: str, n: str | None, bc: str | None, *, ng: str | None = None) -> AiRegel:
    return AiRegel(
        omschrijving=o, netto_bedrag=n, btw_bedrag=None, hoeveelheid="1", zekerheid=0.9, btw_kolom=bc, niet_gelezen=ng
    )


def _extractie(
    regels: list[AiRegel], *, pinbon: str | None = None, totaal_incl: str | None = None
) -> AiFactuurExtractie:
    kop = {
        "leverancier_naam": _veld("Zilver Horeca B.V."),
        "factuurnummer": _veld("Fac-25-022711"),
        "factuurdatum": _veld("2025-12-17"),
        "totaal_incl": _veld(totaal_incl),
        "totaal_pinbon": _veld(pinbon),
    }
    return AiFactuurExtractie(kop=kop, regels=regels, bsn_verwijderd=0, volledig=True)


class TestKolomPercentage:
    def test_parse(self) -> None:
        assert parse_btw_kolom_percentage("9%") == Decimal("0.0900")
        assert parse_btw_kolom_percentage("0 %") == Decimal("0")
        assert parse_btw_kolom_percentage("21,0%") == Decimal("0.2100")
        # Kolomcodes en kale cijfers zijn géén percentage (een "1" kan een RLZ-code zijn).
        assert parse_btw_kolom_percentage("V") is None
        assert parse_btw_kolom_percentage("vrij") is None
        assert parse_btw_kolom_percentage("9") is None
        assert parse_btw_kolom_percentage("") is None and parse_btw_kolom_percentage(None) is None

    def test_nul_procent_is_het_nul_tarief_nooit_verlegd_of_vrijgesteld(self) -> None:
        afleiding = leid_btw_af_uit_kolom(Decimal("0"), KANDIDATEN)
        assert (afleiding.taxrate_id, afleiding.bron) == (NUL, BTW_BRON_FACTUUR_REGEL)

    def test_negen_procent_favoriet_wint_bij_twee_codes(self) -> None:
        assert leid_btw_af_uit_kolom(Decimal("0.09"), KANDIDATEN).taxrate_id == LAAG

    def test_geen_match_en_meerduidig_blijven_leeg(self) -> None:
        assert leid_btw_af_uit_kolom(Decimal("0.06"), KANDIDATEN).reden == "geen_match"
        twee_favorieten = [
            TaxRateKandidaat(id=LAAG, percentage=Decimal("0.09"), is_favoriet=True),
            TaxRateKandidaat(id=LAAG_VOORUIT, percentage=Decimal("0.09"), is_favoriet=True),
        ]
        assert leid_btw_af_uit_kolom(Decimal("0.09"), twee_favorieten).reden == "meerduidig"


class TestVeldvoorstelZilverHoreca:
    def test_regels_krijgen_kolomtarief_en_berekende_btw(self) -> None:
        vv = bouw_veldvoorstel(
            _extractie([_regel("Twix 32 x 50 gram", "17.95", "9%"), _regel("Emballage ( 24 Stuks )", "10.80", "0%")]),
            vendors=[],
            taxrates=KANDIDATEN,
            zekerheid_drempel=0.8,
        )
        twix, emballage = vv["regels"]
        assert (twix["taxrate_id"], twix["btw_bron"], twix["btw_afleiding_basis"]) == (
            str(LAAG),
            BTW_BRON_FACTUUR_REGEL,
            "kolom",
        )
        assert (twix["btw_bedrag"], twix["btw_bedrag_berekend"], twix["btw_kolom_percentage"]) == (
            "1.62",
            True,
            "0.0900",
        )
        assert (emballage["taxrate_id"], emballage["btw_bedrag"]) == (str(NUL), "0.00")
        assert emballage["btw_kolom_percentage"] == "0.0000"
        assert twix["btw_afleiding_reden"] is None and emballage["btw_afleiding_reden"] is None

    def test_regel_met_gelezen_btw_houdt_de_bedrag_afleiding(self) -> None:
        regel = AiRegel(
            omschrijving="Redbull",
            netto_bedrag="100.00",
            btw_bedrag="21.00",
            hoeveelheid="1",
            zekerheid=0.9,
            btw_kolom="9%",
        )
        vv = bouw_veldvoorstel(_extractie([regel]), vendors=[], taxrates=KANDIDATEN, zekerheid_drempel=0.8)
        # netto × tarief ≈ btw wint (regel-bewijs); de kolom komt pas aan bod als dat niets oplevert.
        assert (vv["regels"][0]["taxrate_id"], vv["regels"][0]["btw_afleiding_basis"]) == (str(HOOG), "regel")
        assert vv["regels"][0]["btw_bedrag_berekend"] is False

    def test_afgedekt_bedrag_is_zichtbaar_niet_gelezen(self) -> None:
        vv = bouw_veldvoorstel(
            _extractie(
                [_regel("Balisto Yobbery 20 x 37 Gr", None, "9%", ng="afgedekt"), _regel("Twix", "17.95", "9%")]
            ),
            vendors=[],
            taxrates=KANDIDATEN,
            zekerheid_drempel=0.8,
        )
        balisto, twix = vv["regels"]
        assert (balisto["bedrag_niet_gelezen"], balisto["niet_gelezen_reden"]) == (True, "afgedekt")
        # Geen bedrag = geen btw-BEDRAG; de kolom "9%" is wél een feit van de factuur → de btw-code staat klaar voor de mens.
        assert balisto["netto_bedrag"] is None and balisto["btw_bedrag"] is None
        assert (balisto["taxrate_id"], balisto["btw_bron"]) == (str(LAAG), BTW_BRON_FACTUUR_REGEL)
        assert (twix["bedrag_niet_gelezen"], twix["niet_gelezen_reden"]) == (False, None)

    def test_pinbon_niet_toetsbaar_bij_regels_zonder_bedrag_dus_geen_totaal(self) -> None:
        vv = bouw_veldvoorstel(
            _extractie([_regel("Balisto", None, "9%", ng="afgedekt"), _regel("Twix", "17.95", "9%")], pinbon="738.27"),
            vendors=[],
            taxrates=KANDIDATEN,
            zekerheid_drempel=0.8,
        )
        assert vv["totaal_incl"] is None and vv["totaal_bron"] is None
        assert (vv["totaal_pinbon"], vv["totaal_pinbon_status"]) == ("738.27", PINBON_NIET_TOETSBAAR)

    def test_pinbon_groen_wordt_het_factuurtotaal(self) -> None:
        # 17,95 × 1,09 = 19,57 + 10,80 (0 %) = 30,37 — de bon zegt 30,37.
        vv = bouw_veldvoorstel(
            _extractie([_regel("Twix", "17.95", "9%"), _regel("Emballage", "10.80", "0%")], pinbon="30.37"),
            vendors=[],
            taxrates=KANDIDATEN,
            zekerheid_drempel=0.8,
        )
        assert (vv["totaal_incl"], vv["totaal_bron"], vv["totaal_pinbon_status"]) == ("30.37", "pinbon", PINBON_GROEN)
        assert vv["controle"]["regelsom_wijkt_af"] is False  # de regelsom-badge sluit op het bon-totaal

    def test_pinbon_afwijkend_blijft_oranje_en_neemt_niets_over(self) -> None:
        vv = bouw_veldvoorstel(
            _extractie([_regel("Twix", "17.95", "9%"), _regel("Emballage", "10.80", "0%")], pinbon="35.00"),
            vendors=[],
            taxrates=KANDIDATEN,
            zekerheid_drempel=0.8,
        )
        assert vv["totaal_incl"] is None and vv["totaal_bron"] is None
        assert (vv["totaal_pinbon_status"], vv["totaal_pinbon_verschil"]) == (PINBON_AFWIJKEND, "4.63")

    def test_gelezen_factuurtotaal_wint_van_de_bon(self) -> None:
        vv = bouw_veldvoorstel(
            _extractie([_regel("Twix", "17.95", "9%")], pinbon="19.57", totaal_incl="19.57"),
            vendors=[],
            taxrates=KANDIDATEN,
            zekerheid_drempel=0.8,
        )
        assert (vv["totaal_incl"], vv["totaal_bron"]) == ("19.57", "factuur")


class TestPinbonToets:
    def test_zonder_bon_geen_status(self) -> None:
        assert toets_pinbon_totaal(netto=[Decimal("1")], btw=[Decimal("0")], totaal_pinbon=None).status is None

    def test_vijf_cent_marge(self) -> None:
        groen = toets_pinbon_totaal(netto=[Decimal("100.00")], btw=[Decimal("21.00")], totaal_pinbon=Decimal("121.05"))
        rood = toets_pinbon_totaal(netto=[Decimal("100.00")], btw=[Decimal("21.00")], totaal_pinbon=Decimal("121.06"))
        assert (groen.status, rood.status) == (PINBON_GROEN, PINBON_AFWIJKEND)
        assert groen.overnemen and not rood.overnemen
