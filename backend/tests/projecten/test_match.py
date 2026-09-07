"""Gedeelde project-matchmotor (`app/projecten/match.py`, blok 10 07-09 — casus Spot Services) — puur, geen DB.

Factuur-motor: volgorde exacte code (groen) > leverancier-werknummer (groen als bevestigd, anders oranje) >
fuzzy plaats/opdrachtgever (altijd oranje, OVH nooit); meerduidig op een niveau = niets invullen mét de
kandidaten; genormaliseerde codes (hoofdletters/spaties/leestekens/haken). Offerte-motor `match_project`
(verplichting 04-09): gedrag ongewijzigd na de verhuizing."""

from __future__ import annotations

import uuid

from app.extractie import verplichting
from app.projecten import match as m

P_TILBURG = uuid.UUID("aaaaaaaa-0000-0000-0000-000000026127")
P_KONING = uuid.UUID("aaaaaaaa-0000-0000-0000-000000026140")
P_ODOO = uuid.UUID("aaaaaaaa-0000-0000-0000-000000026133")
P_OVH = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000999")
P_DUBBEL = uuid.UUID("aaaaaaaa-0000-0000-0000-000000026141")

KANDIDATEN = [
    m.ProjectKandidaat(id=P_TILBURG, naam="26127 Tilburg (Heijmans)"),
    m.ProjectKandidaat(id=P_KONING, naam="26140 Koningstraat (Confide)"),
    m.ProjectKandidaat(id=P_ODOO, naam="[26133] Eindhoven (BAM)"),
    m.ProjectKandidaat(id=P_OVH, naam="OVH · Overhead / algemene kosten (intern)"),
]


class TestNormalisatie:
    def test_code_is_case_spatie_en_leesteken_ongevoelig(self) -> None:
        assert m.normaliseer_projectcode(" 26-140 ") == "26140"
        assert m.normaliseer_projectcode("[26140]") == "26140"
        assert m.normaliseer_projectcode("Proj. 26140") == "proj26140"

    def test_projectcode_uit_naam_ook_met_odoo_haken(self) -> None:
        assert m.projectcode_van("26127 Tilburg (Heijmans)") == "26127"
        assert m.projectcode_van("[26133] Eindhoven (BAM)") == "26133"
        assert m.projectcode_van("OVH · Overhead") is None
        assert m.projectcode_van(None) is None


class TestExacteCode:
    def test_kale_code_is_groen(self) -> None:
        u = m.bepaal_project_uit_factuur("26140", KANDIDATEN)
        assert (u.project_id, u.niveau, u.bevestigd) == (P_KONING, m.NIVEAU_CODE, True)
        assert u.herkomst == m.HERKOMST_FACTUUR
        assert "26140" in (u.detail or "") and "Koningstraat" in (u.detail or "")

    def test_code_genormaliseerd_en_als_token_in_de_tekst(self) -> None:
        assert m.bepaal_project_uit_factuur(" 26-140 ", KANDIDATEN).project_id == P_KONING
        assert m.bepaal_project_uit_factuur("Project 26140", KANDIDATEN).project_id == P_KONING
        assert m.bepaal_project_uit_factuur("Werknr: 26133 / Eindhoven", KANDIDATEN).project_id == P_ODOO

    def test_deelcode_matcht_niet(self) -> None:
        """ "2614" of "261400" is niet code 26140 — nooit een gok."""
        assert m.bepaal_project_uit_factuur("2614", KANDIDATEN).project_id is None
        assert m.bepaal_project_uit_factuur("261400", KANDIDATEN).project_id is None

    def test_hele_projectnaam_is_ook_exact(self) -> None:
        assert m.bepaal_project_uit_factuur("26127 Tilburg (Heijmans)", KANDIDATEN).niveau == m.NIVEAU_CODE

    def test_meerduidige_code_vult_niets_en_noemt_de_kandidaten(self) -> None:
        kandidaten = [*KANDIDATEN, m.ProjectKandidaat(id=P_DUBBEL, naam="26140 Koningstraat fase 2 (Confide)")]
        u = m.bepaal_project_uit_factuur("26140", kandidaten)
        assert u.project_id is None and u.herkomst == m.HERKOMST_FACTUUR_MEERDUIDIG
        assert {k.id for k in u.meerduidig} == {P_KONING, P_DUBBEL}
        assert "meerdere projecten passen" in (u.detail or "")
        assert "Koningstraat fase 2" in (u.detail or "")

    def test_exacte_code_wint_van_een_werknummer_dat_ergens_anders_heen_wijst(self) -> None:
        werknummers = [m.WerknummerKoppeling(werknummer="26140", project_id=P_TILBURG, bevestigd=True)]
        assert m.bepaal_project_uit_factuur("26140", KANDIDATEN, werknummers).project_id == P_KONING


class TestWerknummer:
    def test_bevestigde_mapping_is_groen(self) -> None:
        werknummers = [m.WerknummerKoppeling(werknummer="SPOT-4711", project_id=P_KONING, bevestigd=True)]
        u = m.bepaal_project_uit_factuur("spot 4711", KANDIDATEN, werknummers)
        assert (u.project_id, u.niveau, u.bevestigd, u.herkomst) == (
            P_KONING,
            m.NIVEAU_WERKNUMMER,
            True,
            m.HERKOMST_FACTUUR,
        )

    def test_onbevestigde_mapping_is_oranje(self) -> None:
        werknummers = [m.WerknummerKoppeling(werknummer="SPOT-4711", project_id=P_KONING, bevestigd=False)]
        u = m.bepaal_project_uit_factuur("SPOT-4711", KANDIDATEN, werknummers)
        assert u.project_id == P_KONING and u.bevestigd is False
        assert u.herkomst == m.HERKOMST_FACTUUR_ONBEVESTIGD
        assert "nog niet bevestigd" in (u.detail or "")

    def test_mapping_naar_inactief_project_telt_niet(self) -> None:
        werknummers = [m.WerknummerKoppeling(werknummer="SPOT-4711", project_id=uuid.uuid4(), bevestigd=True)]
        assert m.bepaal_project_uit_factuur("SPOT-4711", KANDIDATEN, werknummers).project_id is None

    def test_twee_mappingen_naar_verschillende_projecten_is_meerduidig(self) -> None:
        werknummers = [
            m.WerknummerKoppeling(werknummer="SPOT-4711", project_id=P_KONING, bevestigd=True),
            m.WerknummerKoppeling(werknummer="spot4711", project_id=P_TILBURG, bevestigd=True),
        ]
        u = m.bepaal_project_uit_factuur("SPOT-4711", KANDIDATEN, werknummers)
        assert u.project_id is None and {k.id for k in u.meerduidig} == {P_KONING, P_TILBURG}

    def test_werknummer_wint_van_fuzzy(self) -> None:
        werknummers = [m.WerknummerKoppeling(werknummer="Koningstraat", project_id=P_TILBURG, bevestigd=True)]
        u = m.bepaal_project_uit_factuur("Koningstraat", KANDIDATEN, werknummers)
        assert (u.project_id, u.niveau) == (P_TILBURG, m.NIVEAU_WERKNUMMER)


class TestFuzzy:
    def test_plaats_of_opdrachtgever_is_altijd_oranje(self) -> None:
        u = m.bepaal_project_uit_factuur("Koningstraat", KANDIDATEN)
        assert (u.project_id, u.niveau, u.bevestigd) == (P_KONING, m.NIVEAU_FUZZY, False)
        assert u.herkomst == m.HERKOMST_FACTUUR_ONBEVESTIGD
        assert m.bepaal_project_uit_factuur("Heijmans", KANDIDATEN).project_id == P_TILBURG

    def test_ovh_nooit_via_fuzzy(self) -> None:
        assert m.bepaal_project_uit_factuur("Overhead", KANDIDATEN).project_id is None
        assert m.bepaal_project_uit_factuur("algemene kosten", KANDIDATEN).project_id is None

    def test_meerduidige_naam_vult_niets(self) -> None:
        u = m.bepaal_project_uit_factuur(
            "Confide", [*KANDIDATEN, m.ProjectKandidaat(id=P_DUBBEL, naam="26141 Breda (Confide)")]
        )
        assert u.project_id is None and len(u.meerduidig) == 2

    def test_te_kort_of_onbekend_is_geen_match(self) -> None:
        assert m.bepaal_project_uit_factuur("abc", KANDIDATEN).herkomst is None
        assert m.bepaal_project_uit_factuur("Volstrekt onbekend werk", KANDIDATEN).herkomst is None


class TestLegeInvoer:
    def test_geen_tekst_geen_kandidaten(self) -> None:
        assert m.bepaal_project_uit_factuur(None, KANDIDATEN).herkomst is None
        assert m.bepaal_project_uit_factuur("   ", KANDIDATEN).gelezen is None
        assert m.bepaal_project_uit_factuur("26140", []).project_id is None


class TestOfferteMotorOngewijzigd:
    """Regressie verplichting 04-09: `verplichting.match_project` is nu een import uit de gedeelde module."""

    def test_verplichting_importeert_de_gedeelde_motor(self) -> None:
        assert verplichting.match_project is m.match_project
        assert verplichting.ProjectKandidaat is m.ProjectKandidaat

    def test_nummer_prefix_naam_bevat_fuzzy_en_meerduidig(self) -> None:
        """Uitkomsten één-op-één vergeleken met de implementatie van vóór de verhuizing (commit fcc35a8)."""
        assert m.match_project("26140 Koningstraat", KANDIDATEN) == (P_KONING, "nummer", "26140 Koningstraat (Confide)")
        assert m.match_project("Koningstraat", KANDIDATEN) == (P_KONING, "naam", "26140 Koningstraat (Confide)")
        assert m.match_project("Tilburg (Heijmans)", KANDIDATEN) == (P_TILBURG, "naam", "26127 Tilburg (Heijmans)")
        # Bewuste delta t.o.v. vóór 07-09: een Odoo-naam "[26133] …" telt nu als nummer-prefix (was: naam-bevat) —
        # zelfde project, sterker match-niveau.
        assert m.match_project("[26133]", KANDIDATEN) == (P_ODOO, "nummer", "[26133] Eindhoven (BAM)")
        # De offerte-motor kent geen OVH-uitsluiting (ongewijzigd gedrag); de factuur-motor wél.
        assert m.match_project("Overhead", KANDIDATEN)[0] == P_OVH
        assert m.match_project("Verbouwing Koningstraat", KANDIDATEN) == (None, None, None)  # < 0,85 — óók vóór 07-09
        # Naam-bevat op een deelnummer: ongewijzigd in de offerte-motor (de factuur-motor sluit dit uit).
        assert m.match_project("2614", KANDIDATEN) == (P_KONING, "naam", "26140 Koningstraat (Confide)")
        dubbel = [*KANDIDATEN, m.ProjectKandidaat(id=P_DUBBEL, naam="26140 Koningstraat fase 2")]
        assert m.match_project("26140", dubbel) == (None, None, None)
        assert m.match_project(None, KANDIDATEN) == (None, None, None)
        assert m.match_project("xyz", KANDIDATEN) == (None, None, None)
