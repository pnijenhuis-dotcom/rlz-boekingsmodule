"""Deterministische extractie-terugval — pure logica (best-practice-besluit 2, 31-08): leren uit N
bevestigde documenten, alles-of-niets-validatie bij toepassen (cent-exact, vormpatroon, percentage),
crediteur-herkenning zonder AI. Geen DB, geen AI."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.extractie import template_terugval as tt
from app.extractie.controle import VendorKandidaat
from tests.extractie.pdf_helper import maak_tekst_pdf

D = Decimal


def _tekst(*regels: str, modus: str = "layout") -> tt.Tekstlaag:
    return tt.Tekstlaag(regels=tuple(regels), modus=modus)


def _factuur_tekst(
    nr: str, dat: str, verval: str, excl: str, btw: str, incl: str, *, incl_label: str = "Totaal incl. btw"
) -> tt.Tekstlaag:
    """Layout-tekst zoals pypdf 'm oplevert: kolomkoppen boven de waarden, totalen met label ervoor."""
    return _tekst(
        "Bouwmaat Nederland B.V.",
        "Btw-nummer: NL001234567B01   KvK 12345678   IBAN NL91ABNA0417164300",
        "Factuurnummer                Factuurdatum               Vervaldatum",
        f"{nr:<29}{dat:<27}{verval}",
        "Omschrijving                Bedrag",
        f"Huur kantoorruimte     € {excl}",
        f"Totaal excl. btw   € {excl}",
        f"BTW 21%           € {btw}",
        f"{incl_label}   € {incl}",
    )


def _doc(
    nr: str,
    dat: str,
    verval: str | None,
    excl: str,
    btw: str,
    incl: str,
    *,
    tekst: tt.Tekstlaag | None = None,
    regels=None,
) -> tt.Leerdocument:
    tekst = tekst or _factuur_tekst(nr, dat, verval or "", excl, btw, incl)
    e, b, i = tt.parse_bedrag_tekst(excl), tt.parse_bedrag_tekst(btw), tt.parse_bedrag_tekst(incl)
    assert e is not None and b is not None and i is not None
    return tt.Leerdocument(
        document_id=nr,
        tekst=tekst,
        factuurnummer=nr,
        factuurdatum=tt.parse_datum_tekst(dat) or date.min,
        vervaldatum=tt.parse_datum_tekst(verval) if verval else None,
        totaal_excl=e,
        btw_bedrag=b,
        totaal_incl=i,
        regels=tuple(regels) if regels is not None else (tt.BevestigdeRegel(e, b, "Huur kantoorruimte"),),
    )


_DRIE = [
    _doc("F-2026-042", "01-06-2026", "30-06-2026", "1.000,00", "210,00", "1.210,00"),
    _doc("F-2026-051", "01-07-2026", "31-07-2026", "1.000,00", "210,00", "1.210,00"),
    _doc("F-2026-063", "01-08-2026", "31-08-2026", "1.050,00", "220,50", "1.270,50"),
]


class TestParsen:
    @pytest.mark.parametrize(
        ("ruw", "verwacht"),
        [
            ("1.234,56", "1234.56"),
            ("1234,56", "1234.56"),
            ("1,234.56", "1234.56"),
            ("1234.56", "1234.56"),
            ("€ 12,00", "12.00"),
            ("-25,00", "-25.00"),
            ("− 25,00", "-25.00"),
        ],
    )
    def test_bedrag_nl_en_en_notatie(self, ruw: str, verwacht: str) -> None:
        assert tt.parse_bedrag_tekst(ruw) == D(verwacht)

    def test_bedrag_zonder_centen_of_onzin_is_none(self) -> None:
        assert tt.parse_bedrag_tekst("1234") is None
        assert tt.parse_bedrag_tekst("abc") is None
        assert tt.parse_bedrag_tekst("1,2345") is None

    @pytest.mark.parametrize(
        ("ruw", "verwacht"),
        [
            ("2026-08-01", date(2026, 8, 1)),
            ("01-08-2026", date(2026, 8, 1)),
            ("1/8/2026", date(2026, 8, 1)),
            ("01.08.2026", date(2026, 8, 1)),
            ("1 augustus 2026", date(2026, 8, 1)),
            ("1 aug 2026", date(2026, 8, 1)),
            ("1 August 2026", date(2026, 8, 1)),
        ],
    )
    def test_datum_formaten(self, ruw: str, verwacht: date) -> None:
        assert tt.parse_datum_tekst(ruw) == verwacht

    def test_datum_onplausibel_is_none(self) -> None:
        assert tt.parse_datum_tekst("31-02-2026") is None
        assert tt.parse_datum_tekst("01-08-1926") is None
        assert tt.parse_datum_tekst("1 foo 2026") is None


class TestVormpatroon:
    def test_gelijke_structuur_geeft_vaste_lengtes(self) -> None:
        vorm = tt.leer_vorm(["F-2026-042", "F-2026-051", "F-2026-063"])
        assert vorm == r"[A-Za-z]{1}\-\d{4}\-\d{3}"

    def test_wisselende_lengte_wordt_plus(self) -> None:
        vorm = tt.leer_vorm(["INV-12", "INV-1234"])
        assert vorm == r"[A-Za-z]{3}\-\d+"

    def test_verschillende_structuur_wordt_generiek(self) -> None:
        assert tt.leer_vorm(["F-1", "20260801"]) == tt._GENERIEKE_VORM


class TestLeren:
    def test_drie_documenten_geven_een_volledig_template(self) -> None:
        resultaat = tt.leer_template(_DRIE)
        assert resultaat.reden is None
        definitie = resultaat.definitie
        assert definitie is not None
        assert definitie["tekst_modus"] == "layout"
        assert set(definitie["velden"]) == set(tt.KOPVELDEN)
        # Kolomkoppen voor de datums (layout), labels ervoor voor de totalen.
        assert definitie["velden"]["factuurdatum"] == {"soort": "kolomkop", "anker": ["Factuurdatum"]}
        assert definitie["velden"]["vervaldatum"] == {"soort": "kolomkop", "anker": ["Vervaldatum"]}
        assert definitie["velden"]["totaal_incl"]["soort"] == "prefix"
        assert definitie["velden"]["factuurnummer"]["vorm"] == r"[A-Za-z]{1}\-\d{4}\-\d{3}"
        assert definitie["btw_percentages"] == ["21"]
        assert definitie["regels_modus"] == "enkel"
        assert definitie["regel_omschrijving"] == "Huur kantoorruimte"

    def test_te_weinig_documenten_geen_template(self) -> None:
        resultaat = tt.leer_template(_DRIE[:2])
        assert resultaat.definitie is None
        assert "te weinig" in (resultaat.reden or "")

    def test_een_veld_zonder_reproduceerbaar_anker_geeft_geen_template(self) -> None:
        # Derde document zonder vervaldatum-kolom: het anker reproduceert niet in álle documenten.
        afwijkend = _factuur_tekst("F-2026-063", "01-08-2026", "", "1.050,00", "220,50", "1.270,50")
        docs = _DRIE[:2] + [
            _doc("F-2026-063", "01-08-2026", "31-08-2026", "1.050,00", "220,50", "1.270,50", tekst=afwijkend)
        ]
        resultaat = tt.leer_template(docs)
        assert resultaat.definitie is None  # nooit een gedeeltelijk template
        assert "vervaldatum" in (resultaat.reden or "")

    def test_bevestigde_totalen_die_niet_sluiten_zijn_geen_leerbron(self) -> None:
        kapot = tt.Leerdocument(
            document_id="x",
            tekst=_DRIE[0].tekst,
            factuurnummer="F-2026-042",
            factuurdatum=date(2026, 6, 1),
            vervaldatum=date(2026, 6, 30),
            totaal_excl=D("1000.00"),
            btw_bedrag=D("210.00"),
            totaal_incl=D("1210.01"),
        )
        resultaat = tt.leer_template([kapot, *_DRIE[1:]])
        assert resultaat.definitie is None
        assert "sluiten niet" in (resultaat.reden or "")

    def test_vervaldatum_overal_afwezig_is_toegestaan(self) -> None:
        docs = [
            _doc(nr, dat, None, excl, btw, incl, tekst=_factuur_tekst(nr, dat, "", excl, btw, incl))
            for nr, dat, excl, btw, incl in [
                ("F-1", "01-06-2026", "100,00", "21,00", "121,00"),
                ("F-2", "01-07-2026", "100,00", "21,00", "121,00"),
                ("F-3", "01-08-2026", "100,00", "21,00", "121,00"),
            ]
        ]
        definitie = tt.leer_template(docs).definitie
        assert definitie is not None
        assert definitie["velden"]["vervaldatum"] == {"soort": "afwezig"}
        uitkomst = tt.pas_template_toe(definitie, _factuur_tekst("F-4", "01-09-2026", "", "100,00", "21,00", "121,00"))
        assert uitkomst.vervaldatum is None

    def test_btw_nul_overal_wordt_nul_regel(self) -> None:
        docs = [
            _doc(nr, dat, verval, excl, "0,00", excl, tekst=_factuur_tekst(nr, dat, verval, excl, "verlegd", excl))
            for nr, dat, verval, excl in [
                ("F-1", "01-06-2026", "30-06-2026", "100,00"),
                ("F-2", "01-07-2026", "31-07-2026", "100,00"),
                ("F-3", "01-08-2026", "31-08-2026", "150,00"),
            ]
        ]
        definitie = tt.leer_template(docs).definitie
        assert definitie is not None
        assert definitie["velden"]["btw_bedrag"] == {"soort": "nul"}
        assert definitie["btw_percentages"] == ["0"]
        uitkomst = tt.pas_template_toe(
            definitie, _factuur_tekst("F-4", "01-09-2026", "30-09-2026", "200,00", "verlegd", "200,00")
        )
        assert uitkomst.btw_bedrag == D("0.00") and uitkomst.totaal_incl == D("200.00")

    def test_meerdere_regels_geeft_kop_only(self) -> None:
        regels = (tt.BevestigdeRegel(D("600.00"), D("126.00"), "A"), tt.BevestigdeRegel(D("400.00"), D("84.00"), "B"))
        docs = [
            _doc("F-2026-042", "01-06-2026", "30-06-2026", "1.000,00", "210,00", "1.210,00", regels=regels),
            _doc("F-2026-051", "01-07-2026", "31-07-2026", "1.000,00", "210,00", "1.210,00", regels=regels),
            _doc("F-2026-063", "01-08-2026", "31-08-2026", "1.000,00", "210,00", "1.210,00", regels=regels),
        ]
        definitie = tt.leer_template(docs).definitie
        assert definitie is not None
        assert definitie["regels_modus"] == "geen"
        assert tt.pas_template_toe(definitie, _DRIE[0].tekst).regels == ()

    def test_echte_pdf_tekstlaag_leert_en_reproduceert(self) -> None:
        """Volledige keten op échte PDF-bytes (pypdf layout-modus): dezelfde factuur als bytes."""

        def pdf(nr: str, dat: str, verval: str, excl: str, btw: str, incl: str) -> bytes:
            return maak_tekst_pdf(
                [
                    "Bouwmaat Nederland B.V.",
                    "Btw-nummer: NL001234567B01",
                    [(50, "Factuurnummer"), (200, "Factuurdatum"), (350, "Vervaldatum")],
                    [(50, nr), (200, dat), (350, verval)],
                    f"Totaal excl. btw   € {excl}",
                    f"BTW 21%           € {btw}",
                    f"Totaal incl. btw   € {incl}",
                ]
            )

        docs = []
        for nr, dat, verval, excl, btw, incl in [
            ("F-2026-042", "01-06-2026", "30-06-2026", "1.000,00", "210,00", "1.210,00"),
            ("F-2026-051", "01-07-2026", "31-07-2026", "1.000,00", "210,00", "1.210,00"),
            ("F-2026-063", "01-08-2026", "31-08-2026", "1.050,00", "220,50", "1.270,50"),
        ]:
            tekst = tt.lees_tekstlaag(pdf(nr, dat, verval, excl, btw, incl))
            assert tekst is not None and tekst.modus == "layout"
            docs.append(_doc(nr, dat, verval, excl, btw, incl, tekst=tekst))
        definitie = tt.leer_template(docs).definitie
        assert definitie is not None
        for doc in docs:
            assert tt.reproduceert(definitie, doc)
        vierde = tt.lees_tekstlaag(pdf("F-2026-071", "01-09-2026", "30-09-2026", "1.050,00", "220,50", "1.270,50"))
        assert vierde is not None
        uitkomst = tt.pas_template_toe(definitie, vierde)
        assert (uitkomst.factuurnummer, uitkomst.factuurdatum, uitkomst.totaal_incl) == (
            "F-2026-071",
            date(2026, 9, 1),
            D("1270.50"),
        )

    def test_pdf_zonder_tekstlaag_is_none(self) -> None:
        assert tt.lees_tekstlaag(b"%PDF-1.4 geen echte pdf") is None
        assert tt.lees_tekstlaag(maak_tekst_pdf(["x"])) is None  # te weinig tekst om als tekstlaag te tellen


class TestToepassenAllesOfNiets:
    @pytest.fixture
    def definitie(self) -> dict:
        definitie = tt.leer_template(_DRIE).definitie
        assert definitie is not None
        return definitie

    def test_nieuw_document_wordt_volledig_geparst(self, definitie: dict) -> None:
        uitkomst = tt.pas_template_toe(
            definitie, _factuur_tekst("F-2026-071", "01-09-2026", "30-09-2026", "1.050,00", "220,50", "1.270,50")
        )
        assert uitkomst.factuurnummer == "F-2026-071"
        assert uitkomst.vervaldatum == date(2026, 9, 30)
        assert (uitkomst.totaal_excl, uitkomst.btw_bedrag, uitkomst.totaal_incl) == (
            D("1050.00"),
            D("220.50"),
            D("1270.50"),
        )
        assert uitkomst.btw_percentage == "21"
        assert uitkomst.regels == (tt.TemplateRegel(D("1050.00"), D("220.50"), "Huur kantoorruimte"),)

    def test_een_cent_verschil_verwerpt_alles(self, definitie: dict) -> None:
        with pytest.raises(tt.TemplateVerworpen, match="≠ incl"):
            tt.pas_template_toe(
                definitie, _factuur_tekst("F-2026-071", "01-09-2026", "30-09-2026", "1.050,00", "220,51", "1.270,50")
            )

    def test_referentie_buiten_vormpatroon_verwerpt(self, definitie: dict) -> None:
        with pytest.raises(tt.TemplateVerworpen, match="patroon"):
            tt.pas_template_toe(
                definitie, _factuur_tekst("2026071", "01-09-2026", "30-09-2026", "1.050,00", "220,50", "1.270,50")
            )

    def test_layoutwijziging_label_weg_verwerpt(self, definitie: dict) -> None:
        with pytest.raises(tt.TemplateVerworpen, match="totaal_incl niet gevonden"):
            tt.pas_template_toe(
                definitie,
                _factuur_tekst(
                    "F-2026-071", "01-09-2026", "30-09-2026", "1.050,00", "220,50", "1.270,50", incl_label="Te betalen"
                ),
            )

    def test_percentage_buiten_geleerde_set_verwerpt(self, definitie: dict) -> None:
        with pytest.raises(tt.TemplateVerworpen, match="btw-percentage"):
            tt.pas_template_toe(
                definitie, _factuur_tekst("F-2026-071", "01-09-2026", "30-09-2026", "1.000,00", "90,00", "1.090,00")
            )

    def test_vervaldatum_voor_factuurdatum_verwerpt(self, definitie: dict) -> None:
        with pytest.raises(tt.TemplateVerworpen, match="vervaldatum"):
            tt.pas_template_toe(
                definitie, _factuur_tekst("F-2026-071", "01-09-2026", "30-08-2026", "1.050,00", "220,50", "1.270,50")
            )

    def test_andere_tekstmodus_verwerpt(self, definitie: dict) -> None:
        with pytest.raises(tt.TemplateVerworpen, match="modus"):
            tt.pas_template_toe(definitie, _tekst("x", modus="plain"))

    def test_reproduceert_toetst_exact_tegen_bevestigde_waarden(self, definitie: dict) -> None:
        assert tt.reproduceert(definitie, _DRIE[2])
        gecorrigeerd = tt.Leerdocument(
            document_id="c",
            tekst=_DRIE[2].tekst,
            factuurnummer="F-2026-063-A",  # controleur wijzigde de referentie
            factuurdatum=_DRIE[2].factuurdatum,
            vervaldatum=_DRIE[2].vervaldatum,
            totaal_excl=_DRIE[2].totaal_excl,
            btw_bedrag=_DRIE[2].btw_bedrag,
            totaal_incl=_DRIE[2].totaal_incl,
        )
        assert not tt.reproduceert(definitie, gecorrigeerd)


class TestPrefixEnVorigeRegel:
    def test_label_op_vorige_regel(self) -> None:
        def tekst(nr: str, dat: str, incl: str, excl: str, btw: str) -> tt.Tekstlaag:
            return _tekst(
                "Factuurnummer", nr, "Factuurdatum", dat, "Excl. btw", excl, "Btw", btw, "Totaal", incl, modus="plain"
            )

        docs = [
            _doc(
                "A1",
                "01-06-2026",
                None,
                "100,00",
                "21,00",
                "121,00",
                tekst=tekst("A1", "01-06-2026", "121,00", "100,00", "21,00"),
            ),
            _doc(
                "A2",
                "01-07-2026",
                None,
                "100,00",
                "21,00",
                "121,00",
                tekst=tekst("A2", "01-07-2026", "121,00", "100,00", "21,00"),
            ),
            _doc(
                "A3",
                "01-08-2026",
                None,
                "200,00",
                "42,00",
                "242,00",
                tekst=tekst("A3", "01-08-2026", "242,00", "200,00", "42,00"),
            ),
        ]
        definitie = tt.leer_template(docs).definitie
        assert definitie is not None
        assert definitie["velden"]["factuurnummer"]["soort"] == "vorige_regel"
        uitkomst = tt.pas_template_toe(definitie, tekst("A4", "01-09-2026", "363,00", "300,00", "63,00"))
        assert (uitkomst.factuurnummer, uitkomst.totaal_incl) == ("A4", D("363.00"))


class TestHerkenCrediteur:
    VENDOR_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
    VENDOR_B = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")

    def test_btw_nummer_wint(self) -> None:
        kandidaten = [
            VendorKandidaat(self.VENDOR_A, "Bouwmaat Nederland B.V.", btw_nummer="NL001234567B01"),
            VendorKandidaat(self.VENDOR_B, "Andere B.V.", btw_nummer="NL999999999B01"),
        ]
        h = tt.herken_crediteur(_DRIE[0].tekst, kandidaten)
        assert h is not None and (h.vendor_id, h.soort) == (self.VENDOR_A, "btw_nummer")

    def test_kvk_dan_iban_dan_naam(self) -> None:
        op_kvk = tt.herken_crediteur(_DRIE[0].tekst, [VendorKandidaat(self.VENDOR_A, "X", kvk_nummer="12345678")])
        assert op_kvk is not None and op_kvk.soort == "kvk_nummer"
        op_iban = tt.herken_crediteur(
            _DRIE[0].tekst, [VendorKandidaat(self.VENDOR_A, "X")], ibans={"NL91ABNA0417164300": self.VENDOR_A}
        )
        assert op_iban is not None and op_iban.soort == "iban"
        op_naam = tt.herken_crediteur(_DRIE[0].tekst, [VendorKandidaat(self.VENDOR_A, "Bouwmaat Nederland BV")])
        assert op_naam is not None and op_naam.soort == "naam"

    def test_twijfel_geeft_geen_herkenning(self) -> None:
        dubbel = [
            VendorKandidaat(self.VENDOR_A, "Bouwmaat Nederland B.V.", btw_nummer="NL001234567B01"),
            VendorKandidaat(self.VENDOR_B, "Bouwmaat Nederland", btw_nummer="NL001234567B01"),
        ]
        assert tt.herken_crediteur(_DRIE[0].tekst, dubbel) is None
        assert tt.herken_crediteur(_DRIE[0].tekst, [VendorKandidaat(self.VENDOR_A, "Onbekend B.V.")]) is None
