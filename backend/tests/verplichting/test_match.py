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
