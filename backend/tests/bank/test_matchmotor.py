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


def _post(
    *,
    bedrag: str = "-121.00",
    referentie: str | None = "2026-0642",
    naam: str | None = "Bouwmaat Nederland B.V.",
    soort: str | None = "Inkoopfactuur",
    entity_guid: uuid.UUID | None = None,
) -> OpenPost:
    """RLZ-conventie: inkoop-post NEGATIEF, verkoop-post POSITIEF (api-verkenning H1/replay 09-08)."""
    return OpenPost(
        id=uuid.uuid4(), bedrag=Decimal(bedrag), referentie=referentie, referentie2=None,
        rlz_document_id=uuid.uuid4(), tegenpartij_naam=naam, documentsoort=soort, entity_guid=entity_guid,
    )


def _regel(*, sleutel: str, iban: str | None = None, taxrate: uuid.UUID | None = None) -> VasteRegelGegevens:
    return VasteRegelGegevens(
        id=uuid.uuid4(), tegenpartij_sleutel=sleutel, tegenrekening_iban=iban,
        ledger_id=uuid.uuid4(), taxrate_id=taxrate, project_id=None, omschrijving=None,
    )


# --- stap 1/2: open-post-matching (blok 2 bundel 08-09: teken + naam/IBAN + nummer + bedrag) -------------


def test_exacte_match_teken_naam_nummer_bedrag_is_groen() -> None:
    post = _post()
    voorstel = bepaal_voorstel(_mutatie(), open_posten=[post], vaste_regels=[])
    assert voorstel.soort == VoorstelSoort.EXACTE_MATCH
    assert voorstel.kleur == "groen"
    assert voorstel.payment_item_id == post.id
    assert voorstel.bron == "naam + nummer + bedrag"


def test_naam_en_nummer_met_afwijkend_bedrag_is_oranje_deelmatch() -> None:
    post = _post(bedrag="-150.00")  # deelbetaling / G-rekening-split
    voorstel = bepaal_voorstel(_mutatie(), open_posten=[post], vaste_regels=[])
    assert voorstel.soort == VoorstelSoort.DEEL_MATCH
    assert voorstel.kleur == "oranje"
    assert voorstel.payment_item_id == post.id
    assert voorstel.bron == "naam + nummer, bedrag wijkt af"


def test_naam_en_bedrag_zonder_nummer_is_oranje() -> None:
    post = _post(referentie="XYZ-9999")
    voorstel = bepaal_voorstel(
        _mutatie(omschrijving="huur juli zonder kenmerk"), open_posten=[post], vaste_regels=[]
    )
    assert voorstel.soort == VoorstelSoort.DEEL_MATCH
    assert voorstel.payment_item_id == post.id
    assert voorstel.bron == "naam + bedrag, nummer niet gevonden"


def test_nummer_en_bedrag_zonder_naam_is_oranje_nooit_groen() -> None:
    """Label zegt exact wat matchte — nooit meer "naam + referentie" als de naam niet getoetst is."""
    post = _post(naam="Tegenpartij Onder Andere Naam B.V.")
    voorstel = bepaal_voorstel(_mutatie(naam="Betaalservice X"), open_posten=[post], vaste_regels=[])
    assert voorstel.soort == VoorstelSoort.DEEL_MATCH
    assert voorstel.kleur == "oranje"
    assert voorstel.bron == "nummer + bedrag, naam onbekend"


def test_alleen_bedrag_of_alleen_naam_geeft_geen_open_post_voorstel() -> None:
    alleen_bedrag = _post(referentie="XYZ-9999", naam="Iemand Anders")
    assert (
        bepaal_voorstel(_mutatie(omschrijving="zonder kenmerk"), open_posten=[alleen_bedrag], vaste_regels=[]).soort
        == VoorstelSoort.HANDMATIG
    )
    alleen_naam = _post(referentie="XYZ-9999", bedrag="-999.99")
    assert (
        bepaal_voorstel(_mutatie(omschrijving="zonder kenmerk"), open_posten=[alleen_naam], vaste_regels=[]).soort
        == VoorstelSoort.HANDMATIG
    )


def test_opmaakverschillen_in_referentie_breken_de_match_niet() -> None:
    post = _post(referentie="2026 0642")
    voorstel = bepaal_voorstel(_mutatie(omschrijving="FACT.NR 2026-0642"), open_posten=[post], vaste_regels=[])
    assert voorstel.soort == VoorstelSoort.EXACTE_MATCH


def test_te_korte_referentie_matcht_nooit() -> None:
    post = _post(referentie="1", bedrag="-999.99")
    voorstel = bepaal_voorstel(_mutatie(omschrijving="betaling 1"), open_posten=[post], vaste_regels=[])
    assert voorstel.soort == VoorstelSoort.HANDMATIG


def test_meerdere_referentie_kandidaten_zonder_bedragmatch_wordt_handmatig() -> None:
    posten = [_post(bedrag="-150.00"), _post(bedrag="-175.00")]
    voorstel = bepaal_voorstel(_mutatie(), open_posten=posten, vaste_regels=[])
    assert voorstel.soort == VoorstelSoort.HANDMATIG
    assert "meerdere" in voorstel.bron


def test_meerdere_referentie_kandidaten_met_een_exacte_bedragmatch_blijft_groen() -> None:
    exact = _post(bedrag="-121.00")
    posten = [exact, _post(bedrag="-175.00")]
    voorstel = bepaal_voorstel(_mutatie(), open_posten=posten, vaste_regels=[])
    assert voorstel.soort == VoorstelSoort.EXACTE_MATCH
    assert voorstel.payment_item_id == exact.id


def test_meerdere_bedrag_kandidaten_zonder_referentie_geeft_geen_gok() -> None:
    posten = [_post(referentie="A-1111"), _post(referentie="B-2222")]
    voorstel = bepaal_voorstel(_mutatie(omschrijving="zonder kenmerk"), open_posten=posten, vaste_regels=[])
    assert voorstel.soort == VoorstelSoort.HANDMATIG


# --- productiegevallen C.V. 08-09 (aanleiding blok 2) ------------------------------------------------------


def test_productiegeval_a_substring_in_betalingskenmerk_geeft_geen_voorstel() -> None:
    """€ 12.500 BIJ van een privépersoon, kenmerk 26247623521810 → de oude motor stelde verkoopfactuur 2352
    Tupker Beheer (open € 26,56) voor omdat "2352" in het kenmerk zat. Nu: teken ok maar géén naam, géén
    nummer als heel token, géén bedrag → geen open-post-voorstel (handmatig)."""
    post = _post(bedrag="26.56", referentie="2352", naam="Tupker Beheer B.V.", soort="Verkoopfactuur")
    mutatie = _mutatie(bedrag="12500.00", naam="Hr P.W. N.-P.", omschrijving="26247623521810")
    voorstel = bepaal_voorstel(mutatie, open_posten=[post], vaste_regels=[])
    assert voorstel.soort == VoorstelSoort.HANDMATIG
    assert voorstel.payment_item_id is None


def test_productiegeval_b_afschrijving_matcht_nooit_een_verkoopfactuur() -> None:
    """DNA Notaris € −99,99 AF → de oude motor stelde verkoopfactuur 2337 Kempen Chalets voor (deelbetaling).
    Een verkoopfactuur hoort bij een BIJschrijving: teken-mismatch = nooit kandidaat, ook niet oranje."""
    post = _post(bedrag="2337.00", referentie="2337", naam="Kempen Chalets B.V.", soort="Verkoopfactuur")
    mutatie = _mutatie(bedrag="-99.99", naam="DNA Notaris", omschrijving="factuur 2337 kosten")
    voorstel = bepaal_voorstel(mutatie, open_posten=[post], vaste_regels=[])
    assert voorstel.soort == VoorstelSoort.HANDMATIG
    assert voorstel.payment_item_id is None


# --- teken -------------------------------------------------------------------------------------------------


def test_teken_mismatch_is_nooit_kandidaat_ook_niet_met_naam_nummer_bedrag() -> None:
    post = _post(bedrag="121.00", soort="Verkoopfactuur")  # verkoop-post positief ↔ afschrijving −121
    voorstel = bepaal_voorstel(_mutatie(bedrag="-121.00"), open_posten=[post], vaste_regels=[])
    assert voorstel.soort == VoorstelSoort.HANDMATIG
    assert matchmotor.teken_toets(_mutatie(bedrag="-121.00"), post) == matchmotor.TEKEN_MISMATCH


def test_verkoopfactuur_bij_bijschrijving_is_groen() -> None:
    post = _post(bedrag="850.00", referentie="2026-0100", naam="Huurder Jansen", soort="Verkoopfactuur")
    voorstel = bepaal_voorstel(
        _mutatie(bedrag="850.00", naam="J. Jansen", omschrijving="huur factuur 2026-0100"),
        open_posten=[post], vaste_regels=[],
    )
    assert voorstel.soort == VoorstelSoort.EXACTE_MATCH


def test_inkoopcreditnota_positieve_post_hoort_bij_bijschrijving() -> None:
    """Creditnota omgekeerd: een inkoop-post met POSITIEF open bedrag = creditnota → bijschrijving."""
    post = _post(bedrag="121.00", soort="Inkoopfactuur")
    bij = bepaal_voorstel(_mutatie(bedrag="121.00"), open_posten=[post], vaste_regels=[])
    assert bij.soort == VoorstelSoort.EXACTE_MATCH
    af = bepaal_voorstel(_mutatie(bedrag="-121.00"), open_posten=[post], vaste_regels=[])
    assert af.soort == VoorstelSoort.HANDMATIG


def test_onbekende_documentsoort_is_hooguit_oranje_nooit_groen() -> None:
    post = _post(soort=None)
    voorstel = bepaal_voorstel(_mutatie(), open_posten=[post], vaste_regels=[])
    assert voorstel.soort == VoorstelSoort.DEEL_MATCH
    assert voorstel.kleur == "oranje"
    assert "documentsoort onbekend" in voorstel.bron


# --- nummer als heel token ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("referentie", "tekst", "verwacht"),
    [
        ("2352", "26247623521810", False),  # substring van een langer cijferblok — productiegeval A
        ("2026-0642", "factuur 2026-0642 bedankt", True),  # samengestelde referentie, tokens 2026 + 0642
        ("2026-0642", "factuur 20260642", True),
        ("F-2026-0642", "betaling F-2026-0642", True),
        ("2026-0642", "INV20260642", True),  # letter-voorvoegsel, cijferkern gelijk
        ("2026-0642", "202606421", False),  # langer cijferblok
        ("2026-0642", "12026-0642", False),
        ("2026053", "Factuur 2026053 NPG", True),
        ("2026053", "20260530", False),
        ("ab", "ab", False),  # te kort
    ],
)
def test_referentie_als_token(referentie: str, tekst: str, verwacht: bool) -> None:
    assert matchmotor.referentie_als_token(referentie, None, tekst) is verwacht


def test_korte_referentie_telt_alleen_samen_met_exact_bedrag() -> None:
    """4–5 tekens: als heel token wél gevonden, maar zonder exact bedrag telt het nummer niet."""
    zonder_bedrag = _post(referentie="2352", bedrag="-26.56", naam="Iemand Anders")
    voorstel = bepaal_voorstel(
        _mutatie(bedrag="-500.00", naam="Betaler", omschrijving="factuur 2352"),
        open_posten=[zonder_bedrag],
        vaste_regels=[],
    )
    assert voorstel.soort == VoorstelSoort.HANDMATIG
    met_bedrag = _post(referentie="2352", bedrag="-26.56", naam="Iemand Anders")
    voorstel = bepaal_voorstel(
        _mutatie(bedrag="-26.56", naam="Betaler", omschrijving="factuur 2352"),
        open_posten=[met_bedrag],
        vaste_regels=[],
    )
    assert voorstel.soort == VoorstelSoort.DEEL_MATCH
    assert voorstel.bron == "nummer + bedrag, naam onbekend"


# --- naam / IBAN -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b", "verwacht"),
    [
        ("Bouwmaat Nederland B.V.", "BOUWMAAT NEDERLAND", True),
        ("Hr P.W. N.-P.", "Tupker Beheer B.V.", False),
        ("DNA Notaris", "Kempen Chalets B.V.", False),
        ("Tupker Beheer B.V.", "Kempen Beheer B.V.", False),  # 'beheer' is nooit significant
        ("De Vries en Zonen V.O.F.", "Vries Zonen", True),
        ("J. Jansen", "Huurder Jansen", True),
        ("NPG Administratiekantoor", "NPG Administratiekantoor B.V.", True),
        ("TransIP B.V.", "TransIP", True),
    ],
)
def test_naam_komt_overeen(a: str, b: str, verwacht: bool) -> None:
    assert matchmotor.naam_komt_overeen(a, b) is verwacht


def test_iban_geheugen_vervangt_de_naam_toets() -> None:
    """Een tegenpartij die onder een andere naam betaalt ("Hr P.W. N.-P." voor een B.V.) wordt groen zodra
    het IBAN eerder bevestigd is aan de RLZ-entity van de post."""
    entity = uuid.uuid4()
    post = _post(
        bedrag="1210.00",
        referentie="2026-0700",
        naam="Nijenhuis Vastgoed B.V.",
        soort="Verkoopfactuur",
        entity_guid=entity,
    )
    mutatie = _mutatie(
        bedrag="1210.00", naam="Hr P.W. N.-P.", omschrijving="2026-0700", iban="NL91 ABNA 0417 1643 00"
    )
    zonder = bepaal_voorstel(mutatie, open_posten=[post], vaste_regels=[])
    assert zonder.soort == VoorstelSoort.DEEL_MATCH and zonder.bron == "nummer + bedrag, naam onbekend"
    met = bepaal_voorstel(
        mutatie, open_posten=[post], vaste_regels=[],
        iban_relaties=[matchmotor.IbanRelatie(iban="NL91ABNA0417164300", entity_guid=entity)],
    )
    assert met.soort == VoorstelSoort.EXACTE_MATCH
    assert met.bron == "IBAN + nummer + bedrag"
    # Ander IBAN of andere entity: geen IBAN-match.
    anders = bepaal_voorstel(
        mutatie, open_posten=[post], vaste_regels=[],
        iban_relaties=[matchmotor.IbanRelatie(iban="NL91ABNA0417164300", entity_guid=uuid.uuid4())],
    )
    assert anders.soort == VoorstelSoort.DEEL_MATCH


def test_vaste_regel_iban_dient_als_naam_geheugen_voor_de_open_post() -> None:
    """Hergebruik van het bestaande IBAN-geheugen van de vaste regels: regel op dit IBAN met een
    tegenpartij-sleutel die de postnaam dekt → "IBAN"-been."""
    regel = _regel(sleutel=matchmotor.tegenpartij_sleutel("Bouwmaat Nederland B.V.") or "", iban="NL91INGB0002445588")
    post = _post()
    mutatie = _mutatie(naam="Onbekende Incasso", iban="NL91INGB0002445588")
    voorstel = bepaal_voorstel(mutatie, open_posten=[post], vaste_regels=[regel])
    assert voorstel.soort == VoorstelSoort.EXACTE_MATCH
    assert voorstel.bron == "IBAN + nummer + bedrag"


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
