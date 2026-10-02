"""Punt 8 run A 02-10 (Peter, casus Universal Steigerbouw f00117f4 — RLZ-2080142625, brandstof diesel): het
leverancier-geheugen zette 7005 Inhuur steiger ("Geheugen 71 %") op een brandstofregel. Regel: het leverancier-geheugen
(kop-niveau-engine) vult de GROOTBOEKREKENING alleen bij zekerheid ≥ 90 % (`GEHEUGEN_GROOTBOEK_MIN_ZEKERHEID`) óf een
recency-consensus; de deterministische omschrijvingsroute (regel-geheugen) gaat er altijd vóór; daaronder blijft het
veld LEEG mét herkomst-info (`gb_bron = leverancier_geheugen_niet_ingevuld`), de mens kiest, de harde check blijft de
poort.
Pure tests (geen DB): engine-observaties → `_met_leverancier_geheugen`; snapshot-herstel; autoboek-poort."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from app.documenten import autoboeken, boekvoorstel, regel_prefill
from app.documenten.boekvoorstel import BoekvoorstelRegelData
from app.documenten.models import BoekvoorstelRegel
from app.geheugen import regel_gb
from app.geheugen.engine import GeheugenVoorstel, Observatie, VeldVoorstel, bepaal_voorstel

GB_INHUUR = uuid.UUID("77777777-0000-0000-0000-000000007005")
GB_BRANDSTOF = uuid.UUID("77777777-0000-0000-0000-000000004310")
BTW_HOOG = uuid.UUID("55555555-0000-0000-0000-000000000021")
VANDAAG = date(2026, 10, 2)


def _obs(gb: uuid.UUID, *, bron: str = "app", dagen_geleden: int = 10, sleutel: str | None = None) -> Observatie:
    return Observatie(
        regel_sleutel=sleutel,
        gb_id=gb,
        btw_id=BTW_HOOG,
        project_id=None,
        bron=bron,
        bron_datum=VANDAAG - timedelta(days=dagen_geleden),
        boeking_sleutel=f"boek-{gb}-{dagen_geleden}",
    )


def _regel(**extra: object) -> BoekvoorstelRegelData:
    velden: dict[str, object] = {
        "ledger_id": None,
        "taxrate_id": None,
        "project_id": None,
        "netto_bedrag": Decimal("751.15"),
        "btw_bedrag": Decimal("157.74"),
        "omschrijving": "Brandstof diesel Floor",
        **extra,
    }
    return BoekvoorstelRegelData(**velden)  # type: ignore[arg-type]


def _leverancier_geheugen(regel: BoekvoorstelRegelData, observaties: list[Observatie]) -> BoekvoorstelRegelData:
    return regel_prefill._met_leverancier_geheugen(
        regel,
        engine_observaties=observaties,
        regel_sleutel=None,
        project_verplicht=False,
        vandaag=VANDAAG,
    )


class TestDrempel:
    def test_gesplitste_stem_71_procent_vult_het_grootboek_niet_maar_blijft_zichtbaar(self) -> None:
        # 5 × app 7005 (gewicht 3) vs 2 × app 4310 (gewicht 3) ≈ 71 % — exact de f00117f4-stand ("Geheugen 71 %").
        observaties = [_obs(GB_INHUUR, dagen_geleden=d) for d in (5, 15, 25, 35, 45)] + [
            _obs(GB_BRANDSTOF, dagen_geleden=d) for d in (10, 20)
        ]
        voorstel = bepaal_voorstel(observaties, vandaag=VANDAAG)
        assert voorstel.gb.waarde == GB_INHUUR and voorstel.gb.oranje
        assert 0.70 <= voorstel.gb.confidence < 0.72
        assert not regel_prefill.geheugen_grootboek_zeker(voorstel.gb)

        regel = _leverancier_geheugen(_regel(), observaties)
        assert regel.ledger_id is None, "onder de drempel wordt het grootboek NIET ingevuld"
        assert regel.gb_bron == regel_prefill.GB_BRON_GEHEUGEN_NIET_INGEVULD == "leverancier_geheugen_niet_ingevuld"
        assert regel.gb_voorstel_detail is not None
        assert "71 % zekerheid" in regel.gb_voorstel_detail and "drempel van 90 %" in regel.gb_voorstel_detail
        assert "gesplitste stem" in regel.gb_voorstel_detail
        # Geen herkomst "grootboek" (er is niets gevuld → geen autosave-trigger); btw volgt wél het geheugen.
        assert (regel.prefill_herkomst or {}).get("grootboek") is None
        assert regel.taxrate_id == BTW_HOOG and regel.prefill_herkomst == {"btw": "leverancier_geheugen"}

    def test_eenduidig_100_procent_vult_in_met_herkomst(self) -> None:
        observaties = [_obs(GB_INHUUR, dagen_geleden=d) for d in (5, 15, 25)]
        regel = _leverancier_geheugen(_regel(), observaties)
        assert regel.ledger_id == GB_INHUUR and regel.gb_bron is None
        assert regel.prefill_herkomst == {"grootboek": "leverancier_geheugen", "btw": "leverancier_geheugen"}

    def test_net_boven_de_drempel_vult_in(self) -> None:
        # 10 × app A vs 1 × app B ≈ 91 % → invullen (de drempel is ≥ 90 %).
        observaties = [_obs(GB_INHUUR, dagen_geleden=d) for d in range(1, 11)] + [_obs(GB_BRANDSTOF, dagen_geleden=3)]
        voorstel = bepaal_voorstel(observaties, vandaag=VANDAAG)
        assert voorstel.gb.confidence >= 0.90
        regel = _leverancier_geheugen(_regel(), observaties)
        assert regel.ledger_id == GB_INHUUR

    def test_recency_consensus_wint_ook_onder_de_90_procent(self) -> None:
        # Besluit Peter 10-09 ("recency wint") blijft staan: B, B, B, B, A, A, A → de laatste drie mens-boekingen zijn
        # identiek → A groen + app-bevestigd, ook al is het gewogen aandeel < 90 %.
        observaties = [_obs(GB_BRANDSTOF, dagen_geleden=d) for d in (40, 50, 60, 70)] + [
            _obs(GB_INHUUR, dagen_geleden=d) for d in (5, 10, 15)
        ]
        voorstel = bepaal_voorstel(observaties, vandaag=VANDAAG)
        assert voorstel.gb.waarde == GB_INHUUR and voorstel.gb.recent_consensus and voorstel.gb.confidence < 0.90
        assert regel_prefill.geheugen_grootboek_zeker(voorstel.gb)
        regel = _leverancier_geheugen(_regel(), observaties)
        assert regel.ledger_id == GB_INHUUR

    def test_seed_only_hoge_zekerheid_vult_in_oranje_zoals_voorheen(self) -> None:
        # Seed-only is oranje (chip "uit historie, nog niet bevestigd") maar eenduidig 100 % → wél invullen, zoals A10
        # 07-09.
        observaties = [_obs(GB_INHUUR, bron="rlz_seed", dagen_geleden=d) for d in (100, 200)]
        regel = _leverancier_geheugen(_regel(), observaties)
        assert regel.ledger_id == GB_INHUUR

    def test_zonder_observaties_niets(self) -> None:
        regel = _leverancier_geheugen(_regel(), [])
        assert regel.ledger_id is None and regel.gb_bron is None


class TestWinnaarsvolgorde:
    def test_mens_of_deterministische_bron_wordt_nooit_geraakt(self) -> None:
        # Een al gevuld grootboek (mens, UBL/template óf regel-geheugen) blijft staan — ook bij een 100 %-leverancier-
        # geheugen op een ANDERE rekening: het leverancier-geheugen komt er nooit overheen (markeren, niet overnemen).
        observaties = [_obs(GB_INHUUR, dagen_geleden=d) for d in (5, 15, 25)]
        regel = _leverancier_geheugen(_regel(ledger_id=GB_BRANDSTOF, gb_bron=regel_gb.BRON_GEHEUGEN), observaties)
        assert regel.ledger_id == GB_BRANDSTOF and regel.gb_bron == regel_gb.BRON_GEHEUGEN
        assert (regel.prefill_herkomst or {}).get("grootboek") is None

    def test_regel_geheugen_op_de_omschrijving_gaat_voor_het_leverancier_geheugen(self) -> None:
        # De deterministische omschrijvingsroute: "brandstof diesel" is bij deze leverancier als 4310 bevestigd →
        # `bepaal_regel_gb` wijst 4310 aan (groen) — het leverancier-niveau (7005) komt er niet meer aan te pas.
        sleutel = "brandstof diesel floor"
        regel_observaties = [
            regel_gb.RegelObservatie(regel_sleutel=sleutel, gb_id=GB_BRANDSTOF, bron="app", bron_datum=VANDAAG),
            regel_gb.RegelObservatie(regel_sleutel=None, gb_id=GB_INHUUR, bron="app", bron_datum=VANDAAG),
            regel_gb.RegelObservatie(regel_sleutel=None, gb_id=GB_INHUUR, bron="app", bron_datum=VANDAAG),
        ]
        voorstel = regel_gb.bepaal_regel_gb(regel_observaties, regel_sleutel=sleutel)
        assert voorstel is not None and voorstel.ledger_id == GB_BRANDSTOF and voorstel.bron == regel_gb.BRON_GEHEUGEN

    def test_een_bestaande_gb_bron_wordt_niet_overschreven_door_niet_ingevuld(self) -> None:
        # Een regel die al een gb_bron draagt zonder waarde (bv. een eerder herstelde chip) houdt die.
        observaties = [_obs(GB_INHUUR, dagen_geleden=d) for d in (5, 15, 25, 35, 45)] + [
            _obs(GB_BRANDSTOF, dagen_geleden=d) for d in (10, 20)
        ]
        regel = _leverancier_geheugen(_regel(gb_bron="ai", gb_voorstel_detail="AI koos …"), observaties)
        assert regel.ledger_id is None and regel.gb_bron == "ai"


class TestSnapshotHerstel:
    def test_niet_ingevuld_chip_komt_na_het_persisteren_terug_zolang_het_veld_leeg_is(self) -> None:
        regel = BoekvoorstelRegel(volgnummer=1, ledger_id=None, omschrijving="Brandstof diesel Floor")
        snap = {
            "regels": [
                {
                    "volgnummer": 1,
                    "omschrijving": "Brandstof diesel Floor",
                    "ledger_id": None,
                    "gb_bron": "leverancier_geheugen_niet_ingevuld",
                    "gb_voorstel_detail": "historie … 71 % zekerheid … drempel van 90 %",
                    "herkomst": {"btw": "factuur"},
                }
            ]
        }
        data = boekvoorstel._opgeslagen_regel_data(regel, snap)
        assert data.ledger_id is None
        assert data.gb_bron == "leverancier_geheugen_niet_ingevuld"
        assert data.gb_voorstel_detail is not None and "71 %" in data.gb_voorstel_detail
        # Mens koos daarna een rekening → de uitleg-chip verdwijnt (bewust, zelfde regel als elke herkomst-chip).
        gekozen = BoekvoorstelRegel(volgnummer=1, ledger_id=GB_BRANDSTOF, omschrijving="Brandstof diesel Floor")
        assert boekvoorstel._opgeslagen_regel_data(gekozen, snap).gb_bron is None

    def test_niet_ingevuld_is_geen_autosave_trigger(self) -> None:
        # Er is niets gevuld → geen reden om bij het openen te persisteren (anders zou een lege prefill opgeslagen
        # raken).
        assert "leverancier_geheugen_niet_ingevuld" not in boekvoorstel._AUTOSAVE_HERKOMSTEN


class TestAutoboekPoort:
    def test_71_procent_voorstel_boekt_nooit_automatisch(self) -> None:
        gb = VeldVoorstel(
            waarde=GB_INHUUR, confidence=0.71, telling=5, oranje=True, reden="gesplitste stem", app_bevestigd=True
        )
        btw = VeldVoorstel(waarde=BTW_HOOG, confidence=1.0, telling=7, oranje=False, reden=None, app_bevestigd=True)
        reden = autoboeken._geheugen_veld_geblokkeerd(
            GeheugenVoorstel(gb=gb, btw=btw, project=btw), project_vereist=False
        )
        assert reden is not None and "grootboek" in reden and "gesplitste stem" in reden

    def test_zonder_grootboek_voorstel_is_de_reden_zichtbaar(self) -> None:
        geen = VeldVoorstel(waarde=None, confidence=0.0, telling=0, oranje=True, reden="geen observaties")
        btw = VeldVoorstel(waarde=BTW_HOOG, confidence=1.0, telling=7, oranje=False, reden=None, app_bevestigd=True)
        reden = autoboeken._geheugen_veld_geblokkeerd(
            GeheugenVoorstel(gb=geen, btw=btw, project=btw), project_vereist=False
        )
        assert reden == "geheugen heeft geen voorstel voor grootboek"
