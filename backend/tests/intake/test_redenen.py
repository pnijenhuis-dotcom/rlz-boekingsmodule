"""Intake-redenen (02-09): de verzamelbak-rij toont de échte reden; "geen tenaamstelling gelezen"
uitsluitend als de AI werkelijk niets las. Plus de gedeelde verworpen-definitie voor de bewaking."""

from __future__ import annotations

import pytest

from app.intake.redenen import is_verworpen_intake_reden, omschrijf_intake_reden

PAGINABEREIK = (
    "splitsingsdetectie_mislukt: Splitsingsvoorstel ongeldig: paginabereik 1–2 valt buiten het document (1 pagina's)"
)
API_FOUT = "splitsingsdetectie_mislukt: Claude API-fout: 529 overloaded"
VOORSTEL_MET_ONGELDIG = (
    "splitsingsvoorstel_ter_controle: 3 facturen herkend, 1 deel ongeldig — "
    "paginabereik 3–9 valt buiten het document (4 pagina's)"
)


class TestOmschrijfIntakeReden:
    def test_oude_paginabereik_rij_benoemt_verwerping_niet_niet_gelezen(self) -> None:
        label = omschrijf_intake_reden(PAGINABEREIK, tenaamstelling=None)
        assert label is not None
        assert label.startswith("AI-voorstel verworpen door code: paginabereik 1–2")
        assert "tenaamstelling niet overgenomen" in label
        assert "geen tenaamstelling gelezen" not in label

    def test_geen_facturen_herkend(self) -> None:
        reden = "splitsingsdetectie_mislukt: Splitsingsvoorstel ongeldig: geen facturen herkend"
        assert omschrijf_intake_reden(reden, tenaamstelling=None) == "AI herkende geen factuur in dit document"

    def test_api_fout(self) -> None:
        label = omschrijf_intake_reden(
            "splitsingsdetectie_mislukt: Claude API-fout: 529 overloaded", tenaamstelling=None
        )
        assert label == "AI-lezing mislukt: Claude API-fout: 529 overloaded"

    def test_nooit_splitsen_regel_benoemt_de_afzender_en_is_geen_verwerping(self) -> None:
        """Blok B 04-09: de AI is bewust overgeslagen — geen "geen tenaamstelling gelezen", geen
        verworpen poging voor de bewaking."""
        reden = "splitsing_overgeslagen_nooit_splitsen: administratie@bouwmaat.nl"
        assert omschrijf_intake_reden(reden, tenaamstelling=None) == (
            "splitsing overgeslagen: regel 'nooit splitsen' voor administratie@bouwmaat.nl — handmatig toewijzen"
        )
        assert is_verworpen_intake_reden(reden) is False

    def test_niet_eenduidig_met_en_zonder_tenaamstelling(self) -> None:
        assert (
            omschrijf_intake_reden("tenaamstelling_niet_eenduidig", tenaamstelling="Belastingbutler B.V.")
            == "tenaamstelling matcht geen administratie of geleerde regel"
        )
        assert (
            omschrijf_intake_reden("tenaamstelling_niet_eenduidig", tenaamstelling=None)
            == "geen tenaamstelling gelezen"
        )

    def test_gate_en_limiet(self) -> None:
        assert (
            omschrijf_intake_reden("intake_ai_uitgeschakeld", tenaamstelling=None)
            == "intake-AI staat uit — handmatig toewijzen"
        )
        assert (
            omschrijf_intake_reden("ai_limiet_bereikt", tenaamstelling=None)
            == "AI-limiet bereikt — handmatig verwerken"
        )

    def test_splitsingsvoorstel_gewoon_geen_label_met_ongeldig_wel(self) -> None:
        assert (
            omschrijf_intake_reden("splitsingsvoorstel_ter_controle: 2 facturen herkend", tenaamstelling=None) is None
        )
        label = omschrijf_intake_reden(VOORSTEL_MET_ONGELDIG, tenaamstelling=None)
        assert label == "splitsingsvoorstel bevat een ongeldig deel — beoordeel de bereiken"

    def test_herlezen_uitkomsten(self) -> None:
        assert (
            omschrijf_intake_reden("intake_herlezen: tenaamstelling 'X' gelezen, niet eenduidig", tenaamstelling="X")
            == "opnieuw gelezen: tenaamstelling matcht geen administratie of geleerde regel"
        )
        assert (
            omschrijf_intake_reden("intake_herlezen_mislukt: AI plat", tenaamstelling=None)
            == "AI-lezing mislukt: AI plat"
        )

    def test_geen_reden(self) -> None:
        assert omschrijf_intake_reden(None, tenaamstelling=None) == "geen tenaamstelling gelezen"
        assert omschrijf_intake_reden(None, tenaamstelling="X") is None

    def test_lange_detail_wordt_ingekort_zonder_jargon_underscores(self) -> None:
        label = omschrijf_intake_reden("onbekende_technische_reden_" + "x" * 200, tenaamstelling=None)
        assert label is not None and len(label) <= 141 and "_" not in label


class TestIsVerworpenIntakeReden:
    @pytest.mark.parametrize(
        "reden",
        [
            PAGINABEREIK,
            API_FOUT,
            "intake_herlezen_mislukt: AI plat",
            VOORSTEL_MET_ONGELDIG,
        ],
    )
    def test_verworpen(self, reden: str) -> None:
        assert is_verworpen_intake_reden(reden)

    @pytest.mark.parametrize(
        "reden",
        [
            None,
            "",
            "tenaamstelling_niet_eenduidig",
            "intake_ai_uitgeschakeld",
            "ai_limiet_bereikt",
            "splitsingsvoorstel_ter_controle: 2 facturen herkend",
            "intake_herlezen: toegewezen op tenaamstelling_register",
        ],
    )
    def test_niet_verworpen(self, reden: str | None) -> None:
        assert not is_verworpen_intake_reden(reden)
