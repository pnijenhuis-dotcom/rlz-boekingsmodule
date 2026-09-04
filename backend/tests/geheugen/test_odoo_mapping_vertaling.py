# ruff: noqa: F811 — pytest-fixtures als parameters
"""Eén vertaalpunt per lader (blok A Odoo-afrondingsrun 04-09, migratie 0111): staat er een Odoo-rekening-
mapping voor de administratie, dan vertalen `geheugen.service.voorstel_voor`, `regel_gb.laad_observaties` en
de prefill-lader `documenten/regel_prefill._engine_observaties` de RLZ-UUID's VÓÓR de engine — app-bevestiging
blijft, geen gesplitste stem. Zonder mapping-rijen verandert er niets."""

from __future__ import annotations

import uuid
from datetime import date

from app.db.session import scoped_session
from app.documenten import regel_prefill
from app.geheugen import regel_gb
from app.geheugen import service as geheugen_service
from app.geheugen.models import BoekingObservatie
from app.geheugen.normalisatie import normaliseer_regel_sleutel
from app.odoo.ids import odoo_uuid
from app.odoo.models import OdooRekeningMapping
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import gescoopte_gebruiker  # noqa: F401

VENDOR = uuid.UUID("cccccccc-0000-0000-0000-000000000077")
RLZ_GB = uuid.UUID("aaaaaaaa-0000-0000-0000-000000004808")
RLZ_BTW = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000021")
ODOO_GB = odoo_uuid(1, "account.account", 11)
ODOO_BTW = odoo_uuid(1, "account.tax", 21)
SLEUTEL = normaliseer_regel_sleutel("Diesel NEN590")


def _seed(aid: uuid.UUID, *, met_mapping: bool, beheerder: uuid.UUID) -> None:
    with scoped_session(aid, actor_id=beheerder) as session:
        session.add(
            BoekingObservatie(
                id=uuid.uuid4(),
                administratie_id=aid,
                vendor_id=VENDOR,
                regel_sleutel=SLEUTEL,
                gb_id=RLZ_GB,
                btw_id=RLZ_BTW,
                project_id=uuid.uuid4(),
                bron="app",
                bron_datum=date(2026, 8, 1),
            )
        )
        if met_mapping:
            for soort, rlz, odoo, odoo_id in (("grootboek", RLZ_GB, ODOO_GB, 11), ("btw", RLZ_BTW, ODOO_BTW, 21)):
                session.add(
                    OdooRekeningMapping(
                        administratie_id=aid,
                        soort=soort,
                        rlz_id=rlz,
                        rlz_code="4808" if soort == "grootboek" else None,
                        rlz_naam="x",
                        odoo_lokaal_id=odoo,
                        odoo_id=odoo_id,
                        odoo_code="480800" if soort == "grootboek" else None,
                        odoo_naam="y",
                        bron="code_verlengd" if soort == "grootboek" else "tarief",
                        versie=1,
                        bevestigd_door=beheerder,
                    )
                )


class TestVoorstelVoor:
    def test_zonder_mapping_ongewijzigd(self, administratie_id, beheerder_id) -> None:
        _seed(administratie_id, met_mapping=False, beheerder=beheerder_id)
        v = geheugen_service.voorstel_voor(administratie_id=administratie_id, vendor_id=VENDOR)
        assert v.gb.waarde == RLZ_GB and v.btw.waarde == RLZ_BTW and v.project.waarde is not None

    def test_met_mapping_vertaald_app_bevestigd_blijft(self, administratie_id, beheerder_id) -> None:
        _seed(administratie_id, met_mapping=True, beheerder=beheerder_id)
        v = geheugen_service.voorstel_voor(administratie_id=administratie_id, vendor_id=VENDOR)
        assert v.gb.waarde == ODOO_GB and v.gb.app_bevestigd and not v.gb.oranje and v.gb.confidence == 1.0
        assert v.btw.waarde == ODOO_BTW and v.btw.app_bevestigd
        assert v.project.waarde is None  # RLZ-project ≠ Odoo-analytic-account: nooit meegenomen

    def test_nieuwe_odoo_observatie_telt_bij_dezelfde_stem(self, administratie_id, beheerder_id) -> None:
        _seed(administratie_id, met_mapping=True, beheerder=beheerder_id)
        with scoped_session(administratie_id) as session:
            session.add(
                BoekingObservatie(
                    id=uuid.uuid4(),
                    administratie_id=administratie_id,
                    vendor_id=VENDOR,
                    regel_sleutel=None,
                    gb_id=ODOO_GB,
                    btw_id=ODOO_BTW,
                    project_id=None,
                    bron="app",
                    bron_datum=date(2026, 9, 3),
                )
            )
        v = geheugen_service.voorstel_voor(administratie_id=administratie_id, vendor_id=VENDOR)
        assert v.gb.waarde == ODOO_GB and v.gb.telling == 2 and v.gb.confidence == 1.0
        assert "gesplitste stem" not in (v.gb.reden or "")


class TestRegelGbEnPrefillLader:
    def test_laad_observaties_vertaalt_en_bepaal_regel_gb_treft_odoo_rekening(
        self, administratie_id, beheerder_id
    ) -> None:
        _seed(administratie_id, met_mapping=True, beheerder=beheerder_id)
        with scoped_session(administratie_id) as session:
            obs = regel_gb.laad_observaties(session, administratie_id=administratie_id, vendor_ids=frozenset({VENDOR}))
        assert [o.gb_id for o in obs] == [ODOO_GB] and obs[0].bron == "app"
        voorstel = regel_gb.bepaal_regel_gb(obs, regel_sleutel=SLEUTEL)
        assert voorstel is not None and voorstel.ledger_id == ODOO_GB and voorstel.bron == regel_gb.BRON_GEHEUGEN

    def test_prefill_engine_lader_is_dezelfde_bron_als_voorstel_voor(self, administratie_id, beheerder_id) -> None:
        _seed(administratie_id, met_mapping=True, beheerder=beheerder_id)
        with scoped_session(administratie_id) as session:
            obs = regel_prefill._engine_observaties(session, administratie_id=administratie_id, vendor_id=VENDOR)
        assert [(o.gb_id, o.btw_id, o.project_id) for o in obs] == [(ODOO_GB, ODOO_BTW, None)]
        assert regel_prefill._engine_heeft_btw(obs, regel_sleutel=SLEUTEL)
