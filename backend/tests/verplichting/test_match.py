"""Pure match-motor factuur↔verplichting (app/verplichting/match.py) — geen DB, geen AI.

Dekt de beslisboom van CONTRACT_B/mockup ②③: binnen/buiten cumulatief, offertenummer versterkt de
match, meerdere kandidaten + de onthouden keuze, factuur zónder project, verstreken geldigheid, en
het gedrag zodra een verplichting vervalt (de pipeline levert 'm dan niet meer als kandidaat, al
verrekende facturen blijven ongemoeid).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.verplichting import match as m

PROJECT_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
PROJECT_B = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
SLEUTEL = "btw:NL001234567B01"
FACTUURDATUM = date(2026, 9, 4)


def kandidaat(
    *,
    nummer: str | None = "26140-OFF-01",
    project: uuid.UUID | None = PROJECT_A,
    totaal: str | None = "48500.00",
    verbruikt: str = "0.00",
    geldig_tot: date | None = None,
) -> m.Kandidaat:
    return m.Kandidaat(
        document_id=uuid.uuid4(),
        project_id=project,
        offertenummer=nummer,
        soort_label="offerte",
        goedgekeurd_bedrag_excl=Decimal(totaal) if totaal is not None else None,
        verbruikt_bedrag_excl=Decimal(verbruikt),
        geldig_tot=geldig_tot,
    )


def feiten(
    *,
    bedrag: str | None = "12400.00",
    project: uuid.UUID | None = PROJECT_A,
    sleutel: str | None = SLEUTEL,
    teksten: tuple[str, ...] = (),
    eigen_verrekend: str | None = None,
    factuurdatum: date | None = FACTUURDATUM,
) -> m.FactuurFeiten:
    return m.FactuurFeiten(
        document_id=uuid.uuid4(),
        vendor_sleutel=sleutel,
        project_id=project,
        bedrag_excl=Decimal(bedrag) if bedrag is not None else None,
        factuurdatum=factuurdatum,
        teksten=teksten,
        eigen_verrekend=Decimal(eigen_verrekend) if eigen_verrekend is not None else None,
    )


class TestNietToetsbaar:
    def test_zonder_crediteur(self):
        uitkomst = m.bepaal_match(feiten(sleutel=None), [kandidaat()])
        assert uitkomst.uitkomst == m.NIET_TOETSBAAR
        assert "crediteur" in uitkomst.melding

    def test_zonder_bedrag(self):
        uitkomst = m.bepaal_match(feiten(bedrag=None), [kandidaat()])
        assert uitkomst.uitkomst == m.NIET_TOETSBAAR

    def test_kandidaat_zonder_goedgekeurd_bedrag(self):
        uitkomst = m.bepaal_match(feiten(), [kandidaat(totaal=None)])
        assert uitkomst.uitkomst == m.NIET_TOETSBAAR
        assert "geen goedgekeurd bedrag" in uitkomst.melding


class TestGeenKandidaten:
    def test_geen_verplichting_is_stil(self):
        uitkomst = m.bepaal_match(feiten(), [])
        assert uitkomst.uitkomst == m.GEEN_VERPLICHTING
        assert uitkomst.verplichting_document_id is None

    def test_verstreken_geldigheid_is_geen_kandidaat(self):
        """Verstreken t.o.v. de FACTUURDATUM = geen kandidaat; dat is geen_match (er was wel een
        offerte, ze geldt alleen niet meer) — niet stil geen_verplichting."""
        verstreken = kandidaat(geldig_tot=date(2026, 8, 31))
        uitkomst = m.bepaal_match(feiten(), [verstreken])
        assert uitkomst.uitkomst == m.GEEN_MATCH
        assert uitkomst.details["verstreken_kandidaten"] == 1

    def test_geldigheid_op_de_factuurdatum_telt_nog_mee(self):
        nog_geldig = kandidaat(geldig_tot=FACTUURDATUM)
        uitkomst = m.bepaal_match(feiten(), [nog_geldig])
        assert uitkomst.uitkomst == m.BINNEN

    def test_zonder_factuurdatum_wordt_geldigheid_niet_getoetst(self):
        uitkomst = m.bepaal_match(feiten(factuurdatum=None), [kandidaat(geldig_tot=date(2020, 1, 1))])
        assert uitkomst.uitkomst == m.BINNEN


class TestCumulatief:
    def test_binnen_bij_eerste_factuur(self):
        k = kandidaat(totaal="48500.00", verbruikt="14750.00")
        uitkomst = m.bepaal_match(feiten(bedrag="12400.00"), [k])
        assert uitkomst.uitkomst == m.BINNEN
        assert uitkomst.verbruik_voor == Decimal("14750.00")
        assert uitkomst.verbruik_na == Decimal("27150.00")
        assert uitkomst.overschrijding_excl is None
        assert uitkomst.details["percentage_na"] == 56

    def test_exact_op_de_grens_is_binnen(self):
        """③: geen tolerantiemarge, maar de grens ís het offertebedrag — exact gelijk = binnen."""
        k = kandidaat(totaal="48500.00", verbruikt="36100.00")
        uitkomst = m.bepaal_match(feiten(bedrag="12400.00"), [k])
        assert uitkomst.uitkomst == m.BINNEN
        assert uitkomst.verbruik_na == Decimal("48500.00")

    def test_één_cent_erover_is_buiten(self):
        k = kandidaat(totaal="48500.00", verbruikt="36100.01")
        uitkomst = m.bepaal_match(feiten(bedrag="12400.00"), [k])
        assert uitkomst.uitkomst == m.BUITEN
        assert uitkomst.overschrijding_excl == Decimal("0.01")

    def test_buiten_draagt_handelingsperspectief_meerwerk(self):
        k = kandidaat(totaal="48500.00", verbruikt="39500.00")
        uitkomst = m.bepaal_match(feiten(bedrag="12400.00"), [k])
        assert uitkomst.uitkomst == m.BUITEN
        assert uitkomst.overschrijding_excl == Decimal("3400.00")
        assert m.MEERWERK_HANDELING in uitkomst.melding

    def test_herberekening_telt_het_eigen_verrekende_bedrag_niet_dubbel(self):
        """Ná boeken zit het eigen bedrag al in verbruikt_bedrag_excl — een herberekening mag de
        factuur niet nóg eens optellen (dan zou een binnen-factuur plots buiten vallen)."""
        k = kandidaat(totaal="20000.00", verbruikt="12400.00")
        uitkomst = m.bepaal_match(feiten(bedrag="12400.00", eigen_verrekend="12400.00"), [k])
        assert uitkomst.uitkomst == m.BINNEN
        assert uitkomst.verbruik_voor == Decimal("0.00")
        assert uitkomst.verbruik_na == Decimal("12400.00")


class TestSleutels:
    def test_offertenummer_in_de_factuurtekst_versterkt_de_match(self):
        """② — het nummer wijst de kandidaat aan, óók als het project van de factuur bij een
        andere kandidaat hoort."""
        met_nummer = kandidaat(nummer="26140-OFF-01", project=PROJECT_B)
        ander = kandidaat(nummer="26133-OFF-02", project=PROJECT_A)
        uitkomst = m.bepaal_match(
            feiten(project=PROJECT_A, teksten=("Conform uw offerte 26140 OFF 01",)), [met_nummer, ander]
        )
        assert uitkomst.uitkomst == m.BINNEN
        assert uitkomst.verplichting_document_id == met_nummer.document_id
        assert uitkomst.grond == "offertenummer"

    def test_te_kort_offertenummer_is_geen_anker(self):
        kort = kandidaat(nummer="12", project=PROJECT_B)
        ander = kandidaat(nummer="26133-OFF-02", project=PROJECT_A)
        uitkomst = m.bepaal_match(feiten(project=PROJECT_A, teksten=("factuur 12",)), [kort, ander])
        assert uitkomst.verplichting_document_id == ander.document_id
        assert uitkomst.grond == "project"

    def test_project_sleutel_wijst_de_kandidaat_aan(self):
        a = kandidaat(project=PROJECT_A)
        b = kandidaat(nummer="26133-OFF-02", project=PROJECT_B)
        uitkomst = m.bepaal_match(feiten(project=PROJECT_B), [a, b])
        assert uitkomst.verplichting_document_id == b.document_id
        assert uitkomst.grond == "project"

    def test_kandidaten_maar_ander_project_is_geen_match(self):
        uitkomst = m.bepaal_match(feiten(project=PROJECT_B), [kandidaat(project=PROJECT_A)])
        assert uitkomst.uitkomst == m.GEEN_MATCH
        assert "deze leverancier + dit project" in uitkomst.melding

    def test_meerdere_kandidaten_op_hetzelfde_project(self):
        a = kandidaat(nummer="26140-OFF-01")
        b = kandidaat(nummer="26140-OFF-09")
        uitkomst = m.bepaal_match(feiten(), [a, b])
        assert uitkomst.uitkomst == m.MEERDERE_KANDIDATEN
        assert set(uitkomst.kandidaat_ids) == {a.document_id, b.document_id}

    def test_onthouden_keuze_beslist_bij_meerdere_kandidaten(self):
        """② "daarna onthouden": de laatste handmatige koppeling voor dezelfde crediteur + project."""
        a = kandidaat(nummer="26140-OFF-01")
        b = kandidaat(nummer="26140-OFF-09")
        uitkomst = m.bepaal_match(feiten(), [a, b], onthouden_id=b.document_id)
        assert uitkomst.uitkomst == m.BINNEN
        assert uitkomst.verplichting_document_id == b.document_id
        assert uitkomst.grond == "onthouden"

    def test_handmatige_koppeling_wint_altijd(self):
        a = kandidaat(nummer="26140-OFF-01", project=PROJECT_A)
        b = kandidaat(nummer="26133-OFF-02", project=PROJECT_B)
        uitkomst = m.bepaal_match(
            feiten(project=PROJECT_A, teksten=("offerte 26140-OFF-01",)),
            [a, b],
            handmatig_gekoppeld_id=b.document_id,
        )
        assert uitkomst.verplichting_document_id == b.document_id
        assert uitkomst.grond == "handmatig"

    def test_handmatige_koppeling_op_niet_lopende_verplichting_valt_terug(self):
        """Een vervallen/afgewezen verplichting levert de pipeline niet meer als kandidaat — de
        handmatige koppeling verliest dan haar geldigheid en de motor kiest opnieuw."""
        a = kandidaat(project=PROJECT_A)
        uitkomst = m.bepaal_match(feiten(project=PROJECT_A), [a], handmatig_gekoppeld_id=uuid.uuid4())
        assert uitkomst.verplichting_document_id == a.document_id
        assert uitkomst.grond == "project"

    def test_factuur_zonder_project_en_één_kandidaat(self):
        a = kandidaat()
        uitkomst = m.bepaal_match(feiten(project=None), [a])
        assert uitkomst.uitkomst == m.BINNEN
        assert uitkomst.grond == "enige"

    def test_factuur_zonder_project_en_meerdere_kandidaten(self):
        uitkomst = m.bepaal_match(feiten(project=None), [kandidaat(), kandidaat(nummer="26141-OFF-02")])
        assert uitkomst.uitkomst == m.MEERDERE_KANDIDATEN
        assert "geen eenduidig project" in uitkomst.melding


class TestHulpfuncties:
    def test_normaliseer_nummer(self):
        assert m.normaliseer_nummer("26140-OFF-01") == "26140off01"
        assert m.normaliseer_nummer(" 26140 off 01 ") == "26140off01"
        assert m.normaliseer_nummer("A-1") is None  # te kort = geen anker
        assert m.normaliseer_nummer(None) is None

    def test_percentage(self):
        assert m.percentage(Decimal("27150"), Decimal("48500")) == 56
        assert m.percentage(Decimal("51900"), Decimal("48500")) == 107
        assert m.percentage(Decimal("10"), Decimal(0)) is None
        assert m.percentage(None, Decimal("100")) is None

    def test_buiten_offerte_teller_dekt_buiten_en_geen_match(self):
        assert set(m.TELT_ALS_BUITEN_OFFERTE) == {m.BUITEN, m.GEEN_MATCH}


class TestWachtendeVerplichtingEnTermijn:
    """Peter 15-09 (casus Olieman 32948: offerte wachtte op één accordeur → stil `geen_verplichting`)."""

    def _wacht(self, code: str = m.WACHT_NIET_GOEDGEKEURD, nummer: str | None = "OFF-2026-085") -> m.Wachtende:
        reden = (
            "nog niet goedgekeurd (wacht op accordering)"
            if code == m.WACHT_NIET_GOEDGEKEURD
            else "staat op een ander crediteurrecord (Gebr. Olieman) — dubbele crediteur?"
        )
        return m.Wachtende(document_id=uuid.uuid4(), reden_code=code, reden=reden, offertenummer=nummer)

    def test_zonder_kandidaat_maar_met_wachtende_is_zichtbaar_niet_toetsbaar(self):
        w = self._wacht()
        uitkomst = m.bepaal_match(feiten(bedrag="20000.00", project=None), [], wachtende=[w])
        assert uitkomst.uitkomst == m.NIET_TOETSBAAR
        assert uitkomst.verplichting_document_id == w.document_id  # precies één → verwijzing
        assert "gevonden (OFF-2026-085) maar niet toetsbaar: nog niet goedgekeurd (wacht op accordering)" in (
            uitkomst.melding
        )
        assert uitkomst.details["wachtende_reden_code"] == m.WACHT_NIET_GOEDGEKEURD
        assert uitkomst.details["wachtende"] == [str(w.document_id)]

    def test_meerdere_wachtende_geen_verwijzing_wel_beide_redenen(self):
        a, b = self._wacht(), self._wacht(m.WACHT_ANDERE_CREDITEUR, "OFF-2026-090")
        uitkomst = m.bepaal_match(feiten(project=None), [], wachtende=[a, b])
        assert uitkomst.uitkomst == m.NIET_TOETSBAAR and uitkomst.verplichting_document_id is None
        assert "dubbele crediteur" in uitkomst.melding and "wacht op accordering" in uitkomst.melding
        assert uitkomst.details["wachtende_reden_code"] == "meerdere"

    def test_geldige_kandidaat_wint_van_wachtende(self):
        k = kandidaat(project=None, totaal="85000.00")
        uitkomst = m.bepaal_match(feiten(bedrag="20000.00", project=None), [k], wachtende=[self._wacht()])
        assert uitkomst.uitkomst == m.BINNEN and uitkomst.verplichting_document_id == k.document_id

    def test_zonder_wachtende_blijft_geen_verplichting_stil(self):
        assert m.bepaal_match(feiten(project=None), []).uitkomst == m.GEEN_VERPLICHTING

    def test_termijnnummer_in_melding_en_details(self):
        eerste = m.bepaal_match(feiten(bedrag="20000.00", project=None), [kandidaat(project=None, totaal="85000.00")])
        assert eerste.details["termijn"] == 1 and "(1e termijn, € 20.000,00)" in eerste.melding
        assert "€ 20.000,00 van € 85.000,00" in eerste.melding
        basis = kandidaat(project=None, totaal="85000.00", verbruikt="20000.00")
        k2 = m.Kandidaat(**{**basis.__dict__, "aantal_gematcht": 1})
        tweede = m.bepaal_match(feiten(bedrag="30000.00", project=None), [k2])
        assert tweede.details["termijn"] == 2 and "(2e termijn" in tweede.melding
        assert tweede.verbruik_na == Decimal("50000.00")

    def test_ander_project_noemt_de_bestaande_offertes(self):
        uitkomst = m.bepaal_match(feiten(project=PROJECT_B), [kandidaat(project=PROJECT_A)])
        assert uitkomst.uitkomst == m.GEEN_MATCH and "op een ander project (26140-OFF-01)" in uitkomst.melding
        assert uitkomst.details == {"ander_project": True}


class TestOnderwegTeltMee:
    """Peter 18-09 (casus Bouwadvies Oost Nederland, offerte zonder nummer € 1.192.922,50; € 20.000 ter accordering
    + factuur € 50.000 nieuw): verbruik = geboekt + onderweg — "hij moet wel doortellen"."""

    def test_onderweg_telt_op_bij_geboekt_in_verbruik_voor(self):
        k = m.Kandidaat(
            document_id=uuid.uuid4(),
            project_id=PROJECT_A,
            offertenummer=None,
            goedgekeurd_bedrag_excl=Decimal("1192922.50"),
            verbruikt_bedrag_excl=Decimal("0.00"),
            onderweg_bedrag_excl=Decimal("20000.00"),
            onderweg_aantal=1,
            onderweg_ter_accordering=1,
            aantal_gematcht=1,
        )
        uit = m.bepaal_match(feiten(bedrag="50000.00"), [k])
        assert uit.uitkomst == m.BINNEN
        assert uit.verbruik_voor == Decimal("20000.00")
        assert uit.verbruik_na == Decimal("70000.00")
        assert uit.details["verbruik_geboekt"] == "0.00"
        assert uit.details["verbruik_onderweg"] == "20000.00"
        assert uit.details["onderweg_aantal"] == 1
        assert uit.details["onderweg_ter_accordering"] == 1
        assert uit.details["termijn"] == 2
        assert "€ 70.000,00 van € 1.192.922,50" in uit.melding
        assert "waarvan € 20.000,00 nog niet geboekt (1 factuur ter accordering)" in uit.melding

    def test_som_van_geboekt_onderweg_en_eigen_bedrag_beslist_binnen_of_buiten(self):
        # Offerte 60.000: 20.000 onderweg + 50.000 nieuw = 70.000 → buiten, 10.000 over.
        k = kandidaat(totaal="60000.00", verbruikt="0.00")
        k = m.Kandidaat(**{**k.__dict__, "onderweg_bedrag_excl": Decimal("20000.00"), "onderweg_aantal": 1})
        uit = m.bepaal_match(feiten(bedrag="50000.00"), [k])
        assert uit.uitkomst == m.BUITEN
        assert uit.overschrijding_excl == Decimal("10000.00")
        assert "waarvan € 20.000,00 nog niet geboekt (1 factuur in behandeling)" in uit.melding
        # Zonder die onderweg-factuur (afgewezen) past dezelfde factuur wél.
        uit2 = m.bepaal_match(feiten(bedrag="50000.00"), [kandidaat(totaal="60000.00")])
        assert uit2.uitkomst == m.BINNEN
        assert uit2.details["verbruik_onderweg"] == "0.00"
        assert "nog niet geboekt" not in uit2.melding

    def test_geboekt_plus_onderweg_nul_is_het_bestaande_gedrag(self):
        uit = m.bepaal_match(feiten(bedrag="12400.00"), [kandidaat(verbruikt="14750.00")])
        assert uit.verbruik_voor == Decimal("14750.00")
        assert uit.verbruik_na == Decimal("27150.00")
        assert uit.details["verbruik_geboekt"] == "14750.00"
        assert uit.details["verbruik_onderweg"] == "0.00"
        assert uit.details["onderweg_aantal"] == 0

    def test_eigen_verrekend_bedrag_wordt_alleen_van_geboekt_afgetrokken(self):
        k = m.Kandidaat(
            **{
                **kandidaat(verbruikt="12400.00").__dict__,
                "onderweg_bedrag_excl": Decimal("5000.00"),
                "onderweg_aantal": 1,
            }
        )
        uit = m.bepaal_match(feiten(bedrag="12400.00", eigen_verrekend="12400.00"), [k])
        assert uit.verbruik_voor == Decimal("5000.00")
        assert uit.details["verbruik_geboekt"] == "0.00"

    def test_onderweg_tekst(self):
        assert m.onderweg_tekst(Decimal("0.00"), 0, 0) == ""
        assert m.onderweg_tekst(Decimal("20000.00"), 1, 1) == (
            "waarvan € 20.000,00 nog niet geboekt (1 factuur ter accordering)"
        )
        assert m.onderweg_tekst(Decimal("25000.00"), 2, 1) == (
            "waarvan € 25.000,00 nog niet geboekt (2 facturen in behandeling)"
        )
