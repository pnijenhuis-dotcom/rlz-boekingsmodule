"""Voorstel-engine (app/geheugen/engine.py) — puur en deterministisch, dus elk weegpad
expliciet getest (geldlogica)."""

from __future__ import annotations

import uuid
from datetime import date

from app.geheugen.engine import Observatie, bepaal_voorstel

VANDAAG = date(2026, 7, 13)
GB_A = uuid.uuid4()
GB_B = uuid.uuid4()
BTW_HOOG = uuid.uuid4()
BTW_VERLEGD = uuid.uuid4()
PROJECT_P = uuid.uuid4()

SLEUTEL_DIESEL = "diesel nen590"


def _obs(
    *,
    gb: uuid.UUID = GB_A,
    btw: uuid.UUID | None = None,
    project: uuid.UUID | None = None,
    bron: str = "rlz_seed",
    dagen_oud: int = 0,
    sleutel: str | None = None,
) -> Observatie:
    return Observatie(
        regel_sleutel=sleutel,
        gb_id=gb,
        btw_id=btw,
        project_id=project,
        bron=bron,
        bron_datum=date.fromordinal(VANDAAG.toordinal() - dagen_oud),
    )


def _voorstel(observaties: list[Observatie], sleutel: str | None = None, **kwargs):
    return bepaal_voorstel(
        observaties,
        regel_sleutel=sleutel,
        vandaag=VANDAAG,
        halfwaardetijd_dagen=kwargs.pop("halfwaardetijd_dagen", 365),
        gewicht_app=kwargs.pop("gewicht_app", 3.0),
        gewicht_rlz_seed=kwargs.pop("gewicht_rlz_seed", 1.0),
    )


class TestWeging:
    def test_recency_verval_laat_recent_winnen_van_oud(self) -> None:
        # 3× oude observaties GB_B (elk 2 halfwaardetijden oud -> gewicht 0.25) tegen 1× verse
        # GB_A (gewicht 1.0) — samen 0.75 < 1.0: recent wint.
        observaties = [
            _obs(gb=GB_B, dagen_oud=730),
            _obs(gb=GB_B, dagen_oud=730),
            _obs(gb=GB_B, dagen_oud=730),
            _obs(gb=GB_A, dagen_oud=0),
        ]
        voorstel = _voorstel(observaties)
        assert voorstel.gb.waarde == GB_A

    def test_zonder_verval_wint_de_meerderheid(self) -> None:
        # Zelfde observaties maar allemaal vers: 3 stemmen GB_B winnen van 1 stem GB_A.
        observaties = [_obs(gb=GB_B), _obs(gb=GB_B), _obs(gb=GB_B), _obs(gb=GB_A)]
        assert _voorstel(observaties).gb.waarde == GB_B

    def test_app_bron_weegt_zwaarder_dan_seed(self) -> None:
        # 1 verse app-correctie (gewicht 3.0) verslaat 2 verse seed-observaties (2 × 1.0).
        observaties = [_obs(gb=GB_B), _obs(gb=GB_B), _obs(gb=GB_A, bron="app")]
        voorstel = _voorstel(observaties)
        assert voorstel.gb.waarde == GB_A
        # gesplitste stem -> oranje, ook al wint de app-correctie.
        assert voorstel.gb.oranje

    def test_confidence_is_winnend_gewicht_gedeeld_door_totaal(self) -> None:
        observaties = [_obs(gb=GB_A), _obs(gb=GB_A), _obs(gb=GB_B)]
        voorstel = _voorstel(observaties)
        assert voorstel.gb.waarde == GB_A
        assert abs(voorstel.gb.confidence - 2 / 3) < 1e-9
        assert voorstel.gb.telling == 2

    def test_deterministische_tiebreak(self) -> None:
        observaties = [_obs(gb=GB_A), _obs(gb=GB_B)]
        eerste = _voorstel(observaties).gb.waarde
        assert all(_voorstel(observaties).gb.waarde == eerste for _ in range(5))
        assert eerste == min(GB_A, GB_B, key=str)


class TestOranjeTriggers:
    def test_een_seed_observatie_geeft_voorstel_maar_oranje(self) -> None:
        voorstel = _voorstel([_obs(gb=GB_A)])
        assert voorstel.gb.waarde == GB_A
        assert voorstel.gb.oranje
        assert "alleen rlz-historie" in (voorstel.gb.reden or "")
        assert not voorstel.gb.app_bevestigd

    def test_seed_only_blijft_oranje_ook_bij_hoge_eenduidige_confidence(self) -> None:
        # Peters ontwerp (2026-07-14): uitsluitend rlz_seed = oranje, hoe eenduidig de stem ook
        # is — dit verving de oude regel "≥2 consistente observaties is genoeg".
        voorstel = _voorstel([_obs(gb=GB_A), _obs(gb=GB_A), _obs(gb=GB_A)])
        assert voorstel.gb.waarde == GB_A
        assert voorstel.gb.confidence == 1.0
        assert voorstel.gb.oranje
        assert "alleen rlz-historie" in (voorstel.gb.reden or "")
        assert not voorstel.gb.app_bevestigd

    def test_seed_only_wordt_groen_na_eerste_app_bevestiging_van_die_waarde(self) -> None:
        seed_only = [_obs(gb=GB_A), _obs(gb=GB_A)]
        assert _voorstel(seed_only).gb.oranje
        bevestigd = _voorstel([*seed_only, _obs(gb=GB_A, bron="app")])
        assert bevestigd.gb.waarde == GB_A
        assert not bevestigd.gb.oranje
        assert bevestigd.gb.app_bevestigd

    def test_een_app_bevestiging_op_een_ANDERE_waarde_haalt_de_winnaar_niet_uit_oranje(self) -> None:
        # De app-bevestiging moet de wínnende waarde dekken; een app-observatie op een andere
        # GB maakt de stem bovendien gesplitst — dubbel oranje.
        voorstel = _voorstel([_obs(gb=GB_A), _obs(gb=GB_A), _obs(gb=GB_A), _obs(gb=GB_A), _obs(gb=GB_B, bron="app")])
        assert voorstel.gb.waarde == GB_A
        assert voorstel.gb.oranje
        assert not voorstel.gb.app_bevestigd

    def test_een_app_correctie_niet_meer_oranje(self) -> None:
        voorstel = _voorstel([_obs(gb=GB_A, bron="app")])
        assert voorstel.gb.waarde == GB_A
        assert not voorstel.gb.oranje
        assert voorstel.gb.app_bevestigd

    def test_gesplitste_stem_blijft_oranje_ook_met_veel_observaties(self) -> None:
        observaties = [_obs(gb=GB_A), _obs(gb=GB_A), _obs(gb=GB_A), _obs(gb=GB_B)]
        voorstel = _voorstel(observaties)
        assert voorstel.gb.waarde == GB_A
        assert voorstel.gb.oranje
        assert "gesplitste stem" in (voorstel.gb.reden or "")

    def test_geen_observaties_geeft_leeg_oranje_voorstel(self) -> None:
        voorstel = _voorstel([])
        assert voorstel.gb.waarde is None
        assert voorstel.gb.confidence == 0.0
        assert voorstel.gb.oranje


class TestBtw:
    def test_regel_niveau_gaat_voor_leverancier_niveau(self) -> None:
        observaties = [
            _obs(btw=BTW_HOOG),  # leverancier-niveau
            _obs(btw=BTW_VERLEGD, sleutel=SLEUTEL_DIESEL, bron="app"),
            _obs(btw=BTW_VERLEGD, sleutel=SLEUTEL_DIESEL, bron="app"),
        ]
        voorstel = _voorstel(observaties, sleutel=SLEUTEL_DIESEL)
        assert voorstel.btw.waarde == BTW_VERLEGD
        assert not voorstel.btw.oranje  # consistente, app-bevestigde regel-observaties, geen fallback

    def test_leverancier_fallback_is_altijd_oranje(self) -> None:
        # Regel-sleutel bekend, maar geen enkele observatie op dat regel-niveau -> fallback.
        observaties = [_obs(btw=BTW_HOOG), _obs(btw=BTW_HOOG)]
        voorstel = _voorstel(observaties, sleutel=SLEUTEL_DIESEL)
        assert voorstel.btw.waarde == BTW_HOOG
        assert voorstel.btw.oranje
        assert "leverancier-fallback" in (voorstel.btw.reden or "")

    def test_gesplitste_btw_stem_is_altijd_oranje(self) -> None:
        observaties = [
            _obs(btw=BTW_HOOG, sleutel=SLEUTEL_DIESEL),
            _obs(btw=BTW_HOOG, sleutel=SLEUTEL_DIESEL),
            _obs(btw=BTW_VERLEGD, sleutel=SLEUTEL_DIESEL),
        ]
        voorstel = _voorstel(observaties, sleutel=SLEUTEL_DIESEL)
        assert voorstel.btw.waarde == BTW_HOOG
        assert voorstel.btw.oranje
        assert "gesplitste stem" in (voorstel.btw.reden or "")

    def test_zonder_regel_sleutel_is_leverancier_niveau_primair_geen_fallback_vlag(self) -> None:
        observaties = [_obs(btw=BTW_HOOG, bron="app"), _obs(btw=BTW_HOOG, bron="app")]
        voorstel = _voorstel(observaties, sleutel=None)
        assert voorstel.btw.waarde == BTW_HOOG
        assert not voorstel.btw.oranje


class TestGbEnProjectVerfijning:
    def test_regel_niveau_verfijnt_gb_bij_gesplitste_leverancier_stem(self) -> None:
        observaties = [
            _obs(gb=GB_A, sleutel="heater huur"),
            _obs(gb=GB_A, sleutel="heater huur"),
            _obs(gb=GB_B, sleutel=SLEUTEL_DIESEL, bron="app"),
            _obs(gb=GB_B, sleutel=SLEUTEL_DIESEL, bron="app"),
        ]
        voorstel = _voorstel(observaties, sleutel=SLEUTEL_DIESEL)
        assert voorstel.gb.waarde == GB_B
        assert not voorstel.gb.oranje  # regel-niveau is eenduidig én app-bevestigd

    def test_eenduidige_leverancier_stem_wordt_niet_verfijnd(self) -> None:
        observaties = [
            _obs(gb=GB_A, bron="app"),
            _obs(gb=GB_A, bron="app"),
            _obs(gb=GB_A, sleutel=SLEUTEL_DIESEL, bron="app"),
        ]
        voorstel = _voorstel(observaties, sleutel=SLEUTEL_DIESEL)
        assert voorstel.gb.waarde == GB_A
        assert not voorstel.gb.oranje

    def test_project_wordt_alleen_voorgesteld_uit_observaties_met_project(self) -> None:
        observaties = [_obs(), _obs(), _obs(project=PROJECT_P, bron="app")]
        voorstel = _voorstel(observaties)
        assert voorstel.project.waarde == PROJECT_P
        assert not voorstel.project.oranje  # 1 app-correctie volstaat
