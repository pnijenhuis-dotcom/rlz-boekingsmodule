"""Unit-tests op de pure matchmotor (geldlogica — verplicht getest vóór UI-werk)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.bank import matchmotor
from app.bank.matchmotor import (
    MutatieGegevens,
    OpenPost,
    VasteRegelGegevens,
    VoorstelSoort,
    bepaal_voorstel,
    splits_incl_bedrag,
    stel_regel_voor,
)


def _mutatie(
    *,
    bedrag: str = "-121.00",
    naam: str | None = "Bouwmaat Nederland B.V.",
    omschrijving: str | None = "factuur 2026-0642 bedankt",
    iban: str | None = None,
    rlz_voorstel: uuid.UUID | None = None,
) -> MutatieGegevens:
    return MutatieGegevens(
        id=uuid.uuid4(),
        bedrag=Decimal(bedrag),
        open_bedrag=Decimal(bedrag),
        tegenpartij_naam=naam,
        omschrijving=omschrijving,
        tegenrekening_iban=iban,
        rlz_voorstel_item_id=rlz_voorstel,
    )


def _post(*, bedrag: str = "121.00", referentie: str | None = "2026-0642") -> OpenPost:
    return OpenPost(
        id=uuid.uuid4(), bedrag=Decimal(bedrag), referentie=referentie, referentie2=None,
        rlz_document_id=uuid.uuid4(),
    )


def _regel(*, sleutel: str, iban: str | None = None, taxrate: uuid.UUID | None = None) -> VasteRegelGegevens:
    return VasteRegelGegevens(
        id=uuid.uuid4(), tegenpartij_sleutel=sleutel, tegenrekening_iban=iban,
        ledger_id=uuid.uuid4(), taxrate_id=taxrate, project_id=None, omschrijving=None,
    )


# --- stap 1/2: open-post-matching ----------------------------------------------------------------


def test_exacte_match_referentie_en_bedrag_is_groen() -> None:
    post = _post()
    voorstel = bepaal_voorstel(_mutatie(), open_posten=[post], vaste_regels=[])
    assert voorstel.soort == VoorstelSoort.EXACTE_MATCH
    assert voorstel.kleur == "groen"
    assert voorstel.payment_item_id == post.id


def test_referentie_match_met_afwijkend_bedrag_is_oranje_deelmatch() -> None:
    post = _post(bedrag="150.00")  # deelbetaling / G-rekening-split
    voorstel = bepaal_voorstel(_mutatie(), open_posten=[post], vaste_regels=[])
    assert voorstel.soort == VoorstelSoort.DEEL_MATCH
    assert voorstel.kleur == "oranje"
    assert voorstel.payment_item_id == post.id


def test_bedrag_match_zonder_referentie_is_oranje_deelmatch() -> None:
    post = _post(referentie="XYZ-9999")
    voorstel = bepaal_voorstel(
        _mutatie(omschrijving="huur juli zonder kenmerk"), open_posten=[post], vaste_regels=[]
    )
    assert voorstel.soort == VoorstelSoort.DEEL_MATCH
    assert voorstel.payment_item_id == post.id


def test_opmaakverschillen_in_referentie_breken_de_match_niet() -> None:
    post = _post(referentie="2026 0642")
    voorstel = bepaal_voorstel(_mutatie(omschrijving="FACT.NR 2026-0642"), open_posten=[post], vaste_regels=[])
    assert voorstel.soort == VoorstelSoort.EXACTE_MATCH


def test_te_korte_referentie_matcht_nooit() -> None:
    post = _post(referentie="1", bedrag="999.99")
    voorstel = bepaal_voorstel(_mutatie(omschrijving="betaling 1"), open_posten=[post], vaste_regels=[])
    assert voorstel.soort == VoorstelSoort.HANDMATIG


def test_meerdere_referentie_kandidaten_zonder_bedragmatch_wordt_handmatig() -> None:
    posten = [_post(bedrag="150.00"), _post(bedrag="175.00")]
    voorstel = bepaal_voorstel(_mutatie(), open_posten=posten, vaste_regels=[])
    assert voorstel.soort == VoorstelSoort.HANDMATIG
    assert "meerdere" in voorstel.bron


def test_meerdere_referentie_kandidaten_met_een_exacte_bedragmatch_blijft_groen() -> None:
    exact = _post(bedrag="121.00")
    posten = [exact, _post(bedrag="175.00")]
    voorstel = bepaal_voorstel(_mutatie(), open_posten=posten, vaste_regels=[])
    assert voorstel.soort == VoorstelSoort.EXACTE_MATCH
    assert voorstel.payment_item_id == exact.id


def test_meerdere_bedrag_kandidaten_zonder_referentie_geeft_geen_gok() -> None:
    posten = [_post(referentie="A-1111"), _post(referentie="B-2222")]
    voorstel = bepaal_voorstel(_mutatie(omschrijving="zonder kenmerk"), open_posten=posten, vaste_regels=[])
    assert voorstel.soort == VoorstelSoort.HANDMATIG


# --- stap 3/4/5: regels, RLZ-voorstel, handmatig ---------------------------------------------------


def test_vaste_regel_matcht_op_genormaliseerde_naam() -> None:
    regel = _regel(sleutel=matchmotor.tegenpartij_sleutel("ING Bank N.V.") or "")
    voorstel = bepaal_voorstel(
        _mutatie(naam="ING BANK N.V.", omschrijving="kosten zakelijk juni"), open_posten=[], vaste_regels=[regel]
    )
    assert voorstel.soort == VoorstelSoort.VASTE_REGEL
    assert voorstel.regel_id == regel.id
    assert voorstel.kleur == "groen"


def test_vaste_regel_matcht_op_iban_ook_bij_andere_naam() -> None:
    regel = _regel(sleutel="andere naam", iban="NL91INGB0002445588")
    voorstel = bepaal_voorstel(
        _mutatie(naam="Onbekende Incasso", omschrijving="x", iban="NL91INGB0002445588"),
        open_posten=[],
        vaste_regels=[regel],
    )
    assert voorstel.soort == VoorstelSoort.VASTE_REGEL


def test_open_post_match_wint_van_vaste_regel() -> None:
    """Volgorde 1–5: een afletterkandidaat (mensenwerk) gaat altijd vóór een vaste regel —
    automatisch boeken mag een open post nooit wegkapen."""
    regel = _regel(sleutel=matchmotor.tegenpartij_sleutel("Bouwmaat Nederland B.V.") or "")
    post = _post()
    voorstel = bepaal_voorstel(_mutatie(), open_posten=[post], vaste_regels=[regel])
    assert voorstel.soort == VoorstelSoort.EXACTE_MATCH


def test_rlz_voorstel_als_er_verder_niets_matcht() -> None:
    item_id = uuid.uuid4()
    voorstel = bepaal_voorstel(
        _mutatie(naam="X", omschrijving="y", rlz_voorstel=item_id), open_posten=[], vaste_regels=[]
    )
    assert voorstel.soort == VoorstelSoort.RLZ_VOORSTEL
    assert voorstel.payment_item_id == item_id
    assert voorstel.kleur == "oranje"
    assert "Reeleezee" in voorstel.bron


def test_handmatig_zonder_enige_match() -> None:
    voorstel = bepaal_voorstel(_mutatie(naam="X", omschrijving="y"), open_posten=[], vaste_regels=[])
    assert voorstel.soort == VoorstelSoort.HANDMATIG


# --- 3×-regelvoorstel ------------------------------------------------------------------------------


def test_regelvoorstel_na_drie_gelijke_boekingen() -> None:
    ledger = uuid.uuid4()
    sleutel = matchmotor.tegenpartij_sleutel("Ziggo Zakelijk") or ""
    historie = [(sleutel, ledger, None)] * 3
    voorstel = stel_regel_voor(tegenpartij_naam="Ziggo Zakelijk", historie=historie, bestaande_sleutels=set())
    assert voorstel is not None
    assert voorstel.ledger_id == ledger
    assert voorstel.aantal_boekingen == 3


def test_geen_regelvoorstel_onder_de_drempel_of_bij_bestaande_regel() -> None:
    ledger = uuid.uuid4()
    sleutel = matchmotor.tegenpartij_sleutel("Ziggo Zakelijk") or ""
    assert (
        stel_regel_voor(
            tegenpartij_naam="Ziggo Zakelijk", historie=[(sleutel, ledger, None)] * 2, bestaande_sleutels=set()
        )
        is None
    )
    assert (
        stel_regel_voor(
            tegenpartij_naam="Ziggo Zakelijk", historie=[(sleutel, ledger, None)] * 5, bestaande_sleutels={sleutel}
        )
        is None
    )


def test_regelvoorstel_telt_alleen_consistente_boekingen() -> None:
    sleutel = matchmotor.tegenpartij_sleutel("Ziggo Zakelijk") or ""
    historie = [(sleutel, uuid.uuid4(), None) for _ in range(4)]  # 4× ander grootboek
    assert stel_regel_voor(tegenpartij_naam="Ziggo Zakelijk", historie=historie, bestaande_sleutels=set()) is None


# --- btw-splitsing (code rekent) --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bedrag", "pct", "netto", "btw"),
    [
        ("-68.45", "0.21", "-56.57", "-11.88"),  # Ziggo-case uit de mockup
        ("-24.50", None, "-24.50", "0.00"),  # bankkosten zonder btw
        ("121.00", "0.21", "100.00", "21.00"),
        ("-0.01", "0.21", "-0.01", "0.00"),
    ],
)
def test_splits_incl_bedrag(bedrag: str, pct: str | None, netto: str, btw: str) -> None:
    resultaat_netto, resultaat_btw = splits_incl_bedrag(
        Decimal(bedrag), Decimal(pct) if pct is not None else None
    )
    assert resultaat_netto == Decimal(netto)
    assert resultaat_btw == Decimal(btw)
    assert resultaat_netto + resultaat_btw == Decimal(bedrag)  # som is ALTIJD exact het mutatiebedrag


def test_splits_incl_bedrag_som_klopt_altijd_over_een_bereik() -> None:
    pct = Decimal("0.21")
    for centen in range(-2500, 2500, 7):
        bedrag = Decimal(centen) / 100
        netto, btw = splits_incl_bedrag(bedrag, pct)
        assert netto + btw == bedrag


def test_splits_incl_bedrag_echte_syncvorm_fractie() -> None:
    """Geldlogica-verificatie blok A 2026-08-10: de splitsing hanteert de fractie zoals de
    échte sync die levert (TaxRateCache.percentage = 0.2100, bronformaat Numeric(6,4))."""
    netto, btw = splits_incl_bedrag(Decimal("121.00"), Decimal("0.2100"))
    assert (netto, btw) == (Decimal("100.00"), Decimal("21.00"))


def test_splits_incl_bedrag_weigert_ubl_percentagevorm() -> None:
    """Eenheids-guard: een UBL-percentage (21.00) i.p.v. de fractie zou het geld stil verminken
    (121 / 22 i.p.v. 121 / 1,21) — hard falen, nooit stil doorrekenen."""
    with pytest.raises(ValueError, match="fractie"):
        splits_incl_bedrag(Decimal("121.00"), Decimal("21.00"))
    with pytest.raises(ValueError, match="fractie"):
        splits_incl_bedrag(Decimal("121.00"), Decimal("1"))
