"""Regel-niveau GB-geheugen (blok D medewerker-wensen 04-09, app/geheugen/regel_gb.py): pure
beslislogica (app = groen, seed-only = oranje, conflict, geen treffer, app-bevestiging van de waarde
elders) én de kenmerk-groep over twee vendors met hetzelfde btw-nummer (Wola / Wola b.v.)."""

from __future__ import annotations

import uuid
from datetime import date

from app.db.session import scoped_session
from app.documenten.models import CrediteurKenmerk
from app.geheugen import regel_gb
from app.geheugen.models import BoekingObservatie
from app.geheugen.normalisatie import normaliseer_regel_sleutel
from app.sync.models import VendorCache

GB_4110 = uuid.UUID("44444444-0000-0000-0000-000000004110")
GB_4112 = uuid.UUID("44444444-0000-0000-0000-000000004112")
SLEUTEL = normaliseer_regel_sleutel("Microsoft 365 Business Premium (YR-MTH)")


def _obs(gb: uuid.UUID, *, bron: str, dag: int = 1, sleutel: str | None = SLEUTEL) -> regel_gb.RegelObservatie:
    return regel_gb.RegelObservatie(regel_sleutel=sleutel, gb_id=gb, bron=bron, bron_datum=date(2026, 8, dag))


class TestBepaalRegelGb:
    def test_geen_sleutel_of_geen_treffer_geeft_niets(self) -> None:
        assert regel_gb.bepaal_regel_gb([_obs(GB_4110, bron="app")], regel_sleutel=None) is None
        assert regel_gb.bepaal_regel_gb([_obs(GB_4110, bron="app")], regel_sleutel="iets anders") is None
        assert regel_gb.bepaal_regel_gb([], regel_sleutel=SLEUTEL) is None

    def test_app_observaties_eenduidig_is_groen_met_telling_en_laatste_datum(self) -> None:
        voorstel = regel_gb.bepaal_regel_gb(
            [_obs(GB_4110, bron="app", dag=3), _obs(GB_4110, bron="app", dag=12), _obs(GB_4110, bron="rlz_seed")],
            regel_sleutel=SLEUTEL,
        )
        assert voorstel is not None
        assert voorstel.ledger_id == GB_4110
        assert voorstel.bron == regel_gb.BRON_GEHEUGEN
        assert voorstel.detail == "2× bevestigd, laatst 12-08-2026"

    def test_seed_only_is_oranje_uit_historie(self) -> None:
        voorstel = regel_gb.bepaal_regel_gb(
            [_obs(GB_4110, bron="rlz_seed", dag=5), _obs(GB_4110, bron="rlz_seed", dag=9)], regel_sleutel=SLEUTEL
        )
        assert voorstel is not None
        assert voorstel.ledger_id == GB_4110
        assert voorstel.bron == regel_gb.BRON_GEHEUGEN_SEED
        assert "nog niet bevestigd" in voorstel.detail

    def test_seed_regel_maar_waarde_elders_app_bevestigd_is_groen(self) -> None:
        """Geheugen-regel (CLAUDE.md): pas de eerste app-bevestiging van de WAARDE maakt 'm groen —
        ook als die bevestiging op leverancier-niveau (regel_sleutel NULL) of een andere regel zat."""
        voorstel = regel_gb.bepaal_regel_gb(
            [_obs(GB_4110, bron="rlz_seed"), _obs(GB_4110, bron="app", sleutel=None)], regel_sleutel=SLEUTEL
        )
        assert voorstel is not None
        assert voorstel.bron == regel_gb.BRON_GEHEUGEN
        assert "1× bevestigd bij deze leverancier" in voorstel.detail

    def test_seed_regel_met_ander_gb_elders_bevestigd_blijft_oranje(self) -> None:
        voorstel = regel_gb.bepaal_regel_gb(
            [_obs(GB_4110, bron="rlz_seed"), _obs(GB_4112, bron="app", sleutel=None)], regel_sleutel=SLEUTEL
        )
        assert voorstel is not None
        assert voorstel.ledger_id == GB_4110
        assert voorstel.bron == regel_gb.BRON_GEHEUGEN_SEED

    def test_conflict_in_app_observaties_jongste_wint_oranje(self) -> None:
        voorstel = regel_gb.bepaal_regel_gb(
            [_obs(GB_4110, bron="app", dag=2), _obs(GB_4112, bron="app", dag=20), _obs(GB_4110, bron="app", dag=4)],
            regel_sleutel=SLEUTEL,
        )
        assert voorstel is not None
        assert voorstel.ledger_id == GB_4112  # jongste
        assert voorstel.bron == regel_gb.BRON_GEHEUGEN_CONFLICT
        assert "wisselend geboekt (2 grootboeken" in voorstel.detail

    def test_app_wint_altijd_van_seed_ook_bij_oudere_datum(self) -> None:
        voorstel = regel_gb.bepaal_regel_gb(
            [_obs(GB_4110, bron="app", dag=1), _obs(GB_4112, bron="rlz_seed", dag=30)], regel_sleutel=SLEUTEL
        )
        assert voorstel is not None
        assert voorstel.ledger_id == GB_4110 and voorstel.bron == regel_gb.BRON_GEHEUGEN

    def test_kandidaten_zijn_alle_historische_gbs_deterministisch_geordend(self) -> None:
        ids = regel_gb.kandidaat_ids(
            [_obs(GB_4112, bron="rlz_seed"), _obs(GB_4110, bron="app", sleutel=None), _obs(GB_4112, bron="app")]
        )
        assert ids == sorted({GB_4110, GB_4112}, key=str)


class TestVendorGroepOpKenmerk:
    def test_twee_vendors_met_zelfde_btw_nummer_delen_het_regel_geheugen(self, administratie_id: uuid.UUID) -> None:
        wola = uuid.uuid4()
        wola_bv = uuid.uuid4()
        ander = uuid.uuid4()
        with scoped_session(administratie_id) as session:
            for vid, naam in ((wola, "Wola"), (wola_bv, "Wola b.v."), (ander, "Ander B.V.")):
                session.add(VendorCache(id=vid, administratie_id=administratie_id, naam=naam, brondata={}))
            session.add(
                CrediteurKenmerk(administratie_id=administratie_id, vendor_id=wola, btw_nummer="NL123456789B01")
            )
            session.add(
                CrediteurKenmerk(administratie_id=administratie_id, vendor_id=wola_bv, btw_nummer="NL123456789B01")
            )
            session.add(
                CrediteurKenmerk(administratie_id=administratie_id, vendor_id=ander, btw_nummer="NL999999999B01")
            )
            # De boeking op "Wola b.v." is de enige regel-observatie; het document komt binnen op "Wola".
            session.add(
                BoekingObservatie(
                    id=uuid.uuid4(),
                    administratie_id=administratie_id,
                    vendor_id=wola_bv,
                    regel_sleutel=SLEUTEL,
                    gb_id=GB_4110,
                    bron="app",
                    bron_datum=date(2026, 8, 12),
                )
            )
        with scoped_session(administratie_id) as session:
            groep = regel_gb.vendor_groep(session, administratie_id=administratie_id, vendor_id=wola)
            assert groep == frozenset({wola, wola_bv})
            observaties = regel_gb.laad_observaties(session, administratie_id=administratie_id, vendor_ids=groep)
            assert regel_gb.vendor_groep(session, administratie_id=administratie_id, vendor_id=ander) == frozenset(
                {ander}
            )
        voorstel = regel_gb.bepaal_regel_gb(observaties, regel_sleutel=SLEUTEL)
        assert voorstel is not None and voorstel.ledger_id == GB_4110 and voorstel.bron == regel_gb.BRON_GEHEUGEN

    def test_zonder_kenmerk_alleen_de_vendor_zelf(self, administratie_id: uuid.UUID) -> None:
        a = uuid.uuid4()
        with scoped_session(administratie_id) as session:
            session.add(VendorCache(id=a, administratie_id=administratie_id, naam="Naamloos", brondata={}))
        with scoped_session(administratie_id) as session:
            assert regel_gb.vendor_groep(session, administratie_id=administratie_id, vendor_id=a) == frozenset({a})

    def test_kvk_is_terugval_zonder_btw_nummer(self, administratie_id: uuid.UUID) -> None:
        a, b = uuid.uuid4(), uuid.uuid4()
        with scoped_session(administratie_id) as session:
            for vid in (a, b):
                session.add(VendorCache(id=vid, administratie_id=administratie_id, naam=f"V {vid}", brondata={}))
                session.add(CrediteurKenmerk(administratie_id=administratie_id, vendor_id=vid, kvk_nummer="12345678"))
        with scoped_session(administratie_id) as session:
            assert regel_gb.vendor_groep(session, administratie_id=administratie_id, vendor_id=a) == frozenset({a, b})


class TestClassificatieSchema:
    def test_schema_is_union_vrij_en_sentinel_gebaseerd(self) -> None:
        from app.extractie.schema_poort import tel_union_parameters

        assert tel_union_parameters(regel_gb.CLASSIFICATIE_SCHEMA) == 0
        assert regel_gb._parse_keuzes({"keuzes": [{"i": 1, "k": 2}, {"i": 2, "k": 0}, {"i": "x", "k": 1}]}) == {
            1: 2,
            2: 0,
        }
        assert regel_gb._parse_keuzes(None) == {}
